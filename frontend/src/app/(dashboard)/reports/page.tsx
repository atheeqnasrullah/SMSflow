"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { DeliveryChart } from "@/components/charts";
import { Button, Card, DemoBadge, PageHeader, Select, Stat, StatusBadge, Table, Td } from "@/components/ui";
import { api, download } from "@/lib/api";
import { dt, lkr, num } from "@/lib/format";
import type { Overview } from "@/types/api";

interface CampaignRow {
  id: string;
  name: string;
  status: string;
  is_demo: boolean;
  started_at: string | null;
  recipients: number;
  delivered: number;
  failed: number;
  delivery_rate: number;
  spent: number;
}

export default function ReportsPage() {
  const [days, setDays] = useState(30);
  const [includeDemo, setIncludeDemo] = useState(true);
  const overview = useQuery({
    queryKey: ["overview", days, includeDemo],
    queryFn: () => api<Overview>("/reports/overview", { query: { days, include_demo: includeDemo } }),
  });
  const campaigns = useQuery({ queryKey: ["report-campaigns"], queryFn: () => api<CampaignRow[]>("/reports/campaigns") });
  const o = overview.data;
  return (
    <>
      <PageHeader
        title="Reports"
        description="Accepted means the provider took the message; delivered is confirmed by a delivery report."
        actions={
          <>
            <Select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
              <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={365}>Last 12 months</option>
            </Select>
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input type="checkbox" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} /> Include demo
            </label>
            <Button variant="secondary" onClick={() => download("/reports/messages/export", "messages.csv", { days })}>Export CSV</Button>
          </>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Messages" value={num(o?.total_messages)} sub={`${num(o?.total_segments)} segments`} />
        <Stat label="Delivered" value={num(o?.delivered)} sub={`of ${num(o?.submitted)} submitted`} />
        <Stat label="Delivery rate" value={`${o?.delivery_rate ?? 0}%`} />
        <Stat label="Spend" value={lkr(o?.spend)} />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Daily volume" className="lg:col-span-2"><DeliveryChart data={o?.daily ?? []} /></Card>
        <Card title="By status & source">
          <ul className="space-y-2 text-sm">
            {Object.entries(o?.by_status ?? {}).map(([k, v]) => (
              <li key={k} className="flex justify-between"><StatusBadge status={k} /><span>{num(v)}</span></li>
            ))}
          </ul>
          <hr className="my-4 border-slate-100" />
          <ul className="space-y-2 text-sm">
            {Object.entries(o?.by_source ?? {}).map(([k, v]) => (
              <li key={k} className="flex justify-between"><span className="capitalize text-slate-600">{k}</span><span>{num(v)}</span></li>
            ))}
          </ul>
        </Card>
      </div>
      <Card title="Campaign comparison" className="mt-6">
        <Table head={["Campaign", "Status", "Started", "Recipients", "Delivered", "Failed", "Rate", "Spent"]} empty={campaigns.data?.length === 0}>
          {campaigns.data?.map((c) => (
            <tr key={c.id}>
              <Td><Link className="font-medium text-brand-700 hover:underline" href={`/campaigns/${c.id}`}>{c.name}</Link> {c.is_demo && <DemoBadge />}</Td>
              <Td><StatusBadge status={c.status} /></Td>
              <Td>{dt(c.started_at)}</Td>
              <Td>{num(c.recipients)}</Td>
              <Td>{num(c.delivered)}</Td>
              <Td>{num(c.failed)}</Td>
              <Td>
                <div className="flex items-center gap-2">
                  <div className="h-1.5 w-16 overflow-hidden rounded bg-slate-100"><div className="h-full bg-brand-600" style={{ width: `${c.delivery_rate}%` }} /></div>
                  {c.delivery_rate}%
                </div>
              </Td>
              <Td>{c.is_demo ? "—" : lkr(c.spent)}</Td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
