# Audit log v2 — disk persistence design (apf-x1t)

Successor design for the in-memory v1 audit log (`apf/audit_log.py`,
shipped under apf-ive). Status as of 2026-05-19: **decisions locked in
for the day someone needs v2 to exist; the build itself is deferred
until PoC validation produces signal that disk persistence is worth
the ~500-800 LOC + crypto dependency cost.**

## TL;DR

- **Keep counts-only.** Per-span recording is rejected — doubles the
  attack surface for marginal self-review value.
- **SQLite at `~/Library/Application Support/apf/audit.db`** (macOS) /
  `~/.local/share/apf/audit.db` (Linux) / `%LOCALAPPDATA%\apf\audit.db`
  (Windows). Queryable, atomic appends, indexable on `(ts, session_id,
  category)`.
- **File-level AES-256-GCM via `cryptography` lib**, 32-byte key stored
  in macOS Keychain (`security` CLI) / Secret Service (Linux) / DPAPI
  (Windows). No SQLCipher — extra native dependency for no win over
  encrypting the file blob.
- **Default retention 7 days**, configurable via
  `APF_AUDIT_RETENTION_DAYS`. Pruning runs lazily on next write.
- **CLI**: `apf log` with `--since`, `--category`, `--session`,
  `--wipe`, `--disable`. No `--reveal` — there's nothing to reveal.
- **No "panic flush" / lid-close hooks** in v2. The "don't store
  anything worth attacking" mitigation does the heavy lifting.

## What v1 already does

`apf/audit_log.py` — opt-in via `APF_AUDIT_LOG=1`, in-process ring
buffer (`deque(maxlen=1000)`), each entry: `{ts, session_id, summary}`
where summary is `{total, per_tier, per_label, third_party}`. No
values, no surface tokens. Inspectable via
`GET /v1/sessions/{id}/audit`. Disabled = drop on the floor. Dies on
process exit.

The data model is good. v2 changes only the substrate.

## Decision: keep counts-only

The issue raised whether v2 should record full spans (`(text, category,
tier, timestamp)`). **Rejected.**

- Attack surface: the file becomes a transcript of every sensitive
  text the proxy has ever processed. Anyone who reads the file (or a
  forensic copy of it) learns the actual values, not just the
  shape — opposite of the project's primary protection.
- Self-review value: "I redacted Anna Müller at 14:23" vs "I redacted
  a PERSON at 14:23 in session X" — the marginal information is the
  identity, and the user already KNOWS the identity (they typed it).
- Privacy-leak vector: a third-party / subpoena / phishing on the
  audit file leaks the originals the rest of the proxy works to
  protect.

Counts-only stays. Period.

## Decision: SQLite, not JSONL

Three viable shapes were on the table:

| Shape | Pro | Con |
|---|---|---|
| **SQLite** | indexable on `(ts, session_id, category)`, atomic writes via WAL, partial reads cheap | extra file-format complexity |
| JSONL | append-friendly, debuggable raw, no library needed | full-scan for any filter, no concurrent-process story |
| Binary log + sidecar index | densest on disk | hand-rolled formats are bug magnets |

SQLite wins because the user-facing CLI commands (`--since`,
`--category`, `--session`) all want filtered reads, and SQLite gives
that for free. JSONL would work for raw dumps but `apf log --category
PERSON --since 24h` over a multi-MB JSONL is a full scan every
invocation. WAL mode also handles the multi-process case cleanly
(parallel `apf log` reading while the proxy writes).

Schema:

```sql
CREATE TABLE entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    session_id  TEXT NOT NULL,
    total       INTEGER NOT NULL,
    third_party INTEGER NOT NULL,
    summary_json TEXT NOT NULL  -- per_tier + per_label as JSON
);
CREATE INDEX idx_ts ON entries(ts);
CREATE INDEX idx_session ON entries(session_id);
```

`per_tier` + `per_label` get JSON-encoded into one column instead of
normalising into a wide table; the dimensions are small (<10 each)
and the only query pattern that touches them is `--category` which
runs in Python after the SQL filter.

## Decision: file-level AES-GCM, not SQLCipher

SQLCipher is the obvious "encrypt your SQLite" answer. **Rejected for
v2.**

- Native dependency: SQLCipher needs a custom-built SQLite or a
  Python wrapper that bundles its own. Either way it's an additional
  install hurdle on a project whose value proposition is "runs locally
  with as few moving parts as possible".
- File-level encryption is enough: read = decrypt → open in-memory
  SQLite from bytes, write = serialise → encrypt → atomic-replace.
  The attack we're defending against is "someone reads the file at
  rest", and that's exactly the threat AES-GCM stops.
- Performance: counts-only writes are 1–2 per session per turn. The
  encrypt/decrypt cost of the whole DB blob (kilobytes, growing
  slowly) is negligible vs. the I/O.
- Future migration: SQLCipher remains a one-line swap if cost ever
  bites. The data shape doesn't change.

Encryption format:

```
[16B nonce][ciphertext][16B GCM tag]
```

AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
Key is 32 bytes, generated on first write, stored in:

- **macOS**: Keychain via `security add-generic-password -s apf-audit
  -a $USER -w <hex>`. Read via `security find-generic-password`.
  Biometric/passphrase gating depends on Keychain ACL — we set the
  ACL to require user-presence on read.
- **Linux**: Secret Service via the `keyring` library (no extra
  binary).
- **Windows**: DPAPI via `keyring` library (no extra binary).

`keyring` is the cross-platform path; macOS gets a fallback to the
`security` CLI when the user has Keychain Access ACL preferences
beyond what `keyring` exposes.

Key rotation: not in v2. If the user wants to rotate, `apf log --wipe`
gives them a clean slate. A real rotation flow can land later.

## Decision: 7-day default retention, lazy prune

`APF_AUDIT_RETENTION_DAYS` (default `7`). On every `record()`, do:

```python
if random() < 0.01:  # ~1% of writes trigger a prune sweep
    DELETE FROM entries WHERE ts < ? -- (now - retention_days * 86400)
```

Lazy / sampled rather than a background timer: simpler (no extra
threads, no scheduler), and the worst-case overshoot at 7-day
retention is ~100 extra rows (tiny).

Hard cap: `MAX_ENTRIES = 100_000` regardless of retention. Defends
against a runaway proxy generating millions of entries.

## Decision: CLI shape

New module `apf/cli.py` (entry point `apf` via console_scripts), or
fold into `python -m apf.audit` if console_scripts adds packaging
complexity. The CLI commands:

```
apf log                            # last 24h, redacted summary
apf log --since 7d                 # explicit window
apf log --category PERSON          # filter
apf log --session <uuid>           # filter
apf log --since 1d --json          # machine output
apf log --wipe                     # zero the file (re-creates on next write)
apf log --disable                  # writes config to skip recording
apf log --enable                   # mirror of --disable
apf log --stats                    # totals across the file
```

`--reveal` is **not** a flag. There are no values in the log to
reveal; the only thing it would do is satisfy a habit transferred
from other audit-log tools. Removing it removes the cognitive
question "do I trust this command not to leak?"

The `--disable` / `--enable` flags shadow `APF_AUDIT_LOG`. Env wins
if both are set; the CLI sets a sticky config at
`~/Library/Application Support/apf/audit-config.json`. Same path the
key lookup uses.

## Rejected: panic flush, lid-close hooks

The issue raised "optional auto-rotate on lid-close / lock-screen,
optional 'panic flush' bound to a hotkey or system event". **Out of
scope for v2.**

- The threat these mitigate is "attacker grabs the laptop while
  unlocked, dumps the audit file before retention expires".
- Counts-only data + AES-GCM at rest + 7-day retention already
  reduces what such an attacker gets to a histogram of recent
  category counts.
- The complexity of system-event hooks (macOS power-management
  notifications, IOKit observers, etc.) is large relative to that
  marginal protection.

If a real user reports "I need a panic-wipe hotkey", revisit. Until
then, `apf log --wipe` from a terminal is the manual answer.

## Why v2 is deferred

The v1 audit log has been in-memory for a week. No reports of "I
wanted yesterday's audit but the process restarted". Until that signal
arrives, the cost-benefit is:

- **Cost**: ~500-800 LOC across persistence, encryption, key
  management, CLI, tests. New dep on `cryptography` + `keyring`.
- **Benefit**: cross-restart self-review. Possibly useful, no signal
  it's actually used.

Defer. Lock the design above so the build, when it happens, doesn't
re-litigate.

## When to revisit

Build v2 if any of these hit:

1. A user explicitly reports they want persistent audit history.
2. PoC validation produces a need for "what did the proxy do
   yesterday" beyond what session-scoped /audit endpoints answer.
3. A real-world incident makes after-the-fact audit useful (e.g.,
   "I think I leaked X — what did the proxy actually catch?").
4. The audit log is wired into the apf-sgz follow-up (v2 of locked
   categories needs to record locally-routed vs cloud-forwarded
   separately).

## References

- `apf/audit_log.py` — v1 implementation that this would replace.
- `apf/proxy.py` `GET /v1/sessions/{id}/audit` — endpoint that
  continues to work unchanged with v2 (substrate-swap, not API change).
- `docs/THREAT-MODEL-PRIVATE.md` §5.7 — open question this resolves.
- apf-ive (closed) — v1 design + decision.
- Python `cryptography` lib —
  <https://cryptography.io/en/latest/hazmat/primitives/aead/>
- Python `keyring` lib —
  <https://pypi.org/project/keyring/>
