import {
  authHeaders,
  clearAuth,
  fetchCurrentUser,
  getApiBase,
  getStoredToken,
  getStoredUser,
  login,
  register,
  saveAuth,
  type AuthResponse,
  type User,
} from "./auth";

export type { AuthResponse, User };

export {
  clearAuth,
  fetchCurrentUser,
  getStoredToken,
  getStoredUser,
  login,
  register,
  saveAuth,
};

export type Session = {
  id: string;
  title: string;
  company_name?: string | null;
  stock_code?: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  message_type: string;
  created_at: string;
};

export type SessionDetail = Session & {
  messages: ChatMessage[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401) {
    clearAuth();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("未登录或登录已过期");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export async function listSessions(): Promise<Session[]> {
  return request<Session[]>("/sessions");
}

export async function createSession(): Promise<Session> {
  return request<Session>("/sessions", { method: "POST" });
}

export async function getSession(id: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/sessions/${id}`);
}

export async function deleteSession(id: string): Promise<void> {
  await request<void>(`/sessions/${id}`, { method: "DELETE" });
}

export type ProgressEvent = {
  step: string;
  label: string;
  display?: string;
};

export type ChatStreamHandlers = {
  onProgress?: (event: ProgressEvent) => void;
  onMessage?: (message: ChatMessage) => void;
  onDone?: (payload: { session_id: string; report_path?: string }) => void;
  onError?: (message: string) => void;
};

export async function streamChat(
  sessionId: string,
  message: string,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const res = await fetch(`${getApiBase()}/sessions/${sessionId}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify({ message }),
  });

  if (res.status === 401) {
    clearAuth();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    handlers.onError?.("未登录或登录已过期");
    return;
  }

  if (!res.ok) {
    const text = await res.text();
    handlers.onError?.(text || "请求失败");
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    handlers.onError?.("无法读取响应流");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      if (!part.trim()) continue;
      const lines = part.split("\n");
      let event = "message";
      let dataLine = "";
      for (const line of lines) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) dataLine = line.slice(5).trim();
      }
      if (!dataLine) continue;
      const payload = JSON.parse(dataLine);

      if (event === "progress") handlers.onProgress?.(payload);
      else if (event === "message") handlers.onMessage?.(payload.message);
      else if (event === "done") handlers.onDone?.(payload);
      else if (event === "error") handlers.onError?.(payload.message);
    }
  }
}
