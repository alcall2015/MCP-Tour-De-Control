import { Outlet, useLocation } from "react-router-dom";
import { TabNav } from "./TabNav";

export function AppShell() {
  const { pathname } = useLocation();
  const page = {
    "/": ["Automations", "Create, schedule and supervise MCP workflows."],
    "/agents": ["Agents", "Define autonomous agents, their MCP servers and limits."],
    "/reports": ["Reports", "Review the results of every execution."],
    "/activity": ["Activity", "Follow document changes across your workspace."],
    "/pairing": ["SIM Pairing", "Route and manage connected SIM numbers."],
    "/sms-auto-reply": ["SMS Reply", "Keep SMS conversations moving automatically."],
    "/stress-call": ["Stress Call", "Measure SIP capacity and call quality."],
    "/chat": ["Assistant", "Ask, test tools and turn ideas into workflows."],
    "/config": ["Settings", "Configure the control plane and its integrations."],
  }[pathname] ?? ["Tour de Control", "Operations workspace."];
  return (
    <div className="app-frame" style={{ backgroundColor: "var(--bg-void)", color: "var(--text-primary)" }}>
      <TabNav />
      <main className="app-main">
        <div className="page-context"><div><span>Control center</span><h2>{page[0]}</h2><p>{page[1]}</p></div><div className="page-context-status"><i/> All systems operational</div></div>
        <Outlet />
      </main>
    </div>
  );
}
