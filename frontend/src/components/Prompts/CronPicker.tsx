import { useState, useEffect } from "react";
import cronstrue from "cronstrue/i18n";

interface Props {
  value: string;
  onChange: (value: string) => void;
}

const PRESETS = [
  { label: "Every hour", value: "0 * * * *" },
  { label: "Every day at 8am", value: "0 8 * * *" },
  { label: "Every day at midnight", value: "0 0 * * *" },
  { label: "Every Monday at 9am", value: "0 9 * * 1" },
  { label: "Every 5 minutes", value: "*/5 * * * *" },
];

export function CronPicker({ value, onChange }: Props) {
  const [custom, setCustom] = useState(false);
  const [humanReadable, setHumanReadable] = useState("");

  useEffect(() => {
    try {
      setHumanReadable(cronstrue.toString(value, { locale: "en" }));
    } catch {
      setHumanReadable("Invalid cron expression");
    }
  }, [value]);

  return (
    <div>
      <label
        className="mb-1.5 block text-xs font-medium uppercase tracking-wider"
        style={{ color: "var(--text-muted)" }}
      >
        Schedule (cron)
      </label>
      {!custom ? (
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => {
            const isSelected = value === p.value;
            return (
              <button
                key={p.value}
                type="button"
                onClick={() => onChange(p.value)}
                className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-150"
                style={{
                  backgroundColor: isSelected ? "var(--accent)" : "var(--bg-elevated)",
                  color: isSelected ? "#080b12" : "var(--text-secondary)",
                  border: `1px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                }}
              >
                {p.label}
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setCustom(true)}
            className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-150"
            style={{
              backgroundColor: "var(--bg-elevated)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
          >
            Custom...
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <input
            type="text"
            className="input-field font-mono"
            placeholder="0 8 * * *"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          <button
            type="button"
            onClick={() => setCustom(false)}
            className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-150"
            style={{
              backgroundColor: "var(--bg-elevated)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
          >
            ← Use presets
          </button>
        </div>
      )}
      {value && (
        <p
          className="mt-1.5 text-xs"
          style={{ color: "var(--accent)", opacity: 0.8 }}
        >
          {humanReadable}
        </p>
      )}
    </div>
  );
}
