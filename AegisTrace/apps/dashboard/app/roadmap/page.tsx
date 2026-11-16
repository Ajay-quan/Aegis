"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Public page: what is built, what is next.
import { ProductName } from "@/components/Logo";
import { CloseCta, PageIntro, PublicPage } from "@/components/public/Chrome";
import { ROADMAP } from "@/components/public/content";

export default function Roadmap() {
  return (
    <PublicPage>
      <PageIntro eyebrow="Roadmap" title="Built in the order that earns trust."
                 lede="Memory and evidence first, then one governed workspace, then the rest of the harness." />
      <section className="w-section">
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
        <p className="w-honest">Aegis is pre-release and runs on your own infrastructure. An independent security review comes next.</p>
      </section>
      <CloseCta title="Follow along as it ships." sub="Everything is on GitHub." />
    </PublicPage>
  );
}
