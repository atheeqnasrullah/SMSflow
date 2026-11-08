"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Alert, Button, Card, Field, Input, PageHeader, Select, StatusBadge, Table, Tabs, Td, Textarea } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dt } from "@/lib/format";
import type { Invitation, Member, SenderId, WorkspaceDetail } from "@/types/api";

type Tab = "profile" | "workspace" | "team" | "senders" | "support";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("profile");
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs
        tabs={[
          { id: "profile", label: "Profile" },
          { id: "workspace", label: "Workspace" },
          { id: "team", label: "Team" },
          { id: "senders", label: "Sender IDs" },
          { id: "support", label: "Support" },
        ]}
        value={tab}
        onChange={setTab}
      />
      <div className="mt-6 max-w-4xl">
        {tab === "profile" && <Profile />}
        {tab === "workspace" && <WorkspaceTab />}
        {tab === "team" && <Team />}
        {tab === "senders" && <Senders />}
        {tab === "support" && <Support />}
      </div>
    </>
  );
}

function Profile() {
  const { me, reload } = useAuth();
  const [fullName, setFullName] = useState(me?.full_name ?? "");
  const [msg, setMsg] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const save = useMutation({
    mutationFn: () => api("/auth/me", { method: "PATCH", body: { full_name: fullName } }),
    onSuccess: () => { reload(); setMsg({ kind: "success", text: "Profile saved" }); },
  });
  const pw = useMutation({
    mutationFn: () => api("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } }),
    onSuccess: () => { setCurrent(""); setNext(""); setMsg({ kind: "success", text: "Password changed" }); },
    onError: (e) => setMsg({ kind: "error", text: errorMessage(e) }),
  });
  return (
    <div className="space-y-6">
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
      <Card title="Your profile">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label="Email" htmlFor="pe"><Input id="pe" value={me?.email ?? ""} disabled /></Field>
          <Field label="Full name" htmlFor="pn"><Input id="pn" value={fullName} onChange={(e) => setFullName(e.target.value)} /></Field>
          <Button type="submit" loading={save.isPending}>Save</Button>
        </form>
      </Card>
      <Card title="Change password">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); pw.mutate(); }}>
          <Field label="Current password" htmlFor="cp"><Input id="cp" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
          <Field label="New password" htmlFor="np" hint="At least 10 characters."><Input id="np" type="password" autoComplete="new-password" minLength={10} value={next} onChange={(e) => setNext(e.target.value)} /></Field>
          <Button type="submit" variant="secondary" loading={pw.isPending} disabled={!current || next.length < 10}>Change password</Button>
        </form>
      </Card>
    </div>
  );
}

function WorkspaceTab() {
  const { can, reload } = useAuth();
  const qc = useQueryClient();
  const ws = useQuery({ queryKey: ["workspace"], queryFn: () => api<WorkspaceDetail>("/workspace") });
  const [form, setForm] = useState<Partial<WorkspaceDetail>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const v = { ...ws.data, ...form };
  const save = useMutation({
    mutationFn: () => api("/workspace", { method: "PATCH", body: form }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["workspace"] }); reload(); setMsg("Saved"); setForm({}); },
    onError: (e) => setMsg(errorMessage(e)),
  });
  if (!ws.data) return null;
  const disabled = !can("workspace:update");
  return (
    <Card title="Workspace" actions={<StatusBadge status={ws.data.status} />}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        {msg && <Alert kind="info">{msg}</Alert>}
        <Field label="Business name" htmlFor="wn"><Input id="wn" disabled={disabled} value={v.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Business type" htmlFor="wt"><Input id="wt" disabled={disabled} value={v.business_type ?? ""} onChange={(e) => setForm({ ...form, business_type: e.target.value })} /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Billing email" htmlFor="we"><Input id="we" type="email" disabled={disabled} value={v.contact_email ?? ""} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} /></Field>
          <Field label="Phone" htmlFor="wp"><Input id="wp" disabled={disabled} value={v.contact_phone ?? ""} onChange={(e) => setForm({ ...form, contact_phone: e.target.value })} /></Field>
        </div>
        <Field label="Address" htmlFor="wa"><Textarea id="wa" rows={2} disabled={disabled} value={v.address ?? ""} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
        <p className="text-sm text-slate-500">
          Mode: <strong>{ws.data.mode}</strong>
          {ws.data.mode === "demo" && (ws.data.live_requested_at ? ` · Go-live requested ${dt(ws.data.live_requested_at)}` : " · Use 'Request live access' in the banner to go live.")}
        </p>
        {!disabled && <Button type="submit" loading={save.isPending} disabled={Object.keys(form).length === 0}>Save</Button>}
      </form>
    </Card>
  );
}

function Team() {
  const { can, me } = useAuth();
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/workspace/members") });
  const invitations = useQuery({ queryKey: ["invitations"], enabled: can("team:manage"), queryFn: () => api<Invitation[]>("/workspace/invitations") });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("operator");
  const [error, setError] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["members"] }); qc.invalidateQueries({ queryKey: ["invitations"] }); };
  const invite = useMutation({
    mutationFn: () => api("/workspace/invitations", { method: "POST", body: { email, role } }),
    onSuccess: () => { setEmail(""); refresh(); },
    onError: (e) => setError(errorMessage(e)),
  });
  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => api(`/workspace/members/${id}`, { method: "PATCH", body: { role } }),
    onSuccess: refresh,
    onError: (e) => setError(errorMessage(e)),
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`/workspace/members/${id}`, { method: "DELETE" }), onSuccess: refresh, onError: (e) => setError(errorMessage(e)) });
  const revoke = useMutation({ mutationFn: (id: string) => api(`/workspace/invitations/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const manage = can("team:manage");
  return (
    <div className="space-y-6">
      {error && <Alert kind="error">{error}</Alert>}
      {manage && (
        <Card title="Invite a team member">
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); setError(null); invite.mutate(); }}>
            <Field label="Email" htmlFor="ie"><Input id="ie" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
            <Field label="Role" htmlFor="ir">
              <Select id="ir" value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="admin">Admin</option><option value="manager">Manager</option><option value="operator">Operator</option><option value="viewer">Viewer</option>
              </Select>
            </Field>
            <Button type="submit" loading={invite.isPending}>Send invitation</Button>
          </form>
          <p className="mt-3 text-xs text-slate-500">Admins manage billing, team and API keys · Managers manage contacts, templates and campaigns · Operators send messages · Viewers see reports.</p>
        </Card>
      )}
      <Card title="Members">
        <Table head={["Name", "Email", "Role", ""]}>
          {members.data?.map((m) => (
            <tr key={m.user_id}>
              <Td className="font-medium">{m.full_name}</Td>
              <Td>{m.email}</Td>
              <Td>
                {manage && m.user_id !== me?.id ? (
                  <Select className="max-w-[9rem]" value={m.role} onChange={(e) => (e.target.value !== "owner" || confirm("Transfer ownership? You will become an admin.")) && changeRole.mutate({ id: m.user_id, role: e.target.value })}>
                    {(me?.role === "owner" ? ["owner", "admin", "manager", "operator", "viewer"] : ["admin", "manager", "operator", "viewer"]).map((r) => <option key={r}>{r}</option>)}
                    {m.role === "owner" && me?.role !== "owner" && <option>owner</option>}
                  </Select>
                ) : (
                  m.role
                )}
              </Td>
              <Td>{manage && m.role !== "owner" && m.user_id !== me?.id && <Button size="sm" variant="ghost" onClick={() => confirm(`Remove ${m.email}?`) && remove.mutate(m.user_id)}>Remove</Button>}</Td>
            </tr>
          ))}
        </Table>
      </Card>
      {manage && (
        <Card title="Invitations">
          <Table head={["Email", "Role", "Expires", "Status", ""]} empty={invitations.data?.length === 0}>
            {invitations.data?.map((i) => (
              <tr key={i.id}>
                <Td>{i.email}</Td>
                <Td>{i.role}</Td>
                <Td>{dt(i.expires_at)}</Td>
                <Td><StatusBadge status={i.accepted_at ? "accepted" : i.revoked_at ? "revoked" : new Date(i.expires_at) < new Date() ? "expired" : "pending"} /></Td>
                <Td>{!i.accepted_at && !i.revoked_at && <Button size="sm" variant="ghost" onClick={() => revoke.mutate(i.id)}>Revoke</Button>}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </div>
  );
}

function Senders() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["sender-ids"], queryFn: () => api<SenderId[]>("/sender-ids") });
  const [value, setValue] = useState("");
  const [purpose, setPurpose] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api("/sender-ids", { method: "POST", body: { value, purpose } }),
    onSuccess: () => { setValue(""); setPurpose(""); qc.invalidateQueries({ queryKey: ["sender-ids"] }); },
    onError: (e) => setError(errorMessage(e)),
  });
  const del = useMutation({ mutationFn: (id: string) => api(`/sender-ids/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["sender-ids"] }) });
  return (
    <div className="space-y-6">
      {can("sender_ids:request") && (
        <Card title="Request a sender ID">
          <p className="mb-4 text-sm text-slate-500">The name recipients see instead of a number (max 11 letters/digits, e.g. LANKAMART). Sender IDs are registered with the networks and reviewed by SMSFlow before use.</p>
          {error && <Alert kind="error">{error}</Alert>}
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); setError(null); create.mutate(); }}>
            <Field label="Sender ID" htmlFor="sv"><Input id="sv" maxLength={11} required value={value} onChange={(e) => setValue(e.target.value.toUpperCase())} /></Field>
            <Field label="How will you use it?" htmlFor="sp"><Textarea id="sp" rows={2} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Order confirmations and monthly promotions" /></Field>
            <Button type="submit" loading={create.isPending}>Submit request</Button>
          </form>
        </Card>
      )}
      <Card title="Your sender IDs">
        <Table head={["Sender ID", "Status", "Requested", "Note", ""]} empty={list.data?.length === 0}>
          {list.data?.map((s) => (
            <tr key={s.id}>
              <Td className="font-mono">{s.value}</Td>
              <Td><StatusBadge status={s.status} /></Td>
              <Td>{dt(s.created_at)}</Td>
              <Td className="text-xs text-slate-500">{s.rejection_reason ?? s.purpose}</Td>
              <Td>{s.status !== "approved" && can("sender_ids:request") && <Button size="sm" variant="ghost" onClick={() => del.mutate(s.id)}>Delete</Button>}</Td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}

interface Ticket { id: string; subject: string; body: string; status: string; priority: string; admin_notes: string | null; created_at: string }

function Support() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["tickets"], queryFn: () => api<Ticket[]>("/workspace/support-tickets") });
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const create = useMutation({
    mutationFn: () => api("/workspace/support-tickets", { method: "POST", body: { subject, body } }),
    onSuccess: () => { setSubject(""); setBody(""); qc.invalidateQueries({ queryKey: ["tickets"] }); },
  });
  return (
    <div className="space-y-6">
      <Card title="Contact support">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Field label="Subject" htmlFor="ts"><Input id="ts" required value={subject} onChange={(e) => setSubject(e.target.value)} /></Field>
          <Field label="Message" htmlFor="tb"><Textarea id="tb" rows={4} required value={body} onChange={(e) => setBody(e.target.value)} /></Field>
          <Button type="submit" loading={create.isPending}>Send</Button>
        </form>
      </Card>
      <Card title="Your tickets">
        <Table head={["Subject", "Status", "Created", "Reply"]} empty={list.data?.length === 0}>
          {list.data?.map((t) => (
            <tr key={t.id}>
              <Td className="font-medium">{t.subject}</Td>
              <Td><StatusBadge status={t.status === "open" ? "pending" : t.status === "closed" ? "completed" : t.status} /></Td>
              <Td>{dt(t.created_at)}</Td>
              <Td className="max-w-[20rem] truncate text-xs">{t.admin_notes ?? "—"}</Td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
