"""Unit tests for PII redaction at ingest."""
from __future__ import annotations

from domain.privacy.redaction import redact, scan


def test_email_redacted():
    r = redact("contact me at jane.doe@example.com please")
    assert "[REDACTED_EMAIL]" in r.text
    assert "jane.doe@example.com" not in r.text
    assert r.counts.get("EMAIL") == 1


def test_ssn_redacted():
    r = redact("my ssn is 123-45-6789")
    assert "[REDACTED_SSN]" in r.text
    assert r.counts.get("SSN") == 1


def test_valid_credit_card_redacted_invalid_kept():
    # 4242 4242 4242 4242 is a Luhn-valid test card.
    valid = redact("card 4242 4242 4242 4242")
    assert "[REDACTED_CARD]" in valid.text
    # A 16-digit run that fails the Luhn checksum must NOT be redacted as a card.
    invalid = redact("order 1111 1111 1111 1111")
    assert "[REDACTED_CARD]" not in invalid.text


def test_secret_token_redacted():
    r = redact("key sk-abcdefghij0123456789ABCD live")
    assert "[REDACTED_SECRET]" in r.text
    assert r.counts.get("SECRET") == 1


def test_phone_and_ip_redacted():
    r = redact("call +1 (415) 555-2671 or ping 192.168.1.42")
    assert "[REDACTED_PHONE]" in r.text
    assert "[REDACTED_IP]" in r.text


def test_clean_text_untouched():
    text = "The user prefers Python and FAISS for local search."
    r = redact(text)
    assert r.text == text
    assert not r.redacted
    assert r.total == 0


def test_scan_counts_without_mutating():
    counts = scan("a@b.com and c@d.org")
    assert counts.get("EMAIL") == 2
