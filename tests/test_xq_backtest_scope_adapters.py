from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import xq_alert_backtest
import xq_autotrade_backtest
import xq_screener_backtest


class BacktestScopeAdapterTests(unittest.TestCase):
    def calibrated_config(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "xq-ui.json"
        path.write_text(json.dumps({"calibrated": True}), encoding="utf-8")
        return path

    def test_alert_requires_dry_run_before_reading_xq_configuration(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = xq_alert_backtest.main(
                ["--config", "missing.json", "--product", "2330"]
            )

        self.assertEqual(code, 3)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "automation_error")
        self.assertIn("requires --dry-run", payload["message"])

    def test_alert_opener_scopes_uia_to_the_native_toolbar(self) -> None:
        class FakeWindow:
            def __init__(self, wrapped: object) -> None:
                self.wrapped = wrapped

            def wait(self, *_args: object, **_kwargs: object) -> None:
                return None

            def wrapper_object(self) -> object:
                return self.wrapped

        class FakeRoot:
            def __init__(self, toolbar: object) -> None:
                self.toolbar = toolbar
                self.descendant_calls = 0

            def window_text(self) -> str:
                return "XScript 編輯器 - [MyBullishSignalAlert(警示)]"

            def descendants(self) -> list[object]:
                self.descendant_calls += 1
                return [self.toolbar]

        toolbar_handle = SimpleNamespace(
            handle=123,
            class_name=lambda: "XTPToolBar",
            window_text=lambda: "工具列",
            is_visible=lambda: True,
        )
        button = SimpleNamespace(
            element_info=SimpleNamespace(control_type="Button", name=" 回測 ")
        )
        toolbar = SimpleNamespace(
            descendants=lambda **kwargs: [button]
            if kwargs == {"control_type": "Button"}
            else (_ for _ in ()).throw(AssertionError("unexpected full UIA scan"))
        )
        root = FakeRoot(toolbar_handle)
        settings = object()

        def desktop(backend: str) -> object:
            if backend == "win32":
                return SimpleNamespace(window=lambda **_kwargs: FakeWindow(root))
            if backend == "uia":
                return SimpleNamespace(window=lambda **kwargs: FakeWindow(toolbar))
            raise AssertionError(f"unexpected backend: {backend}")

        with (
            patch.dict(sys.modules, {"pywinauto": SimpleNamespace(Desktop=desktop)}),
            patch.object(
                xq_alert_backtest.xq_backtest,
                "guarded_paced_click",
                return_value={"foreground_verified": True},
            ) as click,
            patch.object(
                xq_alert_backtest.xq_backtest,
                "visible_dialog_with_control",
                return_value=settings,
            ) as visible_dialog,
        ):
            observed = xq_alert_backtest.open_alert_backtest_settings(
                {
                    "connect_timeout_seconds": 15,
                    "active_type_title_regex": {"alert": r"\(警示\)"},
                }
            )

        self.assertIs(observed, settings)
        self.assertEqual(root.descendant_calls, 1)
        click.assert_called_once_with(root, button)
        visible_dialog.assert_called_once_with(2033, 15.0)

    def test_screener_requires_dry_run_before_reading_xq_configuration(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = xq_screener_backtest.main(
                [
                    "--config",
                    "missing.json",
                    "--market",
                    "台股",
                    "--system-default-scope",
                    "普通股全部(系統)",
                ]
            )

        self.assertEqual(code, 3)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "automation_error")
        self.assertIn("requires --dry-run", payload["message"])

    def test_autotrade_requires_dry_run_before_reading_xq_configuration(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = xq_autotrade_backtest.main(
                ["--config", "missing.json", "--product", "2330"]
            )

        self.assertEqual(code, 3)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "automation_error")
        self.assertIn("requires --dry-run", payload["message"])

    def test_adapters_leave_ui_untouched_when_recovery_is_not_safe(self) -> None:
        blocked = {"decision": "manual_review_required", "checkpoint_present": True}
        for adapter, argv, opener in (
            (
                xq_alert_backtest,
                ["--product", "2330", "--dry-run"],
                "open_alert_backtest_settings",
            ),
            (
                xq_screener_backtest,
                [
                    "--market",
                    "台股",
                    "--system-default-scope",
                    "普通股全部(系統)",
                    "--dry-run",
                ],
                "preopened_screener_settings",
            ),
            (
                xq_autotrade_backtest,
                ["--product", "2330", "--dry-run"],
                "open_autotrade_backtest_settings",
            ),
        ):
            output = io.StringIO()
            with (
                patch.object(adapter.xq_backtest, "inspect_recovery_status", return_value=blocked),
                patch.object(adapter, opener) as open_settings,
                contextlib.redirect_stdout(output),
            ):
                code = adapter.main(["--config", str(self.calibrated_config()), *argv])

            self.assertEqual(code, 3)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "environment_interruption")
            self.assertEqual(payload["recovery"], blocked)
            open_settings.assert_not_called()

    def test_alert_timeout_never_sends_a_cleanup_click_or_retries(self) -> None:
        output = io.StringIO()
        settings = object()
        with (
            patch.object(
                xq_alert_backtest.xq_backtest,
                "inspect_recovery_status",
                return_value={"decision": "safe_to_start"},
            ),
            patch.object(
                xq_alert_backtest.xq_backtest,
                "capture_runtime_snapshot",
                return_value=object(),
            ),
            patch.object(
                xq_alert_backtest.xq_backtest,
                "classify_runtime_interruption",
                return_value=None,
            ),
            patch.object(
                xq_alert_backtest,
                "open_alert_backtest_settings",
                return_value=settings,
            ) as opener,
            patch.object(
                xq_alert_backtest.xq_backtest,
                "choose_products",
                side_effect=TimeoutError("dialog_timeout"),
            ) as choose,
            patch.object(
                xq_alert_backtest.xq_backtest,
                "guarded_paced_click",
            ) as guarded_click,
            contextlib.redirect_stdout(output),
        ):
            code = xq_alert_backtest.main(
                [
                    "--config",
                    str(self.calibrated_config()),
                    "--product",
                    "2330",
                    "--dry-run",
                ]
            )

        self.assertEqual(code, 3)
        self.assertEqual(json.loads(output.getvalue())["status"], "automation_error")
        opener.assert_called_once()
        choose.assert_called_once()
        guarded_click.assert_not_called()

    def test_public_scope_contract_documents_all_three_adapters_and_guard(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        skill = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        contract = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "references"
            / "backtest-configuration-contract.md"
        ).read_text(encoding="utf-8")

        for document in (readme, skill):
            self.assertIn("xq_alert_backtest.py", document)
            self.assertIn("xq_screener_backtest.py", document)
            self.assertIn("xq_autotrade_backtest.py", document)
        self.assertIn("Windows 前景", readme)
        self.assertIn("foreground guard", skill)
        self.assertIn("警示、選股與自動交易", contract)
        self.assertIn("不得補送取消或自動重試", contract)


if __name__ == "__main__":
    unittest.main()
