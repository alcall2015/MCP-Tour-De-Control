import { Light as SyntaxHighlighter } from "react-syntax-highlighter";
import python from "react-syntax-highlighter/dist/esm/languages/hljs/python";
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs";

SyntaxHighlighter.registerLanguage("python", python);

interface Props {
  code: string;
  version: number;
  needsLlm: boolean;
}

export function ScriptPreview({ code, version, needsLlm }: Props) {
  return (
    <div
      className="overflow-hidden rounded-xl"
      style={{ border: "1px solid var(--border)" }}
    >
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-4 py-2.5"
        style={{
          backgroundColor: "var(--bg-elevated)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <span
          className="text-xs font-semibold font-mono"
          style={{ color: "var(--text-secondary)" }}
        >
          script.py · v{version}
        </span>
        <span
          className="badge"
          style={
            needsLlm
              ? {
                  backgroundColor: "rgba(251, 191, 36, 0.12)",
                  color: "var(--warning)",
                  border: "1px solid rgba(251, 191, 36, 0.25)",
                }
              : {
                  backgroundColor: "rgba(52, 211, 153, 0.1)",
                  color: "var(--success)",
                  border: "1px solid rgba(52, 211, 153, 0.2)",
                }
          }
        >
          {needsLlm ? "Uses LLM at runtime" : "No LLM needed"}
        </span>
      </div>

      <SyntaxHighlighter
        language="python"
        style={atomOneDark}
        customStyle={{
          margin: 0,
          padding: "1rem",
          background: "#0f1320",
          fontSize: "0.8125rem",
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
