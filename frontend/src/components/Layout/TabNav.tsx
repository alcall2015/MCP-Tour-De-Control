import { NavLink } from "react-router-dom";

const tabs = [
  { to: "/", label: "Prompts" },
  { to: "/reports", label: "Reports" },
  { to: "/config", label: "Config" },
];

export function TabNav() {
  return (
    <nav className="border-b border-zinc-800 bg-zinc-950">
      <div className="mx-auto flex max-w-6xl items-center gap-8 px-6">
        <h1 className="py-4 text-lg font-bold text-white">MCP Tour De Control</h1>
        <div className="flex gap-1">
          {tabs.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.to === "/"}
              className={({ isActive }) =>
                `px-4 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? "border-b-2 border-blue-500 text-white"
                    : "text-zinc-400 hover:text-white"
                }`
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </div>
      </div>
    </nav>
  );
}
