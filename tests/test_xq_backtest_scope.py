from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import xq_backtest_scope as scope


class BacktestScopeTests(unittest.TestCase):
    def test_explicit_products_clear_and_verify_exact_final_set(self) -> None:
        selected = iter((("PRIVATE-OLD",), ("2330", "2317")))
        cleared = []
        added = []

        evidence = scope.replace_explicit_products(
            ("2330", "2317"),
            read_selected_codes=lambda: next(selected),
            clear_selected=lambda: cleared.append(True),
            wait_for_empty=lambda: True,
            find_exact_matches=lambda product: [f"row:{product}"],
            add_exact_match=lambda product, row: added.append((product, row)),
        )

        self.assertEqual(cleared, [True])
        self.assertEqual(added, [("2330", "row:2330"), ("2317", "row:2317")])
        self.assertEqual(
            evidence,
            {
                "selection_mode": "explicit_products",
                "source": "product",
                "requested_product_count": 2,
                "preexisting_selection_present": True,
                "cleared_selection_verified": True,
                "final_selection_verified": True,
                "private_source_touched": False,
            },
        )

    def test_explicit_products_rejects_duplicate_or_uncleared_selection(self) -> None:
        with self.assertRaises(scope.BacktestScopeError):
            scope.validate_explicit_products(("2330", "2330"))
        with self.assertRaises(scope.BacktestScopeError):
            scope.replace_explicit_products(
                ("2330",),
                read_selected_codes=lambda: ("OLD",),
                clear_selected=lambda: None,
                wait_for_empty=lambda: False,
                find_exact_matches=lambda _product: [0],
                add_exact_match=lambda _product, _row: None,
            )

    def test_explicit_products_rejects_non_unique_and_final_mismatch(self) -> None:
        with self.assertRaises(scope.BacktestScopeError):
            scope.replace_explicit_products(
                ("2330",),
                read_selected_codes=lambda: (),
                clear_selected=lambda: None,
                wait_for_empty=lambda: True,
                find_exact_matches=lambda _product: [0, 1],
                add_exact_match=lambda _product, _row: None,
            )
        selected = iter(((), ("2317",)))
        with self.assertRaises(scope.BacktestScopeError):
            scope.replace_explicit_products(
                ("2330",),
                read_selected_codes=lambda: next(selected),
                clear_selected=lambda: None,
                wait_for_empty=lambda: True,
                find_exact_matches=lambda _product: [0],
                add_exact_match=lambda _product, _row: None,
            )

    def test_system_default_scope_rereads_range_after_market_selection(self) -> None:
        selected = []
        evidence = scope.apply_system_default_scope(
            "台股",
            "普通股全部(系統)",
            available_markets=lambda: ("台股", "美股"),
            select_market=lambda value: selected.append(("market", value)),
            read_market=lambda: "台股",
            available_universes=lambda: ("普通股全部(系統)",),
            select_universe=lambda value: selected.append(("universe", value)),
            read_universe=lambda: "普通股全部(系統)",
        )

        self.assertEqual(selected, [("market", "台股"), ("universe", "普通股全部(系統)")])
        self.assertEqual(evidence["selection_mode"], "system_default_scope")
        self.assertEqual(evidence["requested_system_default_scope"], "普通股全部(系統)")
        self.assertEqual(evidence["final_selection_verified"], True)
        self.assertEqual(evidence["private_source_touched"], False)

    def test_system_default_scope_rejects_private_scope_or_missing_readback(self) -> None:
        with self.assertRaises(scope.BacktestScopeError):
            scope.validate_system_default_scope("我的自選")
        with self.assertRaises(scope.BacktestScopeError):
            scope.apply_system_default_scope(
                "台股",
                "普通股全部(系統)",
                available_markets=lambda: ("台股",),
                select_market=lambda _value: None,
                read_market=lambda: "台股",
                available_universes=lambda: (),
                select_universe=lambda _value: None,
                read_universe=lambda: "",
            )

    def test_manual_watchlist_group_is_never_named_or_applied_by_codex(self) -> None:
        evidence = scope.manual_watchlist_group_evidence("使用者自選組合")
        self.assertEqual(
            evidence,
            {
                "selection_mode": "manual_watchlist_group",
                "source": "screener_watchlist_group",
                "selection_applied_by_codex": False,
                "manual_selection_present": True,
                "private_group_name_retained": False,
                "private_source_touched": False,
                "final_selection_verified": False,
            },
        )
        with self.assertRaises(scope.BacktestScopeError):
            scope.manual_watchlist_group_evidence("普通股全部(系統)")


if __name__ == "__main__":
    unittest.main()
