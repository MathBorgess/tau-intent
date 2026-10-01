"""A local OpenAI-compatible `/v1/chat/completions` stub, used inside the tests.

No live model, no external network: a ``ThreadingHTTPServer`` on 127.0.0.1 that
answers the way Ollama / LM Studio / llama.cpp do on their ``/v1`` endpoint,
including the shapes tau's parser has to digest (tool-call deltas, the final
``usage`` chunk requested with ``stream_options.include_usage``).

The stub keeps every request body it received, so a test can assert on what
went over the wire (AGENTS.md rule 8) instead of on a config object.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

Turn = dict[str, Any]
#: ``script(index, body)`` returns the turn for the ``index``-th chat request.
Script = Callable[[int, dict[str, Any]], Turn]


def text(content: str, **extra: Any) -> Turn:
    return {"content": content, **extra}


def call(name: str, arguments: dict[str, Any] | str, call_id: str | None = None) -> dict[str, Any]:
    return {"name": name, "arguments": arguments, "id": call_id}


def tools(*calls: dict[str, Any], content: str = "", **extra: Any) -> Turn:
    return {"content": content, "tool_calls": list(calls), **extra}


def _sse(obj: Any) -> bytes:
    data = obj if isinstance(obj, str) else json.dumps(obj)
    return f"data: {data}\n\n".encode()


class StubServer:
    """``StubServer(script)`` is a context manager; ``.url`` is the ``/v1`` base."""

    def __init__(self, script: Script | list[Turn], *, usage: bool = True,
                 split_args: bool = False, status: Callable[[int], int] | None = None,
                 models: list[dict[str, Any]] | None = None) -> None:
        self.script = script if callable(script) else (lambda i, _b, _s=list(script): _s[min(i, len(_s) - 1)])
        self.usage = usage
        self.split_args = split_args
        self.status = status
        self.models = models
        self.requests: list[dict[str, Any]] = []
        self.paths: list[str] = []
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silence
                pass

            def do_GET(self) -> None:  # noqa: N802
                stub.paths.append(self.path)
                if self.path.endswith("/api/tags") and stub.models is not None:
                    body = json.dumps({"models": stub.models}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                body = json.loads(raw or b"{}")
                with stub._lock:
                    index = len(stub.requests)
                    stub.requests.append(body)
                    stub.paths.append(self.path)
                code = stub.status(index) if stub.status else 200
                if code != 200:
                    payload = json.dumps({"error": {"message": f"stub status {code}"}}).encode()
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                turn = stub.script(index, body)
                if turn.get("delay"):
                    time.sleep(turn["delay"])
                if body.get("stream"):
                    chunks = stub._stream_chunks(turn, body)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    for chunk in chunks:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    self.close_connection = True
                else:
                    payload = json.dumps(stub._json_response(turn)).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, request: Any, client_address: Any) -> None:
                pass  # the client hanging up (deadline tests) is not a test failure

        self.httpd = QuietServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True)

    # ------------------------------------------------------------------ shapes
    def _usage_of(self, turn: Turn) -> dict[str, Any] | None:
        if "usage" in turn:
            return turn["usage"]
        if not self.usage:
            return None
        return {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}

    def _stream_chunks(self, turn: Turn, body: dict[str, Any]) -> list[bytes]:
        base = {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 1,
                "model": body.get("model", "stub")}
        chunks: list[bytes] = []
        content = turn.get("content") or ""
        calls = turn.get("tool_calls") or []
        chunks.append(_sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""},
                                                  "finish_reason": None}]}))
        if content:
            for piece in (content[:len(content) // 2], content[len(content) // 2:]):
                if piece:
                    chunks.append(_sse({**base, "choices": [{"index": 0, "delta": {"content": piece},
                                                              "finish_reason": None}]}))
        for position, item in enumerate(calls):
            arguments = item["arguments"]
            arguments = arguments if isinstance(arguments, str) else json.dumps(arguments)
            ident = item.get("id") or f"call_{position}"
            if self.split_args and len(arguments) > 4:
                cut = len(arguments) // 2
                parts = [arguments[:cut], arguments[cut:]]
            else:
                parts = [arguments]
            for n, part in enumerate(parts):
                fn: dict[str, Any] = {"arguments": part}
                head: dict[str, Any] = {"index": position}
                if n == 0:
                    head.update({"id": ident, "type": "function"})
                    fn["name"] = item["name"]
                head["function"] = fn
                chunks.append(_sse({**base, "choices": [{"index": 0, "delta": {"tool_calls": [head]},
                                                          "finish_reason": None}]}))
        finish = turn.get("finish_reason") or ("tool_calls" if calls else "stop")
        chunks.append(_sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}))
        usage = self._usage_of(turn)
        wants = (body.get("stream_options") or {}).get("include_usage")
        if usage is not None and wants:
            chunks.append(_sse({**base, "choices": [], "usage": usage}))
        chunks.append(_sse("[DONE]"))
        return chunks

    def _json_response(self, turn: Turn) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": "chatcmpl-stub", "object": "chat.completion", "created": 1, "model": "stub",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": turn.get("content") or ""},
                         "finish_reason": "stop"}],
        }
        usage = self._usage_of(turn)
        if usage is not None:
            out["usage"] = usage
        return out

    # ----------------------------------------------------------------- control
    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    @property
    def origin(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def chat_requests(self) -> list[dict[str, Any]]:
        return list(self.requests)

    def __enter__(self) -> "StubServer":
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
