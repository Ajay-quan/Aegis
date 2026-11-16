"use client";

import { ArrowDown, ArrowUpRight, Plus, X } from "lucide-react";
import {
  AnimatePresence,
  motion,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform
} from "framer-motion";
import { useEffect, useState } from "react";

const REPO = "https://github.com/Ajay-quan/Aegis";

const menuLinks = [
  ["01", "Home", "#top"],
  ["02", "About", "#about"],
  ["03", "Features", "#work"],
  ["04", "Products", "#services"],
  ["05", "Source", "#contact"]
];

const workItems = [
  {
    title: "Remember",
    copy: "Agents store what they learn through AegisMem. Every write records which run created it, and suspicious writes are quarantined for review.",
    tag: "aegismem"
  },
  {
    title: "Check every action",
    copy: "Before an agent reads memory, sends an email or exports data, AegisTrace checks it against your rules. Anything not allowed is blocked; risky actions wait for a person.",
    tag: "aegistrace"
  },
  {
    title: "Prove it",
    copy: "Everything is written to a signed, tamper-evident log. Anyone, such as an auditor or a customer, can verify a run offline.",
    tag: "evidence"
  }
];

const services = [
  {
    number: "01",
    title: "AegisTrace",
    time: "For agent teams",
    body: "A safety and accountability layer for AI agents: default-deny permissions, human approval bound to the exact action, a signed audit log, and a dashboard showing what needs attention.",
    tags: ["Policies", "Approvals", "Signed log", "Dashboard"]
  },
  {
    number: "02",
    title: "AegisMem",
    time: "Memory for agents",
    body: "A memory server for agents with hybrid search, contradiction handling, quarantine for untrusted writes, and signed erasure receipts. Connected to AegisTrace, every memory access is governed.",
    tags: ["Recall", "Quarantine", "Erasure receipts", "MCP"]
  },
  {
    number: "03",
    title: "AegisMem Recall",
    time: "Free browser extension",
    body: "Search every chat you have had with ChatGPT, Claude, Gemini and Perplexity in one place, and continue any chat in another AI. Encrypted on your device; no servers.",
    tags: ["Chrome", "On-device", "Encrypted", "Free"]
  }
];

const archiveItems = [
  "A support agent may read product notes but never a customer's health details.",
  "Erasing a customer's memories pauses until a person approves, and returns a signed receipt.",
  "A planted instruction stored as a 'memory' is quarantined instead of steering the agent later.",
  "An auditor verifies exactly what an agent remembered and did, without trusting your servers."
];

export default function Home() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [activeWork, setActiveWork] = useState(0);
  const reduceMotion = useReducedMotion();
  const { scrollYProgress } = useScroll();
  const progressX = useSpring(scrollYProgress, { stiffness: 120, damping: 28, mass: 0.3 });
  const heroY = useTransform(scrollYProgress, [0, 0.18], [0, reduceMotion ? 0 : -44]);
  const heroOpacity = useTransform(scrollYProgress, [0, 0.16], [1, reduceMotion ? 1 : 0.72]);

  const reveal = {
    hidden: { opacity: 0, y: reduceMotion ? 0 : 34 },
    visible: { opacity: 1, y: 0 }
  };

  const sectionMotion = {
    initial: "hidden",
    whileInView: "visible",
    viewport: { once: true, margin: "-12% 0px -12% 0px" },
    transition: { duration: reduceMotion ? 0 : 0.7, ease: [0.22, 1, 0.36, 1] }
  } as const;

  useEffect(() => {
    const timer = window.setTimeout(() => setLoaded(true), 700);
    return () => window.clearTimeout(timer);
  }, []);

  function closeMenu() {
    setMenuOpen(false);
  }

  return (
    <main className={`nvx-page ${loaded ? "is-loaded" : ""}`}>
      <motion.div className="nvx-scroll-progress" style={{ scaleX: progressX }} aria-hidden="true" />
      <div className="nvx-transition" aria-hidden="true">
        <div className="nvx-load-logo">Aegis</div>
        {Array.from({ length: 64 }).map((_, index) => (
          <span key={index} />
        ))}
      </div>

      <motion.header
        className="nvx-navbar"
        initial={reduceMotion ? false : { y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
      >
        <a href="#top" className="nvx-logo" onClick={closeMenu} aria-label="Aegis home">
          <span className="nvx-logo-mark">A</span>
          <span>Aegis</span>
        </a>
        <div className="nvx-nav-actions">
          <div className="nvx-slots">
            <span />
            <p>trust for AI agents</p>
          </div>
          <button
            className="nvx-menu-btn"
            aria-expanded={menuOpen}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            onClick={() => setMenuOpen((value) => !value)}
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Plus className="h-5 w-5" />}
            <span>{menuOpen ? "Close" : "Menu"}</span>
          </button>
        </div>
      </motion.header>

      <AnimatePresence>
        {menuOpen && (
          <motion.nav
            className="nvx-menu-overlay"
            aria-label="Main menu"
            initial={reduceMotion ? false : { clipPath: "inset(0 0 100% 0)" }}
            animate={{ clipPath: "inset(0 0 0% 0)" }}
            exit={{ clipPath: "inset(0 0 100% 0)" }}
            transition={{ duration: reduceMotion ? 0 : 0.48, ease: [0.76, 0, 0.24, 1] }}
          >
            <div className="nvx-grid-lines" aria-hidden="true" />
            <div className="nvx-menu-inner">
              <motion.div
                className="nvx-menu-left"
                initial="hidden"
                animate="visible"
                variants={{ visible: { transition: { staggerChildren: reduceMotion ? 0 : 0.055 } } }}
              >
                {menuLinks.map(([number, label, href]) => (
                  <motion.a
                    href={href}
                    key={label}
                    onClick={closeMenu}
                    variants={reveal}
                    transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
                  >
                    <span>{number}</span>
                    <strong>{label}</strong>
                  </motion.a>
                ))}
              </motion.div>
              <motion.div className="nvx-menu-right" variants={reveal} initial="hidden" animate="visible">
                <div>
                  <p className="nvx-pixel">Products</p>
                  <a href="#services" onClick={closeMenu}>AegisTrace</a>
                  <a href="#services" onClick={closeMenu}>AegisMem</a>
                  <a href="#services" onClick={closeMenu}>AegisMem Recall</a>
                </div>
                <div>
                  <p className="nvx-pixel">Source</p>
                  <a href={REPO}>[ GitHub ]</a>
                </div>
              </motion.div>
            </div>
          </motion.nav>
        )}
      </AnimatePresence>

      <div className="nvx-shell">
        <div className="nvx-grid-lines" aria-hidden="true" />

        <motion.section id="top" className="nvx-hero" style={{ y: heroY, opacity: heroOpacity }}>
          <div className="nvx-hero-row nvx-hero-row-top">
            <motion.h1 initial={reduceMotion ? false : { y: 44, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}>AGENTS</motion.h1>
            <motion.p initial={reduceMotion ? false : { y: 28, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.12, duration: 0.65, ease: [0.22, 1, 0.36, 1] }}>
              Aegis checks what your AI agents do, governs what they remember, and keeps a signed
              record anyone can verify.
            </motion.p>
          </div>
          <div className="nvx-hero-row">
            <motion.h1 initial={reduceMotion ? false : { y: 44, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.08, duration: 0.65, ease: [0.22, 1, 0.36, 1] }}>YOU CAN</motion.h1>
            <motion.div
              className="nvx-outlined-word"
              data-cursor="stateful"
              initial={reduceMotion ? false : { scale: 0.96, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.22, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
              whileHover={reduceMotion ? undefined : { y: -4 }}
              whileTap={reduceMotion ? undefined : { scale: 0.985 }}
            >
              <h1>TRUST</h1>
              <span className="corner tl" />
              <span className="corner tr" />
              <span className="corner bl" />
              <span className="corner br" />
            </motion.div>
          </div>
          <motion.h2 initial={reduceMotion ? false : { y: 36, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.18, duration: 0.65, ease: [0.22, 1, 0.36, 1] }}>governed, remembered, provable.</motion.h2>

          <div className="nvx-hero-meta">
            <div>
              <a href="#work">Features,</a>
              <a href="#services">Products,</a>
            </div>
            <a href="#about" className="nvx-scroll-link">
              <ArrowDown className="h-4 w-4" />
              scroll down
            </a>
            <a href={REPO}>GitHub</a>
          </div>

          <motion.a href="#services" className="nvx-hero-btn" whileTap={reduceMotion ? undefined : { scale: 0.98 }}>
            <span>SEE THE PRODUCTS</span>
            <i><ArrowUpRight className="h-5 w-5" /></i>
          </motion.a>
        </motion.section>

        <motion.section id="about" className="nvx-about" {...sectionMotion}>
          <motion.div className="nvx-section-tag" variants={reveal}>ABOUT</motion.div>
          <motion.div className="nvx-about-box" variants={reveal}>
            <h3>
              <em>Agents</em> now send emails, export data and remember things about your customers.
              Aegis makes sure they only do what you allow, and proves what they did.
            </h3>
            <div className="nvx-rule" />
            <div className="nvx-about-lower">
              <div className="nvx-hand">☞</div>
              <p>
                <span>Aegis</span> is two products that work together. AegisTrace decides whether each
                agent action may run and records it in a signed log. AegisMem is the agent&apos;s
                memory, and every read, write and erasure goes through AegisTrace&apos;s checks.
                <strong> Memory you can govern, actions you can prove.</strong>
              </p>
            </div>
          </motion.div>
        </motion.section>

        <motion.section id="work" className="nvx-work" {...sectionMotion}>
          <div className="nvx-work-copy">
            <div className="nvx-section-tag">FEATURES</div>
            {workItems.map((item, index) => (
              <motion.article
                key={item.title}
                className={activeWork === index ? "is-active" : ""}
                onClick={() => setActiveWork(index)}
                onMouseEnter={() => setActiveWork(index)}
                whileTap={reduceMotion ? undefined : { scale: 0.985 }}
                tabIndex={0}
                role="button"
                aria-pressed={activeWork === index}
              >
                <p>{item.tag}</p>
                <h3>{item.title}</h3>
                <span>{item.copy}</span>
              </motion.article>
            ))}
          </div>
          <motion.div className="nvx-work-visual" variants={reveal}>
            <div className="nvx-browser-bar">
              <span />
              <span />
              <span />
              <p>run.timeline</p>
            </div>
            <div className="nvx-memory-map">
              <span className="node core">AegisTrace</span>
              <span className={`node n1 ${activeWork === 0 ? "is-hot" : ""}`}>memory.remember</span>
              <span className={`node n2 ${activeWork === 1 ? "is-hot" : ""}`}>policy check</span>
              <span className={`node n3 ${activeWork === 2 ? "is-hot" : ""}`}>approval</span>
              <span className={`node n4 ${activeWork === 2 ? "is-hot" : ""}`}>signed log</span>
              <svg viewBox="0 0 700 430" aria-hidden="true">
                <path d="M350 215 C260 120 180 110 115 96" />
                <path d="M350 215 C470 110 545 100 600 128" />
                <path d="M350 215 C250 310 160 330 122 350" />
                <path d="M350 215 C452 302 522 326 600 350" />
              </svg>
            </div>
          </motion.div>
        </motion.section>

        <motion.section id="services" className="nvx-services" {...sectionMotion}>
          <motion.div className="nvx-services-header" variants={reveal}>
            <div className="nvx-section-tag">PRODUCTS</div>
            <h2>THE TRUST LAYER FOR AI AGENTS.</h2>
          </motion.div>
          {services.map((service) => (
            <motion.article className="nvx-service-card" key={service.title} variants={reveal} whileTap={reduceMotion ? undefined : { scale: 0.995 }}>
              <div className="nvx-service-top">
                <p>{service.number}</p>
                <h3>{service.title}</h3>
                <div className="nvx-service-line" />
                <span>{service.time}</span>
              </div>
              <div className="nvx-service-content">
                <p>{service.body}</p>
                <ul>
                  {service.tags.map((tag) => (
                    <li key={tag}>{tag},</li>
                  ))}
                </ul>
              </div>
            </motion.article>
          ))}
        </motion.section>

        <motion.section className="nvx-clarity" {...sectionMotion}>
          <div className="nvx-section-tag">WHY IT MATTERS</div>
          <h2>Memory is the newest way to attack an agent. Govern it like any other action.</h2>
          <p>
            A false &quot;memory&quot; can steer an agent long after the conversation that planted it.
            With Aegis, every memory records where it came from, untrusted writes are quarantined,
            and each access is checked and signed.
          </p>
          <motion.div className="nvx-ticket" variants={reveal} whileHover={reduceMotion ? undefined : { rotate: -2, y: -8 }} whileTap={reduceMotion ? undefined : { scale: 0.985 }}>
            <div>GOVERNED MEMORY</div>
            <strong>AEGIS</strong>
            <span>FOR AI AGENTS</span>
          </motion.div>
        </motion.section>

        <motion.section className="nvx-newsletter" {...sectionMotion}>
          <motion.div className="nvx-magazine" variants={reveal}>
            <div>01</div>
            <span>TRUST</span>
          </motion.div>
          <motion.div className="nvx-newsletter-copy" variants={reveal}>
            <div className="nvx-section-tag">USE CASES</div>
            <h2>What <strong>Aegis</strong> makes possible</h2>
            <p>
              Aegis is pre-release: it runs today on your own machine with Docker, and has not had an
              independent security review yet. The source is open to read.
            </p>
            <div className="nvx-archive-list">
              {archiveItems.map((item) => (
                <div key={item}>
                  <span>✦</span>
                  <p>{item}</p>
                </div>
              ))}
            </div>
            <div className="nvx-form nvx-form-single">
              <a href={REPO}>VIEW THE SOURCE ON GITHUB</a>
            </div>
          </motion.div>
        </motion.section>
      </div>

      <motion.footer id="contact" className="nvx-footer" initial="hidden" whileInView="visible" viewport={{ once: true }} variants={reveal}>
        <div className="nvx-footer-upper">
          <div>
            <p>Quick Links</p>
            <a href="#top">Home,</a>
            <a href="#about">About,</a>
            <a href="#work">Features,</a>
            <a href="#services">Products</a>
          </div>
          <div>
            <a href={REPO}>[ GitHub ]</a>
          </div>
        </div>
        <div className="nvx-footer-word">Aegis</div>
        <p>© 2026 All Rights Reserved.</p>
      </motion.footer>
    </main>
  );
}
