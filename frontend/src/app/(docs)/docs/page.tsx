import type { Metadata } from "next";
import Link from "next/link";
import { Logo } from "@/components/Logo";

export const metadata: Metadata = { title: "API documentation" };

const ENDPOINTS = [
  ["POST", "/sms/send", "Send a single SMS", "sms:send"],
  ["POST", "/sms/bulk", "Send up to 1,000 messages in one call", "sms:send"],
  ["GET", "/sms/{message_id}", "Message status and timeline", "sms:read"],
  ["GET", "/sms", "List / filter messages", "sms:read"],
  ["POST", "/otp/send", "Generate and send a one-time password", "otp"],
  ["POST", "/otp/verify", "Verify a one-time password", "otp"],
  ["GET", "/balance", "Wallet balance", "balance:read"],
  ["GET/POST", "/contacts, /groups", "Manage contacts and groups", "contacts:read / contacts:write"],
  ["GET", "/templates, /campaigns", "Read templates and campaigns", "templates:read / campaigns:read"],
];

function Code({ children }: { children: string }) {
  return <pre className="overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs leading-relaxed text-slate-100">{children}</pre>;
}

export default function DocsPage() {
  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-slate-100">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <Logo />
          <div className="flex gap-4 text-sm">
            <a href="/api/docs" className="text-brand-700 hover:underline">Interactive reference</a>
            <a href="/api/redoc" className="text-brand-700 hover:underline">ReDoc</a>
            <Link href="/developers" className="text-slate-600 hover:underline">Get an API key</Link>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-12 px-4 py-12">
        <section>
          <h1 className="text-3xl font-bold text-slate-900">SMSFlow API v1</h1>
          <p className="mt-3 text-slate-600">
            Base URL <code className="rounded bg-slate-100 px-1">https://api.smsflow.lk/api/v1</code>. All requests and responses are JSON. Times are UTC ISO-8601;
            phone numbers are accepted in local (<code>0771234567</code>) or E.164 (<code>+94771234567</code>) form.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Authentication</h2>
          <p className="text-slate-600">
            Create a key in <em>Developers → API keys</em> and send it as a bearer token. Keys look like <code>sf_live_ab12cd34_…</code>.{" "}
            <strong>Test keys</strong> (<code>sf_test_…</code>) always use the demo gateway: messages behave realistically but no SMS is sent and nothing is billed.
          </p>
          <Code>{`Authorization: Bearer sf_live_ab12cd34_xxxxxxxxxxxxxxxxxxxxxxxx`}</Code>
        </section>

        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Send an SMS</h2>
          <Code>{`POST /api/v1/sms/send
Authorization: Bearer sf_live_ab12cd34_…
Idempotency-Key: order-10045-confirmation
Content-Type: application/json

{ "to": "+94771234567", "message": "Your order has been confirmed.", "sender_id": "ABCSTORE" }`}</Code>
          <Code>{`HTTP/1.1 202 Accepted
{
  "message_id": "0193a6c2-…",
  "status": "queued",
  "segments": 1,
  "encoding": "GSM7",
  "cost": 0.85,
  "currency": "LKR",
  "is_demo": false
}`}</Code>
          <p className="text-sm text-slate-600">
            Status lifecycle: <code>queued → accepted → delivered | undelivered | unknown</code>, or <code>failed</code>/<code>rejected</code>.
            <em> Accepted</em> means the network provider took the message; <em>delivered</em> is confirmed by a delivery report.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Endpoints</h2>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead><tr className="text-left text-xs uppercase text-slate-500"><th className="py-2 pr-4">Method</th><th className="pr-4">Path</th><th className="pr-4">Description</th><th>Scope</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {ENDPOINTS.map(([m, p, d, s]) => (
                  <tr key={p}><td className="py-2 pr-4 font-mono text-xs">{m}</td><td className="pr-4 font-mono text-xs">{p}</td><td className="pr-4">{d}</td><td className="font-mono text-xs">{s}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-xl font-semibold">OTP</h2>
          <Code>{`POST /api/v1/otp/send    { "to": "0771234567", "brand": "MyShop" }
→ 202 { "otp_id": "…", "expires_at": "…" }

POST /api/v1/otp/verify  { "to": "0771234567", "code": "482913" }
→ 200 { "verified": true, "reason": "verified" }`}</Code>
          <p className="text-sm text-slate-600">Codes expire after 5 minutes, allow 5 attempts, and each number can request at most 3 codes per 10 minutes. Only a hash of the code is stored.</p>
        </section>

        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Idempotency & rate limits</h2>
          <p className="text-slate-600">
            Send an <code>Idempotency-Key</code> header on send endpoints. Repeating a request with the same key within 24 hours returns the original
            response (header <code>Idempotent-Replayed: true</code>) without sending again. Reusing a key with a different body returns <code>409</code>.
            The default rate limit is 10 requests/second per key; responses include <code>X-RateLimit-Limit</code> / <code>X-RateLimit-Remaining</code>, and
            <code> 429</code> responses include <code>Retry-After</code>.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Webhooks</h2>
          <p className="text-slate-600">
            Events: <code>message.accepted</code>, <code>message.delivered</code>, <code>message.failed</code>, <code>campaign.completed</code>,{" "}
            <code>wallet.low_balance</code>, <code>payment.completed</code>. Failed deliveries are retried after 1m, 5m, 30m, 2h, 6h and 12h.
          </p>
          <Code>{`POST https://your-app.lk/hooks/smsflow
SMSFlow-Event: message.delivered
SMSFlow-Delivery: whd_…
SMSFlow-Timestamp: 1767225600
SMSFlow-Signature: v1=<hex HMAC-SHA256(secret, timestamp + "." + body)>

{ "id": "evt_…", "type": "message.delivered", "created_at": "…", "data": { "message_id": "…", "status": "delivered", … } }`}</Code>
        </section>

        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Errors</h2>
          <Code>{`{ "error": { "code": "insufficient_funds", "message": "Insufficient balance: available 0.50 LKR, required 0.85" } }`}</Code>
          <p className="text-sm text-slate-600">
            Common codes: <code>invalid_number</code>, <code>suppressed</code>, <code>sender_id_not_approved</code>, <code>opt_out_required</code>,{" "}
            <code>insufficient_funds</code>, <code>tenant_suspended</code>, <code>rate_limited</code>, <code>idempotency_mismatch</code>.
          </p>
        </section>
      </main>
    </div>
  );
}
