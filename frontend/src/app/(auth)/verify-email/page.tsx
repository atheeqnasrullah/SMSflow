"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Alert, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

export default function VerifyEmailPage() {
  const token = useSearchParams().get("token");
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [error, setError] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (!token) {
      setState("error");
      setError("Missing verification token.");
      return;
    }
    api("/auth/verify-email", { method: "POST", body: { token } })
      .then(() => setState("ok"))
      .catch((e) => {
        setState("error");
        setError(errorMessage(e));
      });
  }, [token]);

  return (
    <div className="space-y-4 text-center">
      <h1 className="text-xl font-semibold">Email verification</h1>
      {state === "working" && <Spinner className="mx-auto" />}
      {state === "ok" && <Alert kind="success">Your email is verified. You can continue to your dashboard.</Alert>}
      {state === "error" && <Alert kind="error">{error}</Alert>}
      <Link href="/overview" className="inline-block text-sm font-medium text-brand-700 hover:underline">Go to dashboard</Link>
    </div>
  );
}
