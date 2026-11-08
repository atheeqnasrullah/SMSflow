import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

export const LOCALES = ["en", "si", "ta"] as const;
export type Locale = (typeof LOCALES)[number];

export default getRequestConfig(async () => {
  const store = await cookies();
  const raw = store.get("NEXT_LOCALE")?.value;
  const locale: Locale = (LOCALES as readonly string[]).includes(raw ?? "") ? (raw as Locale) : "en";
  return {
    locale,
    timeZone: "Asia/Colombo",
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
