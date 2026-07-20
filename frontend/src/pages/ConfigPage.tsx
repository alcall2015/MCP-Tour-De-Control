import { LlmConfig } from "../components/Config/LlmConfig";
import { McpServerList } from "../components/Config/McpServerList";

export function ConfigPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Config</h2>
      <LlmConfig />
      <McpServerList />
    </div>
  );
}
