"use client";

import { BarChart3, Code2, CreditCard, FileText, LayoutDashboard, LogOut, Megaphone, Menu, MessageSquare, Settings, Shield, Users, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Logo } from "@/components/Logo";
import { Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/format";

const NAV = [
  { href: "/overview", key: "overview", icon: LayoutDashboard },
  { href: "/contacts", key: "contacts", icon: Users },
  { href: "/campaigns", key: "campaigns", icon: Megaphone },
  { href: "/messages", key: "messages", icon: MessageSquare },
  { href: "/templates", key: "templates", icon: FileText },
  { href: "/reports", key: "reports", icon: BarChart3 },
  { href: "/billing", key: "billing", icon: CreditCard },
  { href: "/developers", key: "developers", icon: Code2 },
  { href: "/settings", key: "settings", icon: Settings },
] as const;

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { me, loading, logout, switchTenant } = useAuth();
  const t = useTranslations("nav");
  const c = useTranslations("common");
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [liveRequested, setLiveRequested] = useState(false);

  useEffect(() => {
    if (!loading && !me) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, me, router, pathname]);
  useEffect(() => setOpen(false), [pathname]);

  if (loading || !me) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }
  const workspace = me.workspaces.find((w) => w.id === me.current_tenant_id);
  if (!workspace) {
    return (
      <div className="grid min-h-screen place-items-center p-6 text-center">
        <div className="space-y-3">
          <p className="text-slate-700">You are not a member of any workspace yet.</p>
          {me.is_platform_admin && <Link className="text-brand-700 underline" href="/admin">Open admin console</Link>}
          <button className="block w-full text-sm text-slate-500 underline" onClick={logout}>Log out</button>
        </div>
      </div>
    );
  }

  const sidebar = (
    <nav className="flex h-full flex-col gap-1 p-4" aria-label="Main">
      <div className="mb-4 px-2"><Logo href="/overview" /></div>
      {NAV.map(({ href, key, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
              active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
            )}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {t(key)}
          </Link>
        );
      })}
      {me.is_platform_admin && (
        <Link href="/admin" className="mt-2 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-violet-700 hover:bg-violet-50">
          <Shield className="h-4 w-4" aria-hidden /> {t("admin")}
        </Link>
      )}
      <div className="mt-auto space-y-3 border-t border-slate-100 pt-4">
        <div className="px-3 text-xs text-slate-500">
          <p className="truncate font-medium text-slate-700">{me.full_name}</p>
          <p className="truncate">{me.email}</p>
        </div>
        <button onClick={logout} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">
          <LogOut className="h-4 w-4" aria-hidden /> {t("logout")}
        </button>
      </div>
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 border-r border-slate-200 bg-white lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
          <aside className="relative h-full w-64 bg-white shadow-xl">
            <button className="absolute right-3 top-3 p-1" onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-5 w-5" /></button>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
          <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
          <select
            aria-label="Workspace"
            className="max-w-[16rem] truncate rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
            value={workspace.id}
            onChange={(e) => switchTenant(e.target.value)}
          >
            {me.workspaces.map((w) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </select>
          {workspace.mode === "demo" ? (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">{c("demoMode")}</span>
          ) : (
            <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800">LIVE</span>
          )}
          <span className="hidden text-xs text-slate-500 sm:inline">Role: {me.role}</span>
          <div className="ml-auto"><LocaleSwitcher /></div>
        </header>
        {workspace.mode === "demo" && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900" role="status">
            <span>{c("demoBanner")}</span>
            {me.permissions.includes("workspace:update") && (
              <button
                disabled={liveRequested}
                className="rounded-md border border-amber-300 bg-white px-2.5 py-1 text-xs font-medium hover:bg-amber-100 disabled:opacity-60"
                onClick={async () => {
                  try {
                    await api("/workspace/request-live", { method: "POST" });
                  } finally {
                    setLiveRequested(true);
                  }
                }}
              >
                {liveRequested ? "Request sent" : c("requestLive")}
              </button>
            )}
          </div>
        )}
        {!me.email_verified && (
          <div className="border-b border-brand-100 bg-brand-50 px-4 py-2 text-sm text-brand-800">
            Please verify your email address.{" "}
            <button className="font-medium underline" onClick={() => api("/auth/resend-verification", { method: "POST" })}>Resend link</button>
          </div>
        )}
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
