"use client";

import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// Colour-blind friendly pair (blue / orange) with sufficient contrast.
export function DeliveryChart({ data }: { data: { date: string; total: number; delivered: number; failed: number }[] }) {
  if (!data.length) return <p className="py-10 text-center text-sm text-slate-500">No messages in this period.</p>;
  return (
    <div className="h-72 w-full" role="img" aria-label="Messages per day: total, delivered and failed">
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ left: -10, right: 10, top: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#94a3b8" />
          <YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="#94a3b8" />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area type="monotone" dataKey="total" name="Total" stroke="#64748b" fill="#f1f5f9" />
          <Area type="monotone" dataKey="delivered" name="Delivered" stroke="#1d5ef1" fill="#bcdaff" />
          <Area type="monotone" dataKey="failed" name="Failed" stroke="#c2410c" fill="#fed7aa" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
