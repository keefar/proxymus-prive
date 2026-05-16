# Operational fixtures — Tier B PII

Source for `fixtures/operational.jsonl`. Run `python tools/build_fixtures.py` to regenerate.
Synthetic paths/hostnames/IPs only; see `docs/MODELS.md` § "Synthetic-data rules".

---

## id: en-bash-01 lang=en bucket=operational notes="basic bash session, user-id-bearing path"

$ cd ⟦PATH|/Users/alice/projects/onboarding-rewrite⟧
$ ls -la
total 64
drwxr-xr-x  10 alice  staff   320 May 12 14:02 .
drwxr-xr-x  18 alice  staff   576 May 10 09:11 ..
-rw-r--r--   1 alice  staff  1284 May 12 13:58 ⟦FILENAME|alice-handoff.md⟧
$ grep -r TODO ⟦PATH|src/⟧

## id: en-bash-02 lang=en bucket=operational notes="ssh + hostname"

$ ssh ⟦PERSON|alice⟧@⟦HOSTNAME|build-runner-03.internal.example.com⟧
Last login: Mon May 12 09:14:22 2026 from ⟦IP|10.0.4.118⟧
[alice@build-runner-03 ~]$ tail -f ⟦PATH|/var/log/buildbot/main.log⟧

## id: de-bash-01 lang=de bucket=operational notes="ssh session, mixed German+command output"

⟦PATH|~/projekte/datenpipeline⟧ $ scp report.csv ⟦PERSON|chris⟧@⟦HOSTNAME|backup-nas.lokal⟧:⟦PATH|/srv/backups/2026-05/⟧
Datei wird kopiert (4.2 MB) ...
abgeschlossen. Verbinde nun mit ⟦HOSTNAME|monitor-02.lokal⟧ (⟦IP|192.168.1.42⟧) zur Kontrolle.

## id: en-config-01 lang=en bucket=operational notes="ssh config snippet"

Host ⟦HOSTNAME|prod-db⟧
    HostName ⟦HOSTNAME|db-primary.internal.example.com⟧
    User ⟦PERSON|alice⟧
    Port 22
    IdentityFile ⟦PATH|~/.ssh/id_ed25519_prod⟧

Host ⟦HOSTNAME|jumpbox⟧
    HostName ⟦IP|203.0.113.47⟧
    User ⟦PERSON|alice⟧

## id: en-config-02 lang=en bucket=operational notes="hosts file"

127.0.0.1   localhost
⟦IP|10.0.4.21⟧    ⟦HOSTNAME|gitlab.internal.example.com⟧
⟦IP|10.0.4.22⟧    ⟦HOSTNAME|registry.internal.example.com⟧
⟦IP|192.168.1.10⟧   ⟦HOSTNAME|printer.lokal⟧

## id: en-log-01 lang=en bucket=operational notes="nginx-style access log line"

⟦IP|198.51.100.77⟧ - ⟦PERSON|alice⟧ [12/May/2026:14:02:11 +0000] "GET ⟦URL_LOCAL|/api/v2/users/me⟧ HTTP/1.1" 200 1842 "-" "curl/8.4.0"

## id: en-log-02 lang=en bucket=operational notes="error log with stack-frame paths"

ERROR 2026-05-12T14:02:11Z service=ingest worker=⟦HOSTNAME|ingest-worker-04⟧
  File "⟦PATH|/opt/app/lib/parser.py⟧", line 312, in parse_batch
    raise ValueError(f"unexpected schema in {⟦PATH|/data/raw/2026-05-12/batch-0007.json⟧}")

## id: en-code-01 lang=en bucket=operational notes="hardcoded host + path in source"

```python
DEFAULT_CACHE_DIR = ⟦PATH|"/Users/alice/.cache/myproj"⟧
DB_HOST = ⟦HOSTNAME|"db-primary.internal.example.com"⟧
ADMIN_PORTAL = ⟦URL_LOCAL|"https://admin.internal.example.com/login"⟧
```

## id: de-code-01 lang=de bucket=operational notes="path + IP in code comment"

```python
# Backup-Server im LAN: ⟦HOSTNAME|backup-nas.lokal⟧ (⟦IP|192.168.1.42⟧)
# Dump-Verzeichnis: ⟦PATH|/srv/backups/postgres/⟧
def backup_target() -> str:
    return ⟦PATH|"/srv/backups/postgres/daily"⟧
```

## id: en-shell-01 lang=en bucket=operational notes="env vars hinting at user identity"

```bash
export HOME=⟦PATH|/Users/alice⟧
export ICLOUD_DIR=⟦PATH|/Users/alice/Library/Mobile Documents/com~apple~CloudDocs⟧
export EDITOR=vim
export GIT_AUTHOR_EMAIL=⟦EMAIL|alice@example.com⟧
```
