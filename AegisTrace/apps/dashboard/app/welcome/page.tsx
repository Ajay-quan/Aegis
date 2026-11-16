"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Public introduction to the Aegis harness, shown before sign-in.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import "./welcome.css";

type Status = "Built" | "In progress" | "Planned";

const PILLARS: { name: string; line: string; body: string; points: [string, Status][] }[] = [
  {
    name: "Identity",
    line: "Every action has a name behind it.",
    body: "Agents act for a person and an organization. The harness knows which, before anything runs.",
    points: [["Single sign-on with your identity provider", "Built"], ["Scoped, expiring access per person and agent", "Built"], ["Each organization sealed off from every other", "Built"]],
  },
  {
    name: "Permission",
    line: "Nothing runs until you allow it.",
    body: "Every tool an agent reaches for is checked against your rules first. Anything not granted is refused.",
    points: [["Default-deny rules, enforced outside the model", "Built"], ["Never-allowed and always-ask lists per organization", "Built"], ["Try a rule before it goes live", "Built"]],
  },
  {
    name: "Approval",
    line: "The consequential moments wait for a person.",
    body: "Sending, exporting and erasing pause for a human. An approval covers that exact action, once.",
    points: [["Approval bound to the precise action", "Built"], ["Expires if nobody answers in time", "Built"], ["The decision itself is written to the record", "Built"]],
  },
  {
    name: "Memory",
    line: "What agents remember is governed too.",
    body: "Memory is checked like any other action. Each memory knows the run that wrote it. Planted instructions are held back.",
    points: [["Recall, remember and forget through the same rules", "Built"], ["Provenance for every stored fact", "Built"], ["Erasure with a signed receipt", "Built"]],
  },
  {
    name: "Evidence",
    line: "A record anyone can check.",
    body: "Each step is chained and signed. An auditor or a customer can verify a run offline, without trusting us.",
    points: [["Tamper-evident chain with signed checkpoints", "Built"], ["Signing keys held apart, with no network", "Built"], ["Keys in a managed hardware service", "Planned"]],
  },
  {
    name: "Privacy",
    line: "Sealed by default. Erasable on request.",
    body: "Inputs, responses and results are encrypted with a key for each run. Destroy the key and the content is gone.",
    points: [["Encryption at rest, one key per run", "Built"], ["Erasure, legal hold and retention", "Built"], ["Keys held in your cloud key service", "Planned"]],
  },
  {
    name: "Isolation",
    line: "Contain what agents can touch.",
    body: "Untrusted code runs in a sandbox. Outbound calls go only where you allow, to the address that was checked.",
    points: [["Container sandbox for untrusted code", "Built"], ["Outbound calls pinned to checked addresses", "Built"], ["Hardware-level isolation for hostile code", "In progress"]],
  },
  {
    name: "Insight",
    line: "See what your agents are doing, as it happens.",
    body: "One view of every run, every decision and every action waiting on you. Each run is a single trace from request to result.",
    points: [["Live dashboard and approval inbox", "Built"], ["One trace per run across every service", "Built"], ["Agent scorecards and recommendations", "Built"]],
  },
];

const FLOWS = [
  { agent: "billing-agent", act: "memory.recall", about: "acme", verdict: "Allowed", detail: "within grant", tone: "ok" },
  { agent: "ops-agent", act: "data.export", about: "customers", verdict: "Waiting for you", detail: "consequential write", tone: "wait" },
  { agent: "research-agent", act: "email.send", about: "external address", verdict: "Blocked", detail: "no permission", tone: "no" },
] as const;

const STEPS = ["Requested", "Checked against your rules", "Decided", "Signed into the record"];

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

/** The hero's live sequence: an agent action passing through the harness, one stage at a time. */
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
    <div className="w-live" aria-label="An agent action passing through the harness">
      <div className="w-live-head">
        <span className="w-mono">{f.agent}</span>
        <span className="w-live-dot" aria-hidden />
      </div>
      <p className="w-live-act"><span className="w-mono">{f.act}</span><span className="w-live-about"> · {f.about}</span></p>
      <ol className="w-live-steps">
        {STEPS.map((label, i) => (
          <li key={label} data-on={step > i}>
            <span>{label}</span>
            {i === 2 && step > i ? <b data-tone={f.tone}>{f.verdict}<small> · {f.detail}</small></b> : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** A statement whose words brighten as it scrolls through the viewport. */
function ScrollStatement({ text }: { text: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [progress, setProgress] = useState(1);
  useEffect(() => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const on = () => {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight;
      setProgress(Math.min(1, Math.max(0, (vh * 0.85 - r.top) / (r.height + vh * 0.35))));
    };
    on();
    window.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on);
    return () => { window.removeEventListener("scroll", on); window.removeEventListener("resize", on); };
  }, []);
  const words = text.split(" ");
  return (
    <p ref={ref} className="w-statement">
      {words.map((w, i) => (
        <span key={i} style={{ opacity: i / words.length < progress ? 1 : 0.18 }}>{w} </span>
      ))}
    </p>
  );
}

/** Fades sections in as they arrive. Content stays visible without JavaScript. */
function useReveal() {
  useEffect(() => {
    const els = [...document.querySelectorAll<HTMLElement>("[data-reveal]")];
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    els.forEach((el) => el.classList.add("w-pre"));
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.remove("w-pre"); io.unobserve(e.target); } }),
      { rootMargin: "0px 0px -10% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
}

function Pillars() {
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLElement | null)[]>([]);
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.i)); }),
      { rootMargin: "-45% 0px -50% 0px" },
    );
    refs.current.forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, []);
  return (
    <section id="pillars" className="w-pillars">
      <div className="w-pillars-rail">
        <p className="w-eyebrow">Eight pillars</p>
        <h2 className="w-h2">One harness.<br />Every way an agent can go wrong, covered.</h2>
        <ol className="w-index">
          {PILLARS.map((p, i) => (
            <li key={p.name} data-active={i === active}>
              <a href={`#pillar-${p.name.toLowerCase()}`}>{p.name}</a>
            </li>
          ))}
        </ol>
      </div>
      <div className="w-pillars-list">
        {PILLARS.map((p, i) => (
          <article
            key={p.name}
            id={`pillar-${p.name.toLowerCase()}`}
            data-i={i}
            ref={(el) => { refs.current[i] = el; }}
            className="w-pillar"
            data-active={i === active}
            data-reveal
          >
            <p className="w-pillar-name">{p.name}</p>
            <h3>{p.line}</h3>
            <p className="w-pillar-body">{p.body}</p>
            <ul>
              {p.points.map(([text, status]) => (
                <li key={text}>
                  <span>{text}</span>
                  <em data-status={status}>{status}</em>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}

const PROOF = [
  ["7,334", "of 7,334 runs verified", "after we killed workers and restarted the queue, database and policy engine under load"],
  ["0", "actions without a decision", "no tool ran without an explicit allow from your rules"],
  ["~7 ms", "per policy check", "95th percentile, measured on a single laptop"],
  ["249", "automated tests", "unit, security, end-to-end and browser, all passing"],
] as const;

export default function Welcome() {
  useReveal();
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
          <Link href="/welcome" className="w-wordmark">Aegis</Link>
          <nav className="w-nav-links" aria-label="Sections">
            <a href="#harness">Harness</a>
            <a href="#pillars">Pillars</a>
            <a href="#proof">Proof</a>
          </nav>
          <Link href="/login" className="w-signin">Sign in</Link>
        </div>
      </header>

      <main>
        <section className="w-hero">
          <div className="w-hero-copy">
            <p className="w-eyebrow">The Aegis harness</p>
            <h1><span className="w-keep">Agents that act.</span><br /><span>A harness that answers for them.</span></h1>
            <p className="w-lede">
              AI agents now send email, move data and remember your customers. Aegis decides what they may do,
              asks a person when it matters, and keeps a record anyone can verify.
            </p>
            <div className="w-cta">
              <Link href="/login" className="w-btn w-btn-primary">Sign in</Link>
              <a href="#pillars" className="w-btn">Explore the pillars</a>
            </div>
          </div>
          <LiveAction />
        </section>

        <section id="harness" className="w-harness">
          <p className="w-eyebrow" data-reveal>What a harness is</p>
          <ScrollStatement text="A harness is everything around the model that makes its actions safe to trust. It decides, it remembers, it records, and it lets a person step in. The model proposes. The harness disposes." />
          <div className="w-flow" data-reveal>
            {["Agent proposes", "Rules decide", "People approve", "Record proves"].map((s, i) => (
              <div key={s} className="w-flow-step">
                <span className="w-mono">0{i + 1}</span>
                <p>{s}</p>
              </div>
            ))}
          </div>
        </section>

        <Pillars />

        <section id="proof" className="w-proof">
          <p className="w-eyebrow" data-reveal>Proof, not promises</p>
          <h2 className="w-h2" data-reveal>Measured, then stated.</h2>
          <div className="w-proof-grid">
            {PROOF.map(([n, label, note]) => (
              <div key={label} className="w-proof-cell" data-reveal>
                <p className="w-proof-num">{n}</p>
                <p className="w-proof-label">{label}</p>
                <p className="w-proof-note">{note}</p>
              </div>
            ))}
          </div>
          <p className="w-honest" data-reveal>
            Aegis is pre-release. It runs today on your own infrastructure. An independent security review comes next.
          </p>
        </section>

        <section className="w-close" data-reveal>
          <h2>Give your agents room to act.<br /><span>Keep the right to know.</span></h2>
          <Link href="/login" className="w-btn w-btn-primary">Sign in</Link>
        </section>
      </main>

      <footer className="w-foot">
        <span>Aegis</span>
        <span>Trust infrastructure for AI agents</span>
      </footer>
    </div>
  );
}
