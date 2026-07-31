import { useState, useRef, useEffect } from "react";

interface Props {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + "px";
    }
  }, [text]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (text.trim() && !disabled) {
        onSend(text.trim());
        setText("");
      }
    }
  };

  return (
    <div className="px-6 py-3" style={{ borderTop: "1px solid var(--border)", backgroundColor: "var(--bg-void)" }}>
      <div className="flex gap-2 items-end">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="Posez une question, demandez un rapport, ou creez un script..."
          rows={1}
          className="input-field flex-1 resize-none font-sans text-sm"
          style={{ minHeight: "40px", maxHeight: "120px" }}
        />
        <button
          onClick={() => { if (text.trim() && !disabled) { onSend(text.trim()); setText(""); } }}
          disabled={disabled || !text.trim()}
          className="btn-primary px-4 py-2 text-sm disabled:opacity-50"
        >
          Envoyer
        </button>
      </div>
    </div>
  );
}
