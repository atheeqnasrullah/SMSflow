import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Pricing" };

const PACKAGES = [
  { name: "Starter", price: 1000, bonus: 0, note: "Try it out" },
  { name: "Business", price: 5000, bonus: 250, note: "For growing businesses", featured: true },
  { name: "Pro", price: 20000, bonus: 2000, note: "High-volume senders" },
  { name: "Enterprise", price: 100000, bonus: 15000, note: "Campaigns at scale" },
];
const PER_SEGMENT = 0.85;

export default function PricingPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-16">
      <h1 className="text-center text-3xl font-bold text-slate-900">Simple, prepaid pricing</h1>
      <p className="mx-auto mt-3 max-w-2xl text-center text-slate-600">
        Top up your wallet in LKR and pay only for what you send – per SMS segment. No monthly fees, credits never expire.
      </p>
      <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {PACKAGES.map((p) => (
          <div key={p.name} className={`rounded-2xl border p-6 ${p.featured ? "border-brand-500 shadow-lg ring-1 ring-brand-500" : "border-slate-200"}`}>
            <p className="font-semibold text-slate-900">{p.name}</p>
            <p className="text-sm text-slate-500">{p.note}</p>
            <p className="mt-4 text-3xl font-bold">LKR {p.price.toLocaleString()}</p>
            {p.bonus > 0 && <p className="mt-1 text-sm font-medium text-emerald-700">+ LKR {p.bonus.toLocaleString()} bonus credit</p>}
            <p className="mt-2 text-sm text-slate-600">≈ {Math.floor((p.price + p.bonus) / PER_SEGMENT).toLocaleString()} SMS</p>
            <Link href="/register" className="mt-6 block rounded-lg bg-brand-600 px-4 py-2 text-center text-sm font-medium text-white hover:bg-brand-700">Get started</Link>
          </div>
        ))}
      </div>
      <div className="mt-16 grid gap-8 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 p-6">
          <h2 className="font-semibold">What is a segment?</h2>
          <p className="mt-2 text-sm text-slate-600">
            An English (GSM) SMS holds 160 characters; longer messages are split into 153-character segments. Sinhala, Tamil or emoji
            messages use Unicode: 70 characters, or 67 per segment when longer. Our composer shows the exact segment count before you send.
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 p-6">
          <h2 className="font-semibold">Standard rates</h2>
          <ul className="mt-2 space-y-1 text-sm text-slate-600">
            <li>Promotional & transactional: LKR {PER_SEGMENT.toFixed(2)} / segment</li>
            <li>OTP (priority route): LKR 0.95 / segment</li>
            <li>Enterprise volume pricing available – <Link href="/contact" className="text-brand-700 underline">contact us</Link></li>
          </ul>
        </div>
      </div>
    </div>
  );
}
