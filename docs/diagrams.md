# Guild Scroll — Visual Diagrams Reference

This document collects every Mermaid diagram used across the project in one place, so that contributors and users can quickly understand how Guild Scroll is organised and how it works.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Project Directory Structure](#2-project-directory-structure)
3. [CLI Command Overview](#3-cli-command-overview)
4. [Session Data Flow](#4-session-data-flow)
5. [Recording Lifecycle](#5-recording-lifecycle)
6. [Session Lifecycle State Machine](#6-session-lifecycle-state-machine)
7. [JSONL Data Model](#7-jsonl-data-model)
8. [Export Pipeline](#8-export-pipeline)
9. [Security and Integrity Model](#9-security-and-integrity-model)
10. [Module Dependency Map](#10-module-dependency-map)
11. [Multi-Session Flow](#11-multi-session-flow)

---

## 1. Architecture Overview

High-level picture of how the shell recorder, core processing layer, and user-facing surfaces fit together.

```mermaid
graph LR
    subgraph "Shell & Recorder"
        start["gscroll start"] --> hooks["Hook injector\n(zsh/bash preexec/precmd)"]
        hooks --> script["script process\nraw_io.log + timing.log"]
        hooks --> events["Event stream\nsession.jsonl"]
    end

    subgraph "Core"
        loader["session_loader.py\nLoadedSession + indexes"]
        schema["log_schema.py\nJSONL event types"]
        enrich["asset_detector.py + tool_tagger.py\nauto-label + detect assets"]
        integrity["validator.py + integrity.py\nHMAC, encryption, signing"]
    end

    events --> loader
    schema --> loader
    loader --> enrich
    enrich --> loader
    loader --> integrity

    subgraph "Surfaces"
        cli["cli.py\nClick commands"]
        exporters["exporters/\nmd | html | cast | obsidian"]
        tui["tui/\nTextual dashboard"]
        web["web/app.py\nlocal viewer + API"]
        replay["replay.py\nscriptreplay wrapper"]
        sharing["sharing.py\narchive + uploads"]
        updater["updater.py\nself-update"]
    end

    loader --> exporters
    loader --> tui
    loader --> web
    loader --> replay
    loader --> sharing
    loader --> updater
    cli --> start
```

---

## 2. Project Directory Structure

Visual representation of the repository layout, highlighting how source code, tests, documentation, and infrastructure are organised.

```mermaid
graph TD
    root["Guild-Scroll/"] --> src["src/guild_scroll/\nMain Python package"]
    root --> tests["tests/\nPytest suite"]
    root --> docs["docs/\nDesign & deployment notes"]
    root --> github[".github/\nContributor guidance & skills"]
    root --> docker["docker/\nContainer definitions"]
    root --> k8s["k8s/\nKubernetes manifests"]
    root --> scripts["scripts/\nHelper scripts"]

    src --> cli_mod["cli.py\nClick entry-point"]
    src --> session_mod["session.py\nSession lifecycle"]
    src --> recorder_mod["recorder.py\nscript wrapper"]
    src --> hooks_mod["hooks.py\nShell hook injection"]
    src --> schema_mod["log_schema.py\nJSONL event types"]
    src --> writer_mod["log_writer.py\nEvent writers"]
    src --> enrich_mod["analysis.py / search.py\nasset_detector.py / tool_tagger.py"]
    src --> security_mod["validator.py / integrity.py\ncrypto.py / signer.py"]
    src --> exporters_mod["exporters/\nmd | html | cast | obsidian"]
    src --> tui_mod["tui/\nTextual dashboard"]
    src --> web_mod["web/app.py\nLocal viewer & API"]

    docs --> ctx["context-engineering/\nDesign decisions"]
    docs --> docker_docs["docker/\nDeployment guides"]
    docs --> sec_docs["security/\nSecurity reviews"]
    docs --> diag_docs["diagrams.md\nThis file"]

    github --> instructions[".github/instructions/\nPython, CLI, release rules"]
    github --> skills[".github/skills/\n/issue · /release · /doc-sync"]
    github --> agents[".github/agents/\nShared AI personas"]
```

---

## 3. CLI Command Overview

Every `gscroll` command and its key options at a glance.

```mermaid
mindmap
  root((gscroll))
    start
      NAME
      --mode ctf | assessment
    list
    status
    note
      SESSION
      TEXT
      --tag TAG
    export
      SESSION
      --format md | html | cast
      --writeup
      -o PATH
    search
      SESSION
      --tool TOOL
      --phase PHASE
      --exit-code CODE
      --cwd CWD
      --output-contains TEXT
    replay
      SESSION
      --speed FLOAT
    validate
      SESSION
      --repair
    sign
      SESSION
      --key KEYFILE
    verify
      SESSION
      --key KEYFILE
    finalize
      SESSION
      --result rooted | compromised | partial | failed | incomplete
    tui
      SESSION
    serve
      --host HOST
      --port PORT
      --tls-cert FILE
      --tls-key FILE
    update
```

---

## 4. Session Data Flow

Step-by-step sequence of a full recording session, from `gscroll start` to `gscroll export`.

```mermaid
sequenceDiagram
    participant U as User
    participant G as gscroll
    participant S as script
    participant Z as zsh hooks
    participant L as session.jsonl

    U->>G: gscroll start htb-machine
    G->>S: launch script --log-out raw_io.log
    G->>Z: inject preexec/precmd hooks
    G->>L: write SessionMeta

    loop Each command
        U->>Z: runs a command
        Z->>L: CommandEvent (cmd, exit_code, cwd, timestamps)
        Z->>L: AssetEvent (if download/extract detected)
    end

    U->>G: gscroll note "got shell" --tag exploit
    G->>L: NoteEvent

    U->>G: gscroll export --format md
    G->>L: read all events
    G-->>U: session_report.md
```

---

## 5. Recording Lifecycle

How a session progresses from start to shareable output.

```mermaid
flowchart TD
    start([gscroll start]) --> hook[Inject shell hook\nset GUILD_SCROLL_SESSION]
    hook --> record[Record raw terminal I/O\nscript → raw_io.log + timing.log]
    hook --> evts[Write session_meta + per-command events\nsession.jsonl]
    evts --> enrich[Enrich events\nasset detection + tool tagging]
    enrich --> secure[Validate, sign, encrypt on finalize\nsession.sig + enc files]
    record --> load[Load session\nsession_loader.py]
    secure --> load
    load --> surfaces[[Exports / Search / Replay / TUI / Web]]
    surfaces --> outputs([Reports, downloads, API responses])
```

---

## 6. Session Lifecycle State Machine

The states a session passes through from creation to archival.

```mermaid
stateDiagram-v2
    [*] --> Active : gscroll start
    Active --> Active : command logged\nnote added\nasset captured
    Active --> Validated : gscroll validate
    Validated --> Active : --repair applied
    Active --> Finalized : gscroll finalize
    Finalized --> Signed : gscroll sign
    Signed --> Verified : gscroll verify ✅
    Signed --> Tampered : gscroll verify ❌
    Active --> Exported : gscroll export
    Finalized --> Exported : gscroll export
    Signed --> Exported : gscroll export
    Active --> Replayed : gscroll replay
    Finalized --> Encrypted : AES-256-GCM\n(auto on finalize v0.13+)
    Encrypted --> Exported : transparent decrypt
```

---

## 7. JSONL Data Model

The entity model for events written to `session.jsonl`.

```mermaid
erDiagram
    SESSION_META {
        string session_name
        string session_id
        string start_time
        string end_time
        string hostname
        string platform
        string mode
        bool   finalized
        string result
        int    command_count
        string operator
    }
    COMMAND_EVENT {
        string type
        int    seq
        string command
        string timestamp_start
        string timestamp_end
        int    exit_code
        string working_directory
        string tool
        string phase
        string mitre_technique
        string event_hmac
    }
    ASSET_EVENT {
        string type
        int    seq
        string trigger_command
        string asset_type
        string captured_path
        string original_path
        string timestamp
        string event_hmac
    }
    NOTE_EVENT {
        string type
        string text
        string timestamp
        array  tags
        string event_hmac
    }
    SCREENSHOT_EVENT {
        string type
        string path
        string timestamp
        string event_hmac
    }

    SESSION_META ||--o{ COMMAND_EVENT   : contains
    SESSION_META ||--o{ ASSET_EVENT     : contains
    SESSION_META ||--o{ NOTE_EVENT      : contains
    SESSION_META ||--o{ SCREENSHOT_EVENT : contains
```

---

## 8. Export Pipeline

How a loaded session is transformed into each supported output format.

```mermaid
flowchart LR
    jsonl["session.jsonl\nJSONL events"] --> loader["session_loader.py\nLoadedSession"]
    raw["raw_io.log\nRaw terminal I/O"] --> loader
    loader --> enrich2["Enrichment\nasset_detector + tool_tagger"]
    enrich2 --> md_exp["markdown.py\n→ report.md / writeup.md"]
    enrich2 --> html_exp["html.py\n→ self-contained report.html"]
    enrich2 --> cast_exp["cast.py\n→ session.cast\n(asciicast v2)"]
    enrich2 --> obs_exp["obsidian.py\n→ vault note with wikilinks"]
    enrich2 --> tui_exp["tui/\n→ Textual dashboard"]
    enrich2 --> web_exp["web/\n→ localhost HTTP viewer & API"]
```

---

## 9. Security and Integrity Model

How HMAC signing and AES-256-GCM encryption protect session data.

```mermaid
flowchart TD
    start2([gscroll start]) --> genkeys["Generate keys\nsession.key  → HMAC-SHA256\nsession.enc_key → AES-256-GCM\n(both 0o600)"]
    genkeys --> hmac["Sign each event\nHMAC-SHA256 → event_hmac field"]
    hmac --> write["Append to session.jsonl"]
    write --> finalize2([gscroll finalize])
    finalize2 --> encrypt["AES-256-GCM encrypt\nsession.jsonl + raw_io.log"]
    encrypt --> auto_sign{"Assessment\nmode?"}
    auto_sign -->|Yes| sign2["Auto-sign\n→ session.sig"]
    auto_sign -->|No| skip["Optional manual\ngscroll sign"]
    sign2 --> verify2([gscroll verify])
    skip --> verify2
    verify2 --> result2{Tamper\ndetected?}
    result2 -->|No| pass["Exit 0 ✅\nIntegrity confirmed"]
    result2 -->|Yes| fail["Exit 1 ❌\nMismatch reported"]
```

---

## 10. Module Dependency Map

How the Python modules inside `src/guild_scroll/` depend on each other.

```mermaid
graph TD
    cli_m["cli.py"] --> session_m["session.py"]
    cli_m --> session_loader_m["session_loader.py"]
    cli_m --> recorder_m["recorder.py"]
    cli_m --> hooks_m["hooks.py"]
    cli_m --> search_m["search.py"]
    cli_m --> replay_m["replay.py"]
    cli_m --> sharing_m["sharing.py"]
    cli_m --> updater_m["updater.py"]
    cli_m --> exporters_m["exporters/"]
    cli_m --> tui_m["tui/"]
    cli_m --> web_m["web/"]

    session_m --> log_schema_m["log_schema.py"]
    session_m --> log_writer_m["log_writer.py"]
    session_m --> crypto_m["crypto.py"]
    session_m --> integrity_m["integrity.py"]
    session_m --> config_m["config.py"]

    session_loader_m --> log_schema_m
    session_loader_m --> crypto_m
    session_loader_m --> analysis_m["analysis.py"]
    session_loader_m --> asset_detector_m["asset_detector.py"]
    session_loader_m --> tool_tagger_m["tool_tagger.py"]

    exporters_m --> session_loader_m
    exporters_m --> output_extractor_m["output_extractor.py"]

    tui_m --> session_loader_m
    web_m --> session_loader_m

    validator_m["validator.py"] --> session_loader_m
    validator_m --> integrity_m
    validator_m --> signer_m["signer.py"]

    merge_m["merge.py"] --> session_loader_m
    merge_m --> log_schema_m
```

---

## 11. Multi-Session Flow *(M4)*

For scenarios with multiple concurrent terminals (e.g. attacker shell + reverse shell listener).

```mermaid
graph LR
    T1["Terminal 1\n(attacker shell)"] -->|"part 1"| S["Session: htb-machine"]
    T2["Terminal 2\n(reverse shell)"] -->|"part 2"| S
    T3["Terminal 3\n(listener)"] -->|"part 3"| S
    S -->|"gscroll join"| M["Merged timeline\n(by timestamp)"]
    M --> E["Export / TUI / Writeup"]
```

---

> **Keeping diagrams up to date:** whenever a new module, command, or workflow is added, update the relevant section above and the corresponding diagram in `README.md`. The CI link-checker (`scripts/check_markdown_links.py`) validates all relative links in this file on every push.
