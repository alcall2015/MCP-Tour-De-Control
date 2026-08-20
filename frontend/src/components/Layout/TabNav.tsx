import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listPrompts, listMcpServers } from "../../lib/api";

const tabs = [
  { to: "/", label: "Prompts" },
  { to: "/reports", label: "Reports" },
  { to: "/stress-call", label: "Stress Call" },
  { to: "/chat", label: "Chat" },
  { to: "/config", label: "Config" },
];

function StatusStrip() {
  const { data: servers = [] } = useQuery({
    queryKey: ["mcp-servers"],
    queryFn: listMcpServers,
    refetchInterval: 30000,
  });
  const { data: prompts = [] } = useQuery({
    queryKey: ["prompts"],
    queryFn: listPrompts,
    refetchInterval: 30000,
  });

  const activeServers = servers.filter((s) => s.enabled).length;
  const activePrompts = prompts.filter((p) => p.enabled).length;
  const isRunning = activeServers > 0;

  return (
    <div className="hidden items-center gap-4 sm:flex">
      <div className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "var(--success)" }}>
        <span
          className={`h-1.5 w-1.5 rounded-full ${isRunning ? "pulse-dot" : ""}`}
          style={{ backgroundColor: "var(--success)", opacity: activeServers === 0 ? 0.35 : 1 }}
        />
        <span style={{ color: activeServers === 0 ? "var(--text-muted)" : "var(--success)" }}>
          {activeServers} server{activeServers !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="flex items-center gap-1.5 text-xs font-medium">
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: activePrompts > 0 ? "var(--accent)" : "var(--text-muted)" }}
        />
        <span style={{ color: activePrompts === 0 ? "var(--text-muted)" : "var(--warning)" }}>
          {activePrompts} prompt{activePrompts !== 1 ? "s" : ""}
        </span>
      </div>
    </div>
  );
}

export function TabNav() {
  return (
    <>
      <div className="status-bar-top" />
      <nav
        style={{
          borderBottom: "1px solid var(--border)",
          backgroundColor: "rgba(15, 19, 32, 0.95)",
          backdropFilter: "blur(8px)",
          position: "sticky",
          top: 0,
          zIndex: 50,
        }}
      >
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6">
          {/* Left: Brand */}
          <div className="flex items-center gap-2 py-3.5">
            <span
              className="h-2 w-2 rounded-full pulse-dot flex-shrink-0"
              style={{ backgroundColor: "var(--accent)" }}
            />
            <h1
              className="font-display text-base font-600 tracking-tight"
              style={{ color: "var(--text-primary)", fontFamily: "'Space Grotesk', system-ui, sans-serif", fontWeight: 600 }}
            >
              MCP Tour De Control
            </h1>
          </div>

          {/* Center: Tabs */}
          <div className="flex gap-0.5">
            {tabs.map((tab) => (
              <NavLink
                key={tab.to}
                to={tab.to}
                end={tab.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 px-4 py-3.5 text-sm font-medium transition-all duration-200 relative ${
                    isActive ? "text-white" : "hover:text-white"
                  }`
                }
                style={({ isActive }) => ({
                  color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                  borderBottom: isActive ? "2px solid var(--accent)" : "2px solid transparent",
                  marginBottom: "-1px",
                })}
              >
                {tab.label}
              </NavLink>
            ))}
            {/* AVA admin UI — separate app proxied on :8443, open in a new tab */}
            <a
              href={`https://${window.location.hostname}:8443`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-4 py-3.5 text-sm font-medium transition-all duration-200 hover:text-white"
              style={{
                color: "var(--text-secondary)",
                borderBottom: "2px solid transparent",
                marginBottom: "-1px",
              }}
              title="AVA — AI Voice Agent admin (new tab)"
            >
              AVA Admin ↗
            </a>
          </div>

          {/* Right: Status strip */}
          <StatusStrip />
        </div>
      </nav>
    </>
  );
}
