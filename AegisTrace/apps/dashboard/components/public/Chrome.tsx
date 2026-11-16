"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Shared frame for the public pages: top bar (sign-in at the top right), footer, reveal-on-scroll.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Logo } from "@/components/Logo";
import "./public.css";

const LINKS = [["/welcome#pillars", "Pillars"], ["/platform", "Studio"], ["/roadmap", "Roadmap"], ["/integrations", "Integrations"]] as const;

/** Fades sections in as they arrive. Content stays visible without JavaScript or with reduced motion. */
export function useReveal() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const els = [...document.querySelectorAll<HTMLElement>("[data-reveal]")];
    els.forEach((el) => el.classList.add("w-pre"));
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.remove("w-pre"); io.unobserve(e.target); } }),
      { rootMargin: "0px 0px -8% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
}

export function PublicPage({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [scrolled, setScrolled] = useState(false);
  useReveal();
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <div className="w-root">
      <header className="w-nav" data-scrolled={scrolled}>
        <div className="w-nav-inner">
          <Logo />
          <nav className="w-nav-links" aria-label="Pages">
            {LINKS.map(([href, label]) => (
              <Link key={href} href={href} aria-current={path === href.split("#")[0] && !href.includes("#") ? "page" : undefined}>{label}</Link>
            ))}
          </nav>
          <Link href="/login" className="w-signin">Sign in</Link>
        </div>
      </header>
      <main>{children}</main>
      <footer className="w-foot">
        <div className="w-foot-inner">
          <Logo size={15} />
          <span>Trust infrastructure for AI agents</span>
          <a href="https://github.com/Ajay-quan/Aegis">GitHub</a>
        </div>
      </footer>
    </div>
  );
}

/** Opening of a secondary page: eyebrow, one headline, one sentence. */
export function PageIntro({ eyebrow, title, lede }: { eyebrow: string; title: ReactNode; lede: string }) {
  return (
    <section className="w-page-intro">
      <p className="w-eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="w-lede">{lede}</p>
    </section>
  );
}

export function CloseCta({ title, sub }: { title: string; sub: string }) {
  return (
    <section className="w-close" data-reveal>
      <h2>{title}<br /><span>{sub}</span></h2>
      <Link href="/login" className="w-btn w-btn-primary">Sign in</Link>
    </section>
  );
}
