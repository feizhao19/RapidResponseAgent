"""Sliding-window inference helpers for full-resolution ViPDE.

Strategy (matches training input size, e.g. 1024):
  1. Crop a tile from the full image.
  2. If the crop is smaller than tile_size (image edges), pad with black (0).
  3. Run ViPDE on one or more square tiles (batched) — no extra resize when tile_size == img_size.
  4. Crop model logits to the valid (non-padded) region and stitch with overlap averaging.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import torch


def window_starts(length: int, tile: int, stride: int) -> list[int]:
    if length <= tile:
        return [0]
    starts = list(range(0, length - tile + 1, stride))
    last = length - tile
    if starts[-1] != last:
        starts.append(last)
    return sorted(set(starts))


def pad_tile_black(arr: np.ndarray, tile_size: int) -> tuple[np.ndarray, int, int]:
    """Pad bottom/right with black so the tile is exactly tile_size x tile_size."""
    h, w = arr.shape[:2]
    valid_h, valid_w = min(h, tile_size), min(w, tile_size)
    if valid_h == tile_size and valid_w == tile_size:
        return arr[:tile_size, :tile_size], tile_size, tile_size

    out = np.zeros((tile_size, tile_size, arr.shape[2]), dtype=arr.dtype)
    out[:valid_h, :valid_w] = arr[:valid_h, :valid_w]
    return out, valid_h, valid_w


def _is_oom_error(exc: BaseException) -> bool:
    if isinstance(exc, torch.OutOfMemoryError):
        return True
    name = type(exc).__name__
    if "OutOfMemory" in name:
        return True
    message = str(exc).lower()
    return "out of memory" in message or "oom" in message


def _forward_batch(
    *,
    model,
    pre_batch: torch.Tensor,
    post_batch: torch.Tensor,
    use_fp16: bool,
    device,
    forward_fn: Callable,
) -> torch.Tensor:
    """Run a tile batch; on OOM, split in half and retry."""
    try:
        return forward_fn(model, pre_batch, post_batch, use_fp16=use_fp16, device=device)
    except Exception as exc:  # noqa: BLE001 — device-specific OOM types vary
        if not _is_oom_error(exc) or pre_batch.shape[0] <= 1:
            raise
        if device.type == "cuda":
            torch.cuda.empty_cache()
        mid = pre_batch.shape[0] // 2
        print(
            f"      batch OOM at size={pre_batch.shape[0]}; retrying as {mid}+{pre_batch.shape[0] - mid}",
            flush=True,
        )
        left = _forward_batch(
            model=model,
            pre_batch=pre_batch[:mid],
            post_batch=post_batch[:mid],
            use_fp16=use_fp16,
            device=device,
            forward_fn=forward_fn,
        )
        right = _forward_batch(
            model=model,
            pre_batch=pre_batch[mid:],
            post_batch=post_batch[mid:],
            use_fp16=use_fp16,
            device=device,
            forward_fn=forward_fn,
        )
        return torch.cat([left, right], dim=0)


def sliding_window_predict(
    model,
    pre_orig: np.ndarray,
    post_orig: np.ndarray,
    *,
    device,
    img_size: int,
    tile_size: int,
    stride: int,
    num_classes: int,
    pixel_mean: list[float],
    pixel_std: list[float],
    use_fp16: bool,
    forward_fn,
    batch_size: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (class mask HxW, averaged logits CxHxW) at full input resolution."""
    if tile_size != img_size:
        raise ValueError(
            f"tile_size ({tile_size}) must equal img_size ({img_size}): "
            "crop + black pad to model input, no downscale of the full image."
        )

    batch_size = max(1, int(batch_size))

    from vipde.utils.preprocess import normalize_to_tensor

    h, w = pre_orig.shape[:2]
    logits_sum = np.zeros((num_classes, h, w), dtype=np.float32)
    weight = np.zeros((h, w), dtype=np.float32)

    ys = window_starts(h, tile_size, stride)
    xs = window_starts(w, tile_size, stride)
    windows = [(y0, x0) for y0 in ys for x0 in xs]
    total = len(windows)
    done = 0

    pending_meta: list[tuple[int, int, int, int]] = []
    pending_pre: list[torch.Tensor] = []
    pending_post: list[torch.Tensor] = []

    def flush() -> None:
        nonlocal done
        if not pending_meta:
            return
        pre_batch = torch.cat(pending_pre, dim=0)
        post_batch = torch.cat(pending_post, dim=0)
        logits = _forward_batch(
            model=model,
            pre_batch=pre_batch,
            post_batch=post_batch,
            use_fp16=use_fp16,
            device=device,
            forward_fn=forward_fn,
        )
        log_np = logits.detach().cpu().float().numpy()
        if log_np.ndim != 4:
            raise RuntimeError(f"Expected BxCxHxW logits, got shape {log_np.shape}")
        if log_np.shape[0] != len(pending_meta):
            raise RuntimeError(
                f"Batch size mismatch: logits={log_np.shape[0]} tiles={len(pending_meta)}"
            )

        for i, (y0, x0, valid_h, valid_w) in enumerate(pending_meta):
            tile_logits = log_np[i]
            out_h, out_w = tile_logits.shape[1], tile_logits.shape[2]
            if out_h != tile_size or out_w != tile_size:
                raise RuntimeError(
                    f"ViPDE logits spatial size {out_w}x{out_h} != tile_size {tile_size}. "
                    "Expected 1:1 output for padded tile input."
                )
            # Keep only the region that corresponds to real image pixels (exclude black pad).
            tile_logits = tile_logits[:, :valid_h, :valid_w]
            logits_sum[:, y0 : y0 + valid_h, x0 : x0 + valid_w] += tile_logits
            weight[y0 : y0 + valid_h, x0 : x0 + valid_w] += 1.0

        done += len(pending_meta)
        if done == total or batch_size > 1 or done % 5 == 0:
            print(f"      tiles {done}/{total} (batch={len(pending_meta)})", flush=True)
        pending_meta.clear()
        pending_pre.clear()
        pending_post.clear()

    for y0, x0 in windows:
        pre_crop = pre_orig[y0 : y0 + tile_size, x0 : x0 + tile_size]
        post_crop = post_orig[y0 : y0 + tile_size, x0 : x0 + tile_size]
        pre_tile, valid_h, valid_w = pad_tile_black(pre_crop, tile_size)
        post_tile, _, _ = pad_tile_black(post_crop, tile_size)

        pending_meta.append((y0, x0, valid_h, valid_w))
        pending_pre.append(normalize_to_tensor(pre_tile, pixel_mean, pixel_std).to(device))
        pending_post.append(normalize_to_tensor(post_tile, pixel_mean, pixel_std).to(device))

        if len(pending_meta) >= batch_size:
            flush()

    flush()

    w_safe = np.maximum(weight, 1.0)
    logits_avg = logits_sum / w_safe[np.newaxis, :, :]
    pred = np.argmax(logits_avg, axis=0).astype(np.uint8)
    return pred, logits_avg
