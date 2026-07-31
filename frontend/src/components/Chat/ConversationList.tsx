import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listConversations, createConversation, deleteConversation } from "../../lib/api";
import type { Conversation } from "../../lib/api";

interface Props {
  activeId: string | null;
  onSelect: (id: string) => void;
}

export function ConversationList({ activeId, onSelect }: Props) {
  const queryClient = useQueryClient();
  const { data: conversations = [] } = useQuery({
    queryKey: ["conversations"],
    queryFn: listConversations,
  });

  const createMut = useMutation({
    mutationFn: createConversation,
    onSuccess: (conv) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      onSelect(conv.id);
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });

  const formatDate = (d: string) => {
    const date = new Date(d);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    if (diff < 86400000) return date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    return date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
  };

  return (
    <div
      className="flex flex-col h-full"
      style={{ borderRight: "1px solid var(--border)", backgroundColor: "var(--bg-void)" }}
    >
      <div className="p-3">
        <button
          onClick={() => createMut.mutate()}
          className="btn-primary w-full text-xs py-2"
        >
          + Nouvelle conversation
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {conversations.map((conv: Conversation) => (
          <div
            key={conv.id}
            onClick={() => onSelect(conv.id)}
            className="px-3 py-2.5 cursor-pointer transition-all duration-150 flex items-center justify-between group"
            style={{
              backgroundColor: activeId === conv.id ? "var(--bg-panel)" : "transparent",
              borderLeft: activeId === conv.id ? "2px solid var(--accent)" : "2px solid transparent",
            }}
          >
            <div className="min-w-0 flex-1">
              <p
                className="text-sm truncate"
                style={{ color: activeId === conv.id ? "var(--text-primary)" : "var(--text-secondary)" }}
              >
                {conv.title || "Nouvelle conversation"}
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                {formatDate(conv.updated_at)}
              </p>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (confirm("Supprimer cette conversation ?")) deleteMut.mutate(conv.id);
              }}
              className="opacity-0 group-hover:opacity-100 text-xs px-1.5 py-0.5 rounded transition-opacity"
              style={{ color: "var(--error)" }}
            >
              x
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
