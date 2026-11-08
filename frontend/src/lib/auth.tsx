"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, refreshSession, setAccessToken, setSessionExpiredHandler } from "@/lib/api";
import type { Me } from "@/types/api";

interface AuthState {
  me: Me | null;
  loading: boolean;
  can: (permission: string) => boolean;
  login: (email: string, password: string) => Promise<Me>;
  register: (data: Record<string, unknown>) => Promise<Me>;
  logout: () => Promise<void>;
  switchTenant: (tenantId: string) => Promise<void>;
  reload: () => Promise<Me | null>;
  acceptToken: (token: string) => Promise<Me>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const qc = useQueryClient();

  const reload = useCallback(async () => {
    try {
      const data = await api<Me>("/auth/me");
      setMe(data);
      return data;
    } catch {
      setMe(null);
      return null;
    }
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setMe(null);
      router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    });
    (async () => {
      if (await refreshSession()) await reload();
      setLoading(false);
    })();
  }, [reload, router]);

  const acceptToken = useCallback(
    async (token: string) => {
      setAccessToken(token);
      qc.clear();
      const data = await reload();
      if (!data) throw new Error("Could not load your profile");
      return data;
    },
    [qc, reload],
  );

  const value = useMemo<AuthState>(
    () => ({
      me,
      loading,
      can: (p) => !!me?.permissions.includes(p),
      reload,
      acceptToken,
      login: async (email, password) => {
        const r = await api<{ access_token: string }>("/auth/login", { method: "POST", body: { email, password } });
        return acceptToken(r.access_token);
      },
      register: async (data) => {
        const r = await api<{ access_token: string }>("/auth/register", { method: "POST", body: data });
        return acceptToken(r.access_token);
      },
      logout: async () => {
        try {
          await api("/auth/logout", { method: "POST" });
        } finally {
          setAccessToken(null);
          setMe(null);
          qc.clear();
          router.replace("/login");
        }
      },
      switchTenant: async (tenantId) => {
        const r = await api<{ access_token: string }>("/auth/switch-tenant", { method: "POST", body: { tenant_id: tenantId } });
        await acceptToken(r.access_token);
        router.push("/overview");
      },
    }),
    [me, loading, reload, acceptToken, qc, router],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
