import { Outlet } from "react-router-dom";
import { TabNav } from "./TabNav";

export function AppShell() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <TabNav />
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
