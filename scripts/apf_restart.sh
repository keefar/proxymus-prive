#!/usr/bin/env bash
# Restart the apf proxy, wired to the local oMLX backend.
#
# The default `python -m apf.proxy` leaves the OpenAI path with no
# upstream. For the Hermes/oMLX loopback rig we want apf to forward
# /v1/chat/completions to oMLX and to filter that traffic. This script
# stops any running instance and relaunches with the right env.
#
# Usage:
#   scripts/apf_restart.sh           # restart, wired to oMLX
#   scripts/apf_restart.sh stop      # stop, don't relaunch
#   scripts/apf_restart.sh status    # show health + pid
#
# Env overrides:
#   APF_OPENAI_UPSTREAM  (default http://127.0.0.1:8000 — oMLX)
#   APF_PORT             (default 8765)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LOG=/tmp/claude/apf.log
PIDFILE=/tmp/claude/apf.pid
PORT="${APF_PORT:-8765}"
OPENAI_UPSTREAM="${APF_OPENAI_UPSTREAM:-http://127.0.0.1:8000}"

stop_apf() {
  pkill -f 'apf\.proxy' 2>/dev/null || true
  for _ in $(seq 1 30); do
    lsof -ti tcp:"$PORT" >/dev/null 2>&1 || return 0
    sleep 0.2
  done
  echo "warning: port $PORT still bound after kill" >&2
}

show_status() {
  if curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    echo "apf: UP on :$PORT  (pid $(cat "$PIDFILE" 2>/dev/null || echo '?'))"
    curl -s "http://127.0.0.1:$PORT/healthz"; echo
  else
    echo "apf: DOWN on :$PORT"
  fi
}

case "${1:-restart}" in
  stop)
    stop_apf
    echo "apf stopped."
    exit 0
    ;;
  status)
    show_status
    exit 0
    ;;
  restart) ;;
  *)
    echo "usage: $0 [restart|stop|status]" >&2
    exit 2
    ;;
esac

stop_apf
mkdir -p /tmp/claude
cd "$REPO"

APF_OPENAI_UPSTREAM="$OPENAI_UPSTREAM" APF_PORT="$PORT" \
  nohup "$PY" -m apf.proxy >"$LOG" 2>&1 &
APF_PID=$!
disown
echo "$APF_PID" >"$PIDFILE"

for _ in $(seq 1 60); do
  if curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    echo "apf up on :$PORT (pid $APF_PID) — OpenAI upstream: $OPENAI_UPSTREAM"
    curl -s "http://127.0.0.1:$PORT/healthz"; echo
    exit 0
  fi
  sleep 0.25
done

echo "apf did NOT come up within 15s. Last log lines:" >&2
tail -25 "$LOG" >&2
exit 1
