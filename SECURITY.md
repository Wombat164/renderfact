# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub Security Advisories (the "Report a
vulnerability" button under the repository's Security tab). Do not open a public issue for a security
report, and do not send it by email. We will acknowledge the report and work with you on a fix and a
coordinated disclosure.

## The HTTP API: localhost-only, no authentication

`render serve` binds `127.0.0.1` by default and has NO authentication or authorization controls. It
is a single-operator, local-machine tool. Binding it to a wider address prints an explicit runtime
warning; do so only inside a trusted network, behind your own access controls. Even on localhost the
server defends against browser-driven abuse: it rejects non-loopback `Host` headers (DNS-rebinding
protection), rejects browser-signaled cross-origin POSTs, jails request-named filesystem paths under
its `--root`, rate-limits clients, and gates future write endpoints behind a per-session CSRF token.

## What the projection engine guarantees, and what it does not

The projection engine excludes gated content at the PREPROCESSOR level: content a profile is not
cleared for never enters any downstream parse tree, so it cannot appear in the rendered artifact. On
any clearance or distribution value absent from the configured ladder, the engine FAILS CLOSED
(raises an error) rather than guessing a rank. That is the guarantee: a correct profile produces a
render that structurally cannot contain higher-clearance blocks.

It does NOT guarantee that a rendered artifact stays confidential once it exists. A human can forward
a correctly-projected file to the wrong recipient; the tool governs generation, not distribution. It
also does not encrypt anything. Relatedly, embedded provenance metadata (source identity and version,
stamped into Office documents) is HIDDEN from the casual document UI but is not secure and is trivially
extractable. For that reason provenance is projection-aware: internal profiles embed it, external and
publish profiles strip it entirely. Until the strip mechanism is fully implemented in code, treat every
externally-bound artifact as manually-scrub-required before it leaves your control.
