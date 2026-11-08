"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Alert, Badge, Button, Card, CopyBox, Empty, Field, Input, Modal, PageHeader, StatusBadge, Table, Tabs, Td } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dt } from "@/lib/format";
import type { ApiKey, Page, WebhookDelivery, WebhookEndpoint } from "@/types/api";

const SCOPES = ["sms:send", "sms:read", "otp", "balance:read", "contacts:read", "contacts:write", "templates:read", "campaigns:read"];
const EVENTS = ["message.accepted", "message.delivered", "message.failed", "campaign.completed", "wallet.low_balance", "payment.completed"];

export default function DevelopersPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState<"keys" | "webhooks" | "quickstart">("keys");
  if (!can("developers:manage")) return <Empty title="Only owners and admins can manage API keys and webhooks." />;
  return (
    <>
      <PageHeader title="Developers" description="Integrate SMSFlow with your website, app or POS." actions={<Link href="/docs" className="text-sm text-brand-700 hover:underline">API documentation →</Link>} />
      <Tabs tabs={[{ id: "keys", label: "API keys" }, { id: "webhooks", label: "Webhooks" }, { id: "quickstart", label: "Quick start" }]} value={tab} onChange={setTab} />
      <div className="mt-6">
        {tab === "keys" && <Keys />}
        {tab === "webhooks" && <Webhooks />}
        {tab === "quickstart" && <QuickStart />}
      </div>
    </>
  );
}

function Keys() {
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => api<ApiKey[]>("/developers/api-keys") });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["sms:send", "sms:read", "otp", "balance:read"]);
  const [test, setTest] = useState(false);
  const [created, setCreated] = useState<ApiKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api<ApiKey>("/developers/api-keys", { method: "POST", body: { name, scopes, test } }),
    onSuccess: (k) => { setCreated(k); setOpen(false); setName(""); qc.invalidateQueries({ queryKey: ["api-keys"] }); },
    onError: (e) => setError(errorMessage(e)),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/developers/api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });
  return (
    <Card title="API keys" actions={<Button size="sm" onClick={() => setOpen(true)}>Create key</Button>}>
      {created?.key && (
        <div className="mb-4 space-y-2">
          <Alert kind="warning">Copy this key now – it will not be shown again.</Alert>
          <CopyBox value={created.key} />
        </div>
      )}
      <Table head={["Name", "Key", "Type", "Scopes", "Last used", "Status", ""]} empty={keys.data?.length === 0}>
        {keys.data?.map((k) => (
          <tr key={k.id}>
            <Td className="font-medium">{k.name}</Td>
            <Td className="font-mono text-xs">{k.prefix}_••••</Td>
            <Td>{k.is_test ? <Badge color="yellow">test</Badge> : <Badge color="green">live</Badge>}</Td>
            <Td className="max-w-[14rem] truncate text-xs">{k.scopes.join(", ")}</Td>
            <Td>{dt(k.last_used_at)}</Td>
            <Td>{k.revoked_at ? <StatusBadge status="revoked" /> : <StatusBadge status="active" />}</Td>
            <Td>{!k.revoked_at && <Button size="sm" variant="ghost" onClick={() => confirm(`Revoke ${k.name}? Apps using it stop working immediately.`) && revoke.mutate(k.id)}>Revoke</Button>}</Td>
          </tr>
        ))}
      </Table>
      <Modal open={open} onClose={() => setOpen(false)} title="Create API key" footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button loading={create.isPending} disabled={!name || !scopes.length} onClick={() => create.mutate()}>Create</Button></>}>
        {error && <Alert kind="error">{error}</Alert>}
        <Field label="Name" htmlFor="kn"><Input id="kn" value={name} onChange={(e) => setName(e.target.value)} placeholder="Website checkout" /></Field>
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-slate-700">Scopes</legend>
          <div className="grid grid-cols-2 gap-2">
            {SCOPES.map((s) => (
              <label key={s} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={scopes.includes(s)} onChange={(e) => setScopes((x) => (e.target.checked ? [...x, s] : x.filter((y) => y !== s)))} />
                <code className="text-xs">{s}</code>
              </label>
            ))}
          </div>
        </fieldset>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={test} onChange={(e) => setTest(e.target.checked)} /> Test key (always uses the demo gateway, never billed)
        </label>
      </Modal>
    </Card>
  );
}

function Webhooks() {
  const qc = useQueryClient();
  const endpoints = useQuery({ queryKey: ["webhooks"], queryFn: () => api<WebhookEndpoint[]>("/developers/webhooks") });
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["message.delivered", "message.failed"]);
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api<WebhookEndpoint>("/developers/webhooks", { method: "POST", body: { url, events } }),
    onSuccess: (ep) => { setSecret(ep.secret ?? null); setUrl(""); qc.invalidateQueries({ queryKey: ["webhooks"] }); },
    onError: (e) => setError(errorMessage(e)),
  });
  const del = useMutation({ mutationFn: (id: string) => api(`/developers/webhooks/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }) });
  const toggle = useMutation({
    mutationFn: (ep: WebhookEndpoint) => api(`/developers/webhooks/${ep.id}`, { method: "PATCH", body: { is_active: !ep.is_active } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  });
  const test = useMutation({ mutationFn: (id: string) => api(`/developers/webhooks/${id}/test`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["deliveries"] }) });

  return (
    <div className="space-y-6">
      <Card title="Add endpoint">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); setError(null); create.mutate(); }}>
          {error && <Alert kind="error">{error}</Alert>}
          <Field label="HTTPS URL" htmlFor="wu"><Input id="wu" type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.lk/hooks/smsflow" /></Field>
          <div className="grid gap-2 sm:grid-cols-3">
            {EVENTS.map((ev) => (
              <label key={ev} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={events.includes(ev)} onChange={(e) => setEvents((x) => (e.target.checked ? [...x, ev] : x.filter((y) => y !== ev)))} />
                <code className="text-xs">{ev}</code>
              </label>
            ))}
          </div>
          <Button type="submit" loading={create.isPending} disabled={!events.length}>Add endpoint</Button>
        </form>
        {secret && (
          <div className="mt-4 space-y-2">
            <Alert kind="warning">Signing secret – store it securely. Verify the <code>SMSFlow-Signature</code> header with HMAC-SHA256(secret, timestamp + &quot;.&quot; + body).</Alert>
            <CopyBox value={secret} />
          </div>
        )}
      </Card>
      <Card title="Endpoints">
        <Table head={["URL", "Events", "Status", ""]} empty={endpoints.data?.length === 0}>
          {endpoints.data?.map((ep) => (
            <tr key={ep.id}>
              <Td className="max-w-[18rem] truncate font-mono text-xs">{ep.url}</Td>
              <Td className="text-xs">{ep.events.join(", ")}</Td>
              <Td>{ep.is_active ? <StatusBadge status="active" /> : <span title={ep.disabled_reason ?? ""}><StatusBadge status="suspended" /></span>}</Td>
              <Td className="space-x-1">
                <Button size="sm" variant="ghost" onClick={() => setSelected(ep.id)}>Deliveries</Button>
                <Button size="sm" variant="ghost" onClick={() => test.mutate(ep.id)}>Send test</Button>
                <Button size="sm" variant="ghost" onClick={() => toggle.mutate(ep)}>{ep.is_active ? "Disable" : "Enable"}</Button>
                <Button size="sm" variant="ghost" onClick={() => confirm("Delete endpoint?") && del.mutate(ep.id)}>Delete</Button>
              </Td>
            </tr>
          ))}
        </Table>
      </Card>
      {selected && <Deliveries endpointId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function Deliveries({ endpointId, onClose }: { endpointId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["deliveries", endpointId], queryFn: () => api<Page<WebhookDelivery>>(`/developers/webhooks/${endpointId}/deliveries`), refetchInterval: 5000 });
  const resend = useMutation({ mutationFn: (id: string) => api(`/developers/webhooks/deliveries/${id}/resend`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["deliveries"] }) });
  return (
    <Modal open wide onClose={onClose} title="Recent deliveries">
      <Table head={["Time", "Event", "Attempts", "HTTP", "Status", ""]} empty={list.data?.items.length === 0}>
        {list.data?.items.map((d) => (
          <tr key={d.id}>
            <Td>{dt(d.created_at)}</Td>
            <Td className="text-xs">{d.event_type}</Td>
            <Td>{d.attempt}</Td>
            <Td>{d.response_status ?? "—"}</Td>
            <Td><StatusBadge status={d.status} /></Td>
            <Td><Button size="sm" variant="ghost" onClick={() => resend.mutate(d.id)}>Resend</Button></Td>
          </tr>
        ))}
      </Table>
    </Modal>
  );
}

function QuickStart() {
  const curl = `curl -X POST https://api.smsflow.lk/api/v1/sms/send \\
  -H "Authorization: Bearer sf_live_xxxxxxxx_yyyyyyyy" \\
  -H "Idempotency-Key: order-10045-confirmation" \\
  -H "Content-Type: application/json" \\
  -d '{"to": "+94771234567", "message": "Your order has been confirmed.", "sender_id": "ABCSTORE"}'`;
  const node = `const res = await fetch("https://api.smsflow.lk/api/v1/sms/send", {
  method: "POST",
  headers: { Authorization: \`Bearer \${process.env.SMSFLOW_KEY}\`, "Content-Type": "application/json" },
  body: JSON.stringify({ to: "0771234567", message: "Your appointment is tomorrow at 10:00" }),
});
console.log(await res.json()); // { message_id, status: "queued", segments, cost, ... }`;
  const verify = `import hmac, hashlib

def verify(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"v1={mac}", signature)`;
  return (
    <div className="space-y-6">
      <Card title="Send an SMS (cURL)"><pre className="overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100">{curl}</pre></Card>
      <Card title="Node.js"><pre className="overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100">{node}</pre></Card>
      <Card title="Verify a webhook (Python)"><pre className="overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100">{verify}</pre></Card>
    </div>
  );
}
