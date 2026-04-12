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
