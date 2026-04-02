# Security Model

Guild Scroll stores potentially sensitive terminal session artifacts. This project follows a local-first design.

## Localhost-only web mode

- `gscroll serve` binds to `127.0.0.1` only.
- The server is intended for local use with no authentication layer.
- Session names are validated and resolved under the sessions directory to prevent path traversal and symlink escape.

## Data sensitivity

Session logs may contain secrets, tokens, hostnames, and command output. Treat exported reports and archives as sensitive.

## Headers and browser behavior

The local web server returns conservative headers:

- `Cache-Control: no-store`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`

## Reporting vulnerabilities

Please report vulnerabilities via GitHub Security Advisories:

https://github.com/Panacota96/Guild-Scroll/security/advisories/new
