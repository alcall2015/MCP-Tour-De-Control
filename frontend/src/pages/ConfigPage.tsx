import { GoogleConfig } from "../components/Config/GoogleConfig";
import { LlmConfig } from "../components/Config/LlmConfig";
import { McpServerList } from "../components/Config/McpServerList";

export function ConfigPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <span
          className="h-5 w-1 rounded-full flex-shrink-0"
          style={{ backgroundColor: "var(--accent)" }}
        />
        <h2
          className="text-2xl font-semibold"
          style={{
            fontFamily: "'Space Grotesk', system-ui, sans-serif",
            color: "var(--text-primary)",
          }}
        >
          Config
        </h2>
      </div>
      <LlmConfig />
      <GoogleConfig />
      <McpServerList />
    </div>
  );
}
