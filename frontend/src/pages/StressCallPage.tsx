import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createStressTest } from "../lib/api";
import type { StressTest } from "../lib/api";
import { StressTestList } from "../components/StressCall/StressTestList";
import { StressTestForm } from "../components/StressCall/StressTestForm";
import { StressTestDetail } from "../components/StressCall/StressTestDetail";

type ViewState = "list" | "form" | "detail";

export function StressCallPage() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<ViewState>("list");
  const [selectedTest, setSelectedTest] = useState<StressTest | null>(null);

  const createMut = useMutation({
    mutationFn: createStressTest,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stress-tests"] });
      setView("list");
    },
  });

  const handleViewDetail = (test: StressTest) => {
    setSelectedTest(test);
    setView("detail");
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
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
            {view === "form"
              ? "New Stress Test"
              : view === "detail"
              ? selectedTest?.name ?? "Test Detail"
              : "Stress Call"}
          </h2>
        </div>

        <div className="flex gap-2">
          {view !== "list" && (
            <button
              onClick={() => setView("list")}
              className="btn-secondary"
            >
              Back to List
            </button>
          )}
          {view === "list" && (
            <button
              onClick={() => setView("form")}
              className="btn-primary"
            >
              + New Test
            </button>
          )}
        </div>
      </div>

      {/* Error banner */}
      {createMut.isError && (
        <div
          className="rounded-xl px-4 py-3 text-sm"
          style={{
            backgroundColor: "rgba(248, 113, 113, 0.1)",
            border: "1px solid rgba(248, 113, 113, 0.25)",
            color: "var(--error)",
          }}
        >
          Error: {createMut.error?.message}
        </div>
      )}

      {/* Views */}
      {view === "list" && (
        <StressTestList onViewDetail={handleViewDetail} />
      )}

      {view === "form" && (
        <StressTestForm
          onSubmit={(data) => createMut.mutate(data)}
          onCancel={() => setView("list")}
          isSubmitting={createMut.isPending}
        />
      )}

      {view === "detail" && selectedTest && (
        <StressTestDetail
          testId={selectedTest.id}
          onBack={() => setView("list")}
        />
      )}
    </div>
  );
}
