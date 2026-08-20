import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./components/Layout/AppShell";
import { PromptsPage } from "./pages/PromptsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ConfigPage } from "./pages/ConfigPage";
import { StressCallPage } from "./pages/StressCallPage";
import { ChatPage } from "./pages/ChatPage";
import { ActivityPage } from "./pages/ActivityPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<PromptsPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="activity" element={<ActivityPage />} />
            <Route path="stress-call" element={<StressCallPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="config" element={<ConfigPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
