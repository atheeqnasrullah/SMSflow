"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { SmsComposer } from "@/components/SmsComposer";
import { Alert, Button, Card, DemoBadge, Field, Input, Modal, PageHeader, Pager, Select, StatusBadge, Table, Td } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dt, lkr } from "@/lib/format";
import type { Message, Page, SenderId, Wallet } from "@/types/api";

export default function MessagesPage() {
  return (
    <Suspense>
      <MessagesInner />
    </Suspense>
  );
}

function MessagesInner() {
  const { can } = useAuth();
  const params = useSearchParams();
  const [openId, setOpenId] = useState<string | null>(params.get("id"));
  return (
    <>
      <PageHeader title="Messages" description="Send a single SMS and browse message history." />
      <div className="grid gap-6 lg:grid-cols-3">
        {can("messages:send") && <QuickSend />}
        <History className={can("messages:send") ? "lg:col-span-2" : "lg:col-span-3"} onOpen={setOpenId} />
      </div>
      {openId && <MessageDetail id={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}

function QuickSend() {
  const qc = useQueryClient();
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: () => api<Wallet>("/billing/wallet") });
  const senders = useQuery({ queryKey: ["sender-ids"], queryFn: () => api<SenderId[]>("/sender-ids") });
  const [to, setTo] = useState("");
  const [message, setMessage] = useState("");
  const [sender, setSender] = useState("");
  const [result, setResult] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const isDemo = wallet.data?.mode === "demo";
  const send = useMutation({
    mutationFn: () =>
      api<Message>("/sms/send", {
        method: "POST",
        body: { to, message, sender_id: sender || null },
        headers: { "Idempotency-Key": `dash-${crypto.randomUUID()}` },
      }),
    onSuccess: (m) => {
      setResult({ kind: "success", text: `Queued to ${m.to} · ${m.segments} segment(s)${m.is_demo ? " · demo" : ` · ${lkr(m.cost)}`}` });
      setMessage("");
      qc.invalidateQueries({ queryKey: ["messages"] });
      qc.invalidateQueries({ queryKey: ["wallet"] });
    },
    onError: (e) => setResult({ kind: "error", text: errorMessage(e) }),
  });
  return (
    <Card title="Quick send">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); setResult(null); send.mutate(); }}>
        <Field label="To" htmlFor="to"><Input id="to" type="tel" required placeholder="077 123 4567" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Field label="Sender ID" htmlFor="sid">
          {isDemo ? (
            <Input id="sid" maxLength={11} placeholder="SMSFlow" value={sender} onChange={(e) => setSender(e.target.value)} />
          ) : (
            <Select id="sid" value={sender} onChange={(e) => setSender(e.target.value)}>
              <option value="">Default</option>
              {senders.data?.filter((s) => s.status === "approved").map((s) => <option key={s.id}>{s.value}</option>)}
            </Select>
          )}
        </Field>
        <Field label="Message" htmlFor="msg"><SmsComposer id="msg" value={message} onChange={setMessage} /></Field>
        {result && <Alert kind={result.kind}>{result.text}</Alert>}
        <Button type="submit" className="w-full" loading={send.isPending} disabled={!to || !message}>Send</Button>
        {isDemo && <p className="text-xs text-slate-500">Demo mode: delivered via the demo gateway. Try +94770000001 (fails) or +94770000003 (stays pending).</p>}
      </form>
    </Card>
  );
}

function History({ className, onOpen }: { className?: string; onOpen: (id: string) => void }) {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [to, setTo] = useState("");
  const list = useQuery({
    queryKey: ["messages", page, status, source, to],
    queryFn: () => api<Page<Message>>("/sms", { query: { page, status, source, to } }),
    refetchInterval: (q) => (q.state.data?.items.some((m) => ["queued", "submitting", "accepted"].includes(m.status)) ? 4000 : false),
  });
  return (
    <Card title="History" className={className}>
      <div className="mb-4 flex flex-wrap gap-2">
        <Input className="max-w-[12rem]" placeholder="Phone contains" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} />
        <Select className="max-w-[10rem]" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status">
          <option value="">Any status</option>
          {["queued", "accepted", "delivered", "undelivered", "failed", "rejected", "unknown"].map((s) => <option key={s}>{s}</option>)}
        </Select>
        <Select className="max-w-[10rem]" value={source} onChange={(e) => { setSource(e.target.value); setPage(1); }} aria-label="Source">
          <option value="">Any source</option>
          {["dashboard", "api", "campaign", "otp"].map((s) => <option key={s}>{s}</option>)}
        </Select>
      </div>
      <Table head={["Time", "To", "Message", "Source", "Status", "Cost"]} empty={list.data?.items.length === 0}>
        {list.data?.items.map((m) => (
          <tr key={m.message_id} className="cursor-pointer hover:bg-slate-50" onClick={() => onOpen(m.message_id)}>
            <Td>{dt(m.created_at)}</Td>
            <Td className="font-mono text-xs">{m.to}</Td>
            <Td className="max-w-[16rem] truncate">{m.body}</Td>
            <Td>{m.source}</Td>
            <Td><StatusBadge status={m.status} /> {m.is_demo && <DemoBadge />}</Td>
            <Td>{m.is_demo ? "—" : lkr(m.cost)}</Td>
          </tr>
        ))}
      </Table>
      <Pager page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
    </Card>
  );
}

function MessageDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const msg = useQuery({ queryKey: ["message", id], queryFn: () => api<Message & { error_message?: string }>(`/sms/${id}`) });
  useEffect(() => {
    const t = setInterval(() => msg.refetch(), 4000);
    return () => clearInterval(t);
  }, [msg]);
  const m = msg.data;
  return (
    <Modal open onClose={onClose} title="Message details" wide>
      {!m ? null : (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap gap-2"><StatusBadge status={m.status} />{m.is_demo && <DemoBadge />}</div>
          <p className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3">{m.body}</p>
          <dl className="grid grid-cols-2 gap-2 text-xs text-slate-600">
            <dt>To</dt><dd className="font-mono">{m.to}</dd>
            <dt>Sender</dt><dd>{m.sender}</dd>
            <dt>Encoding / segments</dt><dd>{m.encoding} / {m.segments}</dd>
            <dt>Cost</dt><dd>{m.is_demo ? "Demo (not billed)" : lkr(m.cost)}</dd>
            <dt>Source</dt><dd>{m.source}</dd>
            <dt>Error</dt><dd>{m.error_code ?? "—"} {m.error_message ?? ""}</dd>
          </dl>
          <div>
            <p className="mb-1 text-xs font-semibold uppercase text-slate-500">Timeline</p>
            <ol className="space-y-1 text-xs">
              {m.events?.map((e, i) => <li key={i}><span className="text-slate-400">{dt(e.occurred_at)}</span> · {e.status}</li>)}
            </ol>
          </div>
        </div>
      )}
    </Modal>
  );
}
