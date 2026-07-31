import { useState } from "react";
import { ConversationList } from "./ConversationList";

export function ChatPage() {
  const [activeConvId, setActiveConvId] = useState<string | null>(null);

  return (
    <div className="flex" style={{ height: "calc(100vh - 57px)" }}>
      <div style={{ width: "250px", flexShrink: 0 }}>
        <ConversationList activeId={activeConvId} onSelect={setActiveConvId} />
      </div>
      <div className="flex-1 flex items-center justify-center">
        {activeConvId ? (
          <p style={{ color: "var(--text-muted)" }}>Chat area — Task 6</p>
        ) : (
          <div className="text-center">
            <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
              Selectionnez ou creez une conversation
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Posez des questions, appelez des outils MCP, ou generez des scripts.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
