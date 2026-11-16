"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Public page: what Aegis works with today, and what is planned.
import { CloseCta, PageIntro, PublicPage } from "@/components/public/Chrome";
import { INTEGRATIONS } from "@/components/public/content";

export default function Integrations() {
  return (
    <PublicPage>
      <PageIntro eyebrow="Integrations" title="Works with the stack you already run."
                 lede="Anything not available today is marked Planned." />
      <section className="w-section">
        <div className="w-integrations" data-reveal>
          {INTEGRATIONS.map((g) => (
            <div key={g.group} className="w-int-group">
              <p className="w-int-name">{g.group}</p>
              <ul>
                {g.items.map(([x, ok]) => (
                  <li key={x} className={ok ? undefined : "w-int-planned"}>{x}{ok ? null : <em>Planned</em>}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>
      <CloseCta title="Bring your own models and tools." sub="Aegis governs them all the same way." />
    </PublicPage>
  );
}
