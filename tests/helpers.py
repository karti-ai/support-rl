"""Shared test helpers: gold responses and a mock OpenAI-compatible server."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from supportrl.data import first_user_message, load_split
from supportrl.pack import Pack

ROOT = Path(__file__).resolve().parents[1]
ZOOMBERG = ROOT / "examples" / "zoomberg"

ASK_SENTENCES = {
    # zoomberg
    "identity_verification": "Could you please give me the one-time passcode we just sent so I can verify your identity?",
    "order_id": "Could you share the order ID?",
    "rejection_reason": "What reason did the other firm give for the rejection?",
    "lot_identifiers": "Which lots are affected? Please send the lot identifiers.",
    "executor_documentation": "Please send the letters testamentary when you have them.",
    "bank_link_last_four": "Could you also give me the last four digits of your primary bank link?",
    # starter template
    "damage_photos": "Could you please send photos of the packaging?",
}
NEUTRAL = "Thanks for letting us know. I have recorded this for the right team."


def gold_reply(target: dict) -> str:
    return " ".join([NEUTRAL, *(ASK_SENTENCES[k] for k in target.get("must_ask") or [])])


def gold_obj(target: dict) -> dict:
    return {
        "reply": gold_reply(target),
        "action": {
            "type": target["action_type"],
            "queue": target.get("queue"),
            "escalate_to": target.get("escalate_to"),
            "priority": target.get("priority"),
            "flags": list(target.get("required_flags") or []),
            "policy_ids": list(target.get("must_cite") or []),
        },
    }


def all_decisions(pack: Pack, split: str):
    for ep in load_split(pack, split, allow_locked=True):
        seen = []
        for turn in ep["turns"]:
            if turn["role"] == "customer":
                seen.append(turn["text"])
            else:
                dp = turn["decision_point"]
                yield ep, dp, ep["decisions"][dp], list(seen)


class MockServer:
    """OpenAI-compatible /chat/completions that answers every episode with its gold response.

    It finds the episode from the first user message and the decision from the number of
    assistant turns so far. It records every request body so tests can check what was sent.
    """

    def __init__(self, pack: Pack, splits=("train", "dev", "test"), mode: str = "gold"):
        self.requests: list[dict] = []
        self.by_opening = {}
        for s in splits:
            for ep in load_split(pack, s, allow_locked=True):
                self.by_opening[first_user_message(pack, ep)] = ep
        self.mode = mode
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                msgs = body["messages"]
                users = [m for m in msgs if m["role"] == "user"]
                ep = outer.by_opening.get(users[0]["content"]) if users else None
                k = sum(m["role"] == "assistant" for m in msgs)
                if outer.mode == "gold" and ep is not None:
                    content = json.dumps(gold_obj(ep["decisions"][f"d{k + 1}"]))
                else:
                    content = "Sure! Here is my answer."  # fails the format gate
                resp = {
                    "id": "mock",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body.get("model"),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": content},
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
                }
                data = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


class ScriptServer:
    """OpenAI-compatible endpoint that returns canned contents in order (then repeats the last)."""

    def __init__(self, contents: list[str]):
        self.contents, self.i, self.requests = contents, 0, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                outer.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                text = outer.contents[min(outer.i, len(outer.contents) - 1)]
                outer.i += 1
                data = json.dumps(
                    {
                        "choices": [
                            {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                        ],
                        "usage": {},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
