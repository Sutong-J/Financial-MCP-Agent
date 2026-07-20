const STEPS = [
  { key: "parallel", label: "并行分析" },
  { key: "fundamental", label: "基本面" },
  { key: "technical", label: "技术面" },
  { key: "value", label: "估值" },
  { key: "news", label: "新闻" },
  { key: "summary", label: "汇总" },
];

export default function ProgressSteps({
  activeStep,
  label,
}: {
  activeStep?: string;
  label?: string;
}) {
  if (!activeStep) return null;

  const isHeartbeat = activeStep === "heartbeat";
  const activeIndex = isHeartbeat
    ? STEPS.findIndex((s) => s.key === "parallel")
    : STEPS.findIndex((s) => s.key === activeStep);

  return (
    <div className="rounded-xl border border-accent-soft bg-accent-soft/40 px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium text-accent">
        {isHeartbeat && (
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
        )}
        <span>{label || "分析进行中…"}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {STEPS.map((step, index) => {
          const done = activeIndex >= 0 && index <= activeIndex;
          const current = step.key === activeStep;
          return (
            <span
              key={step.key}
              className={`rounded-full px-3 py-1 text-xs ${
                current
                  ? "bg-accent text-white"
                  : done
                    ? "bg-white text-accent"
                    : "bg-white/60 text-slate-500"
              }`}
            >
              {step.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}
