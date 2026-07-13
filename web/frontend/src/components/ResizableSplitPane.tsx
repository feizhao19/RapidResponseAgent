import { useEffect, useRef, useState, type ReactNode } from "react";

type Props = {
  left: ReactNode;
  right: ReactNode;
  defaultLeftWidth?: number;
  minLeft?: number;
  minRight?: number;
  storageKey?: string;
};

function readStoredWidth(storageKey: string | undefined, fallback: number): number {
  if (!storageKey) return fallback;
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return fallback;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export function ResizableSplitPane({
  left,
  right,
  defaultLeftWidth = 360,
  minLeft = 280,
  minRight = 360,
  storageKey = "geoagent.split.chatWidth",
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const leftWidthRef = useRef(readStoredWidth(storageKey, defaultLeftWidth));
  const [leftWidth, setLeftWidth] = useState(leftWidthRef.current);

  useEffect(() => {
    leftWidthRef.current = leftWidth;
  }, [leftWidth]);

  useEffect(() => {
    function clampWidth(raw: number): number {
      const container = containerRef.current;
      if (!container) return raw;
      const maxLeft = Math.max(minLeft, container.clientWidth - minRight - 6);
      return Math.min(maxLeft, Math.max(minLeft, raw));
    }

    function onPointerMove(event: PointerEvent) {
      if (!draggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      setLeftWidth(clampWidth(event.clientX - rect.left));
    }

    function stopDragging() {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      if (storageKey) {
        try {
          localStorage.setItem(storageKey, String(Math.round(leftWidthRef.current)));
        } catch {
          // ignore quota errors
        }
      }
    }

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [minLeft, minRight, storageKey]);

  useEffect(() => {
    function onResize() {
      const container = containerRef.current;
      if (!container) return;
      const maxLeft = Math.max(minLeft, container.clientWidth - minRight - 6);
      setLeftWidth((current) => Math.min(maxLeft, current));
    }

    window.addEventListener("resize", onResize);
    onResize();
    return () => window.removeEventListener("resize", onResize);
  }, [minLeft, minRight]);

  function startDragging(event: React.PointerEvent<HTMLDivElement>) {
    if (window.matchMedia("(max-width: 960px)").matches) return;
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  return (
    <div className="split-pane" ref={containerRef}>
      <div className="split-pane-left" style={{ width: leftWidth }}>
        {left}
      </div>
      <div
        className="split-pane-divider"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panels"
        aria-valuemin={minLeft}
        aria-valuemax={containerRef.current ? containerRef.current.clientWidth - minRight : undefined}
        aria-valuenow={leftWidth}
        onPointerDown={startDragging}
      />
      <div className="split-pane-right">{right}</div>
    </div>
  );
}
