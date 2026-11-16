"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Public page: Aegis Studio and the guarantees underneath it.
import { CloseCta, PageIntro, PublicPage } from "@/components/public/Chrome";
import { CAPABILITIES, STUDIO } from "@/components/public/content";

export default function Platform() {
  return (
    <PublicPage>
      <PageIntro eyebrow="Aegis Studio" title="One place to build, watch and govern."
                 lede="The workspace for agents, runs, memory, models and security. Each status says what works today." />
      <section className="w-section">
        <div className="w-studio">
          {STUDIO.map((g) => (
            <div key={g.group} className="w-list-group" data-reveal>
              <p className="w-list-name">{g.group}</p>
              <ul className="w-rows">
                {g.items.map(([name, desc, status]) => (
                  <li key={name}>
                    <div><p className="w-row-title">{name}</p><p className="w-row-desc">{desc}</p></div>
                    <em data-status={status}>{status}</em>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>
      <section className="w-section">
        <header className="w-head" data-reveal>
          <p className="w-eyebrow">Underneath</p>
          <h2 className="w-h2">The guarantees that hold it together.</h2>
        </header>
        <ul className="w-caps">
          {CAPABILITIES.map(([name, desc, status]) => (
            <li key={name} data-reveal>
              <p className="w-row-title">{name}</p>
              <p className="w-row-desc">{desc}</p>
              <em data-status={status}>{status}</em>
            </li>
          ))}
        </ul>
      </section>
      <CloseCta title="See it on your own agents." sub="Sign in to the Studio." />
    </PublicPage>
  );
}
