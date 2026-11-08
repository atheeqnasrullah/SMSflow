"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { SmsComposer } from "@/components/SmsComposer";
import { Alert, Badge, Button, Card, Empty, Field, Input, Modal, PageHeader, Select } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Template } from "@/types/api";

export default function TemplatesPage() {
  const { can } = useAuth();
  const [editing, setEditing] = useState<Template | "new" | null>(null);
  const list = useQuery({ queryKey: ["templates"], queryFn: () => api<Template[]>("/templates") });
  return (
    <>
      <PageHeader
        title="Templates"
        description="Reusable messages with {{variables}} filled from contact fields."
        actions={can("templates:write") && <Button onClick={() => setEditing("new")}>New template</Button>}
      />
      {list.data?.length === 0 && <Empty title="No templates yet">Create one for order confirmations, reminders or promotions.</Empty>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.data?.map((t) => (
          <Card key={t.id} title={t.name} actions={can("templates:write") && <Button size="sm" variant="ghost" onClick={() => setEditing(t)}>Edit</Button>}>
            <p className="whitespace-pre-wrap text-sm text-slate-700">{t.body}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <Badge color={t.category === "promotional" ? "purple" : t.category === "otp" ? "yellow" : "blue"}>{t.category}</Badge>
              <Badge>{t.language}</Badge>
              <Badge>{t.encoding} · {t.segments} seg</Badge>
              {t.variables.map((v) => <Badge key={v} color="gray">{`{{${v}}}`}</Badge>)}
            </div>
          </Card>
        ))}
      </div>
      {editing && <TemplateModal template={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function TemplateModal({ template, onClose }: { template: Template | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(template?.name ?? "");
  const [body, setBody] = useState(template?.body ?? "");
  const [category, setCategory] = useState(template?.category ?? "transactional");
  const [language, setLanguage] = useState(template?.language ?? "en");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => {
      const payload = { name, body, category, language };
      return template ? api(`/templates/${template.id}`, { method: "PUT", body: payload }) : api("/templates", { method: "POST", body: payload });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["templates"] }); onClose(); },
    onError: (e) => setError(errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: () => api(`/templates/${template!.id}`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["templates"] }); onClose(); },
  });
  return (
    <Modal
      open
      wide
      onClose={onClose}
      title={template ? "Edit template" : "New template"}
      footer={
        <>
          {template && <Button variant="danger" className="mr-auto" onClick={() => confirm("Delete template?") && del.mutate()}>Delete</Button>}
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} onClick={() => save.mutate()} disabled={!name || !body}>Save</Button>
        </>
      }
    >
      {error && <Alert kind="error">{error}</Alert>}
      <Field label="Name" htmlFor="tn"><Input id="tn" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Category" htmlFor="tc">
          <Select id="tc" value={category} onChange={(e) => setCategory(e.target.value as Template["category"])}>
            <option value="transactional">Transactional</option><option value="promotional">Promotional</option><option value="otp">OTP</option>
          </Select>
        </Field>
        <Field label="Language" htmlFor="tl">
          <Select id="tl" value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="en">English</option><option value="si">Sinhala</option><option value="ta">Tamil</option>
          </Select>
        </Field>
      </div>
      <Field label="Body" htmlFor="tb">
        <SmsComposer id="tb" value={body} onChange={setBody} variables={["first_name", "last_name", "name", "phone"]} />
      </Field>
    </Modal>
  );
}
