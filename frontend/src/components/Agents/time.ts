/** "3 min ago" / "2 h ago" / "yesterday" style label for a timestamp. */
export function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Math.max(0, Date.now() - new Date(iso).getTime());
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export function formatDuration(startIso: string | null, endIso: string | null): string {
  if (!startIso) return "";
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const sec = Math.max(0, Math.round((end - new Date(startIso).getTime()) / 1000));
  return sec < 60 ? `${sec} s` : `${Math.floor(sec / 60)} min ${sec % 60} s`;
}

/** "expires in 3 h 12 min" / "expires in 40 s" / "expired" for a future deadline. */
export function timeLeft(iso: string | null): string {
  if (!iso) return "";
  const sec = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (sec <= 0) return "expired";
  if (sec < 60) return `expires in ${sec} s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `expires in ${min} min`;
  return `expires in ${Math.floor(min / 60)} h ${min % 60} min`;
}
