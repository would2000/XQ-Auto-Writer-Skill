import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
    / "xq_alert.py"
)
SPEC = importlib.util.spec_from_file_location("xq_alert", MODULE_PATH)
xq_alert = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(xq_alert)


class FakeInfo:
    def __init__(self, command_id, state=4):
        self.idCommand = command_id
        self.fsState = state


class FakeButton:
    def __init__(self, command_id, state=4):
        self.info = FakeInfo(command_id, state)
        self.clicked = False

    def click(self):
        self.clicked = True


class FakeToolbar:
    def __init__(self, *buttons):
        self.buttons = list(buttons)

    def button_count(self):
        return len(self.buttons)

    def button(self, index):
        return self.buttons[index]


class AlertResultTests(unittest.TestCase):
    def test_parse_run_label(self):
        self.assertEqual(
            xq_alert.parse_run_label("17:55:25(1)"),
            {"time": "17:55:25", "trigger_count": 1, "label": "17:55:25(1)"},
        )
        self.assertIsNone(xq_alert.parse_run_label("2026/07/22"))
        self.assertIsNone(xq_alert.parse_run_label("17:55(1)"))

    def test_latest_run_ignores_non_run_tree_items(self):
        labels = ["自訂", "2026/07/22", "17:55:25(1)", "17:56:14(0)"]
        self.assertEqual(xq_alert.latest_run(labels)["trigger_count"], 0)

    def test_evaluate_pair_requires_red_green_and_completion(self):
        self.assertTrue(xq_alert.evaluate_pair(1, 0, True)["passed"])
        self.assertFalse(xq_alert.evaluate_pair(0, 0, True)["passed"])
        self.assertFalse(xq_alert.evaluate_pair(1, 1, True)["passed"])
        self.assertFalse(xq_alert.evaluate_pair(1, 0, False)["passed"])

    def test_toolbar_command_lookup_and_state(self):
        start = FakeButton(xq_alert.START_COMMAND, 4)
        stop = FakeButton(xq_alert.STOP_COMMAND, 2)
        toolbar = FakeToolbar(FakeButton(999), start, stop)
        self.assertEqual(xq_alert.command_index(toolbar, xq_alert.START_COMMAND), 1)
        self.assertTrue(xq_alert.command_enabled(toolbar, xq_alert.START_COMMAND))
        self.assertFalse(xq_alert.command_enabled(toolbar, xq_alert.STOP_COMMAND))
        xq_alert.press_command(toolbar, xq_alert.START_COMMAND)
        self.assertTrue(start.clicked)

    def test_invalid_timeout_is_rejected(self):
        with self.assertRaises(SystemExit):
            xq_alert.parse_args(["--script-name", "Probe", "--timeout", "0"])

    def test_false_copy_restores_content_tab_before_copy_command(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        function = source.split("def copy_as_false", 1)[1].split(
            "def delete_exact", 1
        )[0]
        self.assertLess(
            function.index('select_tab(radar.handle, "內容")'),
            function.index("press_command(toolbar, COPY_COMMAND)"),
        )

    def test_main_reselects_true_strategy_after_false_name_probe(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        main = source.split("def main", 1)[1]
        false_probe = 'if search_exact(radar, false_name):'
        true_reselect = 'if not search_exact(radar, true_name):'
        copy_call = 'details["false_setup"] = copy_as_false'
        self.assertLess(main.index(false_probe), main.index(true_reselect))
        self.assertLess(main.index(true_reselect), main.index(copy_call))


if __name__ == "__main__":
    unittest.main()
