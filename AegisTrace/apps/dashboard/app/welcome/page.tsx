"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Public introduction: what Aegis is, the eight pillars (scroll style) and the proof. Detail lives on
// /platform, /roadmap and /integrations.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ProductName } from "@/components/Logo";
import { CloseCta, PublicPage } from "@/components/public/Chrome";
import { PILLARS } from "@/components/public/content";

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
      {words.map((w, i) => <span key={i} style={{ opacity: i / words.length < progress ? 1 : 0.16 }}>{w} </span>)}
    </p>
  );
}

/** Sticky index on the left; each pillar lights up as it reaches the middle of the screen. */
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
    <section id="pillars" className="w-section">
      <div className="w-pillars">
        <div className="w-pillars-rail">
          <p className="w-eyebrow">Eight pillars</p>
          <h2 className="w-h2">One harness for production agents.</h2>
          <p className="w-intro w-intro-rail">Each works on its own through APIs and SDKs. Together they are the platform.</p>
          <ol className="w-index">
            {PILLARS.map((p, i) => (
              <li key={p.name} data-active={i === active}>
                <a href={`#pillar-${p.name.toLowerCase()}`}><span className="w-index-n">0{i + 1}</span><ProductName name={p.name} /></a>
              </li>
            ))}
          </ol>
        </div>
        <div className="w-pillars-list">
          {PILLARS.map((p, i) => (
            <article key={p.name} id={`pillar-${p.name.toLowerCase()}`} data-i={i}
                     ref={(el) => { refs.current[i] = el; }} className="w-pillar" data-active={i === active} data-reveal>
              <p className="w-pillar-name"><span className="w-index-n">0{i + 1}</span><ProductName name={p.name} /></p>
              <h3>{p.line}</h3>
              <p className="w-pillar-body">{p.body}</p>
              <ul>
                {p.points.map(([text, status]) => (
                  <li key={text}><span>{text}</span><em data-status={status}>{status}</em></li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Welcome() {
  return (
    <PublicPage>
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
            <a href="#pillars" className="w-btn">Explore the pillars</a>
          </div>
        </div>
        <LiveAction />
      </section>

      <section id="harness" className="w-section">
        <p className="w-eyebrow" data-reveal>What a harness is</p>
        <ScrollStatement text="Everything around the model that makes its work safe to trust. It remembers, it decides, it records, and it lets a person step in. The model proposes. The harness disposes." />
        <ol className="w-flow" data-reveal>
          {["Agent proposes", "Rules decide", "People approve", "Record proves"].map((s, i) => (
            <li key={s} className="w-flow-step"><span className="w-index-n">0{i + 1}</span><p>{s}</p></li>
          ))}
        </ol>
      </section>

      <Pillars />

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

      <CloseCta title="Give your agents room to act." sub="Keep the right to know." />
    </PublicPage>
  );
}
