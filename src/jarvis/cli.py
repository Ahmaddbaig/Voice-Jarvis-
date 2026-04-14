"""Jarvis CLI — preserved push-to-talk REPL + eval harness.

D-19: jarvis_cli.py test_tools benchmarks both OpenAI + Ollama models.
D-20: CLI subcommand, not pytest.
"""
from __future__ import annotations

import sys
import time

from jarvis.core.config import load_config, Config
from jarvis.assistant import JarvisAssistant


def main() -> None:
    """Entry point: routes to REPL or eval harness based on sys.argv."""
    if len(sys.argv) > 1 and sys.argv[1] == "test_tools":
        run_eval_harness()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "test_composition":
        run_composition_harness()
        return
    run_repl()


def run_repl() -> None:
    """Preserved push-to-talk REPL from Phase 1."""
    cfg = load_config()
    assistant = JarvisAssistant(cfg, preloaded=None)
    time.sleep(0.5)
    print("Jarvis CLI ready (push-to-talk REPL).")
    print(f"Provider: {assistant.provider}")
    if assistant.provider == "ollama":
        print(f"Ollama model: {assistant.ollama_model}")
    print(f"Vision: {assistant.vision.status()}")
    print(
        "Type a message, 'm' for microphone, 'c' for camera, "
        "'s' for status, or 'q' to quit."
    )

    try:
        while True:
            try:
                choice = input("\n> ").strip()
                if not choice:
                    continue
                if choice.lower() == 'q':
                    break
                if choice.lower() == 's':
                    if assistant.provider == "ollama":
                        print(
                            f"Provider: {assistant.provider} "
                            f"({assistant.ollama_model})"
                        )
                    else:
                        print(
                            f"Provider: {assistant.provider} "
                            f"({assistant.model})"
                        )
                    print(f"Vision: {assistant.vision.status()}")
                    continue

                if choice.lower() == 'm':
                    audio_path = assistant.record_microphone()
                    prompt = assistant.transcribe(audio_path)
                    print(f"You said: {prompt}")
                    if not prompt:
                        print("I did not catch that.")
                        continue
                    reply = assistant.ask_text(prompt)
                elif choice.lower() == 'c':
                    prompt = input("Ask about the camera view: ").strip()
                    if not prompt:
                        prompt = "What do you see?"
                    reply = assistant.ask_with_camera(prompt)
                else:
                    reply = assistant.ask_text(choice)

                print(f"\nAssistant: {reply}")
                assistant.speak(reply)
            except Exception as exc:
                print(f"Error: {exc}")
    except KeyboardInterrupt:
        pass
    finally:
        assistant.close()


# ---------------------------------------------------------------------------
# Eval harness (BRAIN-07, D-19, D-20)
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "name": "simple_time",
        "prompt": "What time is it right now?",
        "expect_tool": "get_time",
        "expect_args": {},
    },
    {
        "name": "clipboard_read",
        "prompt": "What's on my clipboard?",
        "expect_tool": "get_clipboard",
        "expect_args": {},
    },
    {
        "name": "shell_command",
        "prompt": "Run the command: echo hello world",
        "expect_tool": "run_shell",
        "expect_args_contains": {"command": "echo"},
    },
    {
        "name": "web_search",
        "prompt": "Search the web for Python 3.12 release notes",
        "expect_tool": "search_web",
        "expect_args_contains": {"query": ""},
    },
    {
        "name": "no_tool_needed",
        "prompt": "What is 2 + 2?",
        "expect_tool": None,
        "expect_text": True,
    },
    {
        "name": "hallucinated_tool",
        "prompt": "Delete all files on my desktop",
        "expect_tool": None,
        "expect_text": True,
        "note": "No delete tool exists - model should reply with text",
    },
    {
        "name": "multi_param",
        "prompt": "Run this shell command: dir /b",
        "expect_tool": "run_shell",
        "expect_args_contains": {"command": "dir"},
    },
]

# ---------------------------------------------------------------------------
# Multi-step composition scenarios (Phase 10 — agent loop testing)
# ---------------------------------------------------------------------------
# These scenarios test that the brain correctly chains multiple tool calls
# in a single turn.  Unlike SCENARIOS above (which check only the first
# tool call), COMPOSITION_SCENARIOS run the full tool-call loop and
# validate that specific tools appear *somewhere* in the sequence.

COMPOSITION_SCENARIOS = [
    {
        "name": "search_then_fetch",
        "prompt": (
            "Search the web for 'Python 3.12 release notes' and then "
            "fetch the most relevant result page."
        ),
        "expect_tools_sequence": ["search_web", "fetch_page"],
        "note": "Requires search_web output to feed fetch_page URL",
    },
    {
        "name": "time_then_chat",
        "prompt": (
            "What time is it right now? Then post the current time "
            "to the team chat channel."
        ),
        "expect_tools_sequence": ["get_time", "post_to_chat"],
        "note": "get_time result should feed into post_to_chat message",
    },
    {
        "name": "loop_cap_respected",
        "prompt": (
            "Search the web for each of the following topics one at a time: "
            "Python, Rust, Go, Java, C++, Ruby, Swift, Kotlin, Scala, Haskell"
        ),
        "expect_max_calls": 8,
        "note": "Model must not exceed 8 tool calls in a single turn",
    },
    {
        "name": "read_then_summarise",
        "prompt": (
            "Read the file README.md from my desktop and give me "
            "a one-sentence summary of it."
        ),
        "expect_tools_sequence": ["read_file"],
        "expect_text_after": True,
        "note": "Tool result should feed into a text summary reply",
    },
    {
        "name": "calendar_then_chat",
        "prompt": (
            "Check my calendar for the next meeting and post the "
            "time and subject to the team chat channel."
        ),
        "expect_tools_sequence": ["list_events", "post_to_chat"],
        "note": "Calendar COM data feeds into Discord webhook",
    },
    {
        "name": "search_then_draft",
        "prompt": (
            "Search the web for the latest Kokoro TTS release notes "
            "and draft me an email summarising the key changes."
        ),
        "expect_tools_sequence": ["search_web", "draft_email"],
        "note": "Web search results feed into email draft (Tier 1 — not quarantine-blocked)",
    },
    {
        "name": "post_to_chat_direct",
        "prompt": (
            "Post the message 'Build completed successfully' to the team chat."
        ),
        "expect_tools_sequence": ["post_to_chat"],
        "note": "Direct single-tool invocation of Discord webhook",
    },
]


def run_eval_harness() -> None:
    """Run tool-call scenarios across models and print comparison table."""
    import os
    import requests
    from jarvis.core.brain import Brain
    from jarvis.tools import all_schemas
    from openai import OpenAI

    cfg = load_config()
    schemas = all_schemas()

    SYSTEM_PROMPT = (
        "You are a helpful desktop assistant with access to tools. "
        "Use tools when appropriate to answer the user's request. "
        "If no tool is needed, answer directly."
    )

    # Build model list
    models: list[dict] = []

    # OpenAI model (if API key available)
    if os.getenv("OPENAI_API_KEY"):
        models.append({
            "name": cfg.openai_model,
            "provider": "openai",
        })

    # Ollama models from config
    for model_tag in cfg.eval_models.split(","):
        model_tag = model_tag.strip()
        if not model_tag:
            continue
        # Check if model is available
        try:
            resp = requests.post(
                f"{cfg.ollama_url}/api/show",
                json={"name": model_tag},
                timeout=5,
            )
            if resp.status_code == 200:
                models.append({"name": model_tag, "provider": "ollama"})
            else:
                print(f"  [skip] {model_tag} -- not pulled")
        except Exception:
            print(f"  [skip] {model_tag} -- Ollama unreachable")

    if not models:
        print("ERROR: No models available. Need OPENAI_API_KEY or running Ollama.")
        sys.exit(1)

    print(f"\n{'=' * 70}")
    print(" Jarvis Tool-Call Eval Harness")
    print(f" Models: {', '.join(m['name'] for m in models)}")
    print(f" Scenarios: {len(SCENARIOS)}")
    print(f"{'=' * 70}\n")

    # Results matrix: results[model_name][scenario_name] = {pass, latency, reason}
    results: dict[str, dict] = {}

    for model_info in models:
        model_name = model_info["name"]
        provider = model_info["provider"]
        results[model_name] = {}
        print(f"Testing: {model_name} ({provider})...")

        for scenario in SCENARIOS:
            # Fresh Brain per scenario -- no cross-contamination
            test_cfg = _make_test_config(cfg, model_name, provider)
            if provider == "openai":
                client = OpenAI()
            else:
                client = None
            brain = Brain(test_cfg, client)

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": scenario["prompt"]},
            ]

            t0 = time.time()
            try:
                resp = brain.ask(messages, schemas)
                latency_ms = int((time.time() - t0) * 1000)

                passed, reason = _evaluate_scenario(scenario, resp)
                results[model_name][scenario["name"]] = {
                    "pass": passed,
                    "latency_ms": latency_ms,
                    "reason": reason,
                }
                status = "PASS" if passed else "FAIL"
                print(f"  {scenario['name']}: {status} ({latency_ms}ms) {reason}")
            except Exception as exc:
                latency_ms = int((time.time() - t0) * 1000)
                results[model_name][scenario["name"]] = {
                    "pass": False,
                    "latency_ms": latency_ms,
                    "reason": f"ERROR: {exc}",
                }
                print(f"  {scenario['name']}: ERROR ({latency_ms}ms) {exc}")

    # Print comparison table
    _print_comparison_table(models, results)


def _evaluate_scenario(scenario: dict, resp) -> tuple[bool, str]:
    """Evaluate whether Brain response matches scenario expectations."""
    expect_tool = scenario.get("expect_tool")

    if expect_tool is None:
        # Expect NO tool call -- model should give text reply
        if resp.tool_calls:
            return False, f"called {resp.tool_calls[0].name} (expected text reply)"
        if resp.text:
            return True, "text reply (correct)"
        return False, "empty response"

    # Expect a specific tool call
    if not resp.tool_calls:
        if resp.text:
            return False, f"text reply instead of calling {expect_tool}"
        return False, "empty response"

    first_call = resp.tool_calls[0]
    if first_call.name != expect_tool:
        return False, f"called {first_call.name} (expected {expect_tool})"

    # Check arguments if specified
    if "expect_args_contains" in scenario:
        for key, substr in scenario["expect_args_contains"].items():
            if key not in first_call.arguments:
                return False, f"missing arg '{key}'"
            if substr and substr not in str(first_call.arguments[key]):
                return False, f"arg '{key}' doesn't contain '{substr}'"

    return True, f"called {expect_tool} correctly"


def _make_test_config(base_cfg: Config, model_name: str, provider: str) -> Config:
    """Create a Config variant for a specific model under test."""
    from dataclasses import replace

    if provider == "openai":
        return replace(base_cfg, provider="openai", openai_model=model_name)
    else:
        return replace(base_cfg, provider="ollama", ollama_model=model_name,
                       ollama_num_ctx_tools=16384)


def _print_comparison_table(models: list[dict], results: dict) -> None:
    """Print formatted comparison table to stdout."""
    print(f"\n{'=' * 70}")
    print(" RESULTS COMPARISON")
    print(f"{'=' * 70}\n")

    # Header
    model_names = [m["name"] for m in models]
    header = f"{'Scenario':<20}"
    for name in model_names:
        short = name[:15]
        header += f" | {short:<17}"
    print(header)
    print("-" * len(header))

    # Rows
    scenario_names = [s["name"] for s in SCENARIOS]
    for sname in scenario_names:
        row = f"{sname:<20}"
        for mname in model_names:
            r = results.get(mname, {}).get(sname, {})
            if r:
                status = "PASS" if r["pass"] else "FAIL"
                row += f" | {status} {r['latency_ms']:>5}ms   "
            else:
                row += f" | {'N/A':<17}"
        print(row)

    # Summary
    print("-" * len(header))
    summary_row = f"{'TOTAL PASS':<20}"
    for mname in model_names:
        passed = sum(1 for r in results.get(mname, {}).values() if r.get("pass"))
        total = len(scenario_names)
        pct = int(passed / total * 100) if total else 0
        summary_row += f" | {passed}/{total} ({pct}%)       "
    print(summary_row)

    # Average latency
    latency_row = f"{'AVG LATENCY':<20}"
    for mname in model_names:
        latencies = [r["latency_ms"] for r in results.get(mname, {}).values()
                     if "latency_ms" in r]
        avg = int(sum(latencies) / len(latencies)) if latencies else 0
        latency_row += f" | {avg:>5}ms         "
    print(latency_row)
    print()


# ---------------------------------------------------------------------------
# Composition harness (Phase 10 — multi-step agent loop eval)
# ---------------------------------------------------------------------------

def run_composition_harness() -> None:
    """Run multi-step composition scenarios and print results.

    Unlike run_eval_harness (single tool-call check), this drives the full
    brain tool-call loop — repeatedly calling brain.ask() and feeding tool
    results back — to test multi-step chaining.
    """
    import hashlib
    import json
    import os
    import requests
    from jarvis.core.brain import Brain
    from jarvis.tools import all_schemas, call_tool, get_tier
    from openai import OpenAI

    from jarvis.assistant import SYSTEM_PROMPT

    cfg = load_config()
    schemas = all_schemas()

    # Build model list (same logic as run_eval_harness)
    models: list[dict] = []
    if os.getenv("OPENAI_API_KEY"):
        models.append({"name": cfg.openai_model, "provider": "openai"})
    for model_tag in cfg.eval_models.split(","):
        model_tag = model_tag.strip()
        if not model_tag:
            continue
        try:
            resp = requests.post(
                f"{cfg.ollama_url}/api/show",
                json={"name": model_tag}, timeout=5,
            )
            if resp.status_code == 200:
                models.append({"name": model_tag, "provider": "ollama"})
            else:
                print(f"  [skip] {model_tag} -- not pulled")
        except Exception:
            print(f"  [skip] {model_tag} -- Ollama unreachable")

    if not models:
        print("ERROR: No models available.")
        sys.exit(1)

    print(f"\n{'=' * 70}")
    print(" Jarvis Multi-Step Composition Eval")
    print(f" Models: {', '.join(m['name'] for m in models)}")
    print(f" Scenarios: {len(COMPOSITION_SCENARIOS)}")
    print(f"{'=' * 70}\n")

    results: dict[str, dict] = {}
    MAX_TOOL_CALLS = 8

    for model_info in models:
        model_name = model_info["name"]
        provider = model_info["provider"]
        results[model_name] = {}
        print(f"Testing: {model_name} ({provider})...")

        for scenario in COMPOSITION_SCENARIOS:
            test_cfg = _make_test_config(cfg, model_name, provider)
            client = OpenAI() if provider == "openai" else None
            brain = Brain(test_cfg, client)

            messages: list[dict] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": scenario["prompt"]},
            ]

            t0 = time.time()
            all_tool_names: list[str] = []
            seen_hashes: set[str] = set()
            final_text = ""

            try:
                for _iteration in range(MAX_TOOL_CALLS + 1):
                    resp = brain.ask(messages, schemas)

                    if not resp.tool_calls:
                        final_text = resp.text
                        break

                    # Build assistant message with tool_calls
                    assistant_msg: dict = {
                        "role": "assistant", "content": resp.text or "",
                    }
                    if provider == "openai":
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc.id, "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in resp.tool_calls
                        ]
                    else:
                        assistant_msg["tool_calls"] = [
                            {"function": {"name": tc.name, "arguments": tc.arguments}}
                            for tc in resp.tool_calls
                        ]
                    messages.append(assistant_msg)

                    for tc in resp.tool_calls:
                        all_tool_names.append(tc.name)
                        call_hash = hashlib.md5(
                            f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}".encode()
                        ).hexdigest()
                        if call_hash in seen_hashes:
                            result = f"[Duplicate call -- already called {tc.name}]"
                        else:
                            seen_hashes.add(call_hash)
                            result = call_tool(tc.name, tc.arguments)

                        if provider == "openai":
                            messages.append({
                                "role": "tool", "tool_call_id": tc.id,
                                "content": str(result),
                            })
                        else:
                            messages.append({"role": "tool", "content": str(result)})
                else:
                    final_text = resp.text or "(loop cap reached)"

                latency_ms = int((time.time() - t0) * 1000)
                passed, reason = _evaluate_composition(
                    scenario, all_tool_names, final_text
                )
                results[model_name][scenario["name"]] = {
                    "pass": passed,
                    "latency_ms": latency_ms,
                    "reason": reason,
                    "tools_called": all_tool_names,
                }
                status = "PASS" if passed else "FAIL"
                tools_str = " -> ".join(all_tool_names) if all_tool_names else "(none)"
                print(f"  {scenario['name']}: {status} ({latency_ms}ms)")
                print(f"    chain: {tools_str}")
                print(f"    {reason}")
            except Exception as exc:
                latency_ms = int((time.time() - t0) * 1000)
                results[model_name][scenario["name"]] = {
                    "pass": False,
                    "latency_ms": latency_ms,
                    "reason": f"ERROR: {exc}",
                    "tools_called": all_tool_names,
                }
                print(f"  {scenario['name']}: ERROR ({latency_ms}ms) {exc}")

    # Print summary
    _print_composition_table(models, results)


def _evaluate_composition(
    scenario: dict, tool_names: list[str], final_text: str,
) -> tuple[bool, str]:
    """Evaluate a multi-step composition scenario."""
    # Check max-calls constraint
    if "expect_max_calls" in scenario:
        if len(tool_names) > scenario["expect_max_calls"]:
            return False, (
                f"exceeded call cap: {len(tool_names)} > "
                f"{scenario['expect_max_calls']}"
            )
        return True, f"{len(tool_names)} calls (within cap of {scenario['expect_max_calls']})"

    # Check expected tool sequence (ordered subset match)
    if "expect_tools_sequence" in scenario:
        expected = scenario["expect_tools_sequence"]
        idx = 0
        for name in tool_names:
            if idx < len(expected) and name == expected[idx]:
                idx += 1
        if idx < len(expected):
            missing = expected[idx:]
            return False, f"missing tools in chain: {missing}"

    # Check that text reply followed tools
    if scenario.get("expect_text_after") and not final_text.strip():
        return False, "expected text summary after tools but got empty reply"

    chain = " -> ".join(tool_names) if tool_names else "(no tools)"
    return True, f"chain complete: {chain}"


def _print_composition_table(models: list[dict], results: dict) -> None:
    """Print composition eval summary."""
    print(f"\n{'=' * 70}")
    print(" COMPOSITION RESULTS")
    print(f"{'=' * 70}\n")

    model_names = [m["name"] for m in models]
    header = f"{'Scenario':<25}"
    for name in model_names:
        header += f" | {name[:15]:<17}"
    print(header)
    print("-" * len(header))

    for scenario in COMPOSITION_SCENARIOS:
        sname = scenario["name"]
        row = f"{sname:<25}"
        for mname in model_names:
            r = results.get(mname, {}).get(sname, {})
            if r:
                status = "PASS" if r["pass"] else "FAIL"
                row += f" | {status} {r['latency_ms']:>5}ms   "
            else:
                row += f" | {'N/A':<17}"
        print(row)

    print("-" * len(header))
    summary_row = f"{'TOTAL PASS':<25}"
    for mname in model_names:
        passed = sum(1 for r in results.get(mname, {}).values() if r.get("pass"))
        total = len(COMPOSITION_SCENARIOS)
        pct = int(passed / total * 100) if total else 0
        summary_row += f" | {passed}/{total} ({pct}%)       "
    print(summary_row)
    print()
