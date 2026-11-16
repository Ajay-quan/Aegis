# Outbound network control (egress)

## In the application (`tools/egress.py`, used by `http.fetch`)
- HTTPS only; destination hostname must be on the tool grant's allowlist.
- Each hop is resolved **once**, every DNS answer is checked (private, loopback, link-local/metadata,
  multicast and reserved addresses are refused; one bad answer refuses the hop), and the request is sent
  to **the checked address itself**. TLS still verifies the certificate against the real hostname (SNI and
  Host header). A different DNS answer at connect time (DNS rebinding) cannot redirect the request.
- Redirects are followed manually (at most 3); every hop is checked again by name.
- Responses are size-capped (256 KiB) and time-bounded.

Tests: `tests/security/test_egress_pinning.py`:
- a rebinding resolver: one lookup, the connection goes to the first, public answer;
- mixed DNS answers;
- a redirect to an internal host;
- IPv6;
- real TLS: hostname verification over a pinned IP, and rejection of a certificate for another name.

## Known gap
Remote MCP servers (`mcpgw/bridge.py`) are checked before connecting, but the MCP SDK resolves the name
again itself, so the rebinding window still exists there. The URL is administrator-configured, never model
input, which limits the risk; network-level control (below) closes it.

## In production: the authoritative boundary
Application checks are defence in depth. Enforce egress where the worker cannot change it:
- **Kubernetes:** a default-deny egress `NetworkPolicy` for worker pods. Allow only Postgres, Redis, OPA,
  the signing service, AegisMem, and an egress proxy.
- **Egress proxy** for internet-bound calls (model providers, `http.fetch`, remote MCP) with a domain
  allowlist that also refuses private address ranges after its own resolution (e.g. Squid `dst` ACLs or
  Smokescreen).
- **Cloud:** security groups or firewall rules with no direct internet route from the worker subnet;
  block the instance-metadata address.
