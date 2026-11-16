"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Public introduction to Aegis, shown before sign-in. Kept short: what it is, the pillars, the proof.
import Link from "next/link";
import { useEffect, useState } from "react";
import { Logo, ProductName } from "@/components/Logo";
import "./welcome.css";

type Status = "Available" | "In progress" | "Planned";

// One line per pillar; the status reflects what runs in the code today.
const PILLARS: [string, string, Status][] = [
  ["Mem", "Memory that lasts, and stays correct.", "Available"],
  ["Trace", "Every step an agent takes, on the record.", "Available"],
  ["Guard", "Nothing runs until you allow it.", "Available"],
  ["Runtime", "Runs that finish, even when things fail.", "Available"],
  ["Models", "Any model, hosted or local.", "Available"],
  ["Studio", "One place to build, watch and govern.", "In progress"],
  ["Eval", "Know an agent is better before it ships.", "In progress"],
  ["Optimize", "The same answer, for fewer tokens.", "Planned"],
];

const FLOWS = [
  { agent: "billing-agent", act: "memory.recall", about: "acme", verdict: "Allowed", detail: "within grant", tone: "ok" },
  { agent: "ops-agent", act: "data.export", about: "customers", verdict: "Waiting for you", detail: "consequential write", tone: "wait" },
  { agent: "research-agent", act: "email.send", about: "external address", verdict: "Blocked", detail: "no permission", tone: "no" },
] as const;
const STEPS = ["Requested", "Checked against your rules", "Decided", "Signed into the record"];

const PROOF = [
  ["7,334", "of 7,334 runs verified", "with workers killed and services restarted under load"],
  ["0", "actions without a decision", "nothing ran without an explicit allow"],
  ["~7 ms", "per policy check", "95th percentile, on a single laptop"],
] as const;

const SECTIONS = [["harness", "Harness"], ["pillars", "Pillars"], ["proof", "Proof"]] as const;

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const m = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(m.matches);
    const on = () => setReduced(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return reduced;
}

function LiveAction() {
  const reduced = useReducedMotion();
  const [flow, setFlow] = useState(0);
  const [step, setStep] = useState(STEPS.length);
  useEffect(() => {
    if (reduced) { setStep(STEPS.length); return; }
    setStep(0);
    const t = setInterval(() => {
      setStep((s) => {
        if (s < STEPS.length + 3) return s + 1;
        setFlow((f) => (f + 1) % FLOWS.length);
        return 0;
      });
    }, 650);
    return () => clearInterval(t);
  }, [reduced]);
  const f = FLOWS[flow];
  return (
    <figure className="w-live" aria-label="An agent action passing through the harness">
      <div className="w-live-head"><span className="w-mono">{f.agent}</span><span className="w-live-state">Live</span></div>
      <p className="w-live-act"><span className="w-mono">{f.act}</span><span className="w-live-about"> · {f.about}</span></p>
      <ol className="w-live-steps">
        {STEPS.map((label, i) => (
          <li key={label} data-on={step > i}>
            <span>{label}</span>
            {i === 2 && step > i ? <b data-tone={f.tone}>{f.verdict}<small> · {f.detail}</small></b> : null}
          </li>
        ))}
      </ol>
    </figure>
  );
}

function useReveal() {
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

function useCurrentSection() {
  const [current, setCurrent] = useState<string | null>(null);
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) setCurrent(e.target.id); }),
      { rootMargin: "-40% 0px -55% 0px" },
    );
    document.querySelectorAll("section[id]").forEach((s) => io.observe(s));
    return () => io.disconnect();
  }, []);
  return current;
}

export default function Welcome() {
  useReveal();
  const current = useCurrentSection();
  const [scrolled, setScrolled] = useState(false);
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
          <nav className="w-nav-links" aria-label="Sections">
            {SECTIONS.map(([id, label]) => (
              <a key={id} href={`#${id}`} aria-current={current === id ? "true" : undefined}>{label}</a>
            ))}
          </nav>
          <Link href="/login" className="w-signin">Sign in</Link>
        </div>
      </header>

      <main>
        <section className="w-hero">
          <div className="w-hero-copy">
            <p className="w-eyebrow">The agent harness</p>
            <h1><span className="w-keep">Agents that act.</span><br /><span>A harness that answers for them.</span></h1>
            <p className="w-lede">
              Aegis gives AI agents memory, decides what they may do, asks a person when it matters, and keeps a record
              anyone can verify.
            </p>
            <div className="w-cta">
              <Link href="/login" className="w-btn w-btn-primary">Sign in</Link>
              <a href="#pillars" className="w-btn">See the platform</a>
            </div>
          </div>
          <LiveAction />
        </section>

        <section id="harness" className="w-section">
          <p className="w-eyebrow" data-reveal>What a harness is</p>
          <p className="w-statement" data-reveal>
            Everything around the model that makes its work safe to trust. <span>The model proposes. The harness disposes.</span>
          </p>
          <ol className="w-flow" data-reveal>
            {["Agent proposes", "Rules decide", "People approve", "Record proves"].map((s, i) => (
              <li key={s} className="w-flow-step"><span className="w-index-n">0{i + 1}</span><p>{s}</p></li>
            ))}
          </ol>
        </section>

        <section id="pillars" className="w-section">
          <header className="w-head" data-reveal>
            <p className="w-eyebrow">Eight pillars</p>
            <h2 className="w-h2">One harness for production agents.</h2>
            <p className="w-intro">Use each on its own through APIs and SDKs, or all of them together.</p>
          </header>
          <ul className="w-grid">
            {PILLARS.map(([name, line, status]) => (
              <li key={name} id={`pillar-${name.toLowerCase()}`} className="w-card" data-reveal>
                <p className="w-card-name"><ProductName name={name} /></p>
                <p className="w-card-line">{line}</p>
                <em data-status={status}>{status}</em>
              </li>
            ))}
          </ul>
        </section>

        <section id="proof" className="w-section">
          <header className="w-head" data-reveal>
            <p className="w-eyebrow">Proof, not promises</p>
            <h2 className="w-h2">Measured, then stated.</h2>
          </header>
          <div className="w-proof-grid">
            {PROOF.map(([n, label, note]) => (
              <div key={label} className="w-proof-cell" data-reveal>
                <p className="w-proof-num">{n}</p>
                <p className="w-proof-label">{label}</p>
                <p className="w-proof-note">{note}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="w-close" data-reveal>
          <h2>Give your agents room to act.<br /><span>Keep the right to know.</span></h2>
          <Link href="/login" className="w-btn w-btn-primary">Sign in</Link>
          <p className="w-honest">Pre-release. Runs on your own infrastructure.</p>
        </section>
      </main>

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
