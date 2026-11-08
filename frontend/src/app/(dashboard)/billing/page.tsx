"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Alert, Badge, Button, Card, Field, Input, PageHeader, Pager, Stat, StatusBadge, Table, Tabs, Td } from "@/components/ui";
import { api, errorMessage, openHtml } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dt, lkr, num } from "@/lib/format";
import type { LedgerEntry, Package, Page, Payment, Wallet } from "@/types/api";

interface CheckoutResponse {
  order_id: string;
  checkout: Record<string, string | boolean> & { action: string; configured: boolean; simulation_available: boolean };
}

export default function BillingPage() {
  return (
    <Suspense>
      <BillingInner />
    </Suspense>
  );
}

function BillingInner() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const params = useSearchParams();
  const returnedOrder = params.get("order_id");
  const [tab, setTab] = useState<"ledger" | "payments">("ledger");
  const [message, setMessage] = useState<{ kind: "success" | "error" | "info"; text: string } | null>(null);
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: () => api<Wallet>("/billing/wallet") });
  const packages = useQuery({ queryKey: ["packages"], queryFn: () => api<Package[]>("/billing/packages") });
  const returned = useQuery({
    queryKey: ["payment", returnedOrder],
    enabled: !!returnedOrder,
    queryFn: () => api<Payment>(`/billing/payments/${returnedOrder}`),
    refetchInterval: (q) => (q.state.data?.status === "pending" ? 3000 : false),
  });

  const buy = useMutation({
    mutationFn: (pkg: Package) => api<CheckoutResponse>("/billing/checkout", { method: "POST", body: { package_id: pkg.id } }),
    onSuccess: async (res) => {
      const c = res.checkout;
      if (c.configured) {
        // Redirect to PayHere with a server-generated hash. The wallet is credited only by the
        // verified server-to-server notification, never by this redirect.
        const form = document.createElement("form");
        form.method = "POST";
        form.action = String(c.action);
        for (const [k, v] of Object.entries(c)) {
          if (["action", "configured", "simulation_available"].includes(k)) continue;
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = k;
          input.value = String(v);
          form.appendChild(input);
        }
        document.body.appendChild(form);
        form.submit();
        return;
      }
      if (c.simulation_available && confirm("PayHere is not configured in this environment. Simulate a successful payment?")) {
        await api(`/billing/payments/${res.order_id}/simulate`, { method: "POST" });
        setMessage({ kind: "success", text: `Payment ${res.order_id} simulated – credits added.` });
        qc.invalidateQueries();
      } else {
        setMessage({ kind: "info", text: `Order ${res.order_id} created but no payment gateway is configured.` });
      }
    },
    onError: (e) => setMessage({ kind: "error", text: errorMessage(e) }),
  });

  const w = wallet.data;
  return (
    <>
      <PageHeader title="Billing" description="Prepaid wallet in LKR. You pay per SMS segment; funds are reserved when a send starts and only charged when the provider accepts the message." />
      {returned.data && (
        <div className="mb-4">
          <Alert kind={returned.data.status === "completed" ? "success" : returned.data.status === "pending" ? "info" : "error"}>
            Payment {returned.data.order_id}: {returned.data.status === "pending" ? "waiting for confirmation from PayHere…" : returned.data.status}
          </Alert>
        </div>
      )}
      {message && <div className="mb-4"><Alert kind={message.kind}>{message.text}</Alert></div>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Balance" value={lkr(w?.balance)} />
        <Stat label="Reserved" value={lkr(w?.reserved)} sub="Held for queued/scheduled sends" />
        <Stat label="Available" value={lkr(w?.available)} />
        <Stat label="Price per segment" value={lkr(w?.price_per_segment)} sub={w?.mode === "demo" ? `${num(w?.demo_credits)} demo credits left` : "Promotional rate"} />
      </div>
      <h2 className="mb-3 mt-8 text-sm font-semibold text-slate-800">Buy credits</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {packages.data?.map((p) => (
          <div key={p.id} className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="font-semibold text-slate-900">{p.name}</p>
            <p className="text-xs text-slate-500">{p.description}</p>
            <p className="mt-3 text-2xl font-bold">{lkr(p.price_lkr, 0)}</p>
            <p className="text-sm text-slate-600">
              {lkr(p.credits, 0)} credit {p.bonus_credits > 0 && <Badge color="green">+{lkr(p.bonus_credits, 0)} bonus</Badge>}
            </p>
            <p className="mt-1 text-xs text-slate-500">≈ {num(Math.floor((p.credits + p.bonus_credits) / (w?.price_per_segment || 0.85)))} SMS</p>
            {can("billing:manage") && (
              <Button className="mt-4" loading={buy.isPending && buy.variables?.id === p.id} onClick={() => buy.mutate(p)}>Buy with PayHere</Button>
            )}
          </div>
        ))}
      </div>
      {can("billing:manage") && w && <ThresholdCard wallet={w} />}
      <div className="mt-8">
        <Tabs tabs={[{ id: "ledger", label: "Transactions" }, { id: "payments", label: "Payments & invoices" }]} value={tab} onChange={setTab} />
        <div className="mt-4">{tab === "ledger" ? <Ledger /> : <Payments />}</div>
      </div>
    </>
  );
}

function ThresholdCard({ wallet }: { wallet: Wallet }) {
  const qc = useQueryClient();
  const [value, setValue] = useState(String(wallet.low_balance_threshold));
  const save = useMutation({
    mutationFn: () => api("/billing/wallet", { method: "PATCH", body: { low_balance_threshold: value } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wallet"] }),
  });
  return (
    <Card title="Low balance alert" className="mt-6">
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <Field label="Email owners and admins when available balance drops below (LKR)" htmlFor="thr">
          <Input id="thr" type="number" min={0} step="1" value={value} onChange={(e) => setValue(e.target.value)} className="max-w-[10rem]" />
        </Field>
        <Button type="submit" variant="secondary" loading={save.isPending}>Save</Button>
      </form>
    </Card>
  );
}

function Ledger() {
  const [page, setPage] = useState(1);
  const list = useQuery({ queryKey: ["ledger", page], queryFn: () => api<Page<LedgerEntry>>("/billing/ledger", { query: { page } }) });
  return (
    <Card>
      <Table head={["Date", "Type", "Amount", "Reserved Δ", "Balance after", "Reference"]} empty={list.data?.items.length === 0}>
        {list.data?.items.map((e) => (
          <tr key={e.id}>
            <Td>{dt(e.created_at)}</Td>
            <Td><Badge color={e.amount > 0 ? "green" : e.type === "charge" ? "red" : "gray"}>{e.type}</Badge></Td>
            <Td className={e.amount < 0 ? "text-red-600" : e.amount > 0 ? "text-emerald-700" : ""}>{e.amount ? lkr(e.amount, 4) : "—"}</Td>
            <Td>{e.reserved_delta ? lkr(e.reserved_delta, 4) : "—"}</Td>
            <Td>{lkr(e.balance_after)}</Td>
            <Td className="text-xs text-slate-500">{e.description ?? e.reference_type}</Td>
          </tr>
        ))}
      </Table>
      <Pager page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
    </Card>
  );
}

function Payments() {
  const [page, setPage] = useState(1);
  const list = useQuery({ queryKey: ["payments", page], queryFn: () => api<Page<Payment>>("/billing/payments", { query: { page } }) });
  return (
    <Card>
      <Table head={["Date", "Order", "Amount", "Credits", "Status", "Invoice"]} empty={list.data?.items.length === 0}>
        {list.data?.items.map((p) => (
          <tr key={p.id}>
            <Td>{dt(p.created_at)}</Td>
            <Td className="font-mono text-xs">{p.order_id}</Td>
            <Td>{lkr(p.amount)}</Td>
            <Td>{lkr(p.credits + p.bonus_credits)}</Td>
            <Td><StatusBadge status={p.status} /></Td>
            <Td>{p.invoice_id ? <button className="text-brand-700 hover:underline" onClick={() => openHtml(`/billing/invoices/${p.invoice_id}`)}>{p.invoice_number}</button> : "—"}</Td>
          </tr>
        ))}
      </Table>
      <Pager page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
    </Card>
  );
}
