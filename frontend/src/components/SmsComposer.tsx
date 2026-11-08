"use client";

import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { Alert, Textarea } from "@/components/ui";
import { analyze } from "@/lib/sms-segments";

/** Message textarea with a live character/segment counter and Unicode warning. */
export function SmsComposer({
  value,
  onChange,
  variables,
  placeholder,
  rows = 5,
  id,
}: {
  value: string;
  onChange: (v: string) => void;
  variables?: string[];
  placeholder?: string;
  rows?: number;
  id?: string;
}) {
  const t = useTranslations("sms");
  const info = useMemo(() => analyze(value), [value]);
  return (
    <div className="space-y-2">
      <Textarea id={id} rows={rows} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <div className="flex flex-wrap gap-1">
          {variables?.map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => onChange(`${value}{{${v}}}`)}
              className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 hover:bg-slate-100"
            >
              {`{{${v}}}`}
            </button>
          ))}
        </div>
        <span aria-live="polite">
          {info.length} {t("characters")} · {info.segments} {t("segments")} · {info.encoding} · {info.remaining} left
        </span>
      </div>
      {info.encoding === "UCS2" && info.nonGsmChars.length > 0 && (
        <Alert kind="warning">{t("unicodeWarning", { chars: info.nonGsmChars.slice(0, 6).join(" ") })}</Alert>
      )}
    </div>
  );
}
