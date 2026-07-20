import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 px-6 text-center">
      <h1 className="text-2xl font-semibold text-slate-800">页面不存在</h1>
      <p className="max-w-md text-sm text-slate-600">
        请从聊天首页进入。若刚启动服务，请等待几秒后刷新。
      </p>
      <Link
        href="/chat/new"
        className="rounded-xl bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700"
      >
        进入金融分析聊天
      </Link>
      <p className="text-xs text-slate-400">
        前端地址：<code className="text-slate-600">http://localhost:3000</code>
        （不是 8000 端口）
      </p>
    </div>
  );
}
