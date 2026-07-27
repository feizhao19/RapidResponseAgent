/** Contiguous US overview for the idle / pre-fly satellite context. */
export const CONUS_CENTER: [number, number] = [39.5, -98.35];
export const CONUS_ZOOM = 4;

/** Initial approach: slow enough to read as intentional, not a snap. */
export const FLY_DURATION_SEC = 2.55;
/** Brief hold on the continental view before the fly begins. */
export const FLY_HOLD_MS = 320;
/** After fly arrives at the AOI, linger on satellite before Pre fades in. */
export const PRE_ARRIVAL_HOLD_MS = 2000;
/** Padding around the AOI after the cinematic fly. */
export const FLY_PADDING: [number, number] = [52, 52];
export const FLY_MAX_ZOOM = 16;

/** Shared map overlay fade (polygons, priority, weather, roads). ~0.3s */
export const OVERLAY_FADE_MS = 320;
export const IMAGERY_FADE_MS = 480;
export const STREET_REF_FADE_MS = 380;
export const POLYGON_FADE_MS = OVERLAY_FADE_MS;

/** After Pre is on-screen (image loaded + fade-in), hold before switching to Post. */
export const PRE_HOLD_MS = 3000;
/** Fade-in + hold once the Pre preview has actually loaded. */
export const PRE_TO_POST_MS = IMAGERY_FADE_MS + PRE_HOLD_MS;

/** Browser-cache warm for AOI imagery previews (first hit builds PNG from GeoTIFF). */
export function imageryPreviewUrl(aoiId: string, which: "pre" | "post"): string {
  return `/api/aois/${encodeURIComponent(aoiId)}/imagery/${which}`;
}

export function prefetchImageryPreview(url: string): Promise<void> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve();
    img.onerror = () => resolve();
    img.src = url;
  });
}
/** After Post appears, short beat before polygons. */
export const POST_TO_POLYGONS_MS = 450;
/** Facility markers appear after polygons have mostly settled. */
export const MARKERS_AFTER_POLYGONS_MS = 280;

/** Detail panel chrome (nav + sections) entrance after AOI becomes active. */
export const CHROME_REVEAL_MS = 1000;

/** User-triggered recenter / chat focus — still gentle, shorter than first reveal. */
export const RECENTER_DURATION_SEC = 1.85;
export const FOCUS_DURATION_SEC = 1.45;

/**
 * Progressive reveal while an assessment runs (or when opening a finished AOI):
 * idle → flying → pre → post → polygons → settled
 */
export type MapRevealPhase = "idle" | "flying" | "pre" | "post" | "polygons" | "settled";

export type PipelineProgressHint = {
  status?: string | null;
  currentStep?: string | null;
  completedSteps?: string[];
};

export type MapRevealReadiness = {
  canFly: boolean;
  canPre: boolean;
  canPost: boolean;
  canPolygons: boolean;
};

const REVEAL_ORDER: Record<MapRevealPhase, number> = {
  idle: 0,
  flying: 1,
  pre: 2,
  post: 3,
  polygons: 4,
  settled: 5,
};

export function revealPhaseOrder(phase: MapRevealPhase): number {
  return REVEAL_ORDER[phase];
}

export function deriveMapRevealReadiness(input: {
  bounds?: [number, number, number, number] | null;
  imagery?: { pre?: boolean; post?: boolean } | null;
  hasBuildings?: boolean;
  progress?: PipelineProgressHint | null;
}): MapRevealReadiness {
  const completed = new Set(input.progress?.completedSteps ?? []);
  const current = String(input.progress?.currentStep ?? "");
  const status = String(input.progress?.status ?? "");
  const passive =
    !input.progress ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled";
  const done = (step: string) =>
    passive || completed.has(step) || current === step;

  const hasBounds = Boolean(input.bounds);
  const hasPre = Boolean(input.imagery?.pre);
  const hasPost = Boolean(input.imagery?.post);
  const hasBuildings = Boolean(input.hasBuildings);

  // Prefer real artifacts over step names: once aligned files exist, reveal can proceed
  // even if the job timeline is slightly behind.
  const alignReady =
    passive ||
    done("align") ||
    done("match_pre") ||
    done("location") ||
    done("preprocessing") ||
    done("route") ||
    hasPre ||
    hasPost;

  return {
    canFly: hasBounds,
    canPre: hasPre && alignReady,
    canPost: hasPost && alignReady,
    canPolygons:
      hasBuildings &&
      (passive ||
        done("fusion") ||
        done("footprints") ||
        done("perception") ||
        done("visualization") ||
        hasBuildings),
  };
}

export function easeInOutCubic(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

export function animateOpacity(
  from: number,
  to: number,
  durationMs: number,
  onFrame: (value: number) => void,
  onDone?: () => void,
): () => void {
  let raf = 0;
  const start = performance.now();
  const tick = (now: number) => {
    const t = Math.min(1, (now - start) / durationMs);
    onFrame(from + (to - from) * easeInOutCubic(t));
    if (t < 1) {
      raf = requestAnimationFrame(tick);
    } else {
      onDone?.();
    }
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}
