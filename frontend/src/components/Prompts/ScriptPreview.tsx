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
    <div className="rounded border border-zinc-700">
      <div className="flex items-center justify-between border-b border-zinc-700 bg-zinc-800 px-4 py-2">
        <span className="text-sm font-medium">Script v{version}</span>
        <span
          className={`rounded px-2 py-0.5 text-xs ${
            needsLlm ? "bg-amber-900 text-amber-300" : "bg-green-900 text-green-300"
          }`}
        >
          {needsLlm ? "Uses LLM at runtime" : "No LLM needed"}
        </span>
      </div>
      <SyntaxHighlighter
        language="python"
        style={atomOneDark}
        customStyle={{ margin: 0, padding: "1rem", background: "#18181b" }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
