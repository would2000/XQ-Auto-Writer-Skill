from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = (
    PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
)
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import xq_screener_backtest_run


class ScreenerBacktestRunTests(unittest.TestCase):
    def base_args(self) -> list[str]:
        return [
            "--config",
            "missing.json",
            "--script-name",
            "MyBreakoutStrengthScreener",
            "--market",
            "台股",
            "--system-default-scope",
            "普通股全部(系統)",
            "--direction",
            "long",
            "--frequency",
            "day",
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-30",
            "--entry-price",
            "next_open",
            "--exit-price",
            "current_close",
            "--take-profit-enabled",
            "--take-profit",
            "8",
            "--take-profit-unit",
            "percent",
            "--stop-loss-enabled",
            "--stop-loss",
            "8",
            "--stop-loss-unit",
            "percent",
            "--max-holding-enabled",
            "--max-holding-periods",
            "20",
            "--stock-fee-percent",
            "0.2",
            "--no-print-enabled",
        ]

    def test_dry_run_requires_every_material_choice(self) -> None:
        args = xq_screener_backtest_run.parse_args(
            [*self.base_args(), "--dry-run"]
        )
        settings = xq_screener_backtest_run.settings_from_args(args)
        self.assertEqual(settings.system_default_scope, "普通股全部(系統)")
        self.assertTrue(settings.take_profit_enabled)
        self.assertTrue(settings.stop_loss_enabled)
        self.assertTrue(settings.max_holding_enabled)
        self.assertFalse(settings.print_enabled)

    def test_real_run_requires_explicit_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirm-historical-backtest"):
            xq_screener_backtest_run.settings_from_args(
                xq_screener_backtest_run.parse_args(self.base_args())
            )

    def test_private_or_incomplete_scope_and_rules_are_rejected(self) -> None:
        private_scope = self.base_args()
        private_scope[private_scope.index("普通股全部(系統)")] = "私人組合"
        with self.assertRaisesRegex(ValueError, "public"):
            xq_screener_backtest_run.settings_from_args(
                xq_screener_backtest_run.parse_args(
                    [*private_scope, "--dry-run"]
                )
            )

        disabled_with_value = self.base_args()
        index = disabled_with_value.index("--take-profit-enabled")
        disabled_with_value[index] = "--no-take-profit-enabled"
        with self.assertRaisesRegex(ValueError, "must not include"):
            xq_screener_backtest_run.settings_from_args(
                xq_screener_backtest_run.parse_args(
                    [*disabled_with_value, "--dry-run"]
                )
            )

    def test_uncompiled_screener_title_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "uncompiled"):
            xq_screener_backtest_run.validate_compiled_screener_title(
                "XScript 編輯器 - [MyBreakoutStrengthScreener(選股)未編譯]",
                "MyBreakoutStrengthScreener",
            )
        title = xq_screener_backtest_run.validate_compiled_screener_title(
            "XScript 編輯器 - [MyBreakoutStrengthScreener(選股)]",
            "MyBreakoutStrengthScreener",
        )
        self.assertNotIn("未編譯", title)


if __name__ == "__main__":
    unittest.main()
