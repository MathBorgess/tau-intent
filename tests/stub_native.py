"""Local stubs of the three native protocols the frontier strand speaks.

Same idea as ``stub_openai.py``: a ``ThreadingHTTPServer`` on 127.0.0.1, no live
model, no external network, every request body kept so a test asserts on what
went over the wire. One server speaks one protocol, the way a subscription proxy
from ``mathai-harness`` does:

* ``anthropic-messages``     ``POST /v1/messages``                    (Anthropic SSE)
* ``openai-codex-responses`` ``POST /codex/responses``               (Responses SSE)
* ``google-generative-ai``   ``POST /v1beta/models/<m>:streamGenerateContent?alt=sse``

Turns are written with the helpers of ``stub_openai`` (``text``, ``tools``, ``call``).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

Turn = dict[str, Any]

ANTHROPIC = "anthropic-messages"
CODEX = "openai-codex-responses"
GOOGLE = "google-generative-ai"


def _args(call: dict[str, Any]) -> dict[str, Any]:
    raw = call["arguments"]
    return json.loads(raw) if isinstance(raw, str) else raw


def anthropic_events(turn: Turn, index: int, usage: bool) -> list[dict[str, Any]]:
    calls = turn.get("tool_calls") or []
    out: list[dict[str, Any]] = [{"type": "message_start", "message": {
        "id": f"msg_{index}", "type": "message", "role": "assistant", "model": "stub", "content": [],
        "stop_reason": None, "usage": ({"input_tokens": 100 + index, "output_tokens": 1,
                                        "cache_read_input_tokens": 20, "cache_creation_input_tokens": 5}
                                       if usage else {"input_tokens": 0, "output_tokens": 0})}}]
    block = 0
    if turn.get("content"):
        out += [{"type": "content_block_start", "index": block, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": block,
                 "delta": {"type": "text_delta", "text": turn["content"]}},
                {"type": "content_block_stop", "index": block}]
        block += 1
    for n, call in enumerate(calls):
        out += [{"type": "content_block_start", "index": block, "content_block": {
                    "type": "tool_use", "id": call.get("id") or f"toolu_{index}_{n}", "name": call["name"],
                    "input": {}}},
                {"type": "content_block_delta", "index": block,
                 "delta": {"type": "input_json_delta", "partial_json": json.dumps(_args(call))}},
                {"type": "content_block_stop", "index": block}]
        block += 1
    out += [{"type": "message_delta", "delta": {"stop_reason": "tool_use" if calls else "end_turn",
                                               "stop_sequence": None},
             "usage": {"output_tokens": 7 if usage else 0}},
            {"type": "message_stop"}]
    return out


def codex_events(turn: Turn, index: int, usage: bool) -> list[dict[str, Any]]:
    calls = turn.get("tool_calls") or []
    out: list[dict[str, Any]] = [{"type": "response.created", "response": {"id": f"resp_{index}"}}]
    output: list[dict[str, Any]] = []
    if turn.get("content"):
        out.append({"type": "response.output_text.delta", "delta": turn["content"]})
        output.append({"type": "message", "role": "assistant",
                       "content": [{"type": "output_text", "text": turn["content"]}]})
    for n, call in enumerate(calls):
        item = {"type": "function_call", "id": f"fc_{index}_{n}", "call_id": call.get("id") or f"call_{index}_{n}",
                "name": call["name"], "arguments": json.dumps(_args(call)), "status": "completed"}
        out += [{"type": "response.output_item.added", "output_index": n, "item": {**item, "arguments": ""}},
                {"type": "response.function_call_arguments.delta", "output_index": n, "item_id": item["id"],
                 "delta": item["arguments"]},
                {"type": "response.output_item.done", "output_index": n, "item": item}]
        output.append(item)
    response: dict[str, Any] = {"id": f"resp_{index}", "status": "completed", "output": output}
    if usage:
        response["usage"] = {"input_tokens": 200 + index, "input_tokens_details": {"cached_tokens": 50},
                             "output_tokens": 9, "output_tokens_details": {"reasoning_tokens": 4},
                             "total_tokens": 209 + index}
    out.append({"type": "response.completed", "response": response})
    return out


def google_chunks(turn: Turn, index: int, usage: bool, model_version: str | None) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    if turn.get("content"):
        parts.append({"text": turn["content"]})
    for call in turn.get("tool_calls") or []:
        parts.append({"functionCall": {"name": call["name"], "args": _args(call)},
                      "thoughtSignature": f"sig-{index}"})
    first: dict[str, Any] = {"candidates": [{"content": {"role": "model", "parts": parts[:1]}, "index": 0}]}
    last: dict[str, Any] = {"candidates": [{"content": {"role": "model", "parts": parts[1:]},
                                            "finishReason": "STOP", "index": 0}]}
    if usage:
        last["usageMetadata"] = {"promptTokenCount": 300 + index, "cachedContentTokenCount": 40,
                                 "candidatesTokenCount": 11, "thoughtsTokenCount": 6,
                                 "totalTokenCount": 317 + index}
        first["usageMetadata"] = {"promptTokenCount": 300 + index, "candidatesTokenCount": 1,
                                  "totalTokenCount": 301 + index}
    if model_version:
        first["modelVersion"] = last["modelVersion"] = model_version
    return [first, last]


class NativeStub:
    """``NativeStub(api, script)`` is a context manager; ``.url`` is what ``--provider-url`` takes."""

    def __init__(self, api: str, script: Callable[[int, dict[str, Any]], Turn] | list[Turn], *,
                 usage: bool = True, status: Callable[[int], int] | None = None,
                 model_version: str | None = None, stream_error: Callable[[int], bool] | None = None) -> None:
        self.api = api
        self.script = script if callable(script) else (lambda i, _b, _s=list(script): _s[min(i, len(_s) - 1)])
        self.usage = usage
        self.status = status
        self.model_version = model_version
        #: Anthropic only: answer 200 and fail inside the stream (``overloaded_error``).
        self.stream_error = stream_error
        self.requests: list[dict[str, Any]] = []
        self.paths: list[str] = []
        self.headers: list[dict[str, str]] = []
        self._lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                with stub._lock:
                    index = len(stub.requests)
                    stub.requests.append(body)
                    stub.paths.append(self.path)
                    stub.headers.append({k.lower(): v for k, v in self.headers.items()})
                code = stub.status(index) if stub.status else 200
                if code != 200:
                    payload = json.dumps({"error": {"type": "stub", "message": f"stub status {code}"}}).encode()
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                turn = stub.script(index, body)
                if stub.api == ANTHROPIC and stub.stream_error and stub.stream_error(index):
                    error = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
                    frames = [f"event: error\ndata: {json.dumps(error)}\n\n"]
                elif stub.api == ANTHROPIC:
                    frames = [f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in
                              anthropic_events(turn, index, stub.usage)]
                elif stub.api == CODEX:
                    frames = [f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in
                              codex_events(turn, index, stub.usage)]
                else:
                    frames = [f"data: {json.dumps(c)}\r\n\r\n" for c in
                              google_chunks(turn, index, stub.usage, stub.model_version)]
                payload = "".join(frames).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def model_paths(self) -> list[str]:
        return [urlparse(p).path for p in self.paths]

    def __enter__(self) -> "NativeStub":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
