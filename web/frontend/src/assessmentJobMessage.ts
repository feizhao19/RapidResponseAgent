import type { AssessmentJob } from "./api/client";

export type JobProgress = {
  overall_current?: number;
  overall_total?: number;
  current_step?: string | null;
  current_label?: string | null;
  step_status?: string;
  message?: string | null;
  unit_current?: number | null;
  unit_total?: number | null;
  unit_label?: string | null;
  completed_steps?: string[];
  timeline?: Array<{
    step?: string;
    label?: string;
    status?: string;
    message?: string | null;
  }>;
};

const STEP_ORDER = [
  "upload",
  "align",
  "route",
  "preprocessing",
  "location",
  "perception",
  "fusion",
  "stats",
  "facilities",
  "report",
  "visualization",
  "finalize",
] as const;

const STEP_LABELS: Record<string, string> = {
  upload: "Upload received",
  align: "Aligning pre/post GeoTIFF pair",
  route: "Routing to assessment pipeline",
  preprocessing: "Preprocessing imagery",
  location: "Resolving location (geocoding)",
  perception: "ViPDE damage perception",
  fusion: "Fusing damage to building footprints",
  stats: "Computing AOI statistics",
  facilities: "Looking up nearest hospitals",
  report: "Generating assessment report",
  visualization: "Rendering map overlays",
  finalize: "Finalizing outputs",
};

export function formatPreMatch(job: AssessmentJob): string | null {
  const match = job.pre_match;
  if (!match) return null;
  const overlap =
    match.overlap_ratio != null ? `${(match.overlap_ratio * 100).toFixed(0)}% overlap` : "";
  return `Auto-matched pre: quad ${match.quad ?? "?"} · ${match.date ?? "?"} · ${overlap}`;
}

export function assessmentProgressMessageId(sessionId: string): string {
  return `assessment-progress-${sessionId}`;
}

export function formatInitialAssessmentMarkdown(userMessage: string): string {
  return [
    "**Running assessment**",
    "",
    "Uploading imagery and preparing your assessment…",
    "",
    `**Your request:** ${userMessage}`,
    "",
    "**Overall progress: 0/100**",
    "",
    "**Current step:** Upload received",
  ].join("\n");
}

function stepIcon(step: string, progress: JobProgress | undefined, job: AssessmentJob): string {
  const completed = new Set(progress?.completed_steps ?? job.completed_steps ?? []);
  if (completed.has(step)) return "✓";
  if (progress?.current_step === step) return "→";
  return "·";
}

function formatStepChecklist(progress: JobProgress | undefined, job: AssessmentJob): string {
  const lines = STEP_ORDER.map((step) => {
    const icon = stepIcon(step, progress, job);
    const label = STEP_LABELS[step] ?? step;
    const timeline = progress?.timeline?.find((item) => item.step === step);
    const detail = timeline?.message ? ` — ${timeline.message}` : "";
    return `${icon} ${label}${icon === "→" ? detail : ""}`;
  });
  return lines.join("\n\n");
}

export function formatAssessmentJobMarkdown(job: AssessmentJob): string {
  const progress = job.progress as JobProgress | undefined;
  const lines: string[] = [];

  if (job.status === "completed") {
    lines.push("**Assessment completed**");
  } else if (job.status === "failed") {
    lines.push("**Assessment failed**");
  } else {
    lines.push("**Running assessment**");
  }

  if (job.job_id) {
    lines.push(`Job \`${job.job_id}\` · ${job.status}`);
  } else {
    lines.push(`Status · ${job.status}`);
  }

  if (job.status === "completed") {
    lines.push("**Overall progress: 100/100**");
  } else if (progress?.overall_total) {
    const current = progress.overall_current ?? 0;
    lines.push(`**Overall progress: ${current}/${progress.overall_total}**`);
  }

  if (progress?.current_label && job.status !== "completed") {
    lines.push(`**Current step:** ${progress.current_label}`);
  }

  if (
    progress?.unit_total &&
    progress.unit_current != null &&
    progress.unit_current > 0
  ) {
    lines.push(
      `**${progress.unit_label ?? "Progress"}:** ${progress.unit_current}/${progress.unit_total}`,
    );
  }

  if (progress?.message || job.message) {
    lines.push(progress?.message || job.message || "");
  }

  const preMatch = formatPreMatch(job);
  if (preMatch) {
    lines.push(preMatch);
  }

  if (job.valid_pair_coverage != null) {
    lines.push(`Valid pair coverage: **${(job.valid_pair_coverage * 100).toFixed(1)}%**`);
  }

  lines.push("**Pipeline steps**");
  lines.push(formatStepChecklist(progress, job));

  if (job.errors && job.errors.length > 0) {
    lines.push(job.errors.join("; "));
  }

  if (job.status === "completed") {
    lines.push(`Results for **${job.aoi_id}** are loaded on the right.`);
  }

  return lines.filter(Boolean).join("\n\n");
}
