"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Logo } from "@/components/Logo";
import { Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { me, loading, logout } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && (!me || !me.is_platform_admin)) router.replace(me ? "/overview" : "/login?next=/admin");
  }, [loading, me, router]);
  if (loading || !me?.is_platform_admin) {
    return <div className="grid min-h-screen place-items-center"><Spinner className="h-8 w-8" /></div>;
  }
  return (
    <div className="min-h-screen">
      <header className="border-b border-violet-200 bg-violet-50">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <Logo href="/admin" />
          <span className="rounded bg-violet-600 px-2 py-0.5 text-xs font-semibold text-white">SUPER ADMIN</span>
          <div className="ml-auto flex items-center gap-4 text-sm">
            {me.current_tenant_id && <Link href="/overview" className="text-slate-600 hover:underline">My workspace</Link>}
            <span className="text-slate-500">{me.email}</span>
            <button onClick={logout} className="text-slate-600 hover:underline">Log out</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl p-4 md:p-8">{children}</main>
    </div>
  );
}
