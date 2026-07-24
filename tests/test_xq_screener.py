import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".agents/skills/xq-xscript-compiler/scripts/xq_screener.py"
SPEC = importlib.util.spec_from_file_location("xq_screener", MODULE_PATH)
xq_screener = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(xq_screener)


class ScreenerCsvTests(unittest.TestCase):
    def test_parses_cp950_xq_export_and_normalizes_first_separator(self):
        text = "\r\n".join(
            [
                "符合條件商品",
                "資料日期：2026年  7月 22日",
                "策略,\tCodexCapturePositive",
                '"序號","代碼","商品","Close","所有細產業"',
                '1\t,"1216.TW","統一","76.8","飲料,食品加工"',
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.csv"
            path.write_bytes(text.encode("cp950"))
            result = xq_screener.parse_xq_screener_csv(path)

        self.assertEqual(result["strategy_name"], "CodexCapturePositive")
        self.assertEqual(result["data_date"], "2026年  7月 22日")
        self.assertEqual(result["rows"][0]["代碼"], "1216.TW")
        self.assertEqual(result["rows"][0]["所有細產業"], "飲料,食品加工")

    def test_rejects_malformed_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("not a report", encoding="utf-8")
            with self.assertRaises(ValueError):
                xq_screener.parse_xq_screener_csv(path)

    def test_parses_xq_empty_result_as_empty_rows(self):
        text = "\r\n".join(
            [
                "符合條件商品",
                "資料日期：2026年  7月 22日",
                "策略,\tCodexCaptureEmpty",
                '"序號","代碼","商品","Close"',
                "無任何符合選股條件的商品",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            path.write_bytes(text.encode("cp950"))
            result = xq_screener.parse_xq_screener_csv(path)

        self.assertEqual(result["strategy_name"], "CodexCaptureEmpty")
        self.assertEqual(result["rows"], [])

    def test_parses_xq_empty_execution_error_result(self):
        text = "\r\n".join(
            [
                "執行錯誤的商品",
                "資料日期：2026年  7月 22日",
                "策略,\tCodexNoErrors",
                '"序號","代碼","商品",錯誤訊息',
                "所有商品都已正常執行!!",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "errors.csv"
            path.write_bytes(text.encode("cp950"))
            result = xq_screener.parse_xq_screener_csv(path)
        self.assertEqual(result["result_kind"], "執行錯誤的商品")
        self.assertEqual(result["rows"], [])

    def test_normalizes_error_details_without_inventing_missing_code(self):
        rows = [
            {
                "序號": "1",
                "代碼": "2330.TW",
                "商品": "台積電",
                "錯誤訊息": "CODEX_MARKER",
            },
            {
                "序號": "2",
                "代碼": "2317.TW",
                "商品": "鴻海",
                "錯誤訊息": "[(1301)RaiseRunTimeError:MARKER]",
            },
        ]
        details = xq_screener.normalize_error_rows(rows)
        self.assertIsNone(details[0]["error_code"])
        self.assertEqual(details[0]["message"], "CODEX_MARKER")
        self.assertEqual(details[1]["error_code"], "1301")

    def test_result_classification_distinguishes_partial_failure(self):
        self.assertEqual(xq_screener.classify_screener_result(5, 0)[0], "success")
        self.assertEqual(xq_screener.classify_screener_result(0, 5)[0], "failure")
        self.assertEqual(
            xq_screener.classify_screener_result(5, 2)[0], "partial_failure"
        )

    def test_timeout_requests_stop_and_proves_control_recovery(self):
        class Button:
            def __init__(self, command, enabled):
                self.idCommand = command
                self.fsState = 4 if enabled else 2

        class Toolbar:
            def __init__(self):
                self.running = False

            def button_count(self):
                return 2

            def get_button(self, index):
                if index == 0:
                    return Button(xq_screener.START_COMMAND, not self.running)
                return Button(xq_screener.STOP_COMMAND, self.running)

            def press_button(self, index):
                self.running = index == 0

        toolbar = Toolbar()
        with mock.patch.object(
            xq_screener, "top_and_result_toolbars", return_value=(toolbar, object())
        ):
            result = xq_screener.run_strategy(object(), 0.001, 0.1)
        self.assertEqual(result["outcome"], "cancelled")
        self.assertTrue(result["stop_requested"])
        self.assertTrue(result["recovery_complete"])
        self.assertTrue(result["start_enabled"])
        self.assertFalse(result["stop_enabled"])

    def test_timeout_reports_incomplete_recovery(self):
        class Button:
            def __init__(self, command, enabled):
                self.idCommand = command
                self.fsState = 4 if enabled else 2

        class Toolbar:
            def button_count(self):
                return 2

            def get_button(self, index):
                return Button(
                    (xq_screener.START_COMMAND, xq_screener.STOP_COMMAND)[index],
                    index == 1,
                )

            def press_button(self, index):
                pass

        toolbar = Toolbar()
        with mock.patch.object(
            xq_screener, "top_and_result_toolbars", return_value=(toolbar, object())
        ):
            result = xq_screener.run_strategy(object(), 0.001, 0.01)
        self.assertEqual(result["outcome"], "recovery_failed")
        self.assertFalse(result["recovery_complete"])

    def test_command_index_uses_native_command_id(self):
        class Button:
            def __init__(self, command):
                self.idCommand = command

        class Toolbar:
            def button_count(self):
                return 3

            def get_button(self, index):
                return Button((10, 20, 30)[index])

        self.assertEqual(xq_screener.command_index(Toolbar(), 20), 1)
        with self.assertRaises(RuntimeError):
            xq_screener.command_index(Toolbar(), 99)

    def test_xq_names_reject_unsafe_or_oversized_values(self):
        self.assertEqual(
            xq_screener.validate_xq_name("  CodexCapture  ", "strategy-name", 40),
            "CodexCapture",
        )
        for value in ("", "bad/name", "bad\nname", "x" * 41):
            with self.assertRaises(ValueError):
                xq_screener.validate_xq_name(value, "strategy-name", 40)

    def test_public_universe_allowlist_excludes_user_watchlists(self):
        self.assertIn("台灣五十成分股(系統)", xq_screener.TAIWAN_SYSTEM_UNIVERSES)
        self.assertTrue(
            all("(系統)" in universe for universe in xq_screener.TAIWAN_SYSTEM_UNIVERSES)
        )

    def test_failed_creation_cancels_visible_dialog(self):
        class Control:
            def __init__(self, dialog):
                self.dialog = dialog

            def exists(self):
                return True

            def is_visible(self):
                return True

            def click_input(self):
                self.dialog.open = False

        class Dialog:
            def __init__(self):
                self.open = True

            def exists(self):
                return self.open

            def is_visible(self):
                return self.open

            def child_window(self, **kwargs):
                self.assert_cancel = kwargs
                return Control(self)

        dialog = Dialog()
        self.assertTrue(xq_screener.cancel_new_strategy_dialog(dialog))
        self.assertFalse(dialog.exists())
        self.assertEqual(dialog.assert_cancel["control_id"], 2)

    def test_search_uses_only_visible_no_result_controls(self):
        class Search:
            def set_edit_text(self, value):
                self.value = value

            def set_focus(self):
                pass

            def type_keys(self, keys, **kwargs):
                self.keys = keys

        class Static:
            def __init__(self, control_id, visible):
                self._control_id = control_id
                self._visible = visible

            def control_id(self):
                return self._control_id

            def is_visible(self):
                return self._visible

        class Window:
            def __init__(self, controls):
                self.search = Search()
                self.controls = controls

            def child_window(self, **kwargs):
                return self.search

            def descendants(self, **kwargs):
                return self.controls

        hidden_only = Window([Static(20502, False), Static(999, True)])
        visible = Window([Static(20502, False), Static(20502, True)])
        self.assertFalse(xq_screener.has_visible_no_result(hidden_only))
        self.assertTrue(xq_screener.has_visible_no_result(visible))

    def test_replace_search_text_forces_edit_notification_without_changing_value(self):
        class Edit:
            def set_edit_text(self, value):
                self.value = value

            def set_focus(self):
                self.focused = True

            def type_keys(self, keys, **kwargs):
                self.keys = keys

        edit = Edit()
        xq_screener.replace_search_text(edit, "CodexScript")
        self.assertEqual(edit.value, "CodexScript")
        self.assertTrue(edit.focused)
        self.assertEqual(edit.keys, "{END}{SPACE}{BACKSPACE}")

    def test_selected_script_readback_uses_visible_exact_condition_labels(self):
        class Static:
            def __init__(self, control_id, text, visible=True):
                self._control_id = control_id
                self._text = text
                self._visible = visible

            def control_id(self):
                return self._control_id

            def window_text(self):
                return self._text

            def is_visible(self):
                return self._visible

        class Dialog:
            def descendants(self, **kwargs):
                return [
                    Static(18710, " CodexExpected "),
                    Static(18710, "WrongHidden", False),
                    Static(999, "Other"),
                ]

        self.assertEqual(
            xq_screener.visible_condition_script_names(Dialog()), ["CodexExpected"]
        )


if __name__ == "__main__":
    unittest.main()
