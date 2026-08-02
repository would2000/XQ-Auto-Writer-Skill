from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = (
    PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
)
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import xq_screener_backtest_probe


class ScreenerBacktestProbeTests(unittest.TestCase):
    def test_private_scope_name_is_redacted_but_system_scope_is_public(self) -> None:
        self.assertEqual(
            xq_screener_backtest_probe.public_control_text(
                2094, "普通股全部(系統)"
            ),
            ("普通股全部(系統)", False),
        )
        self.assertEqual(
            xq_screener_backtest_probe.public_control_text(2094, "私人組合"),
            ("<private-scope-redacted>", True),
        )
        self.assertEqual(
            xq_screener_backtest_probe.public_control_text(2003, "8"),
            ("8", False),
        )

    def test_uncalibrated_probe_stops_before_xq(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config = Path(temporary_directory) / "xq-ui.json"
            config.write_text('{"calibrated": false}', encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = xq_screener_backtest_probe.main(
                    ["--config", str(config)]
                )

        self.assertEqual(code, 3)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "automation_error")
        self.assertIn("not calibrated", payload["message"])


if __name__ == "__main__":
    unittest.main()
