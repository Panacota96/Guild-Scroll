# Guild Scroll — Internal Process Diagrams

Visual walkthroughs of the key workflows inside Guild Scroll using Mermaid diagrams.

See also: [session-storage.md](session-storage.md) · [runtime-requirements.md](runtime-requirements.md) · [README](../../README.md)

---

## Export Pipeline

When `gscroll export` runs it loads the session once and then routes to a format-specific exporter. The diagram below shows every step from the CLI call to the final output file.

```mermaid
flowchart TD
    cmd["gscroll export SESSION --format FMT"] --> resolve["resolve_session()\nfall back to GUILD_SCROLL_SESSION env var"]
    resolve --> load["session_loader.load_session()\nparse session.jsonl\ndecrypt if enc_key present"]
    load --> merge["merge parts\n(if parts/ directory exists)"]
    merge --> enrich["enrich events\ntool_tagger.tag_command()\nanalysis.compute_phase_timeline()"]
    enrich --> route{Format?}

    route -->|md| md["exporters/markdown.py\nexport_markdown()\ncommand table + phase timeline"]
    route -->|html| html["exporters/html.py\nexport_html()\nself-contained HTML + CSS/JS"]
    route -->|cast| cast["exporters/cast.py\nexport_cast()\nasciicast v2 from raw_io.log + timing.log"]
    route -->|obsidian| obs["exporters/obsidian.py\nexport_obsidian()\nMarkdown vault with wikilinks"]

    md --> out["Output file\n(default: SESSION_report.md)"]
    html --> out2["Output file\n(default: SESSION_report.html)"]
    cast --> out3["Output file\n(default: SESSION.cast)"]
    obs --> out4["Output directory\n(Obsidian vault structure)"]
```

---

## Encryption Lifecycle

Every session gets a dedicated 256-bit AES key (`session.enc_key`) at creation time. Encryption is applied automatically on finalize and decryption is transparent whenever any `gscroll` sub-command reads log data.

```mermaid
sequenceDiagram
    participant CLI as gscroll
    participant S as session.py
    participant C as crypto.py
    participant FS as Filesystem

    CLI->>S: start_session(name, mode)
    S->>C: generate 32-byte random key
    C->>FS: write session.enc_key (0o600)
    S->>FS: write session.jsonl + raw_io.log (plaintext during recording)

    Note over CLI,FS: Session is active — data written in plaintext

    CLI->>S: finalize_session()
    S->>C: encrypt_file(session.jsonl, enc_key) → AES-256-GCM
    C->>FS: overwrite session.jsonl with ciphertext + GCM tag
    S->>C: encrypt_file(raw_io.log, enc_key) → AES-256-GCM
    C->>FS: overwrite raw_io.log with ciphertext + GCM tag

    Note over CLI,FS: Data at rest is now encrypted

    CLI->>S: load_session(name) [any sub-command: export/search/tui/web]
    S->>C: read_plaintext(session.jsonl)
    C->>FS: read ciphertext
    C-->>S: decrypted bytes (in memory only)
    S-->>CLI: LoadedSession object
```

---

## Session Integrity Chain

Guild Scroll uses HMAC-SHA256 to provide tamper-evidence for every event written to a session log. The integrity chain covers three phases: signing at write time, validation on demand, and chain-of-custody signing.

```mermaid
flowchart LR
    subgraph Write["Write (recording)"]
        ev["New event\n(command / note / asset)"] --> key["Load session.key\n(32-byte HMAC key)"]
        key --> hmac["integrity.compute_event_hmac()\nHMAC-SHA256 over sorted payload"]
        hmac --> append["log_writer.JSONLWriter.write()\nappend event + event_hmac to session.jsonl"]
    end

    subgraph Validate["Validate (gscroll validate)"]
        read["Load all events\nsession_loader.load_session()"] --> recompute["Recompute HMAC\nfor each signed event"]
        recompute --> compare{Match?}
        compare -->|Yes| ok["✅ Event valid"]
        compare -->|No| err["❌ HMAC mismatch\ntamper detected"]
        compare -->|No key file| skip["⚠️ Skip HMAC check\n(legacy session)"]
    end

    subgraph Sign["Sign (gscroll sign)"]
        load2["Load session"] --> sig["signer.sign_session()\nSHA-256 digest of full session.jsonl"]
        sig --> write2["Write session.sig\n(chain-of-custody signature)"]
    end

    append --> read
    ok --> load2
```

---

## Web Server Request Routing

`gscroll serve` starts a single-threaded HTTP server. Every request is dispatched by `GuildScrollRequestHandler._dispatch()` based on the URL path.

```mermaid
flowchart TD
    req["Incoming HTTP request"] --> dispatch["GuildScrollRequestHandler._dispatch()"]

    dispatch --> r1{URL path}

    r1 -->|"GET /"| root["_render_root_html()\nList all sessions"]
    r1 -->|"GET /api/sessions"| api_list["JSON array of session summaries\nname · start_time · command_count · assets"]
    r1 -->|"GET /session/NAME"| detail["load_session(NAME)\nexport_html() → session detail page"]
    r1 -->|"GET /api/session/NAME/report"| report["Generate report on-the-fly\n?format=md or ?format=html"]
    r1 -->|"GET /api/session/NAME/search"| search["search_commands()\nfilter by tool / phase / exit-code / cwd"]
    r1 -->|"GET /download/NAME"| dl["Stream export file\n(md / html / cast)"]
    r1 -->|"POST /api/session/NAME/delete"| del["delete_session(NAME)\nvalidate path is inside sessions_dir"]
    r1 -->|"POST /upload/NAME"| upload["_parse_multipart_upload()\nsave to assets/ directory"]
    r1 -->|"POST /api/heartbeat"| hb["_record_heartbeat()\nmark session as live"]
    r1 -->|"GET /terminal"| term["_TerminalInfo\nzsh PTY integration"]

    root --> resp["HTTP response"]
    api_list --> resp
    detail --> resp
    report --> resp
    search --> resp
    dl --> resp
    del --> resp
    upload --> resp
    hb --> resp
    term --> resp
```

---

## CTF vs Assessment Mode Decision Tree

The `--mode` flag (or `GUILD_SCROLL_MODE` env var) selects the security policy applied from session start through finalization. The tree below highlights where the two paths diverge.

```mermaid
flowchart TD
    start(["gscroll start SESSION --mode MODE"]) --> detect{Mode?}

    detect -->|ctf| ctf_dir["Create session dir\nstandard permissions\n0o755 dir / 0o644 files"]
    detect -->|assessment| ass_dir["Create session dir\nstrict permissions\n0o700 dir / 0o600 files"]

    ctf_dir --> ctf_hmac["Generate session.key\nHMAC signing optional\nunsigned events accepted"]
    ass_dir --> ass_hmac["Generate session.key\nMandatory HMAC\nunsigned events = error"]

    ctf_hmac --> ctf_enc["Generate session.enc_key\nAES-256-GCM at rest\n(both modes v0.13.0+)"]
    ass_hmac --> ass_enc["Generate session.enc_key\nAES-256-GCM at rest\n+ 0o600 key permissions"]

    ctf_enc --> record["Record session\n(shared path)"]
    ass_enc --> record

    record --> ctf_fin{Finalize mode?}
    ctf_fin -->|ctf| ctf_sign["Encrypt logs\nsigning optional\n(gscroll sign to add sig)"]
    ctf_fin -->|assessment| ass_sign["Encrypt logs\nauto-sign session.sig\nvalidator enforces all checks"]

    ctf_sign --> done(["Session finalized"])
    ass_sign --> done
```
