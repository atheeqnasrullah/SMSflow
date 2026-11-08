"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert, Button, Field, Input, Select } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const schema = z.object({
  full_name: z.string().min(2, "Enter your name"),
  business_name: z.string().min(2, "Enter your business name"),
  business_type: z.string().optional(),
  email: z.string().email("Enter a valid email"),
  phone: z.string().optional(),
  password: z
    .string()
    .min(10, "At least 10 characters")
    .refine((v) => /[A-Za-z]/.test(v) && /[^A-Za-z]/.test(v), "Mix letters with numbers or symbols"),
});
type Form = z.infer<typeof schema>;

const TYPES = ["Retail / shop", "E-commerce", "Clinic / healthcare", "School / education", "Salon / beauty", "Restaurant", "Services", "Other"];

export default function RegisterPage() {
  const t = useTranslations("auth");
  const nav = useTranslations("nav");
  const locale = useLocale();
  const { register: signUp } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (data) => {
    setError(null);
    try {
      await signUp({ ...data, locale });
      router.replace("/overview");
    } catch (e) {
      setError(errorMessage(e));
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <h1 className="text-xl font-semibold text-slate-900">{t("registerTitle")}</h1>
      <p className="text-sm text-slate-500">You start in demo mode with 500 free demo SMS. No real messages are sent until you go live.</p>
      {error && <Alert kind="error">{error}</Alert>}
      <Field label={t("fullName")} htmlFor="full_name" error={formState.errors.full_name?.message}>
        <Input id="full_name" autoComplete="name" {...register("full_name")} />
      </Field>
      <Field label={t("businessName")} htmlFor="business_name" error={formState.errors.business_name?.message}>
        <Input id="business_name" autoComplete="organization" {...register("business_name")} />
      </Field>
      <Field label={t("businessType")} htmlFor="business_type">
        <Select id="business_type" {...register("business_type")}>
          {TYPES.map((x) => <option key={x}>{x}</option>)}
        </Select>
      </Field>
      <Field label={t("email")} htmlFor="email" error={formState.errors.email?.message}>
        <Input id="email" type="email" autoComplete="email" {...register("email")} />
      </Field>
      <Field label="Mobile (optional)" htmlFor="phone">
        <Input id="phone" type="tel" placeholder="077 123 4567" {...register("phone")} />
      </Field>
      <Field label={t("password")} htmlFor="password" error={formState.errors.password?.message}>
        <Input id="password" type="password" autoComplete="new-password" {...register("password")} />
      </Field>
      <Button type="submit" className="w-full" loading={formState.isSubmitting}>{nav("register")}</Button>
      <p className="text-center text-sm text-slate-500">
        {t("haveAccount")} <Link href="/login" className="font-medium text-brand-700 hover:underline">{nav("login")}</Link>
      </p>
    </form>
  );
}
