export default function ChatErrorPage() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 text-slate-600">
      <p className="text-lg font-medium">无法连接后端 API</p>
      <p className="text-sm">请先运行 scripts/start.ps1 或手动启动 uvicorn api.main:app --port 8000</p>
    </div>
  );
}
