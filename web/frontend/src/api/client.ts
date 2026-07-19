export type AoiRecord = {
  aoi_id: string;
  event: string;
  case_label?: string;
  generated_at?: string;
  post_image?: string;
  location: {
    display_name?: string;
    city?: string;
    county?: string;
    state?: string;
    neighbourhood?: string;
    neighborhood?: string;
    centroid_wgs84?: [number, number];
  };
  summary: {
    buildings_total?: number;
    buildings_official?: number;
    buildings_detected?: number;
    damaged_count?: number;
    damaged_pct?: number;
    severe_count?: number;
    severe_pct?: number;
    destroyed_count?: number;
    destroyed_pct?: number;
  };
  fusion_mode?: string;
};

export type AoiDetail = AoiRecord & {
  stats?: Record<string, unknown>;
  location?: Record<string, unknown>;
  hospitals?: { hospitals?: Hospital[]; nearest?: Hospital };
  report_markdown?: string;
  report_markdown_official?: string;
  report_markdown_fused?: string;
  imagery_bounds_wgs84?: [number, number, number, number];
  imagery_corners_wgs84?: {
    topLeft: [number, number];
    topRight: [number, number];
    bottomLeft: [number, number];
  };
  imagery?: { pre?: boolean; post?: boolean };
  artifacts?: Record<string, string | null>;
  vlm_arbitration?: VlmArbitrationSummary;
  vlm_damage_review?: VlmDamageReviewSummary;
};

export type VlmEnsembleView = {
  transform?: string;
  recommendation?: string;
  judgment?: VlmJudgment;
  error?: string | null;
};

export type VlmEnsembleSummary = {
  enabled?: boolean;
  view_count?: number;
  successful_views?: number;
  vote_counts?: Record<string, number>;
  winning_recommendation?: string;
  views?: VlmEnsembleView[];
  synthesis_error?: string | null;
};

export type VlmJudgment = {
  short_description?: string;
  pre_description?: string;
  post_description?: string;
  rationale?: string;
  building_present?: boolean | string | null;
  building_damaged?: boolean | string | null;
  recommendation?: string;
  needs_field_check?: boolean;
  hypothesis?: string;
  hypothesis_source?: string;
  prompted_from_default?: string;
};

export type VlmHumanPreference = {
  decision?: "agree" | "disagree" | string;
  chosen_role?: "default" | "counterfactual" | string;
  rejected_role?: "default" | "counterfactual" | string;
  created_at?: string;
  session_id?: string | null;
};

export type VlmArbitrationResult = {
  feature_id: string;
  kind: "fp_orphan" | "fn_inferred" | "damage_predicted" | string;
  area?: number;
  damage_label?: string;
  image_source?: "pre" | "pre_post" | string;
  pre_chip?: string;
  pre_chip_url?: string;
  post_chip?: string;
  post_chip_url?: string;
  properties?: Record<string, unknown>;
  vlm?: VlmJudgment;
  default_response?: VlmJudgment;
  counterfactual?: VlmJudgment;
  human_preference?: VlmHumanPreference | null;
  ensemble?: VlmEnsembleSummary;
  vlm_raw?: string;
  error?: string | null;
  dry_run?: boolean;
};

export type VlmArbitrationSummary = {
  aoi_id?: string;
  created_at?: string;
  image_source?: "pre" | string;
  candidate_count?: number;
  dry_run?: boolean;
  ensemble_enabled?: boolean;
  counts_by_kind?: Record<string, number>;
  results?: VlmArbitrationResult[];
};

export type VlmDamageReviewSummary = {
  aoi_id?: string;
  created_at?: string;
  image_source?: "pre_post" | string;
  review_type?: "damage" | string;
  candidate_count?: number;
  dry_run?: boolean;
  ensemble_enabled?: boolean;
  counts_by_pipeline_label?: Record<string, number>;
  counts_by_recommendation?: Record<string, number>;
  results?: VlmArbitrationResult[];
};

export type Hospital = {
  name: string;
  distance_km?: number;
  distance_mi?: number;
  phone?: string;
  website?: string;
  operator?: string;
  address?: string | null;
  coordinates_wgs84?: [number, number];
  latitude?: number;
  longitude?: number;
};

export type ChatTurn = {
  role: "user" | "assistant";
  content: string;
};

export const LLM_MODEL_OPTIONS = [
  { id: "meta-llama/Llama-3.2-1B-Instruct", label: "Llama 3.2 1B (fast)" },
  { id: "meta-llama/Meta-Llama-3.1-8B-Instruct", label: "Llama 3.1 8B (quality)" },
  { id: "meta-llama/Llama-3.2-11B-Vision-Instruct", label: "Llama 3.2 11B Vision (3.1 backbone, ~20GB)" },
] as const;

export type LlmModelId = (typeof LLM_MODEL_OPTIONS)[number]["id"];

export type AskResponse = {
  session_id?: string;
  intent?: string;
  intent_confidence?: number;
  intent_method?: string;
  intent_rationale?: string;
  clarification?: string;
  answer_markdown?: string;
  tools_called?: string[];
  artifacts_used?: string[];
  steps_run?: string[];
  active_aoi_id?: string;
  episode_id?: string;
  historical?: Record<string, unknown>;
  weather?: Record<string, unknown>;
  pipeline?: Record<string, unknown>;
  errors?: string[];
};

export type ServerSession = {
  session_id: string;
  title: string;
  active_aoi_id?: string | null;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta?: string;
};

export type AssessmentJob = {
  job_id: string;
  aoi_id?: string;
  session_id?: string;
  status: "queued" | "aligning" | "running" | "completed" | "failed" | "cancelled" | string;
  message?: string;
  job_kind?: string;
  vlm_mode?: "both" | "discrepancy" | "damage" | string;
  vlm_limit?: number;
  vlm_damaged_only?: boolean;
  auto_match_pre?: boolean;
  pre_match?: {
    quad?: string;
    date?: string;
    catalog?: string;
    overlap_ratio?: number;
    source?: string;
  };
  valid_pair_coverage?: number;
  completed_steps?: string[];
  progress?: {
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
  errors?: string[];
  aligned_dir?: string;
  queue_position?: number;
  created_at?: string;
  updated_at?: string;
};

export type VlmReviewMode = "both" | "discrepancy" | "damage";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err;
    }
    throw err;
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getAois(): Promise<{ records: AoiRecord[] }> {
  return fetchJson("/api/aois");
}

export async function getAoiDetail(aoiId: string): Promise<AoiDetail> {
  return fetchJson(`/api/aois/${encodeURIComponent(aoiId)}`);
}

export async function deleteAoi(aoiId: string): Promise<{
  aoi_id: string;
  deleted_files: boolean;
  remaining_aoi_count: number;
}> {
  return fetchJson(`/api/aois/${encodeURIComponent(aoiId)}`, { method: "DELETE" });
}

export async function getBuildingsGeoJson(aoiId: string): Promise<GeoJSON.FeatureCollection> {
  return fetchJson(`/api/aois/${encodeURIComponent(aoiId)}/buildings`);
}

export async function createServerSession(input: {
  title?: string;
  sessionId?: string;
}): Promise<ServerSession> {
  return fetchJson("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: input.title ?? "New chat",
      session_id: input.sessionId,
    }),
  });
}

export async function getServerSession(sessionId: string): Promise<ServerSession> {
  return fetchJson(`/api/sessions/${encodeURIComponent(sessionId)}`);
}

export async function ensureServerSession(sessionId: string, title = "New chat"): Promise<void> {
  try {
    await getServerSession(sessionId);
  } catch {
    await createServerSession({ sessionId, title });
  }
}

export async function askRapidResponseAgent(
  question: string,
  options?: {
    useLlm?: boolean;
    retrieveOnly?: boolean;
    model?: LlmModelId;
    sessionId?: string;
    activeAoiId?: string;
    history?: ChatTurn[];
    signal?: AbortSignal;
  },
): Promise<AskResponse> {
  return fetchJson("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      session_id: options?.sessionId,
      active_aoi_id: options?.activeAoiId || undefined,
      history: options?.history ?? [],
      use_llm: options?.useLlm ?? true,
      retrieve_only: options?.retrieveOnly ?? false,
      model: options?.model,
    }),
    signal: options?.signal,
  });
}

export function dataAssetUrl(relPath: string): string {
  return `/api/data/${relPath.split("/").map(encodeURIComponent).join("/")}`;
}

export function buildingChipUrl(aoiId: string, bldId: string, which: "pre" | "post"): string {
  return `/api/aois/${encodeURIComponent(aoiId)}/buildings/${encodeURIComponent(bldId)}/chip/${which}`;
}

export async function uploadAssessment(input: {
  post: File;
  pre?: File | null;
  autoMatchPre: boolean;
  sessionId?: string;
  message?: string;
}): Promise<AssessmentJob> {
  const form = new FormData();
  form.append("post", input.post);
  if (input.pre) {
    form.append("pre", input.pre);
  }
  form.append("auto_match_pre", String(input.autoMatchPre));
  if (input.sessionId) {
    form.append("session_id", input.sessionId);
  }
  if (input.message) {
    form.append("message", input.message);
  }

  const response = await fetch("/api/assessments/upload", {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Upload failed: ${response.status}`);
  }
  return response.json() as Promise<AssessmentJob>;
}

export async function getAssessmentJob(jobId: string): Promise<AssessmentJob> {
  return fetchJson(`/api/assessments/jobs/${encodeURIComponent(jobId)}`);
}

export async function startVlmReview(
  aoiId: string,
  options?: {
    mode?: VlmReviewMode;
    limit?: number;
    damagedOnly?: boolean;
    sessionId?: string;
  },
): Promise<AssessmentJob> {
  return fetchJson(`/api/aois/${encodeURIComponent(aoiId)}/vlm-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: options?.mode ?? "both",
      limit: options?.limit ?? 2,
      damaged_only: options?.damagedOnly ?? true,
      session_id: options?.sessionId,
    }),
  });
}

export async function submitVlmPreference(
  aoiId: string,
  input: {
    reviewType: "discrepancy" | "damage";
    featureId: string;
    decision: "agree" | "disagree";
    sessionId?: string;
  },
): Promise<Record<string, unknown>> {
  return fetchJson(`/api/aois/${encodeURIComponent(aoiId)}/vlm-preference`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      review_type: input.reviewType,
      feature_id: input.featureId,
      decision: input.decision,
      session_id: input.sessionId,
    }),
  });
}

export async function cancelAssessmentJob(jobId: string): Promise<AssessmentJob> {
  return fetchJson(`/api/assessments/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}
