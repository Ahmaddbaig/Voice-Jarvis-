"""Unified LLM dispatcher — Brain.ask() with two private provider methods.

D-15: No ABC, no Protocol, no Strategy. Two private functions behind one public API.
D-16: OpenAI uses Chat Completions (not Responses API). previous_response_id retired.
D-17: BrainResponse dataclass normalizes both providers.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import requests
from openai import OpenAI

from jarvis.core.config import Config


@dataclass
class ToolCall:
    id: str         # OpenAI gives real IDs; for Ollama, generate a UUID
    name: str
    arguments: dict  # Always a dict (parse OpenAI's JSON string)


@dataclass
class BrainResponse:
    text: str                         # May be "" if tool_calls present
    tool_calls: list[ToolCall] | None  # None means "no tools called"
    usage: dict | None                # {"prompt_tokens": N, "completion_tokens": N}


class Brain:
    """Unified LLM dispatch. Blocking — call from run_in_executor.

    BRAIN-01: Single ask() method for both providers.
    BRAIN-02: Ollama num_ctx pinned explicitly (16384 with tools, 4096 without).
    BRAIN-03: Token usage logged, warning at 80% num_ctx.
    BRAIN-08: OpenAI uses Chat Completions API.
    """

    def __init__(self, cfg: Config, client: OpenAI | None):
        self.cfg = cfg
        self.client = client

    def ask(self, messages: list[dict], tools: list[dict] | None = None) -> BrainResponse:
        """Unified LLM dispatch. Blocking — call from run_in_executor."""
        if self.cfg.provider == "openai":
            return self._ask_openai(messages, tools)
        else:
            return self._ask_ollama(messages, tools)

    def _ask_openai(self, messages: list[dict], tools: list[dict] | None) -> BrainResponse:
        """Chat Completions API call (D-16: replaces Responses API)."""
        kwargs: dict = {"model": self.cfg.openai_model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                )
                for tc in msg.tool_calls
            ]

        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }

        return BrainResponse(text=msg.content or "", tool_calls=tool_calls, usage=usage)

    def _ask_ollama(self, messages: list[dict], tools: list[dict] | None) -> BrainResponse:
        """Ollama /api/chat call with explicit num_ctx pinning (BRAIN-02)."""
        # Dynamic num_ctx: 16384 when tools present (schemas ~2000 tokens),
        # 4096 for plain conversation turns (saves prefill cost).
        num_ctx = self.cfg.ollama_num_ctx_tools if tools else self.cfg.ollama_num_ctx

        body: dict = {
            "model": self.cfg.ollama_model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.cfg.ollama_keep_alive,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": self.cfg.ollama_num_predict,
            },
        }
        if tools:
            body["tools"] = tools

        resp = requests.post(
            f"{self.cfg.ollama_url}/api/chat", json=body, timeout=120
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["message"]

        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=str(uuid.uuid4()),
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],  # Already a dict
                )
                for tc in msg["tool_calls"]
            ]

        usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }

        # BRAIN-03: Token warning at 80% of num_ctx
        prompt_tokens = usage["prompt_tokens"]
        if prompt_tokens and prompt_tokens > num_ctx * 0.8:
            import sys
            print(
                f"[brain] WARNING: prompt tokens ({prompt_tokens}) at "
                f"{prompt_tokens/num_ctx*100:.0f}% of num_ctx ({num_ctx})",
                file=sys.stderr, flush=True,
            )

        return BrainResponse(text=msg.get("content", ""), tool_calls=tool_calls, usage=usage)
