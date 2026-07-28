import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listScenarios } from "../../lib/api";
import type { StressTestCreate } from "../../lib/api";

interface Props {
  onSubmit: (data: StressTestCreate) => void;
  onCancel: () => void;
  isSubmitting?: boolean;
}

export function StressTestForm({ onSubmit, onCancel, isSubmitting }: Props) {
  const { data: scenarios = [] } = useQuery({
    queryKey: ["stress-scenarios"],
    queryFn: listScenarios,
  });

  const [name, setName] = useState("");
  const [targetHost, setTargetHost] = useState("");
  const [targetPort, setTargetPort] = useState("5060");
  const [transport, setTransport] = useState("udp");
  const [scenario, setScenario] = useState("");
  const [cps, setCps] = useState("10");
  const [maxCalls, setMaxCalls] = useState("100");
  const [callDuration, setCallDuration] = useState("30");
  const [duration, setDuration] = useState("60");
  const [rampUp, setRampUp] = useState("10");
  const [rampStep, setRampStep] = useState("2");
  const [mediaType, setMediaType] = useState("none");
  const [callerId, setCallerId] = useState("sipp-test@127.0.0.1");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      name,
      target_host: targetHost,
      target_port: parseInt(targetPort, 10) || 5060,
      transport,
      scenario: scenario || undefined,
      cps: parseFloat(cps) || 10,
      max_calls: parseInt(maxCalls, 10) || 100,
      call_duration: parseInt(callDuration, 10) || 30,
      duration: parseInt(duration, 10) || 60,
      ramp_up: parseInt(rampUp, 10) || 10,
      ramp_step: parseInt(rampStep, 10) || 2,
      media_type: mediaType,
      caller_id: callerId || undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="card p-6 space-y-6">
      <h3
        className="text-base font-semibold"
        style={{
          fontFamily: "'Space Grotesk', system-ui, sans-serif",
          color: "var(--text-primary)",
        }}
      >
        New Stress Test
      </h3>

      {/* Name */}
      <div>
        <label
          className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Test Name
        </label>
        <input
          required
          className="input-field"
          placeholder="Baseline load test"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {/* Target */}
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="sm:col-span-2">
          <label
            className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}
          >
            Target Host
          </label>
          <input
            required
            className="input-field"
            placeholder="192.168.1.10"
            value={targetHost}
            onChange={(e) => setTargetHost(e.target.value)}
          />
        </div>
        <div>
          <label
            className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}
          >
            Port
          </label>
          <input
            type="number"
            min={1}
            max={65535}
            className="input-field"
            value={targetPort}
            onChange={(e) => setTargetPort(e.target.value)}
          />
        </div>
      </div>

      {/* Transport */}
      <div>
        <label
          className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Transport
        </label>
        <div className="flex gap-3">
          {["udp", "tcp"].map((t) => (
            <label
              key={t}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-150"
              style={{
                backgroundColor:
                  transport === t ? "rgba(226, 179, 64, 0.12)" : "var(--bg-elevated)",
                border: `1px solid ${transport === t ? "rgba(226, 179, 64, 0.35)" : "var(--border)"}`,
                color: transport === t ? "var(--accent)" : "var(--text-secondary)",
              }}
            >
              <input
                type="radio"
                name="transport"
                value={t}
                checked={transport === t}
                onChange={() => setTransport(t)}
                style={{ accentColor: "var(--accent)" }}
              />
              {t.toUpperCase()}
            </label>
          ))}
        </div>
      </div>

      {/* Scenario */}
      <div>
        <label
          className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Scenario
        </label>
        <select
          className="input-field"
          value={scenario}
          onChange={(e) => setScenario(e.target.value)}
          style={{ cursor: "pointer" }}
        >
          <option value="">Default (uac)</option>
          {scenarios.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name} — {s.description}
            </option>
          ))}
        </select>
      </div>

      {/* Load parameters */}
      <div>
        <p
          className="mb-3 text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Load Parameters
        </p>
        <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4">
          <div>
            <label
              className="mb-1.5 block text-xs"
              style={{ color: "var(--text-secondary)" }}
            >
              CPS (calls/sec)
            </label>
            <input
              type="number"
              min={0.1}
              step={0.1}
              className="input-field"
              value={cps}
              onChange={(e) => setCps(e.target.value)}
            />
          </div>
          <div>
            <label
              className="mb-1.5 block text-xs"
              style={{ color: "var(--text-secondary)" }}
            >
              Max Calls
            </label>
            <input
              type="number"
              min={1}
              className="input-field"
              value={maxCalls}
              onChange={(e) => setMaxCalls(e.target.value)}
            />
          </div>
          <div>
            <label
              className="mb-1.5 block text-xs"
              style={{ color: "var(--text-secondary)" }}
            >
              Call Duration (s)
            </label>
            <input
              type="number"
              min={1}
              className="input-field"
              value={callDuration}
              onChange={(e) => setCallDuration(e.target.value)}
            />
          </div>
          <div>
            <label
              className="mb-1.5 block text-xs"
              style={{ color: "var(--text-secondary)" }}
            >
              Test Duration (s)
            </label>
            <input
              type="number"
              min={1}
              className="input-field"
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Ramp-up */}
      <div>
        <p
          className="mb-3 text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Ramp-Up
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label
              className="mb-1.5 block text-xs"
              style={{ color: "var(--text-secondary)" }}
            >
              Ramp-Up Duration (s)
            </label>
            <input
              type="number"
              min={0}
              className="input-field"
              value={rampUp}
              onChange={(e) => setRampUp(e.target.value)}
            />
          </div>
          <div>
            <label
              className="mb-1.5 block text-xs"
              style={{ color: "var(--text-secondary)" }}
            >
              Ramp Step
            </label>
            <input
              type="number"
              min={1}
              className="input-field"
              value={rampStep}
              onChange={(e) => setRampStep(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Media type */}
      <div>
        <label
          className="mb-2 block text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Media Type
        </label>
        <div className="flex flex-wrap gap-3">
          {[
            { value: "none", label: "None (SIP only)" },
            { value: "pcma", label: "PCMA (G.711a)" },
            { value: "pcmu", label: "PCMU (G.711u)" },
            { value: "g729", label: "G.729" },
          ].map((opt) => (
            <label
              key={opt.value}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors duration-150"
              style={{
                backgroundColor:
                  mediaType === opt.value
                    ? "rgba(226, 179, 64, 0.12)"
                    : "var(--bg-elevated)",
                border: `1px solid ${mediaType === opt.value ? "rgba(226, 179, 64, 0.35)" : "var(--border)"}`,
                color:
                  mediaType === opt.value ? "var(--accent)" : "var(--text-secondary)",
              }}
            >
              <input
                type="radio"
                name="media_type"
                value={opt.value}
                checked={mediaType === opt.value}
                onChange={() => setMediaType(opt.value)}
                style={{ accentColor: "var(--accent)" }}
              />
              {opt.label}
            </label>
          ))}
        </div>
      </div>

      {/* Caller ID */}
      <div>
        <label
          className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          Caller ID
        </label>
        <input
          className="input-field"
          placeholder="sipp-test@127.0.0.1"
          value={callerId}
          onChange={(e) => setCallerId(e.target.value)}
        />
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <button type="submit" disabled={isSubmitting} className="btn-primary">
          {isSubmitting ? "Creating..." : "Start Test"}
        </button>
        <button type="button" onClick={onCancel} className="btn-secondary">
          Cancel
        </button>
      </div>
    </form>
  );
}
