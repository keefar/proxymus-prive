# Live-Integration Guide

Wie der PoC-Proxy mit Claude Code (oder einem anderen Anthropic-API-Client)
verbunden wird. Nach diesem Setup laufen alle Anfragen durch den Filter:
PII wird vor dem Versand zur Cloud tokenisiert, in der Antwort wieder
zurückgesetzt, Tier-C-Secrets bleiben dem LLM gegenüber opak und werden
am Tool-Call-Boundary aus dem lokalen Env / Vault wieder eingesetzt.

## Voraussetzungen

- Apple Silicon Mac (für MLX-Modelle nicht zwingend — wir benutzen
  PyTorch+MPS für GLiNER+Presidio).
- Python venv eingerichtet (`.venv/`).
- Ein Authentifizierungs-Mechanismus für die Cloud-API:
  - **API-Key-Modus** (klassisch): Setze `ANTHROPIC_API_KEY` im Client.
    Der Proxy reicht den `x-api-key`-Header transparent weiter.
  - **OAuth-Modus** (Pro Max / Claude.ai-Login): Claude Code nutzt einen
    OAuth-Token im `Authorization`-Header. Der Proxy reicht auch das durch.
    Hinweis: nicht alle Clients respektieren `ANTHROPIC_BASE_URL`, wenn
    sie OAuth-flow durchlaufen — bei Bedarf testen.

## Proxy starten

```bash
# Standard: port 8765, upstream api.anthropic.com
.venv/bin/python -m apf.proxy

# Eigener Port / Upstream zum Testen
APF_PORT=9000 APF_UPSTREAM_BASE=http://localhost:8080 \
    .venv/bin/python -m apf.proxy
```

Beim ersten Start lädt der Proxy alle Detector-Modelle (~10-15 s
Aufwärmphase) und meldet dann "Application startup complete".

Healthcheck:

```bash
curl http://127.0.0.1:8765/healthz
# {"status":"ok","detector":"ensemble-max","active_sessions":0,
#  "upstream":"https://api.anthropic.com"}
```

## Claude Code konfigurieren

```bash
# Terminal A: Proxy läuft auf 127.0.0.1:8765
# Terminal B: Claude Code mit dem Proxy als API-Endpoint starten

export ANTHROPIC_BASE_URL=http://127.0.0.1:8765
export ANTHROPIC_API_KEY=<dein-key>   # falls API-Key-Modus
claude
```

Wenn alles korrekt verbunden ist, sollte Claude Code normal antworten,
aber:

- Alle ausgehenden Texte mit erkannter PII werden tokenisiert (sichtbar
  in den Proxy-Logs, falls `--log-level debug`).
- Der `x-apf-session`-Header wird auf jede Antwort gesetzt — Claude Code
  ignoriert ihn momentan, aber die Vault-State bleibt sauber per Session.
- Tool-Use-Args werden bei der Rückgabe an den Client aus dem Vault
  rückaufgelöst — Claude Code's Tool-Executor sieht echte Werte.

## Smoke-Helper: manueller End-to-End-Check

`apf/manual_smoke.py` startet den Proxy, schickt eine Test-Anfrage mit
PII-haltigem Inhalt, und meldet, ob die Tokenisierung sichtbar wurde
beim Upstream. Setze einen Mock-Upstream oder zeige es kurz gegen einen
echten Anthropic-Endpoint.

```bash
# Gegen Mock-Upstream (default):
.venv/bin/python -m apf.manual_smoke

# Gegen echte Anthropic-API (braucht API-Key):
ANTHROPIC_API_KEY=sk-ant-... \
APF_UPSTREAM_BASE=https://api.anthropic.com \
    .venv/bin/python -m apf.manual_smoke --live
```

## Bekannte Constraints

- **Auth-Pass-Through:** Der Proxy speichert keine Credentials. Was der
  Client schickt, geht weiter. Wenn dein Client per OAuth läuft, klappt
  das automatisch — vorausgesetzt der Client respektiert
  `ANTHROPIC_BASE_URL`.

- **OAuth-Refresh:** Wenn der Client OAuth-Token vor dem Schicken refresht
  (z.B. Claude Code's interner Auth-Flow), passiert das *vor* dem Proxy.
  Der Proxy sieht nur den finalen Token im Authorization-Header.

- **Streaming:** Voll unterstützt seit `apf-jfi`. Text-Tokens werden über
  Chunk-Grenzen hinweg gepuffert; Tool-Use-Input-JSON wird akkumuliert
  und am `content_block_stop`-Event in einem Schwung resolvt.

- **Pro-Max-Subscription:** Wenn du Claude Code per Pro-Max-Login nutzt
  (kein expliziter API-Key), nutzt der Client wahrscheinlich OAuth. Ob
  das mit `ANTHROPIC_BASE_URL` zusammenarbeitet, hängt vom genauen
  Claude-Code-Build ab. Testen.

- **Secret-Store:** Default ist `EnvSecretStore` + `VaultFallbackStore`.
  Für Production-Härte: `APF_VAULT_FALLBACK=0` setzen — dann werden
  unbekannte Secrets bei Tool-Use nicht aus dem Vault aufgelöst sondern
  bleiben ungesetzt (Tool muss explizit fehlschlagen statt einen Wert
  einzusetzen den der Vault gesehen hat).

## Troubleshooting

- **"Connection refused" beim Client:** Proxy läuft nicht, oder Port
  stimmt nicht. `curl http://127.0.0.1:8765/healthz` testen.
- **"401 Unauthorized" vom Upstream:** API-Key fehlt oder ist falsch.
  Der Proxy selbst hat keinen Key, er reicht den Client-Header durch.
- **PII kommt durch ohne Tokenisierung:** Detector hat sie verfehlt.
  `GET /v1/sessions/{id}/uncertain` zeigt was als low-confidence
  markiert wurde. Für eindeutige Misses: in `docs/MODEL-EVALUATION.md`
  schauen, ggf. Tier-C-Regex / GLiNER-Labels erweitern.
- **Tool-Use schlägt fehl, weil Secrets fehlen:** Env-Var-Name muss mit
  dem Pattern matchen, das der Detector erkannte (`OPENAI_API_KEY`,
  `STRIPE_KEY`, etc). Sieht der Detector einen anderen KEY-Namen, brauchst
  du `EnvSecretStore(aliases={"DETECTED_NAME": "REAL_ENV_VAR"})`.

## Pro-Max-Konkrete Anweisung

Wenn du `claude.ai/code` via Pro-Max benutzt:

1. Pro-Max-Login ist OAuth-basiert, kein API-Key.
2. Auf der CLI sollte das vom `ANTHROPIC_BASE_URL` trotzdem akzeptiert
   werden — Claude Code wandelt OAuth in `Authorization: Bearer ...`
   um, was unser Proxy durchreicht.
3. Falls Claude Code beim Setzen von `ANTHROPIC_BASE_URL` auf eine
   andere URL erzwingen will dass die Cloud-Login-Domain übereinstimmt:
   ggf. Issue beim Claude-Code-Projekt aufmachen oder API-Key-Modus
   versuchen.
