import { useEffect, useId, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { AoiRecord, ChatMessage, LlmModelId } from "../api/client";
import { LLM_MODEL_OPTIONS } from "../api/client";
import { buildDefaultAnalysisPrompt } from "../assessmentPrompt";
import type { ChatSession } from "../chatSessions";
import { formatAssessedCaseLabel } from "../caseLabel";
import { parseHospitalMapDeepLink, type HospitalMapDeepLink } from "../mapDeepLink";

const SIDEBAR_COLLAPSED_KEY = "geoagent.chat.sidebarCollapsed";

function readSidebarCollapsed(): boolean {
  try {
    const raw = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (raw === null) return true;
    return raw === "true";
  } catch {
    return true;
  }
}

function storeSidebarCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "true" : "false");
  } catch {
    // ignore quota errors
  }
}

type Props = {
  sessions: ChatSession[];
  activeSessionId: string;
  messages: ChatMessage[];
  records: AoiRecord[];
  selectedAoiId: string;
  loading: boolean;
  uploadBusy: boolean;
  llmModel: LlmModelId;
  onLlmModelChange: (model: LlmModelId) => void;
  onNewSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onSelectAoi: (aoiId: string) => void;
  onDeleteAoi: (aoiId: string) => void;
  onSend: (text: string) => void;
  onStop: () => void;
  onUpload: (input: {
    post: File;
    pre: File | null;
    autoMatchPre: boolean;
    message: string;
  }) => void;
  onHospitalMapLink?: (link: HospitalMapDeepLink) => void;
};

export function ChatPanel({
  sessions,
  activeSessionId,
  messages,
  records,
  selectedAoiId,
  loading,
  uploadBusy,
  llmModel,
  onLlmModelChange,
  onNewSession,
  onSelectSession,
  onDeleteSession,
  onSelectAoi,
  onDeleteAoi,
  onSend,
  onStop,
  onUpload,
  onHospitalMapLink,
}: Props) {
  const [draft, setDraft] = useState("");
  const [postFile, setPostFile] = useState<File | null>(null);
  const [preFile, setPreFile] = useState<File | null>(null);
  const [autoMatchPre, setAutoMatchPre] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);
  const [sidebarPeek, setSidebarPeek] = useState(false);
  const postInputId = useId();
  const preInputId = useId();
  const lastAutoDraftRef = useRef("");
  const chatHistoryRef = useRef<HTMLDivElement>(null);

  const busy = loading || uploadBusy;
  const sidebarCompact = sidebarCollapsed && !sidebarPeek;
  const hasUpload = Boolean(postFile);
  const uploadReady = Boolean(postFile && (preFile || autoMatchPre));
  const canSend = !busy && (uploadReady || (!hasUpload && draft.trim().length > 0));

  useEffect(() => {
    if (!postFile) {
      setDraft((current) => (current === lastAutoDraftRef.current ? "" : current));
      lastAutoDraftRef.current = "";
      return;
    }

    const defaultText = buildDefaultAnalysisPrompt(postFile, preFile, autoMatchPre);
    setDraft((current) => {
      if (!current || current === lastAutoDraftRef.current) {
        lastAutoDraftRef.current = defaultText;
        return defaultText;
      }
      return current;
    });
  }, [postFile, preFile, autoMatchPre]);

  useEffect(() => {
    const container = chatHistoryRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [messages, loading, uploadBusy]);

  function collapseSidebar() {
    setSidebarPeek(false);
    setSidebarCollapsed(true);
    storeSidebarCollapsed(true);
  }

  function toggleSidebar() {
    setSidebarPeek(false);
    setSidebarCollapsed((current) => {
      const next = !current;
      storeSidebarCollapsed(next);
      return next;
    });
  }

  function handleSelectSession(sessionId: string) {
    onSelectSession(sessionId);
    collapseSidebar();
  }

  function handleSend(text: string) {
    onSend(text);
    collapseSidebar();
  }

  function clearAttachments() {
    setPostFile(null);
    setPreFile(null);
    setAutoMatchPre(true);
    setDraft((current) => (current === lastAutoDraftRef.current ? "" : current));
    lastAutoDraftRef.current = "";
  }

  function submit() {
    if (busy) return;

    if (uploadReady && postFile) {
      const message =
        draft.trim() ||
        buildDefaultAnalysisPrompt(postFile, preFile, preFile ? false : autoMatchPre);
      onUpload({
        post: postFile,
        pre: preFile,
        autoMatchPre: preFile ? false : autoMatchPre,
        message,
      });
      clearAttachments();
      collapseSidebar();
      return;
    }

    const text = draft.trim();
    if (!text) return;
    handleSend(text);
    setDraft("");
    lastAutoDraftRef.current = "";
  }

  return (
    <section className="chat-panel">
      <aside
        className={`chat-sidebar ${sidebarCompact ? "collapsed" : ""}`}
        aria-label="Conversations"
        onMouseEnter={() => {
          if (sidebarCollapsed) setSidebarPeek(true);
        }}
        onMouseLeave={() => setSidebarPeek(false)}
      >
        <div className="chat-sidebar-toolbar">
          <button
            type="button"
            className="chat-sidebar-toggle"
            onClick={toggleSidebar}
            aria-label={sidebarCompact ? "Expand conversations" : "Collapse conversations"}
            title={sidebarCompact ? "Expand conversations" : "Collapse conversations"}
          >
            {sidebarCompact ? "›" : "‹"}
          </button>
          {!sidebarCompact && <strong className="chat-sidebar-title">Conversations</strong>}
          <button
            type="button"
            className={`chat-new-btn ${sidebarCompact ? "icon-only" : ""}`}
            onClick={onNewSession}
            disabled={uploadBusy}
            title="New chat"
            aria-label="New chat"
          >
            +
            {!sidebarCompact && " New chat"}
          </button>
        </div>
        <div className="chat-session-list" role="tablist" aria-label="Chat sessions">
          {sessions.map((session) => {
            const active = session.id === activeSessionId;
            const preview =
              session.messages.length > 0
                ? `${session.messages.length} message${session.messages.length === 1 ? "" : "s"}`
                : "Empty";
            const initial = (session.title.trim().charAt(0) || "C").toUpperCase();

            if (sidebarCompact) {
              return (
                <button
                  key={session.id}
                  type="button"
                  className={`chat-session-compact ${active ? "active" : ""}`}
                  role="tab"
                  aria-selected={active}
                  title={`${session.title} · ${preview}`}
                  onClick={() => handleSelectSession(session.id)}
                >
                  {initial}
                </button>
              );
            }

            return (
              <div
                key={session.id}
                className={`chat-session-item ${active ? "active" : ""}`}
                role="tab"
                aria-selected={active}
              >
                <button
                  type="button"
                  className="chat-session-select"
                  onClick={() => handleSelectSession(session.id)}
                >
                  <span className="chat-session-title">{session.title}</span>
                  <span className="chat-session-meta">{preview}</span>
                </button>
                {sessions.length > 1 && (
                  <button
                    type="button"
                    className="chat-session-delete"
                    aria-label={`Delete ${session.title}`}
                    title="Delete conversation"
                    onClick={() => onDeleteSession(session.id)}
                  >
                    ×
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </aside>

      <div
        className="chat-main"
        onClick={() => {
          if (!sidebarCompact) collapseSidebar();
        }}
      >
        <div className="chat-action-panel" onClick={(event) => event.stopPropagation()}>
          <div className="chat-action-panel-header">
            <strong className="chat-action-panel-title">Past assessments</strong>
            <span className="chat-action-panel-hint">
              {records.length === 0 ? "None yet" : `${records.length} completed`}
            </span>
          </div>
          <label className="chat-action-panel-field">
            <span className="sr-only">Select past assessment</span>
            <div className="chat-action-panel-row">
              <select
                className="chat-action-panel-select"
                value={selectedAoiId}
                onChange={(event) => onSelectAoi(event.target.value)}
                disabled={records.length === 0}
              >
                {records.length === 0 ? (
                  <option value="">No past assessments yet</option>
                ) : (
                  records.map((record) => (
                    <option key={record.aoi_id} value={record.aoi_id}>
                      {formatAssessedCaseLabel(record)}
                    </option>
                  ))
                )}
              </select>
              <button
                type="button"
                className="chat-assessment-delete"
                onClick={() => selectedAoiId && onDeleteAoi(selectedAoiId)}
                disabled={!selectedAoiId || records.length === 0}
                title="Delete selected assessment"
                aria-label="Delete selected assessment"
              >
                Delete
              </button>
            </div>
          </label>
          <label className="chat-action-panel-field">
            <span className="chat-action-panel-hint">Report LLM</span>
            <select
              className="chat-action-panel-select"
              value={llmModel}
              onChange={(event) => onLlmModelChange(event.target.value as LlmModelId)}
              disabled={busy}
              title="Model used for chat answers and report generation"
            >
              {LLM_MODEL_OPTIONS.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="chat-history" ref={chatHistoryRef}>
          {messages.length === 0 && (
            <div className="message assistant">
              Attach a post-disaster GeoTIFF below and Send to run a new assessment, or ask about
              past assessments and weather.
            </div>
          )}
          {messages.map((message) => (
            <div
              key={message.id}
              className={`message ${message.role} ${message.meta === "Assessment" && uploadBusy ? "message-live" : ""}`}
            >
              {message.meta && <div className="message-meta">{message.meta}</div>}
              {message.role === "assistant" ? (
                <div className="chat-md">
                  <ReactMarkdown
                    components={{
                      a: ({ href, children }) => {
                        const hospitalLink = parseHospitalMapDeepLink(href);
                        if (hospitalLink && onHospitalMapLink) {
                          return (
                            <button
                              type="button"
                              className="chat-map-link"
                              title="Show on map"
                              onClick={() => onHospitalMapLink(hospitalLink)}
                            >
                              {children}
                            </button>
                          );
                        }
                        return (
                          <a href={href} target="_blank" rel="noreferrer">
                            {children}
                          </a>
                        );
                      },
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <div>{message.content}</div>
              )}
            </div>
          ))}
          {loading && (
            <div className="message assistant message-live">
              <div className="message-meta">RapidResponseAgent</div>
              Running intent router and tools…
            </div>
          )}
        </div>

        <div className="chat-composer" onClick={(event) => event.stopPropagation()}>
          <div className="chat-composer-attachments">
            <div className="chat-composer-attachments-header">
              <strong>New assessment</strong>
              <span className="chat-action-panel-hint">GeoTIFF pair · post required</span>
            </div>
            <div className="upload-fields">
              <div className="upload-field">
                <span className="upload-field-label">Post-disaster (.tif)</span>
                <div className="upload-file-control">
                  <input
                    id={postInputId}
                    type="file"
                    className="upload-file-input"
                    accept=".tif,.tiff,image/tiff"
                    disabled={busy}
                    onChange={(event) => setPostFile(event.target.files?.[0] ?? null)}
                  />
                  <label htmlFor={postInputId} className="upload-file-btn">
                    Choose file
                  </label>
                  {postFile ? (
                    <span className="upload-filename">{postFile.name}</span>
                  ) : (
                    <span className="upload-filename muted">No file chosen</span>
                  )}
                </div>
              </div>
              <div className="upload-field">
                <span className="upload-field-label">Pre-disaster (.tif)</span>
                <div className="upload-file-control">
                  <input
                    id={preInputId}
                    type="file"
                    className="upload-file-input"
                    accept=".tif,.tiff,image/tiff"
                    disabled={busy || autoMatchPre}
                    onChange={(event) => setPreFile(event.target.files?.[0] ?? null)}
                  />
                  <label htmlFor={preInputId} className="upload-file-btn">
                    Choose file
                  </label>
                  {preFile ? (
                    <span className="upload-filename">{preFile.name}</span>
                  ) : (
                    <span className="upload-filename muted">No file chosen</span>
                  )}
                </div>
              </div>
            </div>
            <label className="upload-auto-match">
              <input
                type="checkbox"
                checked={autoMatchPre}
                disabled={busy || Boolean(preFile)}
                onChange={(event) => {
                  setAutoMatchPre(event.target.checked);
                  if (event.target.checked) {
                    setPreFile(null);
                  }
                }}
              />
              Auto-match pre from Maxar (Jan 2025)
            </label>
          </div>

          <div className="chat-input-row">
            <textarea
              rows={1}
              value={draft}
              placeholder={hasUpload ? "Assessment prompt" : "Ask RapidResponseAgent…"}
              disabled={busy}
              onFocus={collapseSidebar}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
            />
            <div className="chat-input-actions">
              <button
                type="button"
                className="chat-stop-btn"
                disabled={!loading}
                onClick={onStop}
                aria-label="Stop generation"
                title="Stop generation"
              >
                <span className="chat-stop-icon" aria-hidden="true" />
              </button>
              <button type="button" className="chat-send-btn" disabled={!canSend} onClick={submit}>
                {uploadBusy ? "Processing…" : "Send"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
