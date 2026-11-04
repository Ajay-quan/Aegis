# Setting your rules and reading your report

## Two layers of control

| Layer | What it decides | Where |
|---|---|---|
| **Agent permissions** | Which tools each agent may use, up to which risk level, and which hosts it may contact | Dashboard → *Agents & permissions*, the API, or the rules file |
| **Organization rules** | What needs a human, what is never allowed, how long approvals last. Applies to every agent. | Dashboard → *Rules*, the API, or the rules file |

Anything not granted is blocked. Organization rules can only add caution: a tool on the *never allowed* list is blocked even if it was granted and approved.

Every organization's rules are separate. Every change is versioned with who made it and how (dashboard, API or file). The history is append-only.

## Getting started: pick a preset

| Preset | Needs a person | Approvals last |
|---|---|---|
| **Strict** | Anything that changes something (risk 2+) | 30 minutes |
| **Balanced** (default) | Consequential changes (risk 3+) | 1 hour |
| **Permissive** | Irreversible actions only (risk 4) | 4 hours |

Then adjust any of these:
- the approval level
- "always ask before touching restricted data"
- tools that are never allowed
- tools that always need a person first
- how long approvals last

The *What happens with these rules* table shows the effect before you save. *Agents & permissions → Policy simulator* answers "what would happen if this agent tried X right now?" without running anything.

## Rules as a file

```yaml
version: 1
preset: balanced            # strict | balanced | permissive
rules:                      # optional overrides
  blocked_tools: [email.send]
  always_require_approval: [http.fetch]
  approval_ttl_minutes: 120
agents:                     # complete permission list per agent (anything missing is revoked)
  agt_14989b732f45312ad20a8ce0:
    - {tool: docs.search, max_risk_class: 1}
    - {tool: http.fetch, max_risk_class: 1, allowed_hosts: [docs.example.com]}
```

```bash
aegistrace policy export -o rules.yaml      # current rules and permissions
aegistrace policy apply rules.yaml --dry-run
aegistrace policy apply rules.yaml
```

The dashboard's *Rules* page has the same Download and Upload buttons. Uploading always shows the changes before anything is applied.

The file is parsed with a safe YAML loader, and unknown fields and unknown agent IDs are rejected.

## The Insights report

Dashboard → *Insights*, or `aegistrace insights --range 7d`. The CLI exits with code 1 when the verdict is *concern*, so you can use it in scheduled checks. **Download report** produces a Markdown summary you can share.

Verdicts follow fixed rules over recorded data; they are not AI judgments. An agent needs at least 5 requests or runs before it is judged.

| Agent status | When |
|---|---|
| **Concern** | Any of: 25%+ of its tool requests blocked; 20%+ of its finished runs failed; 2+ approval requests rejected; a run with an unknown external outcome |
| **Watch** | Any of: 5%+ blocked; 5%+ failed; 1 rejected approval |
| **Healthy** | Active, and none of the above |
| **Idle** | No activity in the period |

Recommendations, each linking to where you'd act on it:
- runs needing a decision
- repeated attempts at tools without permission (a common sign of prompt injection)
- tools failing 10%+ of the time
- agents whose approval requests keep being rejected
- approvals expiring unanswered
- permissions granted but never used (remove them to limit what a compromised agent could do)
