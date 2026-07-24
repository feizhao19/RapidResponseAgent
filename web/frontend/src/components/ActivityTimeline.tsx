import { useMemo, useState } from "react";
import type { ActivityItem } from "../api/client";

type Props = {
  items: ActivityItem[];
  live?: boolean;
};

function summarize(items: ActivityItem[]): string {
  const tools = items.filter((item) => item.tool);
  if (tools.length > 0) {
    return `Used ${tools.length} tool${tools.length === 1 ? "" : "s"}`;
  }
  if (items.some((item) => item.phase === "answering")) {
    return "Answered";
  }
  if (items.length > 0) {
    return items[items.length - 1]?.label.replace(/…$/, "") || "Done";
  }
  return "Done";
}

export function ActivityTimeline({ items, live = false }: Props) {
  const [expanded, setExpanded] = useState(false);
  const running = live && items.some((item) => item.status === "running");
  const summary = useMemo(() => summarize(items), [items]);

  if (!items.length) return null;

  const showList = live || expanded;

  return (
    <div className={`activity-timeline ${live ? "is-live" : "is-done"}`}>
      {!live && (
        <button
          type="button"
          className="activity-timeline-summary"
          onClick={() => setExpanded((current) => !current)}
          aria-expanded={expanded}
        >
          <span className="activity-timeline-chevron" aria-hidden="true">
            {expanded ? "▾" : "▸"}
          </span>
          <span>{summary}</span>
        </button>
      )}
      {showList && (
        <ul className="activity-timeline-list">
          {items.map((item) => (
            <li
              key={item.id}
              className={`activity-timeline-item status-${item.status}${
                item.status === "running" && running ? " is-pulse" : ""
              }`}
            >
              <span className="activity-timeline-marker" aria-hidden="true">
                {item.status === "done" ? "✓" : "·"}
              </span>
              <span className="activity-timeline-label">{item.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
