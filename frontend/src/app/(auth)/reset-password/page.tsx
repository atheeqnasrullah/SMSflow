"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Alert, Button, Field, Input } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

export default function ResetPasswordPage() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await api("/auth/reset-password", { method: "POST", body: { token, password } });
          setDone(true);
        } catch (err) {
          setError(errorMessage(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <h1 className="text-xl font-semibold">Choose a new password</h1>
      {done ? (
        <Alert kind="success">
          Password updated. All other sessions were signed out. <Link href="/login" className="font-medium underline">Log in</Link>
        </Alert>
      ) : (
        <>
          {error && <Alert kind="error">{error}</Alert>}
          <Field label="New password" htmlFor="password" hint="At least 10 characters, mixing letters with numbers or symbols.">
            <Input id="password" type="password" minLength={10} required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <Button type="submit" className="w-full" loading={busy} disabled={!token}>Update password</Button>
        </>
      )}
    </form>
  );
}
