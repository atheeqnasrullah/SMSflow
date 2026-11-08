import type { Metadata } from "next";
import { Noto_Sans_Sinhala, Noto_Sans_Tamil, Inter } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import "./globals.css";
import { Providers } from "./providers";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const sinhala = Noto_Sans_Sinhala({ subsets: ["sinhala"], variable: "--font-sinhala", display: "swap" });
const tamil = Noto_Sans_Tamil({ subsets: ["tamil"], variable: "--font-tamil", display: "swap" });

export const metadata: Metadata = {
  title: { default: "SMSFlow – Bulk SMS & OTP for Sri Lanka", template: "%s · SMSFlow" },
  description:
    "Bulk SMS, OTP and transactional notifications for Sri Lankan businesses. English, Sinhala and Tamil, scheduling, developer API.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();
  return (
    <html lang={locale} className={`${inter.variable} ${sinhala.variable} ${tamil.variable}`}>
      <body className="min-h-screen font-sans">
        <NextIntlClientProvider locale={locale} messages={messages} timeZone="Asia/Colombo">
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
