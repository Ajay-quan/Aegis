"""PII detection and redaction for memory ingestion.

Memory systems are uniquely dangerous for privacy: they *persist* whatever an
agent observes, then resurface it later. Redacting at the ingest boundary means
sensitive tokens are never embedded, never written to the vector/graph stores,
and never returned by retrieval — defense in depth, not an afterthought.

Design choices:
* **Pure stdlib `re`** — no model, no network, no new dependency; keeps the
  zero-infra promise and makes redaction deterministic and auditable.
* **Luhn validation for card numbers** — raw 13–16 digit runs produce many false
  positives (order ids, timestamps); validating the checksum keeps precision
  high. This is the kind of detail that separates a real privacy filter from a
  naive regex.
* **Typed placeholders** — replacements are labeled (`[REDACTED_EMAIL]`) so the
  memory stays useful ("the user gave their email") without leaking the value.
* **Reported, not silent** — `redact()` returns counts per category so callers
  can flag, meter, and audit what was scrubbed.

Off by default (`settings.pii_redaction_enabled`); opt-in for deployments that
handle real user data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Patterns (ordered: most specific first to avoid overlap stealing) -------
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)
# Provider secrets / tokens: OpenAI-style, AWS access keys, generic bearer-ish.
_SECRET = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,})\b"
)
# Phone: international/US-ish; require >=10 digits to limit false positives.
_PHONE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}(?!\d)"
)
# Candidate card numbers: 13–16 digits possibly separated by space/hyphen.
_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,16}\b")

PLACEHOLDERS = {
    "EMAIL": "[REDACTED_EMAIL]",
    "SSN": "[REDACTED_SSN]",
    "CREDIT_CARD": "[REDACTED_CARD]",
    "IP": "[REDACTED_IP]",
    "SECRET": "[REDACTED_SECRET]",
    "PHONE": "[REDACTED_PHONE]",
}


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def redacted(self) -> bool:
        return bool(self.counts)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _luhn_ok(digits: str) -> bool:
    """Luhn checksum — validates real card numbers, rejects random digit runs."""
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 16:
        return False
    checksum = 0
    parity = len(nums) % 2
    for i, n in enumerate(nums):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        checksum += n
    return checksum % 10 == 0


def scan(text: str) -> dict[str, int]:
    """Return counts of detected PII by category without modifying the text."""
    return redact(text).counts


def redact(text: str) -> RedactionResult:
    """Replace detected PII with typed placeholders; report per-category counts.

    Order matters: secrets, emails, SSNs, and cards are matched before phones so
    a card or SSN is not partially eaten by the phone pattern.
    """
    if not text:
        return RedactionResult(text=text, counts={})

    counts: dict[str, int] = {}

    def _sub(pattern: re.Pattern, label: str, s: str, validator=None) -> str:
        def _repl(m: re.Match) -> str:
            if validator and not validator(m.group(0)):
                return m.group(0)
            counts[label] = counts.get(label, 0) + 1
            return PLACEHOLDERS[label]
        return pattern.sub(_repl, s)

    out = text
    out = _sub(_SECRET, "SECRET", out)
    out = _sub(_EMAIL, "EMAIL", out)
    out = _sub(_SSN, "SSN", out)
    out = _sub(_CARD_CANDIDATE, "CREDIT_CARD", out, validator=_luhn_ok)
    out = _sub(_PHONE, "PHONE", out)
    out = _sub(_IPV4, "IP", out)

    return RedactionResult(text=out, counts=counts)
