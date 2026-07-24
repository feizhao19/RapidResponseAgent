import type { ActivityItem, ActivityStatusEvent } from "./api/client";

/** Merge a live SSE status event into the activity list (keyed by tool or phase). */
export function applyActivityStatus(
  items: ActivityItem[],
  event: ActivityStatusEvent,
): ActivityItem[] {
  const label = (event.label || event.message || "Working…").trim();
  if (!label) return items;

  const phase = event.phase || "routing";
  const key = event.tool || phase;
  const status = event.status ?? "running";
  const nextItem: ActivityItem = {
    id: key,
    phase,
    label,
    tool: event.tool,
    detail: event.detail,
    status,
  };

  const existing = items.findIndex((item) => item.id === key);
  let next = [...items];
  if (existing >= 0) {
    next[existing] = { ...next[existing], ...nextItem };
  } else {
    next.push(nextItem);
  }

  if (status === "running") {
    next = next.map((item) =>
      item.id === key || item.status === "done" ? item : { ...item, status: "done" },
    );
  }
  return next;
}

export function finalizeActivity(items: ActivityItem[]): ActivityItem[] {
  return items.map((item) =>
    item.status === "done" ? item : { ...item, status: "done", label: item.label.replace(/…$/, "") },
  );
}
