import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./components/Layout/AppShell";
import { PromptsPage } from "./pages/PromptsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ConfigPage } from "./pages/ConfigPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<PromptsPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="config" element={<ConfigPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
