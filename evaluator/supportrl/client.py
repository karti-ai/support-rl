"""A minimal OpenAI-compatible chat client on the standard library.

Works with vLLM, SGLang, llama.cpp server, Ollama, OpenAI, OpenRouter, Prime Inference and
anything else that serves ``POST {base_url}/chat/completions``. No SDK dependency.

Thinking models: ``thinking=False`` sends ``chat_template_kwargs: {enable_thinking: false}``
at the top level of the request body, which is where vLLM/SGLang (and servers built on them)
read it. Verify it took effect: responses report ``reasoning_tokens`` and the run summary
counts turns that reasoned anyway.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class EndpointError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    usage: dict = field(default_factory=dict)


@dataclass
class ChatClient:
    base_url: str
    model: str
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    thinking: bool | None = False  # None: send nothing, let the server decide
    extra_body: dict = field(default_factory=dict)
    timeout: float = 120.0
    retries: int = 3

    @classmethod
    def from_args(cls, base_url: str, model: str, api_key_env: str | None = None, **kw) -> ChatClient:
        key = os.environ.get(api_key_env) if api_key_env else None
        if api_key_env and not key:
            raise EndpointError(f"environment variable {api_key_env} is not set")
        return cls(base_url=base_url.rstrip("/"), model=model, api_key=key, **kw)

    def body(self, messages: list[dict]) -> dict:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "n": 1,
        }
        if self.thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": bool(self.thinking)}
        body.update(self.extra_body)
        return body

    def chat(self, messages: list[dict]) -> Completion:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(self.body(messages)).encode(),
            headers={"Content-Type": "application/json"}
            | ({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            method="POST",
        )
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code < 500 and exc.code != 429:
                    raise EndpointError(
                        f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}"
                    ) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = exc
            if attempt < self.retries:
                time.sleep(min(2**attempt, 20))
        else:
            raise EndpointError(f"endpoint failed after {self.retries + 1} attempts: {last}")
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        details = usage.get("completion_tokens_details") or {}
        return Completion(
            text=msg.get("content") or "",
            usage={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": usage.get("reasoning_tokens") or details.get("reasoning_tokens") or 0,
                "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else 0,
                "finish_reason": choice.get("finish_reason"),
            },
        )
