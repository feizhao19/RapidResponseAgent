import type { AoiDetail } from "./api/client";
import { BUILDING_SCOPE_HINTS, BUILDING_SCOPE_LABELS, type BuildingScope } from "./buildingScope";

function stripSevereBuildingsSection(markdown: string): string {
  return markdown.replace(
    /\n## Most Severely Affected Buildings\n[\s\S]*?(?=\n## |\s*$)/,
    "",
  );
}

/** Split report markdown so the severe-buildings table can be rendered interactively in the UI. */
export function splitReportMarkdown(markdown: string): { head: string; tail: string } {
  const cleaned = stripSevereBuildingsSection(markdown);
  const idx = cleaned.indexOf("\n## Limitations");
  if (idx === -1) {
    return { head: cleaned, tail: "" };
  }
  return { head: cleaned.slice(0, idx), tail: cleaned.slice(idx) };
}

export function resolveReportMarkdown(
  detail: AoiDetail | null,
  scope: BuildingScope,
): string | null {
  if (!detail) return null;

  if (scope === "official") {
    return detail.report_markdown_official ?? detail.report_markdown ?? null;
  }

  // Fused and VLM-reviewed views share the fused narrative for now; map/stats use VLM overrides.
  return detail.report_markdown_fused ?? detail.report_markdown ?? null;
}

export function reportScopeNote(scope: BuildingScope): string {
  return `View: ${BUILDING_SCOPE_LABELS[scope]} — ${BUILDING_SCOPE_HINTS[scope]}`;
}
