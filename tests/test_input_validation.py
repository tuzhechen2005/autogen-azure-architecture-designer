"""Regression tests for early and terminal-safe request validation."""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from app import run_architecture
from scripts.orchestrator_smoke_test import ScriptedModelClient
from src.orchestrator import ArchitectureOrchestrator, CollaborationEvent
from src.schemas import RunStatus, TerminationReason


class CountingScriptedClient(ScriptedModelClient):
    def __init__(self) -> None:
        super().__init__([])
        self.create_calls = 0

    async def create(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        self.create_calls += 1
        return await super().create(*args, **kwargs)  # type: ignore[arg-type]


class SlowScriptedClient(ScriptedModelClient):
    async def create(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        await asyncio.sleep(1)
        return await super().create(*args, **kwargs)  # type: ignore[arg-type]


class EarlyInputValidationTests(unittest.TestCase):
    def test_whole_run_has_a_wall_clock_deadline(self) -> None:
        client = SlowScriptedClient(["unused"])
        started = time.monotonic()

        result = asyncio.run(
            ArchitectureOrchestrator(client, max_run_seconds=0.02).run(
                "Design a small highly available API on Azure."
            )
        )

        self.assertEqual(result.status, RunStatus.TIMEOUT)
        self.assertEqual(result.termination_reason, TerminationReason.TIMEOUT)
        self.assertIn("wall-clock timeout", result.error or "")
        self.assertLess(time.monotonic() - started, 0.5)

    def test_orchestrator_returns_failed_result_without_model_call(self) -> None:
        for requirements in (" " * 10, "\u200b" * 10, "\x00" * 10):
            with self.subTest(requirements=repr(requirements)):
                client = CountingScriptedClient()
                events: list[CollaborationEvent] = []

                result = asyncio.run(
                    ArchitectureOrchestrator(client, event_sink=events.append).run(
                        requirements
                    )
                )

                self.assertEqual(result.status, RunStatus.FAILED)
                self.assertIsNone(result.request)
                self.assertEqual(result.error, "Invalid architecture requirements")
                self.assertEqual(client.create_calls, 0)
                self.assertEqual(
                    [event.event_type.value for event in events],
                    ["error"],
                )

    def test_ui_validates_before_loading_model(self) -> None:
        settings = {
            "model_path": "/not/read/model.gguf",
            "max_tokens": 384,
            "n_gpu_layers": 0,
            "max_rounds": 2,
            "save_trace": False,
        }

        with patch("app.load_local_model") as load_model:
            with self.assertRaises(ValueError):
                run_architecture("\u200b" * 10, settings)

        load_model.assert_not_called()
