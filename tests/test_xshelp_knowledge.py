from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from sync_xshelp_index import build_index  # noqa: E402
from xshelp_common import load_index  # noqa: E402
from xshelp_common import DetailSectionParser, normalize_multiline  # noqa: E402


class MockXSHelpHandler(BaseHTTPRequestHandler):
    phase = 1
    list_b_failures = 0

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def send_html(self, status: int, body: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/robots.txt":
            self.send_html(404, "missing")
            return
        if parsed.path == "/XSHelp/" and not query:
            self.send_html(
                200,
                '<a href="/XSHelp/lists?a=A">類別A</a>'
                '<a href="/XSHelp/lists?a=B">類別B</a>',
            )
            return
        if parsed.path == "/XSHelp/lists" and query.get("a") == ["A"]:
            if self.phase == 3:
                self.send_html(503, "temporary failure")
                return
            self.send_html(
                200,
                '<h2>內建函數 - 測試A</h2>'
                '<a href="/XSHelp/?HelpName=Foo&group=A">Foo</a>'
                '<a href="/XSHelp/?HelpName=Shared&group=S">Shared</a>',
            )
            return
        if parsed.path == "/XSHelp/lists" and query.get("a") == ["B"]:
            if self.phase == 1 and self.list_b_failures == 0:
                type(self).list_b_failures += 1
                self.send_html(503, "retry me")
                return
            extra = '<a href="/XSHelp/?HelpName=Baz&group=B">Baz</a>' if self.phase == 2 else ""
            self.send_html(
                200,
                '<h2>資料欄位 - 測試B</h2>'
                '<a href="/XSHelp/?HelpName=Shared&group=S">Shared</a>'
                '<a href="/XSHelp/?HelpName=Bar&group=B">Bar</a>'
                + extra,
            )
            return
        if parsed.path == "/XSHelp/" and query.get("HelpName"):
            name = query["HelpName"][0]
            self.send_html(
                200,
                '<div class="result"><div class="content-txt">'
                f'<div class="fnc-title">{name} - (測試函數)</div>'
                f'<div class="syntax">{name} syntax body text</div>'
                f'<div class="desc"><p>{name} description body text</p></div>'
                "</div></div>",
            )
            return
        self.send_html(404, "not found")


class XSHelpKnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockXSHelpHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}/XSHelp/"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def run_cli(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args],
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=20,
            check=False,
        )

    def test_complete_metadata_flow_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            index_path = Path(temporary) / "index.json"
            MockXSHelpHandler.phase = 1
            MockXSHelpHandler.list_b_failures = 0
            first = build_index(
                base_url=self.base_url,
                index_path=index_path,
                delay_seconds=0,
                timeout_seconds=2,
                retries=2,
            )
            self.assertEqual(first["stats"]["category_count"], 2)
            self.assertEqual(first["stats"]["unique_document_count"], 3)
            self.assertEqual(first["stats"]["duplicates_merged"], 1)
            self.assertEqual(first["stats"]["retries"], 1)
            self.assertFalse(first["body_text_stored"])
            self.assertNotIn("syntax body text", index_path.read_text(encoding="utf-8"))

            reloaded = load_index(index_path)
            self.assertEqual(len(reloaded["documents"]), 3)
            shared = next(item for item in reloaded["documents"] if item["name"] == "Shared")
            self.assertEqual(shared["category_codes"], ["A", "B"])

            search = self.run_cli(
                "search_xshelp_index.py", "--index", str(index_path), "--query", "Foo"
            )
            self.assertEqual(search.returncode, 0, search.stderr)
            search_json = json.loads(search.stdout)
            self.assertEqual(search_json["matches"][0]["name"], "Foo")

            foo = next(item for item in reloaded["documents"] if item["name"] == "Foo")
            before_fetch = index_path.read_bytes()
            fetch = self.run_cli(
                "fetch_xshelp_page.py", "--index", str(index_path), "--id", foo["id"]
            )
            self.assertEqual(fetch.returncode, 0, fetch.stderr)
            fetch_json = json.loads(fetch.stdout)
            self.assertIn("Foo syntax", fetch_json["content"]["syntax"])
            self.assertFalse(fetch_json["cached"])
            self.assertEqual(before_fetch, index_path.read_bytes())

            invalid = self.run_cli(
                "fetch_xshelp_page.py",
                "--index",
                str(index_path),
                "--url",
                self.base_url + "?HelpName=NotIndexed&group=A",
            )
            self.assertEqual(invalid.returncode, 3)

            MockXSHelpHandler.phase = 2
            updated = build_index(
                base_url=self.base_url,
                index_path=index_path,
                delay_seconds=0,
                timeout_seconds=2,
                retries=1,
            )
            self.assertEqual(updated["stats"]["unique_document_count"], 4)
            self.assertIn("Baz", [item["name"] for item in load_index(index_path)["documents"]])

            stable_bytes = index_path.read_bytes()
            MockXSHelpHandler.phase = 3
            with self.assertRaises(RuntimeError):
                build_index(
                    base_url=self.base_url,
                    index_path=index_path,
                    delay_seconds=0,
                    timeout_seconds=2,
                    retries=0,
                )
            self.assertEqual(stable_bytes, index_path.read_bytes())

    def test_current_quote_field_table_is_parsed(self) -> None:
        parser = DetailSectionParser()
        parser.feed(
            '<table><tr><td class="field-title text-right">欄位名稱</td>'
            '<td class="field-value">成交 (報價欄位)</td></tr>'
            '<tr><td class="field-title">語法</td><td class="field-vlaue">'
            '<pre><code>Value1 = GetQuote("成交");\nValue1 = q_Last;</code></pre></td></tr>'
            '<tr><td class="field-title">單位</td><td class="field-value">元</td></tr>'
            '<tr><td class="field-title">支援腳本</td><td class="field-value">'
            '<span>警示</span><span>交易</span><span>函數</span></td></tr>'
            '<tr><td class="field-title">說明</td><td class="field-value">最新成交價。</td></tr>'
            '</table>'
        )
        fields = {
            key: normalize_multiline("".join(value))
            for key, value in parser.fields.items()
        }
        self.assertEqual(fields["欄位名稱"], "成交 (報價欄位)")
        self.assertIn('GetQuote("成交")', fields["語法"])
        self.assertEqual(fields["單位"], "元")
        self.assertEqual(fields["支援腳本"], "警示交易函數")
        self.assertEqual(fields["說明"], "最新成交價。")


if __name__ == "__main__":
    unittest.main()
