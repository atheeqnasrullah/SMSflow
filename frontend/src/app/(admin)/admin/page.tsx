"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Alert, Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Stat, StatusBadge, Table, Tabs, Td, Textarea } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { dt, lkr, num } from "@/lib/format";

type Tab = "tenants" | "senders" | "providers" | "pricing" | "revenue" | "abuse" | "tickets" | "audit";

interface Stats {
  tenants_by_status: Record<string, number>;
  tenants_by_mode: Record<string, number>;
  messages_24h: Record<string, number>;
  revenue_30d: number;
  pending_sender_ids: number;
  open_tickets: number;
  go_live_requests: number;
}

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("tenants");
  const stats = useQuery({ queryKey: ["admin-stats"], queryFn: () => api<Stats>("/admin/stats") });
  const s = stats.data;
  const sum = (o?: Record<string, number>) => Object.values(o ?? {}).reduce((a, b) => a + b, 0);
  return (
    <>
      <PageHeader title="Platform administration" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Tenants" value={num(sum(s?.tenants_by_status))} sub={`${s?.tenants_by_mode.live ?? 0} live · ${s?.tenants_by_mode.demo ?? 0} demo`} />
        <Stat label="Messages (24h)" value={num(sum(s?.messages_24h))} sub={`${num(s?.messages_24h.delivered)} delivered`} />
        <Stat label="Revenue (30d)" value={lkr(s?.revenue_30d, 0)} />
        <Stat label="Pending sender IDs" value={num(s?.pending_sender_ids)} />
        <Stat label="Open tickets" value={num(s?.open_tickets)} sub={`${s?.go_live_requests ?? 0} go-live requests`} />
      </div>
      <div className="mt-8">
        <Tabs
          tabs={[
            { id: "tenants", label: "Tenants" },
            { id: "senders", label: "Sender IDs" },
            { id: "providers", label: "Providers" },
            { id: "pricing", label: "Packages & pricing" },
            { id: "revenue", label: "Revenue" },
            { id: "abuse", label: "Abuse monitor" },
            { id: "tickets", label: "Support" },
            { id: "audit", label: "Audit log" },
          ]}
          value={tab}
          onChange={setTab}
        />
        <div className="mt-6">
          {tab === "tenants" && <Tenants />}
          {tab === "senders" && <Senders />}
          {tab === "providers" && <Providers />}
          {tab === "pricing" && <Pricing />}
          {tab === "revenue" && <Revenue />}
          {tab === "abuse" && <Abuse />}
          {tab === "tickets" && <Tickets />}
          {tab === "audit" && <Audit />}
        </div>
      </div>
    </>
  );
}

interface TenantRow {
  id: string; name: string; slug: string; status: string; mode: string; business_type: string | null; contact_email: string | null;
  created_at: string; live_requested_at: string | null; balance: number; reserved: number; demo_credits: number;
}

function Tenants() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [adjust, setAdjust] = useState<TenantRow | null>(null);
  const list = useQuery({ queryKey: ["admin-tenants", q], queryFn: () => api<{ total: number; items: TenantRow[] }>("/admin/tenants", { query: { q } }) });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, string> }) => api(`/admin/tenants/${id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-tenants"] }),
  });
  return (
    <Card title={`${num(list.data?.total)} tenants`}>
      <Input className="mb-4 max-w-xs" placeholder="Search name, slug, email" value={q} onChange={(e) => setQ(e.target.value)} />
      <Table head={["Name", "Status", "Mode", "Balance", "Demo credits", "Created", "Actions"]}>
        {list.data?.items.map((t) => (
          <tr key={t.id}>
            <Td><p className="font-medium">{t.name}</p><p className="text-xs text-slate-500">{t.contact_email}</p></Td>
            <Td><StatusBadge status={t.status} /></Td>
            <Td>{t.mode === "live" ? <Badge color="green">live</Badge> : <Badge color="yellow">demo</Badge>} {t.live_requested_at && t.mode === "demo" && <Badge color="blue">go-live requested</Badge>}</Td>
            <Td>{lkr(t.balance)}<p className="text-xs text-slate-500">{lkr(t.reserved)} reserved</p></Td>
            <Td>{num(t.demo_credits)}</Td>
            <Td>{dt(t.created_at)}</Td>
            <Td className="space-x-1">
              {t.mode === "demo" ? (
                <Button size="sm" variant="secondary" onClick={() => confirm(`Switch ${t.name} to LIVE (real SMS, real billing)?`) && update.mutate({ id: t.id, body: { mode: "live" } })}>Go live</Button>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: t.id, body: { mode: "demo" } })}>To demo</Button>
              )}
              {t.status === "active" ? (
                <Button size="sm" variant="danger" onClick={() => { const r = prompt("Suspension reason"); if (r) update.mutate({ id: t.id, body: { status: "suspended", suspended_reason: r } }); }}>Suspend</Button>
              ) : (
                <Button size="sm" variant="secondary" onClick={() => update.mutate({ id: t.id, body: { status: "active" } })}>Activate</Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setAdjust(t)}>Adjust wallet</Button>
            </Td>
          </tr>
        ))}
      </Table>
      {adjust && <AdjustModal tenant={adjust} onClose={() => setAdjust(null)} />}
    </Card>
  );
}

function AdjustModal({ tenant, onClose }: { tenant: TenantRow; onClose: () => void }) {
  const qc = useQueryClient();
  const [amount, setAmount] = useState("0");
  const [type, setType] = useState("bonus");
  const [demo, setDemo] = useState("0");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api(`/admin/tenants/${tenant.id}/wallet-adjustments`, { method: "POST", body: { amount, type, reason, demo_credits: Number(demo) || null } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-tenants"] }); onClose(); },
    onError: (e) => setError(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} title={`Adjust wallet – ${tenant.name}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={reason.length < 3} onClick={() => save.mutate()}>Apply</Button></>}>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Amount (LKR, signed)" htmlFor="aa"><Input id="aa" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label="Type" htmlFor="at"><Select id="at" value={type} onChange={(e) => setType(e.target.value)}><option value="bonus">Bonus</option><option value="adjustment">Adjustment</option></Select></Field>
      </div>
      <Field label="Demo credits to add (segments)" htmlFor="ad"><Input id="ad" type="number" value={demo} onChange={(e) => setDemo(e.target.value)} /></Field>
      <Field label="Reason (audited)" htmlFor="ar"><Input id="ar" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
    </Modal>
  );
}

interface SenderRow { id: string; tenant_name: string; value: string; status: string; purpose: string | null; created_at: string }

function Senders() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("pending");
  const list = useQuery({ queryKey: ["admin-senders", status], queryFn: () => api<SenderRow[]>("/admin/sender-ids", { query: { status } }) });
  const review = useMutation({
    mutationFn: ({ id, approve, reason }: { id: string; approve: boolean; reason?: string }) => api(`/admin/sender-ids/${id}/review`, { method: "POST", body: { approve, reason } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-senders"] }); qc.invalidateQueries({ queryKey: ["admin-stats"] }); },
  });
  return (
    <Card title="Sender ID requests" actions={<Select value={status} onChange={(e) => setStatus(e.target.value)}><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="">All</option></Select>}>
      <Table head={["Tenant", "Sender ID", "Purpose", "Requested", "Status", ""]} empty={list.data?.length === 0}>
        {list.data?.map((s) => (
          <tr key={s.id}>
            <Td>{s.tenant_name}</Td>
            <Td className="font-mono">{s.value}</Td>
            <Td className="max-w-[16rem] truncate text-xs">{s.purpose}</Td>
            <Td>{dt(s.created_at)}</Td>
            <Td><StatusBadge status={s.status} /></Td>
            <Td className="space-x-1">
              {s.status !== "approved" && <Button size="sm" onClick={() => review.mutate({ id: s.id, approve: true })}>Approve</Button>}
              {s.status !== "rejected" && <Button size="sm" variant="danger" onClick={() => { const r = prompt("Rejection reason"); if (r) review.mutate({ id: s.id, approve: false, reason: r }); }}>Reject</Button>}
            </Td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

interface ProviderRow { id: string; name: string; type: string; code: string; priority: number; is_active: boolean; cost_per_segment: number; max_tps: number; categories: string; config: Record<string, string>; healthy: boolean }

function Providers() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["admin-providers"], queryFn: () => api<ProviderRow[]>("/admin/providers") });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", type: "textlk", code: "", priority: "10", cost: "0.45", tps: "20", config: '{\n  "api_token": "",\n  "callback_token": ""\n}' });
  const [error, setError] = useState<string | null>(null);
  const [balance, setBalance] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: () => api("/admin/providers", { method: "POST", body: {
      name: form.name, type: form.type, code: form.code, priority: Number(form.priority), cost_per_segment: form.cost, max_tps: Number(form.tps), config: JSON.parse(form.config),
    } }),
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ["admin-providers"] }); },
    onError: (e) => setError(errorMessage(e)),
  });
  const toggle = useMutation({
    mutationFn: (p: ProviderRow) => api(`/admin/providers/${p.id}`, { method: "PATCH", body: { is_active: !p.is_active } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-providers"] }),
  });
  return (
    <Card title="SMS providers" actions={<Button size="sm" onClick={() => setOpen(true)}>Add provider</Button>}>
      <p className="mb-4 text-sm text-slate-500">Lower priority number = preferred. DLR callback URL: <code>/api/v1/callbacks/dlr/&lt;code&gt;?token=&lt;callback_token&gt;</code></p>
      <Table head={["Name", "Type / code", "Priority", "Cost/seg", "TPS", "Health", "Active", ""]}>
        {list.data?.map((p) => (
          <tr key={p.id}>
            <Td className="font-medium">{p.name}</Td>
            <Td className="text-xs">{p.type} / <code>{p.code}</code></Td>
            <Td>{p.priority}</Td>
            <Td>{lkr(p.cost_per_segment, 4)}</Td>
            <Td>{p.max_tps}</Td>
            <Td>{p.healthy ? <Badge color="green">healthy</Badge> : <Badge color="red">circuit open</Badge>}</Td>
            <Td>{p.is_active ? <Badge color="green">yes</Badge> : <Badge>no</Badge>}</Td>
            <Td className="space-x-1">
              <Button size="sm" variant="ghost" onClick={() => toggle.mutate(p)}>{p.is_active ? "Disable" : "Enable"}</Button>
              {p.type !== "demo" && (
                <Button size="sm" variant="ghost" onClick={async () => {
                  try { const b = await api<{ amount: number | null; currency: string | null }>(`/admin/providers/${p.id}/balance`); setBalance((x) => ({ ...x, [p.id]: b.amount == null ? "n/a" : `${b.amount} ${b.currency ?? ""}` })); }
                  catch (e) { setBalance((x) => ({ ...x, [p.id]: errorMessage(e) })); }
                }}>{balance[p.id] ?? "Balance"}</Button>
              )}
            </Td>
          </tr>
        ))}
      </Table>
      <Modal open={open} wide onClose={() => setOpen(false)} title="Add provider" footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button loading={create.isPending} onClick={() => { try { JSON.parse(form.config); create.mutate(); } catch { setError("Config must be valid JSON"); } }}>Create</Button></>}>
        {error && <Alert kind="error">{error}</Alert>}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name" htmlFor="pn"><Input id="pn" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Code (URL-safe)" htmlFor="pc"><Input id="pc" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
          <Field label="Type" htmlFor="pt"><Select id="pt" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>{["textlk", "smslenz", "twilio", "generic"].map((t) => <option key={t}>{t}</option>)}</Select></Field>
          <Field label="Priority" htmlFor="pp"><Input id="pp" type="number" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} /></Field>
          <Field label="Cost per segment (LKR)" htmlFor="pcs"><Input id="pcs" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} /></Field>
          <Field label="Max TPS" htmlFor="ptps"><Input id="ptps" type="number" value={form.tps} onChange={(e) => setForm({ ...form, tps: e.target.value })} /></Field>
        </div>
        <Field label="Credentials / config (JSON, stored encrypted)" htmlFor="pcfg" hint="twilio: account_sid, auth_token · textlk/smslenz: api_token, callback_token, optional base_url and field overrides">
          <Textarea id="pcfg" rows={6} className="font-mono text-xs" value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} />
        </Field>
      </Modal>
    </Card>
  );
}

interface PackageRow { id: string; name: string; description: string | null; price_lkr: number; credits: number; bonus_credits: number; is_active: boolean; sort_order: number }
interface PricingRow { id: string; tenant_id: string | null; message_category: string | null; price_per_segment: number; effective_from: string }

function Pricing() {
  const qc = useQueryClient();
  const pkgs = useQuery({ queryKey: ["admin-packages"], queryFn: () => api<PackageRow[]>("/admin/packages") });
  const rules = useQuery({ queryKey: ["admin-pricing"], queryFn: () => api<PricingRow[]>("/admin/pricing") });
  const [pkg, setPkg] = useState({ name: "", price_lkr: "", credits: "", bonus_credits: "0" });
  const [rule, setRule] = useState({ tenant_id: "", message_category: "", price_per_segment: "" });
  const [error, setError] = useState<string | null>(null);
  const addPkg = useMutation({
    mutationFn: () => api("/admin/packages", { method: "POST", body: { ...pkg, sort_order: (pkgs.data?.length ?? 0) + 1 } }),
    onSuccess: () => { setPkg({ name: "", price_lkr: "", credits: "", bonus_credits: "0" }); qc.invalidateQueries({ queryKey: ["admin-packages"] }); },
    onError: (e) => setError(errorMessage(e)),
  });
  const togglePkg = useMutation({
    mutationFn: (p: PackageRow) => api(`/admin/packages/${p.id}`, { method: "PUT", body: { ...p, is_active: !p.is_active } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-packages"] }),
  });
  const addRule = useMutation({
    mutationFn: () => api("/admin/pricing", { method: "POST", body: { tenant_id: rule.tenant_id || null, message_category: rule.message_category || null, price_per_segment: rule.price_per_segment } }),
    onSuccess: () => { setRule({ tenant_id: "", message_category: "", price_per_segment: "" }); qc.invalidateQueries({ queryKey: ["admin-pricing"] }); },
    onError: (e) => setError(errorMessage(e)),
  });
  return (
    <div className="space-y-6">
      {error && <Alert kind="error">{error}</Alert>}
      <Card title="Credit packages">
        <form className="mb-4 grid gap-2 sm:grid-cols-5" onSubmit={(e) => { e.preventDefault(); addPkg.mutate(); }}>
          <Input placeholder="Name" required value={pkg.name} onChange={(e) => setPkg({ ...pkg, name: e.target.value })} />
          <Input placeholder="Price LKR" required type="number" value={pkg.price_lkr} onChange={(e) => setPkg({ ...pkg, price_lkr: e.target.value })} />
          <Input placeholder="Credits LKR" required type="number" value={pkg.credits} onChange={(e) => setPkg({ ...pkg, credits: e.target.value })} />
          <Input placeholder="Bonus LKR" type="number" value={pkg.bonus_credits} onChange={(e) => setPkg({ ...pkg, bonus_credits: e.target.value })} />
          <Button type="submit" loading={addPkg.isPending}>Add package</Button>
        </form>
        <Table head={["Name", "Price", "Credits", "Bonus", "Active", ""]}>
          {pkgs.data?.map((p) => (
            <tr key={p.id}>
              <Td className="font-medium">{p.name}</Td><Td>{lkr(p.price_lkr, 0)}</Td><Td>{lkr(p.credits, 0)}</Td><Td>{lkr(p.bonus_credits, 0)}</Td>
              <Td>{p.is_active ? <Badge color="green">yes</Badge> : <Badge>no</Badge>}</Td>
              <Td><Button size="sm" variant="ghost" onClick={() => togglePkg.mutate(p)}>{p.is_active ? "Disable" : "Enable"}</Button></Td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card title="Pricing rules (per segment)">
        <p className="mb-4 text-sm text-slate-500">Most specific rule wins: tenant + category › tenant › category › global. New rules apply from now on.</p>
        <form className="mb-4 grid gap-2 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); addRule.mutate(); }}>
          <Input placeholder="Tenant ID (blank = global)" value={rule.tenant_id} onChange={(e) => setRule({ ...rule, tenant_id: e.target.value })} />
          <Select value={rule.message_category} onChange={(e) => setRule({ ...rule, message_category: e.target.value })}>
            <option value="">Any category</option><option value="otp">OTP</option><option value="transactional">Transactional</option><option value="promotional">Promotional</option>
          </Select>
          <Input placeholder="LKR per segment" required value={rule.price_per_segment} onChange={(e) => setRule({ ...rule, price_per_segment: e.target.value })} />
          <Button type="submit" loading={addRule.isPending}>Add rule</Button>
        </form>
        <Table head={["Scope", "Category", "Price", "Effective from"]}>
          {rules.data?.map((r) => (
            <tr key={r.id}>
              <Td className="font-mono text-xs">{r.tenant_id ?? "global"}</Td><Td>{r.message_category ?? "any"}</Td><Td>{lkr(r.price_per_segment, 4)}</Td><Td>{dt(r.effective_from)}</Td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}

function Revenue() {
  const data = useQuery({ queryKey: ["admin-revenue"], queryFn: () => api<{ daily: { date: string; amount: number; payments: number }[]; total: number; billed_usage: number; billed_segments: number }>("/admin/revenue") });
  const d = data.data;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Top-ups (90d)" value={lkr(d?.total, 0)} />
        <Stat label="Billed usage (90d)" value={lkr(d?.billed_usage, 0)} />
        <Stat label="Billed segments (90d)" value={num(d?.billed_segments)} />
      </div>
      <Card title="Daily top-ups">
        <Table head={["Date", "Payments", "Amount"]} empty={d?.daily.length === 0}>
          {d?.daily.map((r) => <tr key={r.date}><Td>{r.date}</Td><Td>{r.payments}</Td><Td>{lkr(r.amount)}</Td></tr>)}
        </Table>
      </Card>
    </div>
  );
}

function Abuse() {
  const [hours, setHours] = useState(24);
  const data = useQuery({ queryKey: ["admin-abuse", hours], queryFn: () => api<{ tenant_id: string; tenant_name: string; messages: number; failed: number; otp: number; failure_rate: number }[]>("/admin/abuse", { query: { hours } }) });
  return (
    <Card title="Volume & failure rates" actions={<Select value={hours} onChange={(e) => setHours(Number(e.target.value))}><option value={1}>Last hour</option><option value={24}>Last 24h</option><option value={168}>Last 7 days</option></Select>}>
      <p className="mb-4 text-sm text-slate-500">High failure rates or sudden OTP volume can indicate SMS pumping or bad lists.</p>
      <Table head={["Tenant", "Messages", "Failed", "Failure rate", "OTP"]} empty={data.data?.length === 0}>
        {data.data?.map((r) => (
          <tr key={r.tenant_id}>
            <Td className="font-medium">{r.tenant_name}</Td><Td>{num(r.messages)}</Td><Td>{num(r.failed)}</Td>
            <Td>{r.failure_rate > 20 ? <Badge color="red">{r.failure_rate}%</Badge> : `${r.failure_rate}%`}</Td><Td>{num(r.otp)}</Td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

interface TicketRow { id: string; tenant_name: string; subject: string; body: string; status: string; priority: string; admin_notes: string | null; created_at: string }

function Tickets() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("open");
  const list = useQuery({ queryKey: ["admin-tickets", status], queryFn: () => api<TicketRow[]>("/admin/tickets", { query: { status } }) });
  const [open, setOpen] = useState<TicketRow | null>(null);
  const [notes, setNotes] = useState("");
  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/admin/tickets/${open!.id}`, { method: "PATCH", body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-tickets"] }); setOpen(null); },
  });
  return (
    <Card title="Support tickets" actions={<Select value={status} onChange={(e) => setStatus(e.target.value)}><option value="open">Open</option><option value="pending">Pending</option><option value="closed">Closed</option><option value="">All</option></Select>}>
      <Table head={["Tenant", "Subject", "Priority", "Status", "Created"]} empty={list.data?.length === 0}>
        {list.data?.map((t) => (
          <tr key={t.id} className="cursor-pointer hover:bg-slate-50" onClick={() => { setOpen(t); setNotes(t.admin_notes ?? ""); }}>
            <Td>{t.tenant_name}</Td><Td className="font-medium">{t.subject}</Td>
            <Td>{t.priority === "high" ? <Badge color="red">high</Badge> : t.priority}</Td><Td>{t.status}</Td><Td>{dt(t.created_at)}</Td>
          </tr>
        ))}
      </Table>
      {open && (
        <Modal open wide onClose={() => setOpen(null)} title={open.subject} footer={<>
          <Button variant="secondary" onClick={() => update.mutate({ admin_notes: notes, status: "pending", assign_to_me: true })}>Reply & mark pending</Button>
          <Button onClick={() => update.mutate({ admin_notes: notes, status: "closed" })}>Reply & close</Button>
        </>}>
          <p className="text-xs text-slate-500">{open.tenant_name} · {dt(open.created_at)}</p>
          <p className="whitespace-pre-wrap rounded bg-slate-50 p-3 text-sm">{open.body}</p>
          <Field label="Reply / notes (visible to tenant)" htmlFor="tn"><Textarea id="tn" rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        </Modal>
      )}
    </Card>
  );
}

function Audit() {
  const [action, setAction] = useState("");
  const list = useQuery({
    queryKey: ["admin-audit", action],
    queryFn: () => api<{ id: string; tenant_id: string | null; actor_type: string; action: string; target_type: string | null; target_id: string | null; metadata: Record<string, unknown>; ip: string | null; created_at: string }[]>("/admin/audit-logs", { query: { action } }),
  });
  return (
    <Card title="Audit log">
      <Input className="mb-4 max-w-xs" placeholder="Action prefix, e.g. admin. or auth." value={action} onChange={(e) => setAction(e.target.value)} />
      <Table head={["Time", "Action", "Actor", "Target", "Details", "IP"]} empty={list.data?.length === 0}>
        {list.data?.map((a) => (
          <tr key={a.id}>
            <Td>{dt(a.created_at)}</Td><Td className="font-mono text-xs">{a.action}</Td><Td>{a.actor_type}</Td>
            <Td className="text-xs">{a.target_type} {a.target_id?.slice(0, 8)}</Td>
            <Td className="max-w-[18rem] truncate font-mono text-xs">{JSON.stringify(a.metadata)}</Td><Td className="text-xs">{a.ip}</Td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}
