import AuthGate from "@/components/AuthGate";
import ChatWorkspace from "@/components/ChatWorkspace";

export default async function ChatSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return (
    <AuthGate>
      <ChatWorkspace sessionId={sessionId} />
    </AuthGate>
  );
}
