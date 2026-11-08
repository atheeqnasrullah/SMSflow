import type { Metadata } from "next";

export const metadata: Metadata = { title: "Features" };

const SECTIONS = [
  { title: "Contact management", items: ["CSV & Excel import with automatic +94 formatting", "Groups and custom fields for personalisation", "Duplicate detection and invalid-number reports", "Consent tracking and a suppression list for opt-outs"] },
  { title: "Campaigns", items: ["Four-step wizard with live cost estimate", "Personalised messages: {{first_name}}, {{city}} …", "Schedule in Asia/Colombo time, or repeat daily/weekly/monthly", "Pause, resume, cancel – unused funds are released automatically"] },
  { title: "Delivery you can trust", items: ["Queue-based sending with automatic retries", "Separate priority route for OTP and transactional SMS", "Delivery reports: accepted vs delivered, never confused", "Provider failover for transactional traffic"] },
  { title: "Developer API", items: ["REST API v1 with OpenAPI documentation", "Scoped, revocable API keys; test keys use the demo gateway", "Idempotency keys so retries never double-send", "HMAC-signed webhooks with retries for up to ~21 hours"] },
  { title: "Billing", items: ["Prepaid LKR wallet with PayHere top-ups", "Per-segment pricing; funds reserved, then charged on acceptance", "Full transaction ledger and receipts", "Low-balance email alerts"] },
  { title: "Security & compliance", items: ["Strict tenant isolation enforced in the database (row-level security)", "Role-based access: owner, admin, manager, operator, viewer", "Audit log of logins, payments and admin actions", "Designed with Sri Lanka's PDPA and TRCSL rules in mind"] },
];

export default function FeaturesPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-16">
      <h1 className="text-3xl font-bold text-slate-900">Features</h1>
      <p className="mt-3 max-w-2xl text-slate-600">One platform for bulk SMS, OTP and notifications – built for Sri Lankan businesses of every size.</p>
      <div className="mt-10 grid gap-6 md:grid-cols-2">
        {SECTIONS.map((s) => (
          <section key={s.title} className="rounded-xl border border-slate-200 p-6">
            <h2 className="font-semibold text-slate-900">{s.title}</h2>
            <ul className="mt-3 space-y-2 text-sm text-slate-600">
              {s.items.map((i) => <li key={i} className="flex gap-2"><span className="text-brand-600">✓</span>{i}</li>)}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
