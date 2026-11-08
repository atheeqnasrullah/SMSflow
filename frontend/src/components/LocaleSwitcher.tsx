"use client";

import { useLocale } from "next-intl";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { getAccessToken } from "@/lib/api";

const LABELS: Record<string, string> = { en: "English", si: "සිංහල", ta: "தமிழ்" };

export function LocaleSwitcher({ className }: { className?: string }) {
  const locale = useLocale();
  const router = useRouter();
  return (
    <select
      aria-label="Language"
      value={locale}
      className={className ?? "rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700"}
      onChange={async (e) => {
        const next = e.target.value;
        document.cookie = `NEXT_LOCALE=${next}; path=/; max-age=31536000; samesite=lax`;
        if (getAccessToken()) {
          try {
            await api("/auth/me", { method: "PATCH", body: { locale: next } });
          } catch {
            /* preference still saved in cookie */
          }
        }
        router.refresh();
      }}
    >
      {Object.entries(LABELS).map(([k, v]) => (
        <option key={k} value={k}>
          {v}
        </option>
      ))}
    </select>
  );
}
