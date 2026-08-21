"""Minimal local AutoGen + Phi-3 integration check for development setup."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autogen_agentchat.agents import AssistantAgent

from src.config import AppConfig, ConfigurationError
from src.local_model_client import LlamaCppChatCompletionClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate imports and non-model configuration without loading Phi-3.",
    )
    return parser.parse_args()


async def run_model_smoke(config: AppConfig) -> None:
    client = LlamaCppChatCompletionClient(config)
    agent = AssistantAgent(
        "local_smoke_agent",
        model_client=client,
        system_message=(
            "You are a local runtime verifier. Reply with exactly LOCAL_AUTOGEN_OK."
        ),
        model_client_stream=False,
    )
    try:
        result = await agent.run(task="Confirm that the local model is responding.")
        final_message = result.messages[-1]
        content = str(getattr(final_message, "content", "")).strip()
        if not content:
            raise RuntimeError("The local model returned an empty response")
        usage = client.actual_usage()
        if usage.completion_tokens < 1:
            raise RuntimeError("The local model did not report completion token usage")
        print("AutoGen + local Phi-3 smoke test passed.")
        print(f"Response: {content}")
        print(
            "Usage: "
            f"{usage.prompt_tokens} prompt tokens, "
            f"{usage.completion_tokens} completion tokens"
        )
    finally:
        await client.close()


def main() -> int:
    args = parse_args()
    try:
        config = AppConfig.from_env(require_model=not args.check_config)
        if args.check_config:
            print("Imports and configuration contract are valid.")
            return 0
        asyncio.run(run_model_smoke(config))
    except (ConfigurationError, RuntimeError) as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
