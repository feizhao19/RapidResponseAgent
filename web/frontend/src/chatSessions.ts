import type { AssessmentJob, ChatMessage } from "./api/client";

export type ChatSession = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
  activeJob: AssessmentJob | null;
};

const STORAGE_KEY = "geoagent.chat.sessions.v1";

export function createChatSession(title = "New chat"): ChatSession {
  const now = Date.now();
  return {
    id: crypto.randomUUID(),
    title,
    createdAt: now,
    updatedAt: now,
    messages: [],
    activeJob: null,
  };
}

export function sessionTitleFromMessage(content: string): string {
  const oneLine = content.replace(/\s+/g, " ").trim();
  if (!oneLine) return "New chat";
  return oneLine.length > 42 ? `${oneLine.slice(0, 42)}…` : oneLine;
}

export function loadStoredSessions(): { sessions: ChatSession[]; activeSessionId: string } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { sessions: ChatSession[]; activeSessionId: string };
    if (!parsed.sessions?.length || !parsed.activeSessionId) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function storeSessions(sessions: ChatSession[], activeSessionId: string): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        sessions,
        activeSessionId,
      }),
    );
  } catch {
    // Ignore quota / private mode errors.
  }
}

export function patchSession(
  sessions: ChatSession[],
  sessionId: string,
  patch: Partial<ChatSession>,
): ChatSession[] {
  return sessions.map((session) =>
    session.id === sessionId
      ? { ...session, ...patch, updatedAt: Date.now() }
      : session,
  );
}

export function upsertSessionMessage(
  sessions: ChatSession[],
  sessionId: string,
  message: ChatMessage,
): ChatSession[] {
  return sessions.map((session) => {
    if (session.id !== sessionId) return session;
    const index = session.messages.findIndex((item) => item.id === message.id);
    if (index === -1) {
      return {
        ...session,
        messages: [...session.messages, message],
        updatedAt: Date.now(),
      };
    }
    const messages = [...session.messages];
    messages[index] = message;
    return {
      ...session,
      messages,
      updatedAt: Date.now(),
    };
  });
}

export function appendSessionMessage(
  sessions: ChatSession[],
  sessionId: string,
  message: ChatMessage,
): ChatSession[] {
  return sessions.map((session) => {
    if (session.id !== sessionId) return session;
    const title =
      session.title === "New chat" && message.role === "user"
        ? sessionTitleFromMessage(message.content)
        : session.title;
    return {
      ...session,
      title,
      messages: [...session.messages, message],
      updatedAt: Date.now(),
    };
  });
}

export function mergeSessionFromServer(
  session: ChatSession,
  server: {
    title?: string;
    active_aoi_id?: string | null;
    messages?: Array<{
      id: string;
      role: string;
      content: string;
      meta?: string | null;
    }>;
  },
): ChatSession {
  const serverMessages: ChatMessage[] = (server.messages ?? []).map((message) => ({
    id: message.id,
    role: message.role as ChatMessage["role"],
    content: message.content,
    meta: message.meta ?? undefined,
  }));

  if (serverMessages.length === 0) {
    return {
      ...session,
      title: server.title && server.title !== "New chat" ? server.title : session.title,
      updatedAt: Date.now(),
    };
  }

  const progressId = `assessment-progress-${session.id}`;
  const hasServerCompletion = serverMessages.some((message) =>
    message.content.includes("**Assessment completed**"),
  );
  const localOnly = session.messages.filter((message) => {
    if (serverMessages.some((serverMessage) => serverMessage.id === message.id)) {
      return false;
    }
    if (hasServerCompletion && message.id === progressId) {
      return false;
    }
    return message.id === progressId;
  });
  const mergedMessages = [...serverMessages];
  for (const message of localOnly) {
    if (message.id === progressId) {
      mergedMessages.push(message);
    }
  }

  return {
    ...session,
    title: server.title && server.title !== "New chat" ? server.title : session.title,
    messages: mergedMessages,
    updatedAt: Date.now(),
  };
}
