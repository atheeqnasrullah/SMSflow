import type { Metadata } from "next";

export const metadata: Metadata = { title: "Contact" };

export default function ContactPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16">
      <h1 className="text-3xl font-bold text-slate-900">Talk to us</h1>
      <p className="mt-3 text-slate-600">
        Questions about pricing, sender ID registration, or moving a large volume to SMSFlow? We reply within one business day.
      </p>
      <div className="mt-10 grid gap-6 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 p-6">
          <h2 className="font-semibold">Sales & onboarding</h2>
          <p className="mt-2 text-sm text-slate-600">sales@smsflow.lk</p>
        </div>
        <div className="rounded-xl border border-slate-200 p-6">
          <h2 className="font-semibold">Support</h2>
          <p className="mt-2 text-sm text-slate-600">support@smsflow.lk · or open a ticket from Settings → Support in your dashboard.</p>
        </div>
      </div>
    </div>
  );
}
