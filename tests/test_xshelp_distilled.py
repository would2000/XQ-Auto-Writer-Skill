from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
    / "search_xshelp_distilled.py"
)
KNOWLEDGE = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "references"
    / "xshelp-distilled"
    / "quote-fields.json"
)
MANIFEST = KNOWLEDGE.with_name("manifest.json")
INDEX = PROJECT_ROOT / "third_party" / "xshelp" / "index.json"


class XSHelpDistilledTests(unittest.TestCase):
    def run_search(self, knowledge: Path, query: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--knowledge", str(knowledge), "--query", query],
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=20,
            check=False,
        )

    def test_production_knowledge_contract_and_search(self) -> None:
        data = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        self.assertFalse(data["body_text_stored"])
        self.assertEqual(len(data["records"]), 132)
        self.assertEqual(len({item["source_id"] for item in data["records"]}), 132)
        self.assertTrue(all(item["verification_status"] == "文件蒸餾" for item in data["records"]))
        self.assertTrue(all(item["retrieved_at"] == "2026-07-20" for item in data["records"]))
        self.assertTrue(all("source_version" in item for item in data["records"]))
        self.assertTrue(all(isinstance(item["q_identifier"], str) for item in data["records"]))
        self.assertEqual(len(manifest["completed_source_ids"]), 132)
        self.assertEqual(manifest["coverage"]["distilled_quote_fields"], 132)
        self.assertEqual(manifest["coverage"]["quote_field_percent"], 100.0)
        self.assertEqual(
            manifest["last_batch"]["batch_id"],
            "quote-fields-complete-007",
        )
        self.assertEqual(manifest["last_batch"]["succeeded"], 12)
        self.assertEqual(manifest["last_batch"]["failed"], 0)
        record_ids = {item["source_id"] for item in data["records"]}
        self.assertEqual(record_ids, set(manifest["completed_source_ids"]))
        indexed = {item["id"]: item for item in index["documents"]}
        self.assertTrue(record_ids.issubset(indexed))
        quote_category_codes = {
            "QOFTEN", "QPRICE", "QVOLUME", "QFINANCE", "QMARKET", "QOPTION", "QFIVE"
        }
        indexed_quote_ids = {
            item["id"]
            for item in index["documents"]
            if quote_category_codes.intersection(item["category_codes"])
        }
        self.assertEqual(len(indexed_quote_ids), 132)
        self.assertEqual(record_ids, indexed_quote_ids)
        self.assertFalse(indexed_quote_ids - record_ids)
        for item in data["records"]:
            self.assertEqual(item["name"], indexed[item["source_id"]]["name"])
            self.assertEqual(item["url"], indexed[item["source_id"]]["url"])
            self.assertTrue({"syntax", "description", "html", "body"}.isdisjoint(item))

        result = self.run_search(KNOWLEDGE, "成交量 台股")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreater(payload["match_count"], 0)
        self.assertIn("警示", payload["matches"][0]["supported_scripts"])
        self.assertIn("access_names", payload["matches"][0])

        depth = self.run_search(KNOWLEDGE, "委買3 期貨")
        self.assertEqual(depth.returncode, 0, depth.stderr)
        depth_match = json.loads(depth.stdout)["matches"][0]
        self.assertEqual(depth_match["name"], "委買3")
        self.assertEqual(depth_match["book_side"], "buy")
        self.assertEqual(depth_match["level"], 3)
        self.assertEqual(depth_match["value_kind"], "size")
        self.assertIn("口", depth_match["unit"])

        depth_records = [item for item in data["records"] if item.get("category") == "五檔統計"]
        self.assertEqual(len(depth_records), 28)
        indexed_depth_ids = {
            item["id"] for item in index["documents"] if "QFIVE" in item["category_codes"]
        }
        self.assertEqual({item["source_id"] for item in depth_records}, indexed_depth_ids)
        for side in ("buy", "sell"):
            for kind in ("price", "size"):
                levels = sorted(
                    item["level"]
                    for item in depth_records
                    if item.get("book_side") == side
                    and item.get("value_kind") == kind
                    and isinstance(item.get("level"), int)
                )
                self.assertEqual(levels, [1, 2, 3, 4, 5])

        option_records = [item for item in data["records"] if item.get("category") == "期權"]
        self.assertEqual(len(option_records), 28)
        indexed_option_ids = {
            item["id"] for item in index["documents"] if "QOPTION" in item["category_codes"]
        }
        self.assertEqual({item["source_id"] for item in option_records}, indexed_option_ids)
        self.assertEqual(
            {item["name"] for item in option_records if item.get("value_kind") == "greek"},
            {"Delta", "Gamma", "Theta", "Vega", "RHO"},
        )
        remaining = self.run_search(KNOWLEDGE, "剩餘日 例假日")
        remaining_match = json.loads(remaining.stdout)["matches"][0]
        self.assertEqual(remaining_match["name"], "剩餘日")
        self.assertIn("包含例假日", remaining_match["meaning"])

        volatility = self.run_search(KNOWLEDGE, "波動率 23.12")
        volatility_names = {item["name"] for item in json.loads(volatility.stdout)["matches"]}
        self.assertIn("波動率", volatility_names)
        self.assertIn("買進隱含波動率", volatility_names)

        put_call = self.run_search(KNOWLEDGE, "賣權 買權 未平倉量")
        put_call_match = json.loads(put_call.stdout)["matches"][0]
        self.assertEqual(put_call_match["name"], "買賣權未平倉量比率")
        self.assertEqual(put_call_match["unit"], "比值")
        self.assertIn("PUT 未平倉量 / CALL 未平倉量", put_call_match["formula"])

        previous_prices = sorted(
            (item for item in data["records"] if item.get("value_kind") == "previous_trade_price"),
            key=lambda item: item["tick_offset"],
        )
        self.assertEqual([item["tick_offset"] for item in previous_prices], [1, 2, 3, 4])
        previous = self.run_search(KNOWLEDGE, "前四價 Tick")
        previous_match = json.loads(previous.stdout)["matches"][0]
        self.assertEqual(previous_match["name"], "前四價")
        self.assertIn("不是前 4 個交易日", previous_match["usage"])

        indexed_price_ids = {
            item["id"] for item in index["documents"] if "QPRICE" in item["category_codes"]
        }
        self.assertEqual(len(indexed_price_ids), 23)
        self.assertTrue(indexed_price_ids.issubset(record_ids))

        weekly = self.run_search(KNOWLEDGE, "一週前 五個交易日")
        weekly_match = json.loads(weekly.stdout)["matches"][0]
        self.assertEqual(weekly_match["lookback"], "5 trading days")
        self.assertTrue(weekly_match["adjusted_for_stocks"])

        basis = self.run_search(KNOWLEDGE, "基差 現貨 期貨")
        spread = self.run_search(KNOWLEDGE, "價差 期貨 現貨")
        self.assertEqual(
            json.loads(basis.stdout)["matches"][0]["formula"],
            "現貨價格 - 期貨價格",
        )
        self.assertEqual(
            json.loads(spread.stdout)["matches"][0]["formula"],
            "期貨價格 - 現貨價格",
        )

        completed_volume_ids = {
            item["source_id"]
            for item in data["records"]
            if "QVOLUME" in indexed[item["source_id"]]["category_codes"]
        }
        indexed_volume_ids = {
            item["id"] for item in index["documents"] if "QVOLUME" in item["category_codes"]
        }
        self.assertEqual(len(indexed_volume_ids), 27)
        self.assertEqual(completed_volume_ids, indexed_volume_ids)

        finance_records = [item for item in data["records"] if item.get("category") == "財務"]
        self.assertEqual(len(finance_records), 10)
        indexed_finance_ids = {
            item["id"] for item in index["documents"] if "QFINANCE" in item["category_codes"]
        }
        self.assertEqual({item["source_id"] for item in finance_records}, indexed_finance_ids)
        eps = self.run_search(KNOWLEDGE, "每股盈餘 近四季")
        eps_match = json.loads(eps.stdout)["matches"][0]
        self.assertEqual(eps_match["name"], "每股盈餘")
        self.assertIn("不可直接當作近四季", eps_match["usage"])

        roe = self.run_search(KNOWLEDGE, "股東權益報酬率 美股 單季")
        roe_match = json.loads(roe.stdout)["matches"][0]
        self.assertEqual(roe_match["market_period_basis"], "台股/陸股/港股=累計；美股=單季")

        opening_average = self.run_search(KNOWLEDGE, "開盤買均 開盤委買")
        opening_average_match = json.loads(opening_average.stdout)["matches"][0]
        self.assertEqual(opening_average_match["name"], "開盤買均")
        self.assertIn("開盤委買 / 開盤買筆", opening_average_match["formula"])

        revenue = self.run_search(KNOWLEDGE, "營收年增率 台股 每月")
        self.assertEqual(revenue.returncode, 0, revenue.stderr)
        revenue_match = json.loads(revenue.stdout)["matches"][0]
        self.assertEqual(revenue_match["name"], "營收年增率")
        self.assertIn("台股=每月", revenue_match["revenue_cadence"])
        self.assertIn("去年同期營收", revenue_match["formula"])

        breadth = self.run_search(KNOWLEDGE, "上漲家數 漲停家數 不含")
        self.assertEqual(breadth.returncode, 0, breadth.stderr)
        breadth_match = json.loads(breadth.stdout)["matches"][0]
        self.assertEqual(breadth_match["name"], "上漲家數")
        self.assertEqual(breadth_match["direction"], "up")
        self.assertIn("上漲家數不含漲停家數", breadth_match["caveats"])

        period = self.run_search(KNOWLEDGE, "財報期別 YYYYMM")
        self.assertEqual(period.returncode, 0, period.stderr)
        period_match = json.loads(period.stdout)["matches"][0]
        self.assertEqual(period_match["name"], "財報期別")
        self.assertIn("YYYYMM", period_match["format"])

        for category_code, expected_count in (("QOFTEN", 12), ("QMARKET", 4)):
            category_ids = {
                item["id"]
                for item in index["documents"]
                if category_code in item["category_codes"]
            }
            completed_ids = {
                item["source_id"]
                for item in data["records"]
                if category_code in indexed[item["source_id"]]["category_codes"]
            }
            self.assertEqual(len(category_ids), expected_count)
            self.assertEqual(completed_ids, category_ids)

    def test_mock_create_write_read_update_save_reload_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mock_path = Path(temporary) / "quote-fields.json"
            mock = {
                "schema_version": 1,
                "body_text_stored": False,
                "records": [
                    {
                        "source_id": "mock-1",
                        "name": "模擬量",
                        "category": "量能",
                        "unit": "張",
                        "format": "數值",
                        "supported_scripts": ["警示"],
                        "supported_products": ["台股"],
                        "timing": "即時",
                        "usage": "測試讀取",
                        "verification_status": "文件蒸餾",
                        "url": "https://xshelp.xq.com.tw/XSHelp/?mock=1",
                    }
                ],
            }
            mock_path.write_text(json.dumps(mock, ensure_ascii=False), encoding="utf-8")
            created = self.run_search(mock_path, "模擬量 台股")
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertEqual(json.loads(created.stdout)["matches"][0]["unit"], "張")

            reloaded = json.loads(mock_path.read_text(encoding="utf-8"))
            reloaded["records"][0]["unit"] = "股"
            mock_path.write_text(json.dumps(reloaded, ensure_ascii=False), encoding="utf-8")
            updated = self.run_search(mock_path, "模擬量 台股")
            self.assertEqual(json.loads(updated.stdout)["matches"][0]["unit"], "股")

        self.assertFalse(mock_path.exists())


if __name__ == "__main__":
    unittest.main()
