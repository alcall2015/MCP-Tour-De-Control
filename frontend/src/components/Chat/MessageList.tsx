import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";

export interface DisplayMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  toolCalls?: Array<{ name: string; args: Record<string, unknown>; result: string }> | null;
  pendingToolCall?: { tool: string; server: string; args?: Record<string, unknown> } | null;
  pendingToolResult?: { tool: string; data: unknown } | null;
}

interface Props {
  messages: DisplayMessage[];
  conversationId: string;
  streaming?: boolean;
}

export function MessageList({ messages, conversationId, streaming }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4">
      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          role={msg.role}
          content={msg.content}
          toolCalls={msg.toolCalls}
          pendingToolCall={msg.pendingToolCall}
          pendingToolResult={msg.pendingToolResult}
          conversationId={conversationId}
        />
      ))}
      {streaming && (
        <div className="flex justify-start mb-3">
          <div
            className="rounded-xl px-4 py-2.5 text-sm"
            style={{ backgroundColor: "var(--bg-panel)", color: "var(--text-muted)", border: "1px solid var(--border)" }}
          >
            <span className="animate-pulse">...</span>
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
