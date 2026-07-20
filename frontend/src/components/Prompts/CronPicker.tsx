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
      <label className="mb-1 block text-sm text-zinc-400">Schedule (cron)</label>
      {!custom ? (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.value}
                type="button"
                onClick={() => onChange(p.value)}
                className={`rounded px-3 py-1 text-xs ${
                  value === p.value ? "bg-blue-600 text-white" : "bg-zinc-700 text-zinc-300 hover:bg-zinc-600"
                }`}
              >
                {p.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setCustom(true)}
              className="rounded bg-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-600"
            >
              Custom...
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <input
            type="text"
            className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-white"
            placeholder="0 8 * * *"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          <button
            type="button"
            onClick={() => setCustom(false)}
            className="rounded bg-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-600"
          >
            Use presets
          </button>
        </div>
      )}
      {value && <p className="mt-1 text-xs text-zinc-500">{humanReadable}</p>}
    </div>
  );
}
