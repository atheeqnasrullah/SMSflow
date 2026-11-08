"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { DeliveryChart } from "@/components/charts";
import { Card, PageHeader, Stat, StatusBadge, Table, Td } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dt, lkr, num } from "@/lib/format";
import type { Campaign, Overview, Page, Wallet } from "@/types/api";

export default function OverviewPage() {
  const { me } = useAuth();
  const overview = useQuery({ queryKey: ["overview", 30], queryFn: () => api<Overview>("/reports/overview", { query: { days: 30 } }) });
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: () => api<Wallet>("/billing/wallet") });
  const campaigns = useQuery({
    queryKey: ["campaigns", "recent"],
    queryFn: () => api<Page<Campaign>>("/campaigns", { query: { page_size: 5 } }),
  });
  const o = overview.data;
  const w = wallet.data;

  return (
    <>
      <PageHeader
        title={`Welcome, ${me?.full_name.split(" ")[0] ?? ""}`}
        description="Last 30 days at a glance"
        actions={
          <>
            <Link href="/messages" className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Quick send</Link>
            <Link href="/campaigns/new" className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">New campaign</Link>
          </>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Messages sent" value={num(o?.total_messages)} sub={`${num(o?.total_segments)} segments`} />
        <Stat label="Delivery rate" value={`${o?.delivery_rate ?? 0}%`} sub={`${num(o?.delivered)} of ${num(o?.submitted)} submitted`} />
        {w?.mode === "demo" ? (
          <Stat label="Demo credits" value={num(w?.demo_credits)} sub="Segments left in demo mode" />
        ) : (
          <Stat label="Available balance" value={lkr(w?.available)} sub={`${lkr(w?.reserved)} reserved`} />
        )}
        <Stat label="Contacts" value={num(o?.contacts)} sub={`${o?.active_campaigns ?? 0} active campaigns`} />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Delivery trend" className="lg:col-span-2">
          <DeliveryChart data={o?.daily ?? []} />
        </Card>
        <Card title="Status breakdown">
          <ul className="space-y-2 text-sm">
            {Object.entries(o?.by_status ?? {}).map(([k, v]) => (
              <li key={k} className="flex items-center justify-between">
                <StatusBadge status={k} />
                <span className="font-medium text-slate-700">{num(v)}</span>
              </li>
            ))}
            {!o || Object.keys(o.by_status).length === 0 ? <li className="text-slate-500">No messages yet.</li> : null}
          </ul>
        </Card>
      </div>
      <Card title="Recent campaigns" className="mt-6" actions={<Link href="/campaigns" className="text-sm text-brand-700 hover:underline">View all</Link>}>
        <Table head={["Name", "Status", "Recipients", "Delivered", "Created"]} empty={campaigns.data?.items.length === 0}>
          {campaigns.data?.items.map((c) => (
            <tr key={c.id}>
              <Td><Link href={`/campaigns/${c.id}`} className="font-medium text-brand-700 hover:underline">{c.name}</Link></Td>
              <Td><StatusBadge status={c.status} /></Td>
              <Td>{num(c.stats.total ?? c.estimated_recipients)}</Td>
              <Td>{num(c.stats.delivered)}</Td>
              <Td>{dt(c.created_at)}</Td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
