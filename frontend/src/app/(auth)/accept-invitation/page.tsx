"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Field, Input } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AcceptInvitationPage() {
  const token = useSearchParams().get("token") ?? "";
  const { me, acceptToken } = useAuth();
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function accept(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, string> = { token };
      if (!me) {
        if (fullName) body.full_name = fullName;
        body.password = password;
      }
      const r = await api<{ access_token: string }>("/auth/accept-invitation", { method: "POST", body });
      await acceptToken(r.access_token);
      router.replace("/overview");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={accept} className="space-y-4">
      <h1 className="text-xl font-semibold">Join workspace</h1>
      {error && <Alert kind="error">{error}</Alert>}
      {me ? (
        <p className="text-sm text-slate-600">You are signed in as {me.email}. Accept the invitation to join the workspace.</p>
      ) : (
        <>
          <p className="text-sm text-slate-600">
            New to SMSFlow? Enter your name and choose a password. Already have an account? Enter just your existing password.
          </p>
          <Field label="Full name (new accounts)" htmlFor="name">
            <Input id="name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Password" htmlFor="password">
            <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
        </>
      )}
      <Button type="submit" className="w-full" loading={busy} disabled={!token}>Accept invitation</Button>
    </form>
  );
}
