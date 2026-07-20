"use client";

import type { ChatMessage } from "@/lib/api";
import MarkdownRenderer from "./MarkdownRenderer";

export default function ChatMessages({ messages }: { messages: ChatMessage[] }) {
  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-slate-500">
        <div className="max-w-md text-center">
          <p className="text-lg font-medium text-slate-700">开始你的金融分析</p>
          <p className="mt-2 text-sm">
            例如：「分析贵州茅台 600519」或「帮我看看比亚迪这只股票怎么样」
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {messages.map((message) => {
        const isUser = message.role === "user";
        return (
          <div key={message.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[90%] rounded-2xl px-4 py-3 shadow-sm ${
                isUser
                  ? "bg-accent text-white"
                  : "border border-slate-200 bg-white text-slate-800"
              }`}
            >
              {isUser ? (
                <p className="whitespace-pre-wrap text-sm">{message.content}</p>
              ) : message.message_type === "report" ? (
                <MarkdownRenderer content={message.content} />
              ) : (
                <MarkdownRenderer content={message.content} />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
