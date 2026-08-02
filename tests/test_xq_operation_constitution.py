from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = PROJECT_ROOT / "docs" / "XQ-OPERATION-CONSTITUTION.md"
AGENTS = PROJECT_ROOT / "AGENTS.md"
SKILL = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "SKILL.md"
README = PROJECT_ROOT / "README.md"


class XQOperationConstitutionTests(unittest.TestCase):
    def test_constitution_is_linked_from_every_persistent_entry_point(self) -> None:
        self.assertTrue(CONSTITUTION.is_file())
        for path in (AGENTS, SKILL, README):
            with self.subTest(path=path.name):
                self.assertIn(
                    "XQ-OPERATION-CONSTITUTION.md",
                    path.read_text(encoding="utf-8"),
                )

    def test_private_content_and_codex_folder_boundaries_are_explicit(self) -> None:
        text = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "最高優先持久規則",
            "只允許複製與唯讀讀取",
            "自訂範圍內建立或使用 `CODEX` 專用資料夾",
            "選股中心",
            "策略雷達",
            "本次 manifest",
            "刪除後再驗證不存在",
        ):
            self.assertIn(required, text)

    def test_account_slow_operation_cleanup_and_foreground_rules_are_explicit(self) -> None:
        text = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "不得操作 XQ 軟體帳號的登入或登出",
            "不得操作實際證券帳號下單功能",
            "只允許使用 XQ 內建模擬帳號",
            "`WaitGuiThreadIdle`",
            "立即停止後續輸入",
            "使用者指定成果及其必要函數必須保留",
            "保留本次成果腳本及其 XScript 編輯視窗",
            "XQ 軟體的主程式視窗必須最大化（非全螢幕）",
            "XScript 編輯器、技術線圖、報告或其他子視窗維持原本大小即可",
            "不得切換成無邊框或隱藏系統介面的全螢幕模式",
            "`IsZoomed`",
            "任務完成的最後前景一律切回 ChatGPT／Codex",
            "相關 XQ 視窗仍存在，以及 XQ 主程式視窗保持最大化（非全螢幕）",
        ):
            self.assertIn(required, text)

    def test_local_state_uses_exact_xq_window_capture_without_bypassing_gates(self) -> None:
        constitution = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "本機 XQ 視窗狀態不得長時間盲等",
            "目標 XQ 視窗或對話框",
            "不得截取整個桌面",
            "畫面證據不能取代編譯成功、報告、checkpoint 關聯",
        ):
            self.assertIn(required, constitution)
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("do not wait through a slow full-window UIA tree", skill)
        self.assertIn("capture only the uniquely identified XQ window or dialog", skill)

    def test_new_script_codex_creation_uses_type_scoped_storage_path(self) -> None:
        text = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "開啟「新增腳本」",
            "先選取並讀回腳本類型",
            "類型限定的「選擇資料夾」",
            "唯一 `自訂` 根節點",
            "唯一直接子節點 `CODEX`",
            "讀回精確 `自訂/CODEX/`",
            "不得為新建文件改用自繪分類頁籤",
        ):
            self.assertIn(required, text)

    def test_coordinate_fallback_is_limited_and_verifiable(self) -> None:
        constitution = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "能使用語意控制時不得改用座標",
            "才允許把座標當作最後手段",
            "不得沿用跨工作階段的固定螢幕座標",
            "每次只執行一個節流點擊",
            "座標例外絕對不得用於 XQ 登入／登出",
            "亦不得藉此規避私人內容不可變、CODEX 專區、manifest、刪除證據",
        ):
            self.assertIn(required, constitution)
        for path in (AGENTS, SKILL, README):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue("座標" in text or "coordinate" in text)

    def test_temporary_screenshots_and_reporting_rules_are_explicit(self) -> None:
        constitution = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "確有需要時建立畫面截圖",
            "知識已蒸餾並納入知識庫",
            "必須刪除非必要的暫存截圖及視覺探測檔",
            "清理後驗證不存在",
            "AI 模型只負責回報可觀察的客觀事實",
            "不得預設、替使用者選擇或暗示任何策略立場、腳本立場",
            "不得延伸推論為策略可行、能獲利、適合實盤、安全或具有投資價值",
        ):
            self.assertIn(required, constitution)
        agents = AGENTS.read_text(encoding="utf-8")
        self.assertIn("非必要暫存截圖與視覺探測檔已精確清理", agents)
        self.assertIn("不得預設策略或腳本立場", agents)
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("temporary-screenshot cleanup after knowledge distillation", skill)
        self.assertIn("Report only observable software settings", skill)

    def test_specific_category_uses_screenshot_switch_and_exact_codex_open(self) -> None:
        constitution = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "`xq_category_selector.py`",
            "記憶體截圖重新偵測五個穩定頁籤區段",
            "不得保存或沿用螢幕座標、比例或成功截圖",
            "`xq_open_existing_script.py`",
            "完整名稱匹配唯一的 CODEX 直接子文件",
            "建立臨時空腳本、密集點擊或推測命令繼續",
        ):
            self.assertIn(required, constitution)
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("xq_category_selector.py", skill)
        self.assertIn("xq_open_existing_script.py", skill)
        self.assertIn("requires five stable visual tab segments", skill)
        self.assertIn("must never persist or reuse screen coordinates", skill)
        self.assertIn("Match exactly one direct document", skill)
        self.assertIn("Never create a temporary routing document", skill)
        self.assertNotIn("xq_category_" + "tab_route.py", skill)

    def test_print_contract_preserves_exact_user_examples_and_requires_confirmation(self) -> None:
        text = CONSTITUTION.read_text(encoding="utf-8")
        self.assertIn(r'print(file("C:\print\"),date,symbol,close);', text)
        self.assertIn(
            r'print(file("c:\Print\[Symbol].log"),date,symbol,close);',
            text,
        )
        self.assertIn("第一次啟用 Print 檔案輸出前，必須向使用者確認", text)
        self.assertIn("C:\\SysJust\\XQLite", text)


if __name__ == "__main__":
    unittest.main()
