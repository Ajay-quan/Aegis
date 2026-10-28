/**
 * Masks high-risk secrets in chat text before it is stored: API keys/tokens, payment card numbers
 * (Luhn-checked), US SSNs, and "password: x" assignments. Emails and phone numbers are kept, since
 * they are often what a user is searching for.
 */
const SECRET = /\b(?:sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})\b/g;
const CARD = /\b(?:\d[ -]?){13,19}\b/g;
const SSN = /\b\d{3}-\d{2}-\d{4}\b/g;
const PASSWORD = /\b(password|passwd|passcode|pin)(\s*(?:is|:|=)\s*)\S+/gi;

function luhn(d: string): boolean {
  let s = 0;
  let dbl = false;
  for (let i = d.length - 1; i >= 0; i--) {
    let x = d.charCodeAt(i) - 48;
    if (dbl && (x *= 2) > 9) x -= 9;
    s += x;
    dbl = !dbl;
  }
  return s % 10 === 0;
}

export function maskSecrets(text: string): string {
  return text
    .replace(SECRET, "[SECRET]")
    .replace(PASSWORD, (_m, w, sep) => `${w}${sep}[REDACTED]`)
    .replace(CARD, (m) => {
      const d = m.replace(/\D/g, "");
      return d.length >= 13 && d.length <= 19 && luhn(d) ? "[CARD]" : m;
    })
    .replace(SSN, "[SSN]");
}
