"use client";

import type { Session } from "@/lib/api";

export default function SessionSidebar({
  sessions,
  activeId,
  onSelect,
  onCreate,
  onDelete,
}: {
  sessions: Session[];
  activeId?: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className="flex h-full w-72 flex-col border-r border-slate-200 bg-slate-50">
      <div className="border-b border-slate-200 p-4">
        <button
          onClick={onCreate}
          className="w-full rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          + 新对话
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {sessions.map((session) => (
          <div
            key={session.id}
            className={`group mb-1 flex items-center rounded-lg ${
              session.id === activeId ? "bg-white shadow-sm" : "hover:bg-white/70"
            }`}
          >
            <button
              onClick={() => onSelect(session.id)}
              className="flex-1 px-3 py-3 text-left text-sm"
            >
              <div className="truncate font-medium text-slate-800">{session.title}</div>
              <div className="truncate text-xs text-slate-500">
                {session.stock_code || session.updated_at.slice(0, 19)}
              </div>
            </button>
            <button
              onClick={() => onDelete(session.id)}
              className="mr-2 hidden rounded px-2 py-1 text-xs text-red-500 group-hover:block hover:bg-red-50"
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}
