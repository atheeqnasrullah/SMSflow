export const TZ = "Asia/Colombo";

export function lkr(n: number | null | undefined, digits = 2) {
  return `LKR ${(n ?? 0).toLocaleString("en-LK", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function num(n: number | null | undefined) {
  return (n ?? 0).toLocaleString("en-LK");
}

export function dt(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: TZ,
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function dateOnly(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", { timeZone: TZ, day: "2-digit", month: "short", year: "numeric" });
}

/** Convert a <input type="datetime-local"> value interpreted as Asia/Colombo time to ISO UTC. */
export function colomboLocalToIso(local: string) {
  // Asia/Colombo is UTC+05:30 with no DST.
  return new Date(`${local}:00+05:30`).toISOString();
}

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}
