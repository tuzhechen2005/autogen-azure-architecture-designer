"""Regression tests for trace failures after successful inference."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import app
from src.orchestrator import CollaborationEvent, EventType
from src.schemas import RunStatus, TerminationReason


class TraceTerminalStateTests(unittest.TestCase):
    def test_trace_failure_preserves_result_and_precedes_completed_ui(self) -> None:
        timeline: list[str] = []
        status_box = SimpleNamespace(
            update=Mock(
                side_effect=lambda **kwargs: timeline.append(
                    str(kwargs.get("state", "unknown"))
                )
            )
        )
        fake_streamlit = SimpleNamespace(
            status=Mock(return_value=status_box),
            container=Mock(return_value=nullcontext()),
            warning=Mock(side_effect=lambda *args, **kwargs: timeline.append("warning")),
        )
        expected_result = SimpleNamespace(
            status=RunStatus.COMPLETED,
            termination_reason=TerminationReason.APPROVED,
        )

        class CompletingOrchestrator:
            def __init__(self, *args: object, event_sink=None, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
                self._event_sink = event_sink

            async def run(self, requirements: str) -> object:
                self._event_sink(
                    CollaborationEvent(
                        event_type=EventType.COMPLETED,
                        text="completed",
                        result=expected_result,  # type: ignore[arg-type]
                    )
                )
                return expected_result

        def fail_trace(*args: object, **kwargs: object) -> None:
            timeline.append("trace")
            raise OSError("disk full")

        settings = {
            "model_path": "/trusted/model.gguf",
            "max_tokens": 384,
            "n_gpu_layers": 0,
            "max_rounds": 2,
            "save_trace": True,
        }
        with (
            patch.object(app, "st", fake_streamlit),
            patch.object(app, "load_local_model", return_value=object()),
            patch.object(app, "ArchitectureOrchestrator", CompletingOrchestrator),
            patch.object(app, "save_trace", side_effect=fail_trace),
        ):
            actual_result = app.run_architecture(
                "Design a small highly available Azure API.",
                settings,
            )

        self.assertIs(actual_result, expected_result)
        self.assertEqual(timeline, ["running", "trace", "warning", "complete"])
        fake_streamlit.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
