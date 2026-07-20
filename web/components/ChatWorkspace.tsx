"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ChatInput from "@/components/ChatInput";
import ChatMessages from "@/components/ChatMessages";
import ProgressSteps from "@/components/ProgressSteps";
import SessionSidebar from "@/components/SessionSidebar";
import {
  clearAuth,
  createSession,
  deleteSession,
  getSession,
  getStoredUser,
  listSessions,
  streamChat,
  type ChatMessage,
  type Session,
} from "@/lib/api";

export default function ChatWorkspace({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [progressStep, setProgressStep] = useState<string | undefined>();
  const [progressLabel, setProgressLabel] = useState<string | undefined>();
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadSessions = useCallback(async () => {
    const rows = await listSessions();
    setSessions(rows);
  }, []);

  const loadMessages = useCallback(async (id: string) => {
    const detail = await getSession(id);
    setMessages(detail.messages);
  }, []);

  useEffect(() => {
    loadSessions().catch(console.error);
  }, [loadSessions]);

  useEffect(() => {
    if (sessionId) {
      loadMessages(sessionId).catch(console.error);
    }
  }, [sessionId, loadMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, progressStep]);

  const handleCreate = async () => {
    const created = await createSession();
    await loadSessions();
    router.push(`/chat/${created.id}`);
  };

  const handleDelete = async (id: string) => {
    await deleteSession(id);
    const rows = await listSessions();
    setSessions(rows);
    if (id === sessionId) {
      if (rows.length > 0) router.push(`/chat/${rows[0].id}`);
      else {
        const created = await createSession();
        router.push(`/chat/${created.id}`);
      }
    }
  };

  const handleSend = async (text: string) => {
    if (!sessionId || busy) return;
    setBusy(true);
    setProgressStep("start");
    setProgressLabel("任务已开始…");

    const optimistic: ChatMessage = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: text,
      message_type: "text",
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);

    try {
      await streamChat(sessionId, text, {
        onProgress: (event) => {
          setProgressStep(event.step);
          setProgressLabel(event.display || event.label);
        },
        onMessage: (message) => {
          setMessages((prev) => [...prev, message]);
        },
        onError: (message) => {
          setMessages((prev) => [
            ...prev,
            {
              id: `err-${Date.now()}`,
              role: "assistant",
              content: `❌ ${message}`,
              message_type: "text",
              created_at: new Date().toISOString(),
            },
          ]);
        },
        onDone: async () => {
          await loadSessions();
        },
      });
    } finally {
      setBusy(false);
      setProgressStep(undefined);
      setProgressLabel(undefined);
      await loadMessages(sessionId);
    }
  };

  return (
    <div className="flex h-screen bg-white">
      <SessionSidebar
        sessions={sessions}
        activeId={sessionId}
        onSelect={(id) => router.push(`/chat/${id}`)}
        onCreate={handleCreate}
        onDelete={handleDelete}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-ink-900">金融分析智能体</h1>
            <p className="text-sm text-slate-500">完整分析 · 多轮追问 · 多用户隔离</p>
          </div>
          <div className="flex items-center gap-3 text-sm text-slate-600">
            <span>{getStoredUser()?.display_name || getStoredUser()?.email}</span>
            <button
              type="button"
              onClick={() => {
                clearAuth();
                router.replace("/login");
              }}
              className="rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-100"
            >
              退出
            </button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <ChatMessages messages={messages} />
          <div ref={bottomRef} />
        </div>
        <div className="space-y-3 border-t border-slate-200 bg-slate-50 px-6 py-4">
          <ProgressSteps activeStep={progressStep} label={progressLabel} />
          <ChatInput disabled={busy} onSend={handleSend} />
        </div>
      </main>
    </div>
  );
}
