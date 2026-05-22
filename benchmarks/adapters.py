"""Detector adapters.

A detector takes a text and returns predicted PII spans. The base class is the
interface every model adapter must implement. The regex baseline is a deliberately
imperfect mock — it lets us validate the metrics code against a detector with
known characteristic blind spots (no implicit PII, no context-aware health,
etc.), before any MLX model is wired up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str
    tier: str  # "A" | "B" | "C"
    confidence: float = 1.0  # 1.0 = deterministic (regex), <1.0 = model probability
    # Optional Tier-C context: the surrounding KEY name when this span came
    # from a `KEY=value` regex match. Used by the secret resolver to look
    # up the real value from env/keychain by name instead of from the vault.
    context_key: str | None = None


class Detector(Protocol):
    """A detector consumes a text and emits predicted PII spans.

    Adapters MAY override `warmup` to load weights / prime caches before
    timing-relevant detection calls. `name` is what shows up in result files.
    """

    name: str

    def warmup(self) -> None: ...
    def detect(self, text: str) -> list[Span]: ...


LABEL_TIER = {
    "PERSON": "A", "EMAIL": "A", "PHONE": "A", "ADDRESS": "A", "LOCATION": "A",
    "ORG": "A", "DATE": "A", "APPOINTMENT": "A", "APPOINTMENT_HEALTH": "A",
    "HEALTH": "A", "RELATIONSHIP": "A", "FINANCIAL": "A",
    "NOTE_SENSITIVE": "A", "IMPLICIT_PII": "A",
    "PATH": "B", "FILENAME": "B", "HOSTNAME": "B", "IP": "B", "URL_LOCAL": "B",
    "CREDENTIAL": "C", "API_KEY": "C", "PRIVATE_KEY": "C",
    "PASSWORD": "C", "TOKEN": "C", "CONNECTION_STRING": "C",
}


class RegexBaseline:
    """Stage-1 regex detector. Aims to be a *deterministic high-precision*
    layer covering Tier-B (paths, IPs, hostnames) and Tier-C (secrets in
    their structurally regular forms). NOT a complete detector — pair with
    GLiNER + Presidio for natural-language PII.

    Tier-C coverage expanded 2026-05-17 (apf-1qo): PEM blocks, KEY=VALUE
    env-style assignments with sensitivity-aware label inference, OAuth
    Bearer tokens, Slack/Discord webhooks, broader API-key prefixes,
    bare base64 secret strings, and CONNECTION_STRING DSNs with embedded
    credentials.
    """

    name = "regex-baseline"

    # Plain finditer-style patterns. Order matters: earlier patterns "win"
    # the overlap dedup, so put the most specific first.
    PATTERNS = [
        # PEM blocks — match the whole block including header/footer.
        ("PRIVATE_KEY", re.compile(
            r"-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED |PGP )?PRIVATE KEY-----"
            r".*?"
            r"-----END (?:OPENSSH |RSA |EC |DSA |ENCRYPTED |PGP )?PRIVATE KEY-----",
            re.DOTALL)),

        # OAuth Bearer tokens (often followed by JWT) — anchor on the
        # word "Bearer " and capture the token after.
        ("TOKEN", re.compile(
            r"\bBearer\s+[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+){2}\b")),

        # JWT-style triple-base64 without explicit Bearer prefix.
        ("TOKEN", re.compile(
            r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")),

        # Slack webhook URLs — distinctive shape.
        ("TOKEN", re.compile(
            r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+")),

        # DSN-style connection strings: scheme://user:password@host[:port]/db
        ("CONNECTION_STRING", re.compile(
            r"\b(?:postgres(?:ql)?(?:\+[a-z]+)?|mysql|mongodb|redis|amqp)://"
            r"[A-Za-z0-9_\-]+:[^\s\"'@]+@[A-Za-z0-9_.\-]+(?::\d+)?(?:/[A-Za-z0-9_\-/]+)?")),

        # API-key prefixes. Includes:
        #   sk-… / sk_… (OpenAI, Anthropic-test, Stripe-test/live)
        #   ghp_/gho_/ghu_/ghr_/ghs_… (GitHub PATs and OAuth tokens)
        #   AKIA / ASIA… (AWS access key IDs)
        #   xox[bopars]-… (Slack bot/user tokens)
        ("API_KEY", re.compile(
            r"\b(?:sk[_-](?:test|live|fake)?[_-]?[A-Za-z0-9_\-]{20,}"
            r"|sk[_-][A-Za-z0-9_\-]{20,}"
            r"|gh[opusr]_[A-Za-z0-9]{20,}"
            r"|AKIA[0-9A-Z]{16}"
            r"|ASIA[0-9A-Z]{16}"
            r"|xox[bopars]-[A-Za-z0-9\-]{10,})")),

        # KEY=VALUE: sensitivity-aware label inference. Pattern captures
        # the value side. Group 1 is the key, group 2 the value.
        # We list per-sensitivity-class to label correctly. The same regex
        # is used multiple times below, with different label assignments.
        # Note: only matches uppercase-style env keys.
        ("PASSWORD", re.compile(
            r"\b(PASSWORD|PASSWD|PWD|PASS|ADMIN_PASSWORD|SMTP_PASSWORD)"
            r"\s*[=:]\s*([\"']?)([^\"'\n\r]+?)\2(?=\s|$|;|,)")),

        ("API_KEY", re.compile(
            r"\b((?:OPENAI|ANTHROPIC|STRIPE|GOOGLE|AZURE|HUGGINGFACE|HF|GROQ|"
            r"MISTRAL|COHERE|REPLICATE|ELEVENLABS|DEEPGRAM|TWILIO|SENDGRID|"
            r"MAILGUN|GITHUB)_(?:API_)?(?:KEY|TOKEN|SECRET))"
            r"\s*[=:]\s*([\"']?)([^\"'\n\r]+?)\2(?=\s|$|;|,)")),

        ("CONNECTION_STRING", re.compile(
            r"\b(DATABASE_URL|DB_URL|DSN|POSTGRES_URL|MYSQL_URL|REDIS_URL)"
            r"\s*[=:]\s*([\"']?)([^\"'\n\r]+?)\2(?=\s|$|;|,)")),

        ("CREDENTIAL", re.compile(
            r"\b((?:JWT_SECRET|JWT_SIGNING_SECRET|SESSION_SECRET|SECRET_KEY|"
            r"AUTH_SECRET|ENCRYPTION_KEY)[A-Z0-9_]*)"
            r"\s*[=:]\s*([\"']?)([^\"'\n\r]+?)\2(?=\s|$|;|,)")),

        ("TOKEN", re.compile(
            r"\b((?:GITHUB|GH|GITLAB|BITBUCKET|SLACK|DISCORD|TELEGRAM|"
            r"NPM|PYPI|DOCKER)_TOKEN)"
            r"\s*[=:]\s*([\"']?)([^\"'\n\r]+?)\2(?=\s|$|;|,)")),

        # ---- Crypto & financial (apf-6ql) -----------------------------
        # Listed BEFORE the base64 CREDENTIAL catch-all so a 32+-char
        # base58 / 0x-hex address lands at FINANCIAL (tier A), not
        # CREDENTIAL (tier C). All gold-labelled FINANCIAL in ai4privacy.
        #
        # Ethereum (and EVM-chain) addresses: 0x + exactly 40 hex chars.
        ("FINANCIAL", re.compile(
            r"\b0x[0-9a-fA-F]{40}\b")),

        # Bitcoin / Litecoin legacy base58 addresses: lead char 1 or 3,
        # then 24-38 base58 chars (alphabet excludes 0 O I l). Length
        # window 25-39 covers every address in the fixture set. The
        # leading word-boundary keeps it from biting into longer tokens;
        # the trailing boundary is a non-base58 lookahead.
        ("FINANCIAL", re.compile(
            r"\b[13][a-km-zA-HJ-NP-Z1-9]{24,38}(?![a-km-zA-HJ-NP-Z1-9])")),

        # IBAN — spaced *or* unspaced. Country (2 letters) + 2 check
        # digits + 11-30 alphanumerics (some national IBANs carry
        # letters in the BBAN). Spaces optional between any group.
        ("FINANCIAL", re.compile(
            r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b")),

        # Bare card-shaped numbers: 13-19 contiguous digits. Long runs of
        # digits are rarely benign; 13 is the shortest real card length.
        # MASKEDNUMBER (16-digit, gold NOTE_SENSITIVE) tier-matches this
        # since both labels are tier A.
        ("FINANCIAL", re.compile(
            r"\b\d{13,19}\b")),

        # Account numbers: bare 6-12 digit run, but ONLY when anchored by
        # an account keyword (matching a standalone short number outright
        # is a precision disaster). Group 1 is the number.
        ("FINANCIAL", re.compile(
            r"\b(?:account(?:\s+number)?|konto(?:nummer)?|"
            r"abrechnungsreferenz|iban)\b[^\d\n]{0,12}(\d{6,12})\b",
            re.IGNORECASE)),

        # Amounts: a number that is *financially* shaped — either
        #   (a) preceded by a currency symbol / sign / currency word, or
        #   (b) carrying a k/m/b magnitude suffix, or
        #   (c) written with thousands separators + decimals, or
        #   (d) a plain decimal immediately followed by an ISO-4217 code.
        # A bare integer with no currency context is deliberately NOT
        # matched (precision). Group 1 is the numeric body.
        #
        # (a) currency symbol / sign / lead-letter prefix immediately
        #     before the number (the ai4privacy synth set prefixes amounts
        #     with symbols incl. non-ASCII ones, Cyrillic 'лв', or a stray
        #     capital letter). The prefix is consumed but not in group 1.
        ("FINANCIAL", re.compile(
            r"(?:[$€£¥₹₽₩₺₴₦₱₪฿௹؋៛₭]|[A-ZЀ-ӿ]{1,3})"
            r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?[kmb]?)\b")),
        # (b) k/m/b magnitude suffix on a decimal/integer:
        ("FINANCIAL", re.compile(
            r"\b(\d+(?:[.,]\d+)?[kmb])\b")),
        # (c) thousands-separated decimal (1.234,56 / 1,234.56):
        ("FINANCIAL", re.compile(
            r"(\d{1,3}(?:[.,]\d{3})+[.,]\d{2})\b")),
        # (d) plain decimal directly followed by a 3-letter ISO-4217-style
        #     currency code — the code makes it precision-safe.
        ("FINANCIAL", re.compile(
            r"\b(\d+[.,]\d{2,})\s?(?=[A-Z]{3}\b)")),

        # Long base64-shaped values (≥32 chars), with optional `=` padding —
        # the catch-all for "looks like a secret blob".
        # Anchored on whitespace/quote/punct boundary to avoid grabbing
        # the middle of long alnum identifiers.
        ("CREDENTIAL", re.compile(
            r"(?:^|[\s\"'=:>])([A-Za-z0-9+/]{32,}={0,2})(?=$|[\s\"',;)])",
            re.MULTILINE)),

        # Existing — moved after the new Tier-C patterns to let the more
        # specific ones win the overlap dedup.
        ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
        ("PHONE", re.compile(r"\+\d{1,3}[\s-]?(?:\d{1,4}[\s-]?){2,4}\d{2,4}")),
        ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
        # PATH — three shapes (apf-6ql loosening), Tier-B:
        #   (1) `~`-rooted paths: ~/dir/file, ~/.ssh/key
        #   (2) any absolute POSIX path with >=2 segments: /seg/seg...
        #       (was: only a fixed /Users|home|opt|... prefix list —
        #       missed /data/raw/...). Requiring two segments keeps a
        #       lone `/` or a bare-root `/etc` (rare) from over-firing.
        #   (3) bare relative DIRECTORY paths only: a leading word
        #       segment then `/`, with optional further segments, ending
        #       in `/` (e.g. `src/`). Restricted to the trailing-slash
        #       directory form on purpose — matching `word/word` would
        #       swallow dates (`7/02`) and user-agent tokens
        #       (`Mozilla/5.0`), a precision collapse seen in the
        #       ai4privacy benchmark during apf-6ql.
        ("PATH", re.compile(
            r"(?:^|[\s\"'(=])(~(?:/[^\s\"'(),]+)+)")),
        ("PATH", re.compile(
            r"(?:^|[\s\"'(=])(/[A-Za-z0-9][^\s\"'(),]*(?:/[^\s\"'(),]*)+)")),
        ("PATH", re.compile(
            r"(?:^|[\s\"'(=])([A-Za-z][\w.-]*/(?:[\w.-]+/)*)"
            r"(?=$|[\s\"'(),]|&&)")),
        # HOSTNAME — Tier-B. Two cases:
        #   (1) 3-part FQDN host.tld.tld (pre-existing).
        #   (2) 2-part host on an internal-network TLD (.lokal/.local/
        #       .internal/.invalid) — apf-6ql. The 2-part TLD set is kept
        #       to non-public, non-filename suffixes so a sentence-final
        #       `notes.txt` is not mistaken for a host.
        ("HOSTNAME", re.compile(
            r"\b[a-z][\w-]*\.[\w.-]+\.(?:com|de|org|internal|lokal|local|invalid)\b")),
        ("HOSTNAME", re.compile(
            r"\b[a-z][\w-]*\.(?:lokal|local|internal|invalid)\b")),
    ]

    # Patterns whose match-group structure differs: which group holds the
    # span we want to flag. Default: whole match. For KEY=VALUE patterns
    # we flag the VALUE portion (the secret), not the key name.
    VALUE_GROUP_INDEX = {
        # (label, pattern_idx): group_number
        # For KEY=VALUE: group 3 is the value (group 1=key, 2=quote).
    }

    def warmup(self) -> None:
        return

    def detect(self, text: str) -> list[Span]:
        seen: list[Span] = []
        used: list[tuple[int, int]] = []
        for label, rx in self.PATTERNS:
            for m in rx.finditer(text):
                context_key: str | None = None
                # KEY=VALUE patterns: capture group 3 is the value (the
                # secret), groups 1 and 2 are key + optional quote. Capture
                # the KEY name so the resolver can look up env/keychain.
                if m.groups() and m.lastindex == 3:
                    start = m.start(3)
                    end = m.end(3)
                    context_key = m.group(1)
                elif m.groups() and m.lastindex == 1:
                    # PATH and similar single-group patterns
                    start = m.start(1)
                    end = m.end(1)
                else:
                    start, end = m.start(), m.end()
                if end <= start:
                    continue
                if any(s < end and e > start for s, e in used):
                    continue
                used.append((start, end))
                seen.append(Span(start=start, end=end, label=label,
                                 tier=LABEL_TIER[label],
                                 context_key=context_key))
        seen.sort(key=lambda s: s.start)
        return seen


ADAPTERS: dict[str, type] = {
    "regex": RegexBaseline,
}
