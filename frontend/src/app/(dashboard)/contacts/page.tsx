"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Empty, Field, Input, Modal, PageHeader, Pager, Select, Table, Tabs, Td } from "@/components/ui";
import { api, download, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dt, num } from "@/lib/format";
import type { Contact, Group, ImportJob, Page, Suppression } from "@/types/api";

type Tab = "contacts" | "groups" | "suppressions" | "import";

export default function ContactsPage() {
  const [tab, setTab] = useState<Tab>("contacts");
  return (
    <>
      <PageHeader title="Contacts" description="Your audience, groups, opt-outs and imports." />
      <Tabs
        tabs={[
          { id: "contacts", label: "Contacts" },
          { id: "groups", label: "Groups" },
          { id: "suppressions", label: "Suppression list" },
          { id: "import", label: "Import" },
        ]}
        value={tab}
        onChange={setTab}
      />
      <div className="mt-6">
        {tab === "contacts" && <ContactsTab />}
        {tab === "groups" && <GroupsTab />}
        {tab === "suppressions" && <SuppressionsTab />}
        {tab === "import" && <ImportTab />}
      </div>
    </>
  );
}

function useGroups() {
  return useQuery({ queryKey: ["groups"], queryFn: () => api<Group[]>("/groups") });
}

function ContactsTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [groupId, setGroupId] = useState("");
  const [editing, setEditing] = useState<Contact | "new" | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const groups = useGroups();
  const contacts = useQuery({
    queryKey: ["contacts", page, q, groupId],
    queryFn: () => api<Page<Contact>>("/contacts", { query: { page, q, group_id: groupId } }),
  });
  const groupName = (id: string) => groups.data?.find((g) => g.id === id)?.name ?? "";
  const bulkDelete = useMutation({
    mutationFn: () => api("/contacts/bulk-delete", { method: "POST", body: { contact_ids: selected } }),
    onSuccess: () => {
      setSelected([]);
      qc.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
  const [targetGroup, setTargetGroup] = useState("");
  const addToGroup = useMutation({
    mutationFn: () => api(`/groups/${targetGroup}/members`, { method: "POST", body: { contact_ids: selected } }),
    onSuccess: () => {
      setSelected([]);
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["groups"] });
    },
  });

  return (
    <Card
      title={`${num(contacts.data?.total)} contacts`}
      actions={
        <>
          <Button variant="secondary" size="sm" onClick={() => download("/contacts/export", "contacts.csv", { group_id: groupId })}>Export CSV</Button>
          {can("contacts:write") && <Button size="sm" onClick={() => setEditing("new")}>Add contact</Button>}
        </>
      }
    >
      <div className="mb-4 flex flex-wrap gap-2">
        <Input className="max-w-xs" placeholder="Search name, phone, email" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <Select className="max-w-xs" value={groupId} onChange={(e) => { setGroupId(e.target.value); setPage(1); }}>
          <option value="">All groups</option>
          {groups.data?.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </Select>
      </div>
      {selected.length > 0 && can("contacts:write") && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-2 text-sm">
          <span>{selected.length} selected</span>
          <Select className="max-w-[12rem]" value={targetGroup} onChange={(e) => setTargetGroup(e.target.value)}>
            <option value="">Add to group…</option>
            {groups.data?.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </Select>
          <Button size="sm" variant="secondary" disabled={!targetGroup} loading={addToGroup.isPending} onClick={() => addToGroup.mutate()}>Add</Button>
          <Button size="sm" variant="danger" loading={bulkDelete.isPending} onClick={() => confirm(`Delete ${selected.length} contacts?`) && bulkDelete.mutate()}>Delete</Button>
        </div>
      )}
      <Table
        head={[
          <input
            key="all"
            type="checkbox"
            aria-label="Select all"
            checked={!!contacts.data?.items.length && selected.length === contacts.data.items.length}
            onChange={(e) => setSelected(e.target.checked ? contacts.data?.items.map((c) => c.id) ?? [] : [])}
          />,
          "Phone", "Name", "Groups", "Consent", "Added", "",
        ]}
        empty={contacts.data?.items.length === 0}
      >
        {contacts.data?.items.map((c) => (
          <tr key={c.id}>
            <Td>
              <input
                type="checkbox"
                aria-label={`Select ${c.phone_e164}`}
                checked={selected.includes(c.id)}
                onChange={(e) => setSelected((s) => (e.target.checked ? [...s, c.id] : s.filter((x) => x !== c.id)))}
              />
            </Td>
            <Td className="font-mono text-xs">{c.phone_e164} {c.suppressed && <Badge color="red">opted out</Badge>}</Td>
            <Td>{[c.first_name, c.last_name].filter(Boolean).join(" ") || "—"}</Td>
            <Td className="max-w-[14rem] truncate">{c.group_ids.map(groupName).join(", ") || "—"}</Td>
            <Td><Badge color={c.consent_status === "granted" ? "green" : c.consent_status === "revoked" ? "red" : "gray"}>{c.consent_status}</Badge></Td>
            <Td>{dt(c.created_at)}</Td>
            <Td>{can("contacts:write") && <Button size="sm" variant="ghost" onClick={() => setEditing(c)}>Edit</Button>}</Td>
          </tr>
        ))}
      </Table>
      <Pager page={page} pageSize={25} total={contacts.data?.total ?? 0} onPage={setPage} />
      {editing && <ContactModal contact={editing === "new" ? null : editing} groups={groups.data ?? []} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function ContactModal({ contact, groups, onClose }: { contact: Contact | null; groups: Group[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    phone: contact?.phone_e164 ?? "",
    first_name: contact?.first_name ?? "",
    last_name: contact?.last_name ?? "",
    email: contact?.email ?? "",
    language: contact?.language ?? "en",
    consent_status: contact?.consent_status ?? "granted",
    group_id: "",
    attributes: Object.entries(contact?.attributes ?? {}).map(([k, v]) => `${k}=${v}`).join("\n"),
  });
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: async () => {
      const attributes = Object.fromEntries(
        form.attributes.split("\n").map((l) => l.split("=")).filter((p) => p.length === 2 && p[0].trim()).map(([k, v]) => [k.trim(), v.trim()]),
      );
      const body = {
        first_name: form.first_name || null, last_name: form.last_name || null, email: form.email || null,
        language: form.language, consent_status: form.consent_status, attributes,
      };
      if (contact) return api(`/contacts/${contact.id}`, { method: "PATCH", body });
      return api("/contacts", { method: "POST", body: { ...body, phone: form.phone, consent_source: "dashboard", group_ids: form.group_id ? [form.group_id] : [] } });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["groups"] });
      onClose();
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: () => api(`/contacts/${contact!.id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contacts"] });
      onClose();
    },
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });

  return (
    <Modal
      open
      onClose={onClose}
      title={contact ? "Edit contact" : "Add contact"}
      footer={
        <>
          {contact && <Button variant="danger" className="mr-auto" loading={del.isPending} onClick={() => confirm("Delete this contact?") && del.mutate()}>Delete</Button>}
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
        </>
      }
    >
      {error && <Alert kind="error">{error}</Alert>}
      <Field label="Mobile number" htmlFor="phone" hint="Sri Lankan numbers like 077 123 4567 are converted to +94 format.">
        <Input id="phone" value={form.phone} onChange={set("phone")} disabled={!!contact} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="First name" htmlFor="fn"><Input id="fn" value={form.first_name} onChange={set("first_name")} /></Field>
        <Field label="Last name" htmlFor="ln"><Input id="ln" value={form.last_name} onChange={set("last_name")} /></Field>
      </div>
      <Field label="Email" htmlFor="em"><Input id="em" type="email" value={form.email} onChange={set("email")} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Language" htmlFor="lang">
          <Select id="lang" value={form.language} onChange={set("language")}>
            <option value="en">English</option><option value="si">Sinhala</option><option value="ta">Tamil</option>
          </Select>
        </Field>
        <Field label="Marketing consent" htmlFor="consent">
          <Select id="consent" value={form.consent_status} onChange={set("consent_status")}>
            <option value="granted">Granted</option><option value="unknown">Unknown</option><option value="revoked">Revoked</option>
          </Select>
        </Field>
      </div>
      {!contact && (
        <Field label="Group" htmlFor="grp">
          <Select id="grp" value={form.group_id} onChange={set("group_id")}>
            <option value="">None</option>
            {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </Select>
        </Field>
      )}
      <Field label="Custom attributes" htmlFor="attrs" hint="One per line, e.g. city=Kandy. Use them as {{city}} in messages.">
        <textarea id="attrs" rows={3} className="block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" value={form.attributes} onChange={set("attributes")} />
      </Field>
    </Modal>
  );
}

function GroupsTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const groups = useGroups();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api("/groups", { method: "POST", body: { name } }),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: ["groups"] });
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/groups/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["groups"] }),
  });
  return (
    <Card title="Groups">
      {can("contacts:write") && (
        <form className="mb-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); setError(null); create.mutate(); }}>
          <Input className="max-w-xs" placeholder="New group name" value={name} onChange={(e) => setName(e.target.value)} required />
          <Button type="submit" loading={create.isPending}>Create group</Button>
        </form>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      <Table head={["Name", "Members", ""]} empty={groups.data?.length === 0}>
        {groups.data?.map((g) => (
          <tr key={g.id}>
            <Td className="font-medium">{g.name}</Td>
            <Td>{num(g.member_count)}</Td>
            <Td>{can("contacts:write") && <Button size="sm" variant="ghost" onClick={() => confirm(`Delete group ${g.name}? Contacts are kept.`) && remove.mutate(g.id)}>Delete</Button>}</Td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}

function SuppressionsTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [phone, setPhone] = useState("");
  const [reason, setReason] = useState("manual");
  const [error, setError] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["suppressions", page], queryFn: () => api<Page<Suppression>>("/suppressions", { query: { page } }) });
  const add = useMutation({
    mutationFn: () => api("/suppressions", { method: "POST", body: { phone, reason } }),
    onSuccess: () => { setPhone(""); qc.invalidateQueries({ queryKey: ["suppressions"] }); },
    onError: (e) => setError(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/suppressions/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["suppressions"] }),
  });
  return (
    <Card title="Suppression list">
      <p className="mb-4 text-sm text-slate-500">Numbers here never receive messages from this workspace (opt-outs, complaints, invalid numbers).</p>
      {can("contacts:write") && (
        <form className="mb-4 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); setError(null); add.mutate(); }}>
          <Input className="max-w-xs" placeholder="077 123 4567" value={phone} onChange={(e) => setPhone(e.target.value)} required />
          <Select className="max-w-[12rem]" value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="manual">Manual</option><option value="unsubscribed">Unsubscribed</option>
            <option value="complaint">Complaint</option><option value="invalid">Invalid</option>
          </Select>
          <Button type="submit" loading={add.isPending}>Add</Button>
        </form>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      <Table head={["Phone", "Reason", "Added", ""]} empty={list.data?.items.length === 0}>
        {list.data?.items.map((s) => (
          <tr key={s.id}>
            <Td className="font-mono text-xs">{s.phone_e164}</Td>
            <Td><Badge>{s.reason}</Badge></Td>
            <Td>{dt(s.created_at)}</Td>
            <Td>{can("contacts:write") && <Button size="sm" variant="ghost" onClick={() => remove.mutate(s.id)}>Remove</Button>}</Td>
          </tr>
        ))}
      </Table>
      <Pager page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
    </Card>
  );
}

function ImportTab() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const groups = useGroups();
  const [file, setFile] = useState<File | null>(null);
  const [groupId, setGroupId] = useState("");
  const [consent, setConsent] = useState("granted");
  const [job, setJob] = useState<ImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!job || job.status === "completed" || job.status === "failed") {
      if (job?.status === "completed") qc.invalidateQueries({ queryKey: ["contacts"] });
      return;
    }
    const t = setTimeout(async () => setJob(await api<ImportJob>(`/contacts/imports/${job.id}`)), 1500);
    return () => clearTimeout(t);
  }, [job, qc]);

  if (!can("contacts:write")) return <Empty title="You don't have permission to import contacts." />;
  return (
    <Card title="Import contacts from CSV or Excel">
      <div className="space-y-4">
        <p className="text-sm text-slate-500">
          Include a <code>phone</code> column (also accepted: mobile, number). Optional: <code>first_name</code>, <code>last_name</code>,{" "}
          <code>email</code>, <code>language</code>. Any other columns become custom attributes. Duplicates and invalid numbers are skipped; existing
          contacts are updated. Max 5 MB.
        </p>
        {error && <Alert kind="error">{error}</Alert>}
        <input type="file" accept=".csv,.xlsx,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="File to import" />
        <div className="grid max-w-xl gap-3 sm:grid-cols-2">
          <Field label="Add to group" htmlFor="ig">
            <Select id="ig" value={groupId} onChange={(e) => setGroupId(e.target.value)}>
              <option value="">None</option>
              {groups.data?.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </Select>
          </Field>
          <Field label="Consent" htmlFor="ic" hint="Only mark granted if these people agreed to receive marketing SMS.">
            <Select id="ic" value={consent} onChange={(e) => setConsent(e.target.value)}>
              <option value="granted">Granted</option><option value="unknown">Unknown</option>
            </Select>
          </Field>
        </div>
        <Button
          disabled={!file}
          loading={busy}
          onClick={async () => {
            if (!file) return;
            setBusy(true);
            setError(null);
            try {
              const form = new FormData();
              form.append("file", file);
              if (groupId) form.append("group_id", groupId);
              form.append("consent_status", consent);
              setJob(await api<ImportJob>("/contacts/imports", { method: "POST", form }));
            } catch (e) {
              setError(errorMessage(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Upload and import
        </Button>
        {job && (
          <Alert kind={job.status === "failed" ? "error" : job.status === "completed" ? "success" : "info"}>
            <p className="font-medium">{job.filename}: {job.status}</p>
            {job.status === "completed" && (
              <p>
                {job.imported} new · {job.updated} updated · {job.duplicates} duplicates · {job.invalid} invalid (of {job.total_rows} rows)
                {job.has_error_report && (
                  <button className="ml-2 underline" onClick={() => download(`/contacts/imports/${job.id}/errors`, "import-errors.csv")}>Download error report</button>
                )}
              </p>
            )}
            {job.error && <p>{job.error}</p>}
          </Alert>
        )}
      </div>
    </Card>
  );
}
