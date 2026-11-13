"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/opportunities", label: "Opportunities" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/intake", label: "Add leads" },
  { href: "/follow-ups", label: "Follow-ups" },
  { href: "/searches", label: "Saved searches" },
  { href: "/analytics", label: "Analytics" },
  { href: "/sources", label: "Sources" },
  { href: "/settings", label: "Settings" },
];

export function Nav({ unread, email, role }: { unread: number; email: string; role: string }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <header className="sticky top-0 z-20 border-b line bg-[var(--panel)]/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">S</span>
          <span className="hidden sm:inline">Signal Engine</span>
        </Link>
        <nav className="ml-4 hidden flex-1 items-center gap-1 lg:flex" aria-label="Main">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href}
              className={`rounded-md px-2.5 py-1.5 text-sm ${active(l.href) ? "bg-brand-50 font-medium text-brand-700 dark:bg-brand-500/15 dark:text-brand-100" : "muted hover:text-[var(--text)]"}`}>
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/notifications" className="btn relative px-2.5" aria-label={`Notifications (${unread} unread)`}>
            <span aria-hidden>🔔</span>
            {unread > 0 ? <span className="absolute -right-1 -top-1 rounded-full bg-red-600 px-1.5 text-[10px] font-semibold text-white">{unread}</span> : null}
          </Link>
          <form action="/auth/signout" method="post" className="hidden sm:block">
            <button className="btn" title={`${email} (${role})`}>Sign out</button>
          </form>
          <button className="btn lg:hidden" onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Menu">☰</button>
        </div>
      </div>
      {open ? (
        <nav className="border-t line px-4 py-2 lg:hidden" aria-label="Mobile">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setOpen(false)}
              className={`block rounded-md px-2 py-2 text-sm ${active(l.href) ? "font-semibold text-brand-600" : ""}`}>{l.label}</Link>
          ))}
          <form action="/auth/signout" method="post"><button className="mt-1 px-2 py-2 text-sm muted">Sign out ({email})</button></form>
        </nav>
      ) : null}
    </header>
  );
}
