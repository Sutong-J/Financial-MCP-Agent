"use client";

export default function ChatInput({
  disabled,
  onSend,
}: {
  disabled?: boolean;
  onSend: (text: string) => void;
}) {
  return (
    <form
      className="flex gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const input = form.elements.namedItem("message") as HTMLInputElement;
        const value = input.value.trim();
        if (!value || disabled) return;
        onSend(value);
        input.value = "";
      }}
    >
      <input
        name="message"
        disabled={disabled}
        placeholder={disabled ? "分析进行中（完整分析约 3–5 分钟）…" : "输入分析需求或追问…"}
        className="flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none ring-accent focus:ring-2 disabled:bg-slate-100"
      />
      <button
        type="submit"
        disabled={disabled}
        className="rounded-xl bg-accent px-5 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
      >
        发送
      </button>
    </form>
  );
}
