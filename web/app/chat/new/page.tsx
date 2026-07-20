"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import AuthGate from "@/components/AuthGate";
import { createSession } from "@/lib/api";
import { getStoredToken } from "@/lib/auth";

function BootstrapInner() {
  const router = useRouter();

  useEffect(() => {
    if (!getStoredToken()) {
      router.replace("/login");
      return;
    }

    createSession()
      .then((session) => router.replace(`/chat/${session.id}`))
      .catch(() => {
        router.replace("/chat/error");
      });
  }, [router]);

  return (
    <div className="flex h-screen items-center justify-center text-slate-600">
      正在创建会话…
    </div>
  );
}

export default function ChatBootstrapPage() {
  return (
    <AuthGate>
      <BootstrapInner />
    </AuthGate>
  );
}
