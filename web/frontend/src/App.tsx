import { useEffect, useMemo, useRef, useState } from "react";
import {
  askRapidResponseAgent,
  createServerSession,
  deleteAoi,
  ensureServerSession,
  getAoiDetail,
  getAois,
  getAssessmentJob,
  getBuildingsGeoJson,
  getServerSession,
  cancelAssessmentJob,
  startVlmReview,
  uploadAssessment,
  LLM_MODEL_OPTIONS,
  type AoiDetail,
  type AoiRecord,
  type AssessmentJob,
  type AskResponse,
  type ChatMessage,
  type Hospital,
  type LlmModelId,
  type VlmReviewMode,
} from "./api/client";
import {
  appendSessionMessage,
  createChatSession,
  loadStoredSessions,
  mergeSessionFromServer,
  patchSession,
  storeSessions,
  upsertSessionMessage,
  type ChatSession,
} from "./chatSessions";
import {
  assessmentProgressMessageId,
  formatAssessmentJobMarkdown,
  formatInitialAssessmentMarkdown,
} from "./assessmentJobMessage";
import { formatAssessedCaseLabel } from "./caseLabel";
import { ChatPanel } from "./components/ChatPanel";
import { DetailScrollView } from "./components/DetailScrollView";
import { ResizableSplitPane } from "./components/ResizableSplitPane";
import type { MapFocus } from "./mapFocus";
import { toMapFocus, type HospitalMapDeepLink } from "./mapDeepLink";

function intentMeta(response: AskResponse): string {
  if (!response.intent) return "RapidResponseAgent";
  const confidence =
    response.intent_confidence != null ? ` · ${(response.intent_confidence * 100).toFixed(0)}%` : "";
  const tools =
    response.tools_called && response.tools_called.length > 0
      ? ` · ${response.tools_called.join(", ")}`
      : "";
  return `${response.intent}${confidence}${tools}`;
}

function formatAnswer(response: AskResponse): string {
  if (response.answer_markdown) return response.answer_markdown;
  if (response.clarification) return response.clarification;
  if (response.errors?.length) return response.errors.join("\n");
  return "No answer returned.";
}

function initialSessionsState(): { sessions: ChatSession[]; activeSessionId: string } {
  const stored = loadStoredSessions();
  if (stored) return stored;
  const session = createChatSession();
  return { sessions: [session], activeSessionId: session.id };
}

const LLM_MODEL_STORAGE_KEY = "geoagent.chat.llmModel";

function readStoredLlmModel(): LlmModelId {
  try {
    const raw = localStorage.getItem(LLM_MODEL_STORAGE_KEY);
    if (raw && LLM_MODEL_OPTIONS.some((option) => option.id === raw)) {
      return raw as LlmModelId;
    }
  } catch {
    // ignore storage errors
  }
  return LLM_MODEL_OPTIONS[0].id;
}

export default function App() {
  const [{ sessions, activeSessionId }, setConversation] = useState(initialSessionsState);
  const [records, setRecords] = useState<AoiRecord[]>([]);
  const [selectedAoiId, setSelectedAoiId] = useState<string>("");
  const [detail, setDetail] = useState<AoiDetail | null>(null);
  const [buildingsCache, setBuildingsCache] = useState<
    Record<string, GeoJSON.FeatureCollection>
  >({});
  const [buildingsLoading, setBuildingsLoading] = useState(false);
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [llmModel, setLlmModel] = useState<LlmModelId>(readStoredLlmModel);
  const [error, setError] = useState<string | null>(null);
  const [chatMapFocus, setChatMapFocus] = useState<MapFocus | null>(null);
  const [vlmJob, setVlmJob] = useState<AssessmentJob | null>(null);
  const [vlmBusy, setVlmBusy] = useState(false);
  const askAbortRef = useRef<AbortController | null>(null);
  const sessionsRef = useRef(sessions);
  const chatMapFocusKeyRef = useRef(0);
  const vlmPollRef = useRef<number | null>(null);

  useEffect(() => {
    sessionsRef.current = sessions;
    storeSessions(sessions, activeSessionId);
  }, [sessions, activeSessionId]);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? sessions[0],
    [sessions, activeSessionId],
  );

  const loading = loadingSessionId === activeSessionId;

  async function hydrateSession(sessionId: string) {
    try {
      const server = await getServerSession(sessionId);
      setSessions((prev) =>
        prev.map((session) =>
          session.id === sessionId ? mergeSessionFromServer(session, server) : session,
        ),
      );
    } catch {
      // Session may not exist on server yet.
    }
  }

  function setSessions(updater: (prev: ChatSession[]) => ChatSession[]) {
    setConversation((prev) => ({
      ...prev,
      sessions: updater(prev.sessions),
    }));
  }

  async function refreshAois(preferredAoiId?: string) {
    const payload = await getAois();
    setRecords(payload.records);
    if (preferredAoiId && payload.records.some((record) => record.aoi_id === preferredAoiId)) {
      setSelectedAoiId(preferredAoiId);
    } else if (payload.records.length > 0) {
      setSelectedAoiId((current) =>
        current && payload.records.some((record) => record.aoi_id === current)
          ? current
          : payload.records[0].aoi_id,
      );
    } else {
      setSelectedAoiId("");
      setDetail(null);
    }

    void Promise.all(
      payload.records.map(async (record) => {
        try {
          const geojson = await getBuildingsGeoJson(record.aoi_id);
          setBuildingsCache((prev) =>
            prev[record.aoi_id] ? prev : { ...prev, [record.aoi_id]: geojson },
          );
        } catch {
          // Some AOIs may not have buildings yet.
        }
      }),
    );
  }

  useEffect(() => {
    refreshAois().catch((err: Error) => setError(err.message));
    void (async () => {
      await Promise.all(
        sessionsRef.current.map((session) => ensureServerSession(session.id, session.title)),
      );
      await Promise.all(sessionsRef.current.map((session) => hydrateSession(session.id)));
    })();
  }, []);

  useEffect(() => {
    if (!selectedAoiId) return;

    let cancelled = false;
    setDetail(null);
    setBuildingsLoading(!buildingsCache[selectedAoiId]);

    const buildingsPromise = buildingsCache[selectedAoiId]
      ? Promise.resolve(buildingsCache[selectedAoiId])
      : getBuildingsGeoJson(selectedAoiId)
          .then((geojson) => {
            if (!cancelled) {
              setBuildingsCache((prev) => ({ ...prev, [selectedAoiId]: geojson }));
            }
            return geojson;
          })
          .catch(() => null);

    Promise.allSettled([getAoiDetail(selectedAoiId), buildingsPromise])
      .then((results) => {
        const detailResult = results[0];
        if (!cancelled && detailResult.status === "fulfilled") {
          setDetail(detailResult.value);
        } else if (!cancelled && detailResult.status === "rejected") {
          setError(detailResult.reason instanceof Error ? detailResult.reason.message : "Failed to load AOI");
        }
      })
      .finally(() => {
        if (!cancelled) setBuildingsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedAoiId]);

  const selectedRecord = useMemo(
    () => records.find((record) => record.aoi_id === selectedAoiId),
    [records, selectedAoiId],
  );

  const bounds = useMemo(() => {
    if (detail?.aoi_id !== selectedAoiId) return undefined;
    if (detail.imagery_bounds_wgs84) {
      return detail.imagery_bounds_wgs84;
    }
    const loc = detail.location as { bounds_wgs84?: [number, number, number, number] } | undefined;
    return loc?.bounds_wgs84;
  }, [detail, selectedAoiId]);

  const mapCenter = useMemo((): [number, number] => {
    if (bounds) {
      return [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2];
    }
    const centroid = selectedRecord?.location?.centroid_wgs84;
    if (centroid) return [centroid[1], centroid[0]];
    return [34.082889, -118.598699];
  }, [bounds, selectedRecord]);

  function handleNewSession() {
    askAbortRef.current?.abort();
    askAbortRef.current = null;
    setLoadingSessionId(null);
    setError(null);
    const session = createChatSession();
    void createServerSession({ sessionId: session.id, title: session.title }).catch(
      (err: Error) => setError(err.message),
    );
    setConversation((prev) => ({
      sessions: [session, ...prev.sessions],
      activeSessionId: session.id,
    }));
  }

  function handleSelectSession(sessionId: string) {
    if (sessionId === activeSessionId) return;
    askAbortRef.current?.abort();
    askAbortRef.current = null;
    setLoadingSessionId(null);
    setConversation((prev) => ({ ...prev, activeSessionId: sessionId }));
    void hydrateSession(sessionId);
  }

  function handleDeleteSession(sessionId: string) {
    askAbortRef.current?.abort();
    askAbortRef.current = null;
    setLoadingSessionId(null);
    setConversation((prev) => {
      const remaining = prev.sessions.filter((session) => session.id !== sessionId);
      if (remaining.length === 0) {
        const session = createChatSession();
        return { sessions: [session], activeSessionId: session.id };
      }
      const activeSessionId =
        prev.activeSessionId === sessionId ? remaining[0].id : prev.activeSessionId;
      return { sessions: remaining, activeSessionId };
    });
  }

  function handleLlmModelChange(model: LlmModelId) {
    setLlmModel(model);
    try {
      localStorage.setItem(LLM_MODEL_STORAGE_KEY, model);
    } catch {
      // ignore quota errors
    }
  }

  async function handleAsk(question: string) {
    const sessionId = activeSessionId;
    askAbortRef.current?.abort();

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
    };
    setSessions((prev) => appendSessionMessage(prev, sessionId, userMessage));
    setLoadingSessionId(sessionId);
    setError(null);

    const controller = new AbortController();
    askAbortRef.current = controller;

    const current = sessionsRef.current.find((session) => session.id === sessionId);
    const history = (current?.messages ?? []).slice(-8).map((message) => ({
      role: message.role,
      content: message.content,
    }));

    try {
      const response = await askRapidResponseAgent(question, {
        signal: controller.signal,
        sessionId,
        history,
        model: llmModel,
        activeAoiId: selectedAoiId || undefined,
      });
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: formatAnswer(response),
        meta: intentMeta(response),
      };
      setSessions((prev) => appendSessionMessage(prev, sessionId, assistantMessage));
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setSessions((prev) =>
          appendSessionMessage(prev, sessionId, {
            id: crypto.randomUUID(),
            role: "assistant",
            content: "Generation stopped.",
            meta: "cancelled",
          }),
        );
        return;
      }
      const message = err instanceof Error ? err.message : "Request failed";
      setError(message);
      setSessions((prev) =>
        appendSessionMessage(prev, sessionId, {
          id: crypto.randomUUID(),
          role: "assistant",
          content: message,
          meta: "Error",
        }),
      );
    } finally {
      if (askAbortRef.current === controller) {
        askAbortRef.current = null;
      }
      setLoadingSessionId((currentId) => (currentId === sessionId ? null : currentId));
    }
  }

  function handleStopAsk() {
    askAbortRef.current?.abort();
  }

  async function pollAssessmentJob(sessionId: string, jobId: string) {
    const terminal = new Set(["completed", "failed"]);
    const progressId = assessmentProgressMessageId(sessionId);

    function syncProgressMessage(job: AssessmentJob) {
      setSessions((prev) =>
        upsertSessionMessage(prev, sessionId, {
          id: progressId,
          role: "assistant",
          content: formatAssessmentJobMarkdown(job),
          meta: job.status === "completed" ? "new_assessment" : "Assessment",
        }),
      );
    }

    for (;;) {
      const job = await getAssessmentJob(jobId);
      setSessions((prev) => patchSession(prev, sessionId, { activeJob: job }));
      syncProgressMessage(job);
      if (terminal.has(job.status)) {
        if (job.status === "completed" && job.aoi_id) {
          setBuildingsCache((prev) => {
            const next = { ...prev };
            delete next[job.aoi_id!];
            return next;
          });
          await refreshAois(job.aoi_id);
          await hydrateSession(sessionId);
        } else if (job.status === "failed") {
          setError(job.errors?.join("; ") || job.message || "Assessment failed");
        }
        break;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
  }

  async function handleUpload(input: {
    post: File;
    pre: File | null;
    autoMatchPre: boolean;
    message: string;
  }) {
    const sessionId = activeSessionId;
    const progressId = assessmentProgressMessageId(sessionId);
    setUploadBusy(true);
    setError(null);
    setSessions((prev) => patchSession(prev, sessionId, { activeJob: null }));

    setSessions((prev) =>
      appendSessionMessage(prev, sessionId, {
        id: crypto.randomUUID(),
        role: "user",
        content: input.message,
      }),
    );

    setSessions((prev) =>
      upsertSessionMessage(prev, sessionId, {
        id: progressId,
        role: "assistant",
        content: formatInitialAssessmentMarkdown(input.message),
        meta: "Assessment",
      }),
    );

    try {
      const job = await uploadAssessment({
        post: input.post,
        pre: input.pre,
        autoMatchPre: input.autoMatchPre,
        sessionId,
        message: input.message,
      });
      setSessions((prev) => patchSession(prev, sessionId, { activeJob: job }));
      setSessions((prev) =>
        upsertSessionMessage(prev, sessionId, {
          id: progressId,
          role: "assistant",
          content: formatAssessmentJobMarkdown(job),
          meta: "Assessment",
        }),
      );
      await pollAssessmentJob(sessionId, job.job_id);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed";
      setError(message);
      setSessions((prev) =>
        upsertSessionMessage(prev, sessionId, {
          id: progressId,
          role: "assistant",
          content: message,
          meta: "Error",
        }),
      );
    } finally {
      setUploadBusy(false);
    }
  }

  async function handleDeleteAoi(aoiId: string) {
    const record = records.find((item) => item.aoi_id === aoiId);
    const label = record ? formatAssessedCaseLabel(record) : aoiId;
    if (
      !window.confirm(
        `Delete "${label}"?\n\nThis permanently removes the assessment data from this server.`,
      )
    ) {
      return;
    }
    setError(null);
    try {
      await deleteAoi(aoiId);
      setBuildingsCache((prev) => {
        const next = { ...prev };
        delete next[aoiId];
        return next;
      });
      const remaining = records.filter((item) => item.aoi_id !== aoiId);
      const nextSelected =
        selectedAoiId === aoiId ? (remaining[0]?.aoi_id ?? "") : selectedAoiId;
      if (selectedAoiId === aoiId) {
        setDetail(null);
        setSelectedAoiId(nextSelected);
      }
      await refreshAois(nextSelected || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  function handleHospitalMapLink(link: HospitalMapDeepLink) {
    chatMapFocusKeyRef.current += 1;
    setChatMapFocus(toMapFocus(link, chatMapFocusKeyRef.current));
  }

  useEffect(() => {
    setVlmJob(null);
    setVlmBusy(false);
    if (vlmPollRef.current != null) {
      window.clearTimeout(vlmPollRef.current);
      vlmPollRef.current = null;
    }
  }, [selectedAoiId]);

  useEffect(() => {
    return () => {
      if (vlmPollRef.current != null) {
        window.clearTimeout(vlmPollRef.current);
      }
    };
  }, []);

  async function refreshSelectedDetail() {
    if (!selectedAoiId) return;
    const next = await getAoiDetail(selectedAoiId);
    setDetail(next);
  }

  async function pollVlmJob(jobId: string, aoiId: string) {
    const terminal = new Set(["completed", "failed", "cancelled"]);
    try {
      const job = await getAssessmentJob(jobId);
      setVlmJob(job);
      if (!terminal.has(job.status)) {
        vlmPollRef.current = window.setTimeout(() => {
          void pollVlmJob(jobId, aoiId);
        }, 2500);
        return;
      }
      setVlmBusy(false);
      if (job.status === "completed" && selectedAoiId === aoiId) {
        await refreshSelectedDetail();
      }
      if (job.status === "failed") {
        setError(job.message || job.errors?.[0] || "VLM review failed");
      }
    } catch (err) {
      setVlmBusy(false);
      setError(err instanceof Error ? err.message : "VLM job poll failed");
    }
  }

  async function handleRunVlm(
    mode: VlmReviewMode,
    options?: { damagedOnly?: boolean },
  ) {
    if (!selectedAoiId || vlmBusy) return;
    setError(null);
    setVlmBusy(true);
    try {
      const job = await startVlmReview(selectedAoiId, {
        mode,
        limit: 8,
        damagedOnly: options?.damagedOnly ?? true,
        sessionId: activeSessionId,
      });
      setVlmJob(job);
      void pollVlmJob(job.job_id, selectedAoiId);
    } catch (err) {
      setVlmBusy(false);
      setError(err instanceof Error ? err.message : "Failed to start VLM review");
    }
  }

  async function handleStopVlm() {
    const jobId = vlmJob?.job_id;
    if (!jobId) return;
    try {
      const job = await cancelAssessmentJob(jobId);
      setVlmJob(job);
      setVlmBusy(false);
      if (vlmPollRef.current != null) {
        window.clearTimeout(vlmPollRef.current);
        vlmPollRef.current = null;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to stop VLM review");
    }
  }

  const hospitals = (detail?.hospitals?.hospitals ?? []) as Hospital[];

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>RapidResponseAgent</h1>
          <p>
            <a href="https://github.com/feizhao19/RapidDamageAssessment" target="_blank" rel="noreferrer">
              ViPDE
            </a>
            -powered post-disaster assessment · Author:{" "}
            <a href="https://feizhao19.github.io/" target="_blank" rel="noreferrer" className="app-header-author">
              Dr. Fei Zhao
            </a>
          </p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="app-body">
        <ResizableSplitPane
          left={
            <ChatPanel
              sessions={sessions}
              activeSessionId={activeSessionId}
              messages={activeSession?.messages ?? []}
              records={records}
              selectedAoiId={selectedAoiId}
              loading={loading}
              uploadBusy={uploadBusy}
              llmModel={llmModel}
              onLlmModelChange={handleLlmModelChange}
              onNewSession={handleNewSession}
              onSelectSession={handleSelectSession}
              onDeleteSession={handleDeleteSession}
              onSelectAoi={setSelectedAoiId}
              onDeleteAoi={handleDeleteAoi}
              onSend={handleAsk}
              onStop={handleStopAsk}
              onUpload={handleUpload}
              onHospitalMapLink={handleHospitalMapLink}
            />
          }
          right={
            selectedAoiId ? (
              <DetailScrollView
                aoiId={selectedAoiId}
                detail={detail?.aoi_id === selectedAoiId ? detail : null}
                bounds={bounds}
                imageryCorners={
                  detail?.aoi_id === selectedAoiId ? (detail.imagery_corners_wgs84 ?? null) : null
                }
                buildingsGeojson={buildingsCache[selectedAoiId] ?? null}
                detectedExtraCount={selectedRecord?.summary?.buildings_detected}
                detailLoading={!detail || detail.aoi_id !== selectedAoiId}
                mapCenter={mapCenter}
                hospitals={hospitals}
                externalMapFocus={chatMapFocus}
                onRunVlm={handleRunVlm}
                onStopVlm={handleStopVlm}
                vlmJob={vlmJob}
                vlmBusy={vlmBusy}
              />
            ) : (
              <div className="detail-panel detail-panel-empty">
                <p>Select an AOI to view assessment details.</p>
              </div>
            )
          }
        />
        {buildingsLoading && selectedAoiId && !buildingsCache[selectedAoiId] && (
          <div className="sr-only" aria-live="polite">
            Loading building footprints…
          </div>
        )}
      </div>
    </div>
  );
}
