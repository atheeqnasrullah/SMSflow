"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert, Button, Field, Input } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
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
          await api("/auth/forgot-password", { method: "POST", body: { email } });
          setSent(true);
        } catch (err) {
          setError(errorMessage(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <h1 className="text-xl font-semibold">Reset your password</h1>
      {sent ? (
        <Alert kind="success">If an account exists for {email}, a reset link is on its way. It is valid for one hour.</Alert>
      ) : (
        <>
          {error && <Alert kind="error">{error}</Alert>}
          <Field label="Email" htmlFor="email">
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Button type="submit" className="w-full" loading={busy}>Send reset link</Button>
        </>
      )}
      <p className="text-center text-sm"><Link href="/login" className="text-brand-700 hover:underline">Back to login</Link></p>
    </form>
  );
}
