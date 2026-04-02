# Security

## Localhost-only web server

`gscroll serve` is intentionally limited to `127.0.0.1`. It is designed for local review on the same machine that recorded the session and must not be exposed on shared interfaces.

## No authentication by design

The local web viewer does not implement authentication, authorization, or multi-user isolation. This is acceptable only because the server is restricted to localhost and is meant for a single trusted operator.

## Session data sensitivity

Guild Scroll sessions can contain command history, terminal output, notes, paths, hostnames, and exported report content. Treat the `guild_scroll/` directory and any browser session displaying it as sensitive pentest/CTF data.

## Browser handling

The web server sends anti-caching and framing/type-sniffing headers for HTML and JSON responses, but local operators should still close the viewer when finished and avoid using it on untrusted systems.
