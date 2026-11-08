"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Card, DemoBadge, PageHeader, Pager, Stat, StatusBadge, Table, Td } from "@/components/ui";
import { api, download, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dt, lkr, num } from "@/lib/format";
import type { Campaign, Message, Page } from "@/types/api";

export default function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const camp = useQuery({
    queryKey: ["campaign", id],
    queryFn: () => api<Campaign>(`/campaigns/${id}`),
    refetchInterval: (q) => (q.state.data && ["processing", "paused"].includes(q.state.data.status) ? 3000 : false),
  });
  const messages = useQuery({
    queryKey: ["campaign-messages", id, page],
    queryFn: () => api<Page<Message>>(`/campaigns/${id}/messages`, { query: { page } }),
    refetchInterval: camp.data?.status === "processing" ? 3000 : false,
  });
  const action = useMutation({
    mutationFn: (a: string) => api<Campaign>(`/campaigns/${id}/${a}`, { method: "POST" }),
    onSuccess: (c, a) => {
      if (a === "duplicate") router.push(`/campaigns/${c.id}`);
      qc.invalidateQueries({ queryKey: ["campaign", id] });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: () => api(`/campaigns/${id}`, { method: "DELETE" }),
    onSuccess: () => router.push("/campaigns"),
  });

  const c = camp.data;
  if (!c) return null;
  const s = c.stats ?? {};
  const total = s.total ?? 0;
  const done = (s.accepted ?? 0) + (s.delivered ?? 0) + (s.undelivered ?? 0) + (s.failed ?? 0) + (s.rejected ?? 0) + (s.unknown ?? 0);
  const progress = total ? Math.round((done / total) * 100) : c.status === "completed" ? 100 : 0;

  return (
    <>
      <PageHeader
        title={c.name}
        description={c.recurrence ? `Recurring: ${c.recurrence}` : undefined}
        actions={
          <>
            <StatusBadge status={c.status} /> {c.is_demo && <DemoBadge />}
            {c.status === "draft" && can("campaigns:write") && (
              <>
                <Button variant="danger" size="sm" onClick={() => confirm("Delete this draft?") && remove.mutate()}>Delete</Button>
                <Button size="sm" loading={action.isPending} onClick={() => confirm("Send this campaign now? Funds will be reserved.") && action.mutate("send")}>Send now</Button>
              </>
            )}
            {c.status === "processing" && can("campaigns:launch") && <Button variant="secondary" size="sm" onClick={() => action.mutate("pause")}>Pause</Button>}
            {c.status === "paused" && can("campaigns:launch") && <Button size="sm" onClick={() => action.mutate("resume")}>Resume</Button>}
            {c.status === "scheduled" && can("campaigns:write") && <Button variant="secondary" size="sm" onClick={() => action.mutate("unschedule")}>Unschedule</Button>}
            {["scheduled", "paused", "processing"].includes(c.status) && can("campaigns:write") && (
              <Button variant="danger" size="sm" onClick={() => confirm("Cancel the campaign? Unsent messages are not sent and their funds are released.") && action.mutate("cancel")}>Cancel</Button>
            )}
            {can("campaigns:write") && <Button variant="ghost" size="sm" onClick={() => action.mutate("duplicate")}>Duplicate</Button>}
          </>
        }
      />
      {error && <div className="mb-4"><Alert kind="error">{error}</Alert></div>}
      {c.notes && <div className="mb-4"><Alert kind="warning">{c.notes}</Alert></div>}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Recipients" value={num(total || c.estimated_recipients)} />
        <Stat label="Delivered" value={num(s.delivered)} sub={`${s.delivery_rate ?? 0}% of submitted`} />
        <Stat label="Accepted (awaiting DLR)" value={num(s.accepted)} />
        <Stat label="Failed" value={num((s.failed ?? 0) + (s.undelivered ?? 0) + (s.rejected ?? 0))} />
        <Stat label={c.is_demo ? "Demo segments" : "Cost"} value={c.is_demo ? num(c.estimated_segments) : lkr(s.spent ?? c.estimated_cost)} sub={c.is_demo ? undefined : `Estimate ${lkr(c.estimated_cost)}`} />
      </div>

      {["processing", "paused", "completed"].includes(c.status) && (
        <div className="mt-6">
          <div className="mb-1 flex justify-between text-xs text-slate-500"><span>Progress</span><span>{progress}%</span></div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-brand-600 transition-all" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Message">
          <p className="whitespace-pre-wrap text-sm text-slate-800">{c.body}</p>
          <dl className="mt-4 space-y-1 text-xs text-slate-500">
            <div>Type: {c.category}</div>
            <div>Sender: {c.sender ?? "—"}</div>
            <div>Scheduled: {dt(c.scheduled_at)}</div>
            <div>Started: {dt(c.started_at)}</div>
            <div>Completed: {dt(c.completed_at)}</div>
            {Object.entries(c.skipped ?? {}).filter(([, v]) => v > 0).map(([k, v]) => <div key={k}>Skipped {k.replace("_", " ")}: {v}</div>)}
          </dl>
        </Card>
        <Card
          title="Messages"
          className="lg:col-span-2"
          actions={<Button variant="secondary" size="sm" onClick={() => download("/reports/messages/export", `campaign-${c.id}.csv`, { campaign_id: c.id, days: 366 })}>Export CSV</Button>}
        >
          <Table head={["To", "Status", "Segments", "Updated", "Error"]} empty={messages.data?.items.length === 0}>
            {messages.data?.items.map((m) => (
              <tr key={m.message_id}>
                <Td className="font-mono text-xs"><Link href={`/messages?id=${m.message_id}`}>{m.to}</Link></Td>
                <Td><StatusBadge status={m.status} /></Td>
                <Td>{m.segments}</Td>
                <Td>{dt(m.delivered_at ?? m.created_at)}</Td>
                <Td className="text-xs text-red-600">{m.error_code ?? ""}</Td>
              </tr>
            ))}
          </Table>
          <Pager page={page} pageSize={25} total={messages.data?.total ?? 0} onPage={setPage} />
        </Card>
      </div>
    </>
  );
}
