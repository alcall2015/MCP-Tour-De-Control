import Markdown from "react-markdown";
import { ToolCallBlock } from "./ToolCallBlock";
import { ScriptBlock } from "./ScriptBlock";

interface Props {
  role: "user" | "assistant" | "tool";
  content: string;
  toolCalls?: Array<{ name: string; args: Record<string, unknown>; result: string }> | null;
  pendingToolCall?: { tool: string; server: string; args?: Record<string, unknown> } | null;
  pendingToolResult?: { tool: string; data: unknown } | null;
  conversationId: string;
}

export function MessageBubble({ role, content, toolCalls, pendingToolCall, pendingToolResult, conversationId }: Props) {
  if (role === "user") {
    return (
      <div className="flex justify-end mb-3">
        <div
          className="rounded-xl px-4 py-2.5 max-w-[75%] text-sm"
          style={{ backgroundColor: "rgba(226, 179, 64, 0.15)", color: "var(--text-primary)" }}
        >
          {content}
        </div>
      </div>
    );
  }

  // Extract python code blocks for ScriptBlock treatment
  const parts = splitContentWithScripts(content);

  return (
    <div className="flex justify-start mb-3">
      <div className="max-w-[85%]">
        <div
          className="rounded-xl px-4 py-2.5 text-sm chat-markdown"
          style={{ backgroundColor: "var(--bg-panel)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
        >
          {parts.map((part, i) =>
            part.type === "script" ? (
              <ScriptBlock key={i} code={part.content} conversationId={conversationId} />
            ) : (
              <Markdown key={i}>{part.content}</Markdown>
            )
          )}
        </div>
        {/* Saved tool calls from history */}
        {toolCalls?.map((tc, i) => (
          <ToolCallBlock key={i} tool={tc.name} server="" args={tc.args} result={tc.result} />
        ))}
        {/* Live streaming tool call */}
        {pendingToolCall && (
          <ToolCallBlock
            tool={pendingToolCall.tool}
            server={pendingToolCall.server}
            args={pendingToolCall.args}
            loading={!pendingToolResult}
            result={pendingToolResult?.data}
          />
        )}
      </div>
    </div>
  );
}

function splitContentWithScripts(content: string): Array<{ type: "text" | "script"; content: string }> {
  const parts: Array<{ type: "text" | "script"; content: string }> = [];
  const regex = /```python\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", content: content.slice(lastIndex, match.index) });
    }
    parts.push({ type: "script", content: match[1].trim() });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    parts.push({ type: "text", content: content.slice(lastIndex) });
  }

  return parts.length ? parts : [{ type: "text", content }];
}
