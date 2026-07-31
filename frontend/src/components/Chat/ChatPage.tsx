import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ConversationList } from "./ConversationList";
import { MessageList, type DisplayMessage } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { listMessages, sendMessageSSE, parseSSEStream } from "../../lib/api";
import type { ChatMessageData } from "../../lib/api";

export function ChatPage() {
  const queryClient = useQueryClient();
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [streamingMessages, setStreamingMessages] = useState<DisplayMessage[]>([]);

  const { data: historyMessages = [] } = useQuery({
    queryKey: ["chat-messages", activeConvId],
    queryFn: () => (activeConvId ? listMessages(activeConvId) : Promise.resolve([])),
    enabled: !!activeConvId,
  });

  const toDisplayMessages = (msgs: ChatMessageData[]): DisplayMessage[] =>
    msgs
      .filter((m) => m.role !== "tool")
      .map((m) => ({
        id: m.id,
        role: m.role as "user" | "assistant",
        content: m.content,
        toolCalls: m.tool_calls,
      }));

  const displayMessages = streaming ? streamingMessages : toDisplayMessages(historyMessages);

  const handleSend = useCallback(
    async (content: string) => {
      if (!activeConvId || streaming) return;

      setStreaming(true);
      const userMsg: DisplayMessage = { id: "user-" + Date.now(), role: "user", content, toolCalls: null };
      const assistantMsg: DisplayMessage = { id: "assistant-" + Date.now(), role: "assistant", content: "", toolCalls: null };

      const currentHistory = toDisplayMessages(historyMessages);
      setStreamingMessages([...currentHistory, userMsg, assistantMsg]);

      try {
        const response = await sendMessageSSE(activeConvId, content);
        if (!response.body) throw new Error("No response body");

        const reader = response.body.getReader();
        let currentText = "";
        let currentToolCall: DisplayMessage["pendingToolCall"] = null;
        let currentToolResult: DisplayMessage["pendingToolResult"] = null;

        await parseSSEStream(reader, (event) => {
          if (event.event === "text") {
            currentText += (event.data as { content: string }).content;
            setStreamingMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              updated[updated.length - 1] = { ...last, content: currentText };
              return updated;
            });
          } else if (event.event === "tool_call") {
            currentToolCall = event.data as DisplayMessage["pendingToolCall"];
            currentToolResult = null;
            setStreamingMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              updated[updated.length - 1] = { ...last, pendingToolCall: currentToolCall, pendingToolResult: null };
              return updated;
            });
          } else if (event.event === "tool_result") {
            currentToolResult = event.data as DisplayMessage["pendingToolResult"];
            setStreamingMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              updated[updated.length - 1] = { ...last, pendingToolResult: currentToolResult };
              return updated;
            });
          }
        });
      } catch (e) {
        console.error("Chat stream error:", e);
      } finally {
        setStreaming(false);
        setStreamingMessages([]);
        queryClient.invalidateQueries({ queryKey: ["chat-messages", activeConvId] });
        queryClient.invalidateQueries({ queryKey: ["conversations"] });
      }
    },
    [activeConvId, streaming, historyMessages, queryClient],
  );

  return (
    <div className="flex" style={{ height: "calc(100vh - 57px)" }}>
      <div style={{ width: "250px", flexShrink: 0 }}>
        <ConversationList activeId={activeConvId} onSelect={setActiveConvId} />
      </div>
      <div className="flex-1 flex flex-col">
        {activeConvId ? (
          <>
            <MessageList messages={displayMessages} conversationId={activeConvId} streaming={streaming && displayMessages[displayMessages.length - 1]?.content === ""} />
            <ChatInput onSend={handleSend} disabled={streaming} />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                Selectionnez ou creez une conversation
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Posez des questions, appelez des outils MCP, ou generez des scripts.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
