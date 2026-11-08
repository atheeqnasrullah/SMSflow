"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert, Button, Field, Input } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const schema = z.object({ email: z.string().email(), password: z.string().min(1, "Required") });
type Form = z.infer<typeof schema>;

export default function LoginPage() {
  const t = useTranslations("auth");
  const nav = useTranslations("nav");
  const { login } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (data) => {
    setError(null);
    try {
      const me = await login(data.email, data.password);
      const next = params.get("next");
      router.replace(next && next.startsWith("/") ? next : me.current_tenant_id ? "/overview" : me.is_platform_admin ? "/admin" : "/overview");
    } catch (e) {
      setError(errorMessage(e));
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-5" noValidate>
      <h1 className="text-xl font-semibold text-slate-900">{t("loginTitle")}</h1>
      {error && <Alert kind="error">{error}</Alert>}
      <Field label={t("email")} htmlFor="email" error={formState.errors.email?.message}>
        <Input id="email" type="email" autoComplete="email" {...register("email")} />
      </Field>
      <Field label={t("password")} htmlFor="password" error={formState.errors.password?.message}>
        <Input id="password" type="password" autoComplete="current-password" {...register("password")} />
      </Field>
      <div className="flex justify-end text-sm">
        <Link href="/forgot-password" className="text-brand-700 hover:underline">{t("forgot")}</Link>
      </div>
      <Button type="submit" className="w-full" loading={formState.isSubmitting}>{nav("login")}</Button>
      <p className="text-center text-sm text-slate-500">
        {t("noAccount")} <Link href="/register" className="font-medium text-brand-700 hover:underline">{nav("register")}</Link>
      </p>
    </form>
  );
}
