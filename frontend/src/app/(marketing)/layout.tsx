import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Logo } from "@/components/Logo";

export default async function MarketingLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations("nav");
  const b = await getTranslations("brand");
  return (
    <div className="flex min-h-screen flex-col bg-white">
      <header className="sticky top-0 z-30 border-b border-slate-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <Logo />
          <nav className="hidden items-center gap-6 text-sm text-slate-600 md:flex">
            <Link href="/features" className="hover:text-slate-900">{t("features")}</Link>
            <Link href="/pricing" className="hover:text-slate-900">{t("pricing")}</Link>
            <Link href="/docs" className="hover:text-slate-900">{t("docs")}</Link>
            <Link href="/contact" className="hover:text-slate-900">{t("contact")}</Link>
          </nav>
          <div className="flex items-center gap-3">
            <LocaleSwitcher />
            <Link href="/login" className="text-sm font-medium text-slate-700 hover:text-slate-900">{t("login")}</Link>
            <Link href="/register" className="rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-700">
              {t("register")}
            </Link>
          </div>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-slate-100 bg-slate-50">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-sm text-slate-500 md:flex-row md:items-center md:justify-between">
          <div>
            <Logo />
            <p className="mt-2">{b("tagline")}</p>
          </div>
          <div className="flex flex-wrap gap-4">
            <Link href="/pricing">{t("pricing")}</Link>
            <Link href="/docs">{t("docs")}</Link>
            <Link href="/contact">{t("contact")}</Link>
            <span>© {new Date().getFullYear()} SMSFlow · Colombo, Sri Lanka</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
