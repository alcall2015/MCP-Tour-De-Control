import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { runScriptInChat } from "../../lib/api";

interface Props {
  code: string;
  conversationId: string;
}

export function ScriptBlock({ code, conversationId }: Props) {
  const navigate = useNavigate();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ status: string; output: string | null; error: string | null } | null>(null);

  const handleTest = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await runScriptInChat(conversationId, code);
      setResult(res);
    } catch (e: unknown) {
      setResult({ status: "failed", output: null, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="my-2">
      <pre
        className="rounded-lg p-3 text-xs font-mono overflow-x-auto"
        style={{ backgroundColor: "rgba(0,0,0,0.3)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
      >
        {code}
      </pre>
      <div className="flex gap-2 mt-2">
        <button
          onClick={handleTest}
          disabled={running}
          className="rounded-lg px-3 py-1 text-xs font-medium transition-all disabled:opacity-50"
          style={{ backgroundColor: "rgba(96, 165, 250, 0.1)", color: "var(--running)", border: "1px solid rgba(96, 165, 250, 0.2)" }}
        >
          {running ? "Execution..." : "Tester"}
        </button>
        <button
          onClick={() => navigate("/?prefill=" + encodeURIComponent(code))}
          className="rounded-lg px-3 py-1 text-xs font-medium transition-all"
          style={{ backgroundColor: "rgba(226, 179, 64, 0.1)", color: "var(--accent)", border: "1px solid rgba(226, 179, 64, 0.2)" }}
        >
          Sauvegarder
        </button>
      </div>
      {result && (
        <div
          className="mt-2 rounded-lg p-3 text-xs font-mono"
          style={{
            backgroundColor: result.status === "success" ? "rgba(74, 222, 128, 0.05)" : "rgba(248, 113, 113, 0.05)",
            border: `1px solid ${result.status === "success" ? "rgba(74, 222, 128, 0.2)" : "rgba(248, 113, 113, 0.2)"}`,
            color: "var(--text-secondary)",
          }}
        >
          <div className="font-medium mb-1" style={{ color: result.status === "success" ? "var(--success)" : "var(--error)" }}>
            {result.status === "success" ? "Succes" : "Erreur"}
          </div>
          <pre className="whitespace-pre-wrap">{result.output || result.error || "Pas de sortie"}</pre>
        </div>
      )}
    </div>
  );
}
