"""Regression tests for isolating a new UI attempt from an old result."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import app
from src.config import ConfigurationError
from src.schemas import RunStatus, TerminationReason
from src import ui


class SessionState(dict[str, object]):
    def __getattr__(self, name: str) -> object:
        return self[name]

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class NewRunIsolationTests(unittest.TestCase):
    def test_failed_new_attempt_does_not_render_previous_success(self) -> None:
        old_result = SimpleNamespace(status=RunStatus.COMPLETED)
        state = SessionState(architecture_result={"run_id": "old-success"})
        fake_streamlit = SimpleNamespace(
            session_state=state,
            subheader=Mock(),
            text_area=Mock(return_value="new requirements"),
            columns=Mock(return_value=[nullcontext(), nullcontext(), nullcontext()]),
            button=Mock(side_effect=[True, False]),
            error=Mock(),
        )

        with (
            patch.object(app, "st", fake_streamlit),
            patch.object(app, "render_header"),
            patch.object(app, "render_sidebar", return_value={}),
            patch.object(
                app,
                "run_architecture",
                side_effect=ConfigurationError("new run failed"),
            ),
            patch.object(
                app.ArchitectureRunResult,
                "model_validate",
                return_value=old_result,
            ),
            patch.object(app, "render_result") as render_result,
        ):
            app.main()

        self.assertIsNone(state.architecture_result)
        render_result.assert_not_called()

    def test_result_identifies_its_run_and_original_requirements(self) -> None:
        fake_streamlit = SimpleNamespace(
            divider=Mock(),
            header=Mock(),
            caption=Mock(),
            expander=Mock(return_value=nullcontext()),
            code=Mock(),
            success=Mock(),
            subheader=Mock(),
        )
        result = SimpleNamespace(
            run_id="run-current",
            request=SimpleNamespace(requirements="current requirements"),
            termination_reason=TerminationReason.APPROVED,
            review_rounds_completed=1,
            final_plan=None,
            final_review=None,
            messages=[],
        )

        with patch.object(ui, "st", fake_streamlit):
            ui.render_result(result)  # type: ignore[arg-type]

        fake_streamlit.caption.assert_any_call("运行 ID：run-current")
        fake_streamlit.code.assert_called_once_with(
            "current requirements",
            language=None,
        )


if __name__ == "__main__":
    unittest.main()
