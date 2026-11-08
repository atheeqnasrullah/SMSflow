import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { BarChart3, CalendarClock, Code2, Languages, ShieldCheck, Users } from "lucide-react";

const FEATURES = [
  { icon: Users, title: "Contacts & groups", body: "Import CSV/Excel, dedupe automatically, track consent and honour opt-outs." },
  { icon: CalendarClock, title: "Scheduled campaigns", body: "Send now, schedule for later or repeat weekly – in Asia/Colombo time." },
  { icon: Languages, title: "Sinhala, Tamil & English", body: "Unicode-aware composer shows exactly how many SMS segments you will pay for." },
  { icon: ShieldCheck, title: "OTP & transactional", body: "Priority routing so verification codes are never stuck behind a bulk campaign." },
  { icon: Code2, title: "Developer API", body: "REST API, scoped API keys, idempotency and signed webhooks for delivery updates." },
  { icon: BarChart3, title: "Delivery reports", body: "Accepted vs delivered, per-campaign comparison and CSV exports." },
];

export default async function Home() {
  const t = await getTranslations("landing");
  return (
    <>
      <section className="bg-gradient-to-b from-brand-50 to-white">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-20 md:grid-cols-2">
          <div>
            <span className="inline-flex rounded-full bg-brand-100 px-3 py-1 text-xs font-medium text-brand-800">
              Built for Sri Lankan businesses
            </span>
            <h1 className="mt-4 text-4xl font-bold tracking-tight text-slate-900 md:text-5xl">{t("heroTitle")}</h1>
            <p className="mt-5 text-lg text-slate-600">{t("heroBody")}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/register" className="rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white shadow hover:bg-brand-700">
                {t("ctaPrimary")}
              </Link>
              <Link href="/docs" className="rounded-lg border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                {t("ctaSecondary")}
              </Link>
            </div>
            <p className="mt-4 text-xs text-slate-500">Free demo workspace with 500 demo SMS – no card required.</p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xl">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Campaign · Weekend sale</p>
            <div className="mt-4 space-y-3">
              {[
                ["Kasun, 20% off everything this weekend at Lanka Mart Kandy! Reply STOP to opt out.", "delivered"],
                ["අයේෂා, මෙම සති අන්තයේ සියල්ලටම 20% වට්ටමක්!", "delivered"],
                ["பிரியா, இந்த வார இறுதியில் 20% தள்ளுபடி!", "accepted"],
              ].map(([m, s]) => (
                <div key={m} className="rounded-xl bg-slate-50 p-3">
                  <p className="text-sm text-slate-700">{m}</p>
                  <p className={`mt-1 text-xs font-medium ${s === "delivered" ? "text-emerald-600" : "text-brand-600"}`}>{s}</p>
                </div>
              ))}
            </div>
            <div className="mt-5 grid grid-cols-3 gap-3 text-center">
              {[["12,480", "sent"], ["96.4%", "delivered"], ["LKR 10,608", "spent"]].map(([v, l]) => (
                <div key={l} className="rounded-lg border border-slate-100 p-2">
                  <p className="text-sm font-semibold text-slate-900">{v}</p>
                  <p className="text-xs text-slate-500">{l}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
      <section className="mx-auto max-w-6xl px-4 py-20">
        <h2 className="text-center text-2xl font-bold text-slate-900">Everything you need to reach customers by SMS</h2>
        <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-xl border border-slate-200 p-6">
              <f.icon className="h-6 w-6 text-brand-600" aria-hidden />
              <h3 className="mt-3 font-semibold text-slate-900">{f.title}</h3>
              <p className="mt-2 text-sm text-slate-600">{f.body}</p>
            </div>
          ))}
        </div>
      </section>
      <section className="bg-slate-900">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-4 py-14 text-center">
          <h2 className="text-2xl font-bold text-white">For shops, clinics, schools, salons and online stores</h2>
          <p className="max-w-2xl text-slate-300">
            Order confirmations, appointment reminders, payment receipts, exam results, promotions and OTPs – pay only per SMS segment, top up with PayHere.
          </p>
          <Link href="/register" className="mt-2 rounded-lg bg-white px-5 py-3 text-sm font-semibold text-slate-900 hover:bg-slate-100">
            Start in demo mode
          </Link>
        </div>
      </section>
    </>
  );
}
