"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Card, DemoBadge, PageHeader, Pager, Select, StatusBadge, Table, Td } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dt, lkr, num } from "@/lib/format";
import type { Campaign, Page } from "@/types/api";

export default function CampaignsPage() {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const list = useQuery({
    queryKey: ["campaigns", page, status],
    queryFn: () => api<Page<Campaign>>("/campaigns", { query: { page, status } }),
    refetchInterval: (q) => (q.state.data?.items.some((c) => c.status === "processing") ? 4000 : false),
  });
  return (
    <>
      <PageHeader
        title="Campaigns"
        description="Bulk sends to groups, contacts or uploaded lists – now, scheduled or recurring."
        actions={can("campaigns:write") && <Link href="/campaigns/new" className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">New campaign</Link>}
      />
      <Card>
        <div className="mb-4 max-w-[12rem]">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Filter by status">
            <option value="">All statuses</option>
            {["draft", "scheduled", "processing", "paused", "completed", "cancelled"].map((s) => <option key={s}>{s}</option>)}
          </Select>
        </div>
        <Table head={["Name", "Status", "Scheduled", "Recipients", "Delivered", "Rate", "Cost"]} empty={list.data?.items.length === 0}>
          {list.data?.items.map((c) => (
            <tr key={c.id}>
              <Td>
                <Link href={`/campaigns/${c.id}`} className="font-medium text-brand-700 hover:underline">{c.name}</Link>{" "}
                {c.is_demo && <DemoBadge />}
                {c.recurrence && <span className="ml-1 text-xs text-slate-400">↻</span>}
              </Td>
              <Td><StatusBadge status={c.status} /></Td>
              <Td>{dt(c.scheduled_at)}</Td>
              <Td>{num(c.stats.total ?? c.estimated_recipients)}</Td>
              <Td>{num(c.stats.delivered)}</Td>
              <Td>{c.stats.delivery_rate != null ? `${c.stats.delivery_rate}%` : "—"}</Td>
              <Td>{c.is_demo ? "—" : lkr(c.stats.spent ?? c.estimated_cost)}</Td>
            </tr>
          ))}
        </Table>
        <Pager page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
      </Card>
    </>
  );
}
