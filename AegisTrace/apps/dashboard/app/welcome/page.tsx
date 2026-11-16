"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Public introduction to Aegis, shown before sign-in.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Logo, ProductName } from "@/components/Logo";
import "./welcome.css";

type Status = "Built" | "In progress" | "Planned";

// The eight pillars of the platform. Statuses describe what exists in the code today.
const PILLARS: { name: string; line: string; body: string; points: [string, Status][] }[] = [
  {
    name: "Mem",
    line: "Memory that lasts, and stays correct.",
    body: "Persistent memory for agents, retrieved by meaning and by keyword. Contradictions are caught, and every fact can be traced, versioned and erased.",
    points: [["Hybrid semantic and keyword retrieval", "Built"], ["Contradiction detection and reflection", "Built"], ["Knowledge-graph relationships", "In progress"]],
  },
  {
    name: "Trace",
    line: "Every step an agent takes, on the record.",
    body: "One trace per run, from the request to the result, across every model and tool call. Each step is signed, so the record can be verified offline.",
    points: [["End-to-end traces across services", "Built"], ["Signed, verifiable execution records", "Built"], ["Token usage and cost analytics", "Planned"]],
  },
  {
    name: "Runtime",
    line: "Runs that finish, even when things fail.",
    body: "Agents execute on a durable state machine. When a worker crashes or a dependency restarts, another worker picks the run up exactly where it stopped.",
    points: [["Durable orchestration with leases", "Built"], ["Recovery from crashes and outages", "Built"], ["Multi-agent workflow definitions", "Planned"]],
  },
  {
    name: "Guard",
    line: "Nothing runs until you allow it.",
    body: "Default-deny permissions enforced outside the model. Risky actions wait for a person, and each organization is sealed off from every other.",
    points: [["Policy enforcement and human approval", "Built"], ["Tenant isolation and encryption at rest", "Built"], ["Secure gateway for MCP tools", "Built"]],
  },
  {
    name: "Eval",
    line: "Know an agent is better before it ships.",
    body: "Test suites, benchmarks and regression checks that show whether a change helped, and where it failed.",
    points: [["Memory retrieval benchmarks", "Built"], ["Agent test suites and regression checks", "Planned"], ["Side-by-side model comparisons", "Planned"]],
  },
  {
    name: "Optimize",
    line: "The same answer, for fewer tokens.",
    body: "Compress context, cache what repeats and route each task to the smallest model that does it well.",
    points: [["Context compression", "Planned"], ["Response and retrieval caching", "Planned"], ["Cost reduction reports", "Planned"]],
  },
  {
    name: "Models",
    line: "Any model, hosted or local.",
    body: "Bring commercial models, open-source LLMs and small local models under one registry, with serving and fine-tuning built in.",
    points: [["Hosted and local model adapters", "In progress"], ["Model registry and routing", "Planned"], ["Fine-tuning with LoRA and QLoRA", "Planned"]],
  },
  {
    name: "Studio",
    line: "One place to build, watch and govern.",
    body: "The workspace where developers inspect runs, review approvals, explore memory and manage the whole platform.",
    points: [["Runs, approvals, rules, memory and security", "Built"], ["Sign-in with your company account", "Built"], ["Agent builder and model hub", "Planned"]],
  },
];

const ROADMAP: { when: string; title: string; products: string[]; body: string; state: string }[] = [
  { when: "Now", title: "Memory and evidence", products: ["Mem", "Trace"], body: "Reliable memory retrieval, signed execution records, trace inspection and developer APIs.", state: "Largely built" },
  { when: "Next", title: "One workspace, governed", products: ["Studio", "Guard"], body: "The components brought together in one dashboard, with stronger authorization, audit and security controls.", state: "In progress" },
  { when: "Later", title: "The full harness", products: ["Runtime", "Eval", "Optimize", "Models"], body: "Orchestration, evaluation, efficiency and local model management, each usable on its own.", state: "Planned" },
];

const INTEGRATIONS: { group: string; available: string[]; planned: string[] }[] = [
  { group: "Models", available: ["OpenAI-compatible APIs", "Anthropic", "Ollama"], planned: ["Google Gemini", "vLLM", "llama.cpp", "Hugging Face"] },
  { group: "Agents and tools", available: ["MCP", "LangChain", "LangGraph"], planned: ["PEFT", "LoRA", "QLoRA", "TRL"] },
  { group: "Data", available: ["PostgreSQL", "Qdrant", "Neo4j", "Redis"], planned: [] },
  { group: "Platform", available: ["OpenTelemetry", "Single sign-on (OIDC)", "Docker", "Python SDK", "TypeScript SDK"], planned: ["AWS"] },
];

const FLOWS = [
  { agent: "billing-agent", act: "memory.recall", about: "acme", verdict: "Allowed", detail: "within grant", tone: "ok" },
  { agent: "ops-agent", act: "data.export", about: "customers", verdict: "Waiting for you", detail: "consequential write", tone: "wait" },
  { agent: "research-agent", act: "email.send", about: "external address", verdict: "Blocked", detail: "no permission", tone: "no" },
] as const;
const STEPS = ["Requested", "Checked against your rules", "Decided", "Signed into the record"];

const PROOF = [
  ["7,334", "of 7,334 runs verified", "after killing workers and restarting the queue, database and policy engine under load"],
  ["0", "actions without a decision", "no tool ran without an explicit allow from your rules"],
  ["~7 ms", "per policy check", "95th percentile, measured on a single laptop"],
  ["249", "automated tests", "unit, security, end-to-end and browser, all passing"],
] as const;

const SECTIONS = [["harness", "Harness"], ["pillars", "Pillars"], ["roadmap", "Roadmap"], ["integrations", "Integrations"]] as const;

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
      <div className="w-live-head">
        <span className="w-mono">{f.agent}</span>
        <span className="w-live-state">Live</span>
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
    </figure>
  );
}

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

/** Which section is under the reading line: highlights the matching link in the top bar. */
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

function SectionHead({ eyebrow, title, intro }: { eyebrow: string; title: React.ReactNode; intro?: string }) {
  return (
    <header className="w-head" data-reveal>
      <p className="w-eyebrow">{eyebrow}</p>
      <h2 className="w-h2">{title}</h2>
      {intro ? <p className="w-intro">{intro}</p> : null}
    </header>
  );
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
    <section id="pillars" className="w-section">
      <div className="w-pillars">
        <div className="w-pillars-rail">
          <p className="w-eyebrow">Eight pillars</p>
          <h2 className="w-h2">One harness for production agents.</h2>
          <p className="w-intro w-intro-rail">Each pillar works on its own through APIs and SDKs. Together they are the platform.</p>
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
              Aegis is the platform around your AI agents. It gives them memory, decides what they may do, asks a
              person when it matters, and keeps a record anyone can verify.
            </p>
            <div className="w-cta">
              <Link href="/login" className="w-btn w-btn-primary">Sign in</Link>
              <a href="#pillars" className="w-btn">Explore the platform</a>
            </div>
          </div>
          <LiveAction />
        </section>

        <section id="harness" className="w-section">
          <p className="w-eyebrow" data-reveal>What a harness is</p>
          <ScrollStatement text="A harness is everything around the model that makes its work safe to trust. It remembers, it decides, it records, and it lets a person step in. The model proposes. The harness disposes." />
          <ol className="w-flow" data-reveal>
            {["Agent proposes", "Rules decide", "People approve", "Record proves"].map((s, i) => (
              <li key={s} className="w-flow-step"><span className="w-index-n">0{i + 1}</span><p>{s}</p></li>
            ))}
          </ol>
        </section>

        <Pillars />

        <section id="roadmap" className="w-section">
          <SectionHead eyebrow="Roadmap" title="Built in the order that earns trust."
                       intro="Memory and evidence come first, because everything else depends on them." />
          <ol className="w-roadmap">
            {ROADMAP.map((r) => (
              <li key={r.when} className="w-stage" data-reveal>
                <div className="w-stage-top"><span className="w-stage-when">{r.when}</span><span className="w-stage-state">{r.state}</span></div>
                <h3>{r.title}</h3>
                <p className="w-stage-products">{r.products.map((p) => <ProductName key={p} name={p} />)}</p>
                <p className="w-stage-body">{r.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="proof" className="w-section">
          <SectionHead eyebrow="Proof, not promises" title="Measured, then stated." />
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

        <section id="integrations" className="w-section">
          <SectionHead eyebrow="Integrations" title="Works with the stack you already run."
                       intro="Available today is marked plainly. Everything else is on the roadmap, not in the product." />
          <div className="w-integrations" data-reveal>
            {INTEGRATIONS.map((g) => (
              <div key={g.group} className="w-int-group">
                <p className="w-int-name">{g.group}</p>
                <ul>
                  {g.available.map((x) => <li key={x}>{x}</li>)}
                  {g.planned.map((x) => <li key={x} className="w-int-planned">{x}<em>Planned</em></li>)}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section className="w-close" data-reveal>
          <h2>Give your agents room to act.<br /><span>Keep the right to know.</span></h2>
          <Link href="/login" className="w-btn w-btn-primary">Sign in</Link>
          <p className="w-honest">Aegis is pre-release and runs on your own infrastructure. An independent security review comes next.</p>
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
