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

const menuLinks = [
  ["01", "Home", "#top"],
  ["02", "About", "#about"],
  ["03", "Features", "#work"],
  ["04", "Platform", "#services"],
  ["05", "Contact", "#contact"]
];

const workItems = [
  {
    title: "Context Memory",
    copy: "Capture facts, preferences, decisions, and working context so agents can continue without a full recap.",
    tag: "capture"
  },
  {
    title: "Reliable Recall",
    copy: "Hybrid retrieval ranks relevant memory by meaning, recency, source, and importance before it reaches the agent.",
    tag: "retrieval"
  },
  {
    title: "Memory Control",
    copy: "Version, update, archive, and remove memory with clear lifecycle rules instead of letting context drift.",
    tag: "governance"
  }
];

const services = [
  {
    number: "01",
    title: "Memory API",
    time: "Simple endpoints",
    body: "Add durable memory to an assistant or agent workflow with clean endpoints for write, search, update, and delete operations.",
    tags: ["Write", "Search", "Update", "Delete"]
  },
  {
    number: "02",
    title: "Recall Layer",
    time: "Ranked context",
    body: "Semantic search, lexical search, recency, and confidence signals combine into a compact context package for every request.",
    tags: ["Vectors", "BM25", "Recency", "Scoring"]
  },
  {
    number: "03",
    title: "Agent Integrations",
    time: "Works anywhere",
    body: "Connect memory to apps, internal tools, or agent runtimes through REST and MCP without changing how your product already works.",
    tags: ["REST", "MCP", "Tools", "Apps"]
  }
];

const archiveItems = [
  "Persist user preferences and project facts across sessions.",
  "Retrieve only the context that matters for the current task.",
  "Track memory changes so stale or contradicted facts can be corrected.",
  "Keep the integration small enough for product teams to ship quickly."
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
        <div className="nvx-load-logo">AegisMem</div>
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
        <a href="#top" className="nvx-logo" onClick={closeMenu} aria-label="AegisMem home">
          <span className="nvx-logo-mark">S</span>
          <span>AegisMem</span>
        </a>
        <div className="nvx-nav-actions">
          <div className="nvx-slots">
            <span />
            <p>memory infrastructure</p>
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
                  <p className="nvx-pixel">Platform</p>
                  <a href="#services" onClick={closeMenu}>REST API</a>
                  <a href="#services" onClick={closeMenu}>MCP tools</a>
                  <a href="#services" onClick={closeMenu}>Hybrid retrieval</a>
                </div>
                <div>
                  <p className="nvx-pixel">E-mail</p>
                  <a href="mailto:hello@AegisMem">[ hello@AegisMem ]</a>
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
            <motion.h1 initial={reduceMotion ? false : { y: 44, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}>MEMORY</motion.h1>
            <motion.p initial={reduceMotion ? false : { y: 28, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.12, duration: 0.65, ease: [0.22, 1, 0.36, 1] }}>
              AegisMem gives AI products a durable memory layer: capture the right context,
              retrieve it when it matters, and keep it accurate over time.
            </motion.p>
          </div>
          <div className="nvx-hero-row">
            <motion.h1 initial={reduceMotion ? false : { y: 44, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.08, duration: 0.65, ease: [0.22, 1, 0.36, 1] }}>FOR AI THAT</motion.h1>
            <motion.div
              className="nvx-outlined-word"
              data-cursor="stateful"
              initial={reduceMotion ? false : { scale: 0.96, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.22, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
              whileHover={reduceMotion ? undefined : { y: -4 }}
              whileTap={reduceMotion ? undefined : { scale: 0.985 }}
            >
              <h1>LASTS</h1>
              <span className="corner tl" />
              <span className="corner tr" />
              <span className="corner bl" />
              <span className="corner br" />
            </motion.div>
          </div>
          <motion.h2 initial={reduceMotion ? false : { y: 36, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.18, duration: 0.65, ease: [0.22, 1, 0.36, 1] }}>simple, persistent, controlled.</motion.h2>

          <div className="nvx-hero-meta">
            <div>
              <a href="#work">Features,</a>
              <a href="#services">Platform,</a>
            </div>
            <a href="#about" className="nvx-scroll-link">
              <ArrowDown className="h-4 w-4" />
              scroll down
            </a>
            <a href="mailto:hello@AegisMem">hello@AegisMem</a>
          </div>

          <motion.a href="#contact" className="nvx-hero-btn" whileTap={reduceMotion ? undefined : { scale: 0.98 }}>
            <span>EXPLORE THE PLATFORM</span>
            <i><ArrowUpRight className="h-5 w-5" /></i>
          </motion.a>
        </motion.section>

        <motion.section id="about" className="nvx-about" {...sectionMotion}>
          <motion.div className="nvx-section-tag" variants={reveal}>ABOUT</motion.div>
          <motion.div className="nvx-about-box" variants={reveal}>
            <h3>
              <em>Most</em> AI products still treat every session like a fresh start. AegisMem
              keeps important context available, organized, and governed so agents can act with
              continuity.
            </h3>
            <div className="nvx-rule" />
            <div className="nvx-about-lower">
              <div className="nvx-hand">☞</div>
              <p>
                <span>AegisMem</span> is built for teams adding long-term memory to assistants,
                copilots, and autonomous workflows. It keeps the surface area small: one place to
                write memory, one place to retrieve it, and clear controls for change.
                <strong> Less noise, better context.</strong>
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
              <p>state.graph</p>
            </div>
            <div className="nvx-memory-map">
              <span className="node core">AegisMem</span>
              <span className={`node n1 ${activeWork === 0 ? "is-hot" : ""}`}>User fact</span>
              <span className={`node n2 ${activeWork === 1 ? "is-hot" : ""}`}>Relevant recall</span>
              <span className={`node n3 ${activeWork === 2 ? "is-hot" : ""}`}>Memory update</span>
              <span className={`node n4 ${activeWork === 2 ? "is-hot" : ""}`}>Retrieved context</span>
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
            <div className="nvx-section-tag">PLATFORM</div>
            <h2>THE TRUST LAYER FOR AGENT MEMORY.</h2>
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
          <h2>Give agents continuity without making your product harder to operate.</h2>
          <p>
            The right memory layer should be quiet infrastructure: simple to add, predictable to
            inspect, and strict enough to keep user context useful over time.
          </p>
          <motion.div className="nvx-ticket" variants={reveal} whileHover={reduceMotion ? undefined : { rotate: -2, y: -8 }} whileTap={reduceMotion ? undefined : { scale: 0.985 }}>
            <div>STATEFUL CONTEXT</div>
            <strong>MEMORY CORE</strong>
            <span>FOR AI SYSTEMS</span>
          </motion.div>
        </motion.section>

        <motion.section className="nvx-newsletter" {...sectionMotion}>
          <motion.div className="nvx-magazine" variants={reveal}>
            <div>01</div>
            <span>MEMORY</span>
          </motion.div>
          <motion.div className="nvx-newsletter-copy" variants={reveal}>
            <div className="nvx-section-tag">USE CASES</div>
            <h2>Where <strong>AegisMem</strong> fits</h2>
            <p>
              Add persistent context to support agents, product copilots, internal assistants, and
              workflow automations without redesigning the entire application around memory.
            </p>
            <div className="nvx-archive-list">
              {archiveItems.map((item) => (
                <div key={item}>
                  <span>✦</span>
                  <p>{item}</p>
                </div>
              ))}
            </div>
            <form className="nvx-form">
              <input aria-label="Name" placeholder="Your name" />
              <input aria-label="Email" placeholder="name@example.com" type="email" />
              <button type="button">REQUEST ACCESS</button>
            </form>
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
            <a href="#contact">Contact</a>
          </div>
          <div>
            <a href="mailto:hello@AegisMem">[ hello@AegisMem ]</a>
          </div>
        </div>
        <div className="nvx-footer-word">AegisMem</div>
        <p>© 2026 All Rights Reserved.</p>
      </motion.footer>
    </main>
  );
}
