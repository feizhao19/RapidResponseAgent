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

/** Compact, user-facing labels — one idea per step. */
const STEP_CORE: Record<string, string> = {
  upload: "Uploading imagery",
  match_pre: "Matching pre imagery",
  align: "Aligning imagery",
  route: "Starting pipeline",
  preprocessing: "Preparing imagery",
  location: "Locating AOI",
  footprints: "Loading building footprints",
  perception: "Detecting damage",
  fusion: "Mapping damage to buildings",
  stats: "Summarizing impact",
  facilities: "Finding nearby facilities",
  report: "Writing report",
  visualization: "Rendering overlays",
  finalize: "Finishing up",
  vlm_arbitrate: "Visual verification",
};

const MARKER_START = "§RAPID_ASSESSMENT§";
const MARKER_END = "§END§";

export type AssessmentProgressView = {
  v: 1;
  status: "running" | "completed" | "failed" | string;
  percent: number;
  /** Short core step label shown under the bar. */
  step?: string | null;
  /** Optional secondary line (unit progress / error), already truncated. */
  detail?: string | null;
  aoiId?: string | null;
};

export function assessmentProgressMessageId(sessionId: string): string {
  return `assessment-progress-${sessionId}`;
}

export function ellipsize(text: string, max = 56): string {
  const cleaned = text.trim().replace(/\s+/g, " ");
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, Math.max(1, max - 1)).trimEnd()}…`;
}

export function encodeAssessmentProgress(
  view: AssessmentProgressView,
  reportMarkdown?: string | null,
): string {
  const payload = JSON.stringify({
    v: 1,
    status: view.status,
    percent: view.percent,
    step: view.step ?? null,
    detail: view.detail ?? null,
    aoiId: view.aoiId ?? null,
  } satisfies AssessmentProgressView);
  const block = `${MARKER_START}${payload}${MARKER_END}`;
  if (reportMarkdown?.trim()) {
    return `${block}\n\n---\n\n${reportMarkdown.trim()}`;
  }
  return block;
}

export function parseAssessmentProgress(
  content: string,
): { view: AssessmentProgressView; reportMarkdown: string | null } | null {
  const start = content.indexOf(MARKER_START);
  if (start < 0) return null;
  const jsonStart = start + MARKER_START.length;
  const end = content.indexOf(MARKER_END, jsonStart);
  if (end < 0) return null;
  try {
    const raw = JSON.parse(content.slice(jsonStart, end)) as AssessmentProgressView;
    if (!raw || typeof raw !== "object" || raw.v !== 1) return null;
    const after = content.slice(end + MARKER_END.length).replace(/^\s*---\s*/, "").trim();
    return {
      view: {
        v: 1,
        status: String(raw.status || "running"),
        percent: Math.max(0, Math.min(100, Number(raw.percent) || 0)),
        step: raw.step ? ellipsize(String(raw.step), 48) : null,
        detail: raw.detail ? ellipsize(String(raw.detail), 64) : null,
        aoiId: raw.aoiId ? String(raw.aoiId) : null,
      },
      reportMarkdown: after || null,
    };
  } catch {
    return null;
  }
}

export function isAssessmentCompletionContent(content: string): boolean {
  const parsed = parseAssessmentProgress(content);
  if (parsed?.view.status === "completed") return true;
  return content.includes("**Assessment completed**");
}

function overallPercent(job: AssessmentJob, progress: JobProgress | undefined): number {
  if (job.status === "completed") return 100;
  const total = progress?.overall_total ?? 100;
  if (total <= 0) return 0;
  const current = progress?.overall_current ?? 0;
  return Math.max(0, Math.min(100, Math.round((current / total) * 100)));
}

function coreStepLabel(progress: JobProgress | undefined): string | null {
  const key = progress?.current_step;
  if (key && STEP_CORE[key]) return STEP_CORE[key];
  // Prefer backend current_label when step key is unknown (already humanized).
  const label = progress?.current_label?.trim();
  if (label) return ellipsize(label, 48);
  return null;
}

function unitDetail(progress: JobProgress | undefined): string | null {
  if (
    progress?.unit_total &&
    progress.unit_current != null &&
    progress.unit_current > 0
  ) {
    const label = (progress.unit_label || "units").trim();
    return ellipsize(`${progress.unit_current}/${progress.unit_total} ${label}`, 40);
  }
  // Align / match subtext when useful and not duplicating the step title.
  const message = progress?.message?.trim();
  const step = coreStepLabel(progress);
  if (message && step && !message.toLowerCase().startsWith(step.toLowerCase().slice(0, 12))) {
    return ellipsize(message, 64);
  }
  return null;
}

export function formatInitialAssessmentMarkdown(_userMessage?: string): string {
  return encodeAssessmentProgress({
    v: 1,
    status: "running",
    percent: 0,
    step: STEP_CORE.upload,
    detail: null,
  });
}

export function formatAssessmentJobMarkdown(
  job: AssessmentJob,
  reportMarkdown?: string | null,
): string {
  const progress = job.progress as JobProgress | undefined;
  const percent = overallPercent(job, progress);
  let status: AssessmentProgressView["status"] = "running";
  if (job.status === "completed") status = "completed";
  else if (job.status === "failed" || job.status === "cancelled") status = job.status;

  let step: string | null = null;
  let detail: string | null = null;

  if (status === "completed") {
    step = "Results ready";
  } else if (status === "failed") {
    step = "Assessment failed";
    detail = ellipsize((job.errors?.join("; ") || job.message || "Something went wrong").trim(), 64);
  } else {
    step = coreStepLabel(progress) || "Working…";
    detail = unitDetail(progress);
  }

  return encodeAssessmentProgress(
    {
      v: 1,
      status,
      percent,
      step,
      detail,
      aoiId: job.aoi_id ?? null,
    },
    status === "completed" ? reportMarkdown : null,
  );
}

/** Server / tests: compact completion payload without job ids. */
export function formatAssessmentCompletionView(
  aoiId: string,
  reportMarkdown?: string | null,
): string {
  return encodeAssessmentProgress(
    {
      v: 1,
      status: "completed",
      percent: 100,
      step: "Results ready",
      detail: null,
      aoiId,
    },
    reportMarkdown,
  );
}
