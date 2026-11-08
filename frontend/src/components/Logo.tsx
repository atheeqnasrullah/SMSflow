import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 font-semibold text-slate-900">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-white" aria-hidden>
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 5h16v10H8l-4 4V5z" strokeLinejoin="round" />
          <path d="M8 9h8M8 12h5" strokeLinecap="round" />
        </svg>
      </span>
      <span>
        SMS<span className="text-brand-600">Flow</span>
      </span>
    </Link>
  );
}
