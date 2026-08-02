import sys
import unittest
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import xq_ui_pacing as pacing  # noqa: E402


class XQUiPacingTests(unittest.TestCase):
    def test_default_level_preserves_baseline(self) -> None:
        profile = pacing.load_ui_pacing({
            "ui_pacing": {
                "default_level": 5,
                "action_interval_floor_seconds": 1.0,
                "keyboard_pause_floor_seconds": 0.02,
            }
        })
        self.assertEqual(profile.level, 5)
        self.assertEqual(profile.action_interval(2.5), 2.5)

    def test_level_seven_is_fifty_percent_faster_when_not_clamped(self) -> None:
        profile = pacing.load_ui_pacing({}, 7)
        self.assertAlmostEqual(profile.action_interval(2.5), 2.5 / 1.5)
        self.assertEqual(profile.action_interval(1.0), 1.0)

    def test_lower_level_is_slower(self) -> None:
        profile = pacing.load_ui_pacing({}, 1)
        self.assertEqual(profile.action_interval(2.5), 5.0)

    def test_invalid_level_is_refused(self) -> None:
        with self.assertRaisesRegex(pacing.UiPacingError, "1 to 10"):
            pacing.load_ui_pacing({}, 11)


if __name__ == "__main__":
    unittest.main()
