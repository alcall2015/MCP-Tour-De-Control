import { NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { listAgents, listApprovals, listPrompts, listMcpServers } from "../../lib/api";

type IconName = "automation" | "agent" | "reports" | "activity" | "sim" | "sms" | "stress" | "chat" | "settings";

const tabs: { to: string; label: string; eyebrow: string; icon: IconName }[] = [
  { to: "/", label: "Automations", eyebrow: "Build & schedule", icon: "automation" },
  { to: "/agents", label: "Agents", eyebrow: "Autonomous runs", icon: "agent" },
  { to: "/reports", label: "Reports", eyebrow: "Run history", icon: "reports" },
  { to: "/activity", label: "Activity", eyebrow: "Team signals", icon: "activity" },
  { to: "/pairing", label: "SIM Pairing", eyebrow: "Number routing", icon: "sim" },
  { to: "/sms-auto-reply", label: "SMS Reply", eyebrow: "Conversations", icon: "sms" },
  { to: "/stress-call", label: "Stress Call", eyebrow: "SIP performance", icon: "stress" },
  { to: "/chat", label: "Assistant", eyebrow: "Live MCP chat", icon: "chat" },
  { to: "/config", label: "Settings", eyebrow: "System setup", icon: "settings" },
];

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    automation: <><path d="M12 2.75v3M12 18.25v3M2.75 12h3M18.25 12h3"/><path d="m6.3 6.3 2.1 2.1m7.2 7.2 2.1 2.1m0-11.4-2.1 2.1m-7.2 7.2-2.1 2.1"/><circle cx="12" cy="12" r="4.2"/></>,
    agent: <><rect x="5" y="8" width="14" height="11" rx="2.5"/><path d="M12 3.5v4.5M9 12.5h.01M15 12.5h.01M9.5 16h5"/><path d="M3 12.5h2M19 12.5h2"/></>,
    reports: <><path d="M5 3.5h10l4 4v13H5z"/><path d="M15 3.5v4h4M8.5 12h7M8.5 15.5h7M8.5 8.5h2"/></>,
    activity: <><path d="M4 12h3l2-6 4 12 2-6h5"/></>,
    sim: <><rect x="6" y="3" width="12" height="18" rx="2"/><path d="M9.5 7h5M9 17h6"/></>,
    sms: <><path d="M4 5.5h16v11H9l-5 3z"/><path d="M8 9.5h8M8 12.5h5"/></>,
    stress: <><path d="M4 17.5a8.5 8.5 0 1 1 16 0"/><path d="m12 12 4-3M7 17.5h10"/></>,
    chat: <><path d="M4 5.5h16v11H9l-5 3z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.1 2.1-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56v.08h-3v-.08A1.7 1.7 0 0 0 10.7 18.64a1.7 1.7 0 0 0-1.88.34l-.06.06-2.1-2.1.06-.06A1.7 1.7 0 0 0 7.06 15a1.7 1.7 0 0 0-1.56-1.03h-.08v-3h.08A1.7 1.7 0 0 0 7.06 9.94a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.1-2.1.06.06a1.7 1.7 0 0 0 1.88.34h.01a1.7 1.7 0 0 0 1.02-1.56v-.08h3v.08a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.1 2.1-.06.06a1.7 1.7 0 0 0-.34 1.88v.01a1.7 1.7 0 0 0 1.56 1.02h.08v3h-.08A1.7 1.7 0 0 0 19.4 15Z"/></>,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function SystemStatus() {
  const { data: servers = [] } = useQuery({ queryKey: ["mcp-servers"], queryFn: listMcpServers, refetchInterval: 30000 });
  const { data: prompts = [] } = useQuery({ queryKey: ["prompts"], queryFn: listPrompts, refetchInterval: 30000 });
  const { data: agents = [] } = useQuery({ queryKey: ["agents", "all"], queryFn: () => listAgents(), refetchInterval: 30000 });
  const { data: pendingApprovals = [] } = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => listApprovals("pending"), refetchInterval: 30000 });
  const activeServers = servers.filter((server) => server.enabled).length;
  const activePrompts = prompts.filter((prompt) => prompt.enabled).length;
  const activeAgents = agents.filter((agent) => agent.status === "active").length;
  return <div className="system-status"><span className="system-status-title">System status</span><div className="system-status-line"><i className={activeServers ? "is-live" : ""}/><span>MCP servers</span><b>{activeServers}</b></div><div className="system-status-line"><i className={activePrompts ? "is-warm" : ""}/><span>Active flows</span><b>{activePrompts}</b></div><div className="system-status-line"><i className={activeAgents ? "is-live" : ""}/><span>Active agents</span><b>{activeAgents}</b></div><div className="system-status-line"><i className={pendingApprovals.length ? "is-warm" : ""}/><span>Pending approvals</span><b>{pendingApprovals.length}</b></div></div>;
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = localStorage.getItem("theme");
    return saved === "light" || saved === "dark" ? saved : (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  });
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem("theme", theme); }, [theme]);
  const light = theme === "light";
  return <button className="theme-toggle" type="button" onClick={() => setTheme(light ? "dark" : "light")} title={light ? "Switch to night mode" : "Switch to day mode"} aria-label={light ? "Switch to night mode" : "Switch to day mode"}><span aria-hidden="true">{light ? "☀" : "☾"}</span><span>{light ? "Day mode" : "Night mode"}</span><i/></button>;
}

export function TabNav() {
  const [moreOpen, setMoreOpen] = useState(false);
  const location = useLocation();
  const primaryTabs = tabs.slice(0, 4);
  const secondaryTabs = tabs.slice(4);
  const isSecondaryActive = secondaryTabs.some((tab) => tab.to === location.pathname);
  const link = (tab: typeof tabs[number], compact = false) => <NavLink key={tab.to} to={tab.to} end={tab.to === "/"} onClick={() => setMoreOpen(false)} className={({ isActive }) => compact ? (isActive ? "active" : "") : `control-nav-link${isActive ? " active" : ""}`}><span className="nav-icon"><Icon name={tab.icon}/></span><span><strong>{tab.label}</strong>{!compact && <small>{tab.eyebrow}</small>}</span></NavLink>;
  return <><aside className="control-sidebar"><div className="control-brand"><div className="brand-mark"><span/><span/><span/></div><div><p>Operations suite</p><h1>Tour de<br/><strong>Control</strong></h1></div></div><div className="nav-caption">Automate</div><nav className="control-nav" aria-label="Automation navigation">{tabs.slice(0, 4).map((tab) => link(tab))}</nav><div className="nav-caption nav-caption-spaced">Telephony</div><nav className="control-nav" aria-label="Telephony navigation">{tabs.slice(4, 7).map((tab) => link(tab))}</nav><div className="nav-caption nav-caption-spaced">Support</div><nav className="control-nav" aria-label="Support navigation">{tabs.slice(7).map((tab) => link(tab))}</nav><div className="sidebar-bottom"><ThemeToggle/><SystemStatus/><a href={`https://${window.location.hostname}:8443`} target="_blank" rel="noopener noreferrer" className="ava-link">Open AVA Admin <span>↗</span></a></div></aside><header className="mobile-control-header"><div className="brand-mark"><span/><span/><span/></div><span>Tour de Control</span><ThemeToggle/></header><nav className="mobile-control-nav" aria-label="Primary navigation">{primaryTabs.map((tab) => link(tab, true))}<button type="button" className={moreOpen || isSecondaryActive ? "active" : ""} onClick={() => setMoreOpen(!moreOpen)}><span className="more-icon">•••</span><span>More</span></button></nav>{moreOpen && <div className="mobile-more-menu">{secondaryTabs.map((tab) => link(tab, false))}<a href={`https://${window.location.hostname}:8443`} target="_blank" rel="noopener noreferrer" className="control-nav-link">Open AVA Admin <span className="external-arrow">↗</span></a></div>}</>;
}
