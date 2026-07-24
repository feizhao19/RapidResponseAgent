import type { ActivityItem, ActivityStatusEvent } from "./api/client";

function activityKey(event: ActivityStatusEvent): string {
  const phase = event.phase || "routing";
  if (event.tool && event.step) return `${event.tool}:${event.step}`;
  if (event.tool) return `tool:${event.tool}`;
  if (event.step) return `${phase}:${event.step}`;
  return phase;
}

/** Merge a live SSE status event into the activity list. */
export function applyActivityStatus(
  items: ActivityItem[],
  event: ActivityStatusEvent,
): ActivityItem[] {
  const label = (event.label || event.message || "Working…").trim();
  if (!label) return items;

  const phase = event.phase || "routing";
  const key = activityKey(event);
  const status = event.status ?? "running";
  const nextItem: ActivityItem = {
    id: key,
    phase,
    label,
    tool: event.tool,
    detail: event.detail,
    step: event.step,
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
    // Keep parent tool rows running while their sub-steps (request/wait) progress.
    next = next.map((item) => {
      if (item.id === key || item.status === "done") return item;
      if (key.startsWith(`${item.id}:`)) return item;
      return { ...item, status: "done" };
    });
  }
  return next;
}

export function finalizeActivity(items: ActivityItem[]): ActivityItem[] {
  return items.map((item) =>
    item.status === "done" ? item : { ...item, status: "done", label: item.label.replace(/…$/, "") },
  );
}
