import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".agents/skills/xq-xscript-compiler/scripts/xq_indicator.py"
SPEC = importlib.util.spec_from_file_location("xq_indicator", MODULE_PATH)
xq_indicator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(xq_indicator)


class IndicatorExportTests(unittest.TestCase):
    class FakeTreeItem:
        def __init__(self, text, children=()):
            self._text = text
            self._children = list(children)
            self.expanded = False

        def text(self):
            return self._text

        def children(self):
            return self._children

        def expand(self):
            self.expanded = True

    def test_codex_indicator_is_resolved_only_as_direct_codex_child(self):
        target = self.FakeTreeItem("Demo")
        private_duplicate = self.FakeTreeItem("Demo")
        codex = self.FakeTreeItem("CODEX", [target])
        custom = self.FakeTreeItem("自訂", [private_duplicate, codex])

        resolved = xq_indicator.codex_indicator_item(custom, "Demo")

        self.assertIs(resolved, target)
        self.assertTrue(custom.expanded)
        self.assertTrue(codex.expanded)

    def test_codex_indicator_rejects_missing_or_duplicate_codex_folder(self):
        with self.assertRaisesRegex(LookupError, "CODEX indicator folder"):
            xq_indicator.codex_indicator_item(self.FakeTreeItem("自訂"), "Demo")
        duplicate = self.FakeTreeItem(
            "自訂", [self.FakeTreeItem("CODEX"), self.FakeTreeItem("CODEX")]
        )
        with self.assertRaisesRegex(LookupError, "found 2"):
            xq_indicator.codex_indicator_item(duplicate, "Demo")

    def test_parses_excel_matrix_and_normalizes_dates(self):
        values = (
            ("時間", "收盤價", "CodexPlot"),
            ("2026-07-21", 100, 207),
            ("2026-07-22", 101.5, 210),
        )
        table = xq_indicator.table_from_excel_values(values)
        self.assertEqual(table["columns"], ["時間", "收盤價", "CodexPlot"])
        self.assertEqual(table["rows"][1]["收盤價"], 101.5)

    def test_rejects_empty_or_header_only_exports(self):
        invalid = (
            None,
            (("時間", "收盤價"),),
            (("時間", ""), ("2026-07-22", "2026-07-22")),
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    xq_indicator.table_from_excel_values(values)

    def test_duplicate_unrelated_columns_are_disambiguated(self):
        table = xq_indicator.table_from_excel_values(
            (("時間", "OBV", "OBV"), ("2026-07-22", 1, 2))
        )
        self.assertEqual(table["columns"], ["時間", "OBV", "OBV [2]"])
        self.assertEqual(table["duplicate_source_columns"], ["OBV"])
        self.assertEqual(table["rows"][0]["OBV [2]"], 2)

    def test_comparison_rejects_ambiguous_required_column(self):
        table = xq_indicator.table_from_excel_values(
            (("時間", "收盤價", "CodexPlot", "CodexPlot"),
             ("2026-07-22", 100, 100, 100))
        )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            xq_indicator.compare_affine_column(
                table, "CodexPlot", "收盤價", 1, 0, 0
            )

    def test_affine_comparison_reports_complete_match(self):
        table = xq_indicator.table_from_excel_values(
            (
                ("時間", "收盤價", "CodexPlot"),
                ("2026-07-21", 100, 207),
                ("2026-07-22", 101.5, 210),
            )
        )
        result = xq_indicator.compare_affine_column(
            table, "CodexPlot", "收盤價", 2, 7, 0
        )
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["mismatch_count"], 0)
        self.assertEqual(result["max_absolute_delta"], 0)

    def test_affine_comparison_reports_mismatch_with_context(self):
        table = xq_indicator.table_from_excel_values(
            (
                ("時間", "收盤價", "CodexPlot"),
                ("2026-07-22", 100, 207),
            )
        )
        result = xq_indicator.compare_affine_column(
            table, "CodexPlot", "收盤價", 2, 8, 0
        )
        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["mismatch_count"], 1)
        self.assertEqual(result["max_absolute_delta"], 1)
        self.assertEqual(result["mismatch_examples"][0]["delta"], -1)

    def test_comparison_requires_numeric_finite_values_and_columns(self):
        table = {"columns": ["收盤價", "CodexPlot"], "rows": [{"收盤價": "x", "CodexPlot": 1}]}
        with self.assertRaisesRegex(ValueError, "not numeric"):
            xq_indicator.compare_affine_column(table, "CodexPlot", "收盤價", 1, 0, 0)
        with self.assertRaisesRegex(ValueError, "Required export column"):
            xq_indicator.compare_affine_column(table, "Missing", "收盤價", 1, 0, 0)
        with self.assertRaisesRegex(ValueError, "tolerance"):
            xq_indicator.compare_affine_column(table, "CodexPlot", "收盤價", 1, 0, -1)

    def test_parser_accepts_zero_max_rows_but_rejects_negative(self):
        parser = xq_indicator.build_parser()
        args = parser.parse_args(
            [
                "--config",
                "x.json",
                "--script-name",
                "Demo",
                "--plot-label",
                "P1",
                "--restore-bookmark",
                "Chart",
                "--max-rows",
                "0",
            ]
        )
        self.assertEqual(args.max_rows, 0)


if __name__ == "__main__":
    unittest.main()
