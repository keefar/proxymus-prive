"""Recording fake OpenAI Chat Completions upstream (apf-pk7).

Stands in for oMLX in the tool-call test rig. Two jobs:

1. Records every request body apf forwards to it. The apf -> upstream
   wire is otherwise invisible; recording it is the only way to *prove*
   that masked tokens (not original PII) crossed the boundary.
2. Returns a script-controlled, deterministic response — so the rig
   never depends on a real model deciding to emit a tool call.

Response logic is set per-request by the rig via the in-process
`Recorder` handle:
  - set_text(...)      -> plain assistant message
  - set_toolcall(...)  -> assistant message with a tool_calls block;
                          template string values may embed {tok0},{tok1},
                          ... (Nth numbered <REF_N>, ordered by index) and
                          {REF} (the bare Tier-C secret token). The tokens
                          are pulled from whatever apf actually forwarded,
                          so the canned tool call echoes the real masked
                          values — exactly what a tool-calling model would.

Run standalone (for manual poking):
    python -m scripts.recording_upstream --port 8099
"""
from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_TOKEN_RE = re.compile(r"<REF(?:_\d+)?>")


class Recorder:
    """Recorded requests + the rig-controlled next response."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        self._next: dict = {"kind": "text", "text": "ok"}

    # -- response control (called by the rig, in-process) ----------------
    def set_text(self, text: str = "ok") -> None:
        with self._lock:
            self._next = {"kind": "text", "text": text}

    def set_toolcall(self, name: str, args_template: dict) -> None:
        with self._lock:
            self._next = {"kind": "toolcall", "name": name,
                          "args_template": args_template}

    # -- recording -------------------------------------------------------
    def record(self, body: dict) -> dict:
        with self._lock:
            self.requests.append(body)
            return dict(self._next)

    @property
    def last(self) -> dict:
        return self.requests[-1]

    def last_blob(self) -> str:
        """Whole most-recent request serialised — for substring leak checks."""
        return json.dumps(self.requests[-1], ensure_ascii=False)


def _tokens(body: dict) -> tuple[list[str], bool]:
    """(numbered <REF_N> tokens ordered by N, bare <REF> present?)."""
    found = _TOKEN_RE.findall(json.dumps(body, ensure_ascii=False))
    numbered = sorted(
        {t for t in found if t != "<REF>"},
        key=lambda t: int(re.search(r"\d+", t).group()),
    )
    return numbered, ("<REF>" in found)


def _fill(template, numbered: list[str], has_ref: bool):
    if isinstance(template, str):
        out = template
        for i, tok in enumerate(numbered):
            out = out.replace("{tok%d}" % i, tok)
        out = out.replace("{REF}", "<REF>")
        return out
    if isinstance(template, dict):
        return {k: _fill(v, numbered, has_ref) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, numbered, has_ref) for v in template]
    return template


def build_response(spec: dict, body: dict) -> dict:
    """Turn a response spec + the incoming request into an OpenAI
    chat.completion response dict."""
    numbered, has_ref = _tokens(body)
    model = body.get("model", "recording-upstream")
    if spec.get("kind") == "toolcall":
        args = _fill(spec["args_template"], numbered, has_ref)
        # Guarantee every numbered token apf produced is echoed into the
        # tool call, regardless of how the per-scenario template maps
        # them — so resolution of *every* token is exercised, not just
        # the ones a template happened to place by index.
        if isinstance(args, dict) and numbered:
            args["context_refs"] = " ".join(numbered)
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_rec_1",
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }],
        }
        finish = "tool_calls"
    else:
        message = {"role": "assistant", "content": spec.get("text", "ok")}
        finish = "stop"
    return {
        "id": "chatcmpl-rec",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": message,
                     "finish_reason": finish}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                  "total_tokens": 0},
    }


def make_server(port: int, recorder: Recorder) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):  # silence per-request logging
            pass

        def _send(self, code: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") == "/v1/models":
                self._send(200, {"object": "list", "data": [
                    {"id": "recording-upstream", "object": "model"}]})
            else:
                self._send(404, {"error": {"message": "not found"}})

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                self._send(400, {"error": {"message": "bad json"}})
                return
            spec = recorder.record(body)
            self._send(200, build_response(spec, body))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve_in_thread(port: int):
    """Start the recorder on a daemon thread. Returns (recorder, server)."""
    recorder = Recorder()
    server = make_server(port, recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return recorder, server


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    args = ap.parse_args()
    recorder, server = serve_in_thread(args.port)
    print(f"recording upstream on http://127.0.0.1:{args.port} "
          f"(Ctrl-C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
        print(f"\n{len(recorder.requests)} requests recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
