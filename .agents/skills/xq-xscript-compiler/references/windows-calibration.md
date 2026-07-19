# Windows 校準與「錄製」方式

## 為何不能直接錄製 Codex skill

OpenAI 的 Codex Record & Replay 目前只在 macOS 提供，且需啟用 Computer Use。XQ 全球贏家是 Windows 軟體，因此本專案採用 UI Automation 控制項校準，而不是螢幕座標巨集。控制項識別碼通常比固定滑鼠座標可靠。

## 第一次校準

1. 安裝 Python 3.10+，再執行：

   ```powershell
   python -m pip install -r .agents/skills/xq-xscript-compiler/scripts/requirements.txt
   ```

2. 開啟並登入 XQ 全球贏家。第一次校準時可手動進入 XScript 編譯器，讓程式碼編輯區、編譯按鈕與結果區都可見。
3. 探測視窗與控制項：

   ```powershell
   python .agents/skills/xq-xscript-compiler/scripts/probe_xq_ui.py --title-re "^XScript.*" --output .xq-auto-writer/control-tree.txt
   ```

4. 在 `control-tree.txt` 找出下列控制項的穩定屬性：
   - 程式碼編輯區 `editor`
   - 編譯按鈕 `compile_button`
   - 編譯訊息區 `result`
5. 將 `auto_id`、`control_type`、`title` 或 `title_re` 填入 `.xq-auto-writer/xq-ui.json`。優先使用 `auto_id + control_type`，避免只用會隨內容變動的標題。
6. 校準 `launcher`：確認 XQ 主視窗的「策略」選單可開啟 XScript。校準 `new_script_dialog`：記錄「新增腳本」對話框內五種腳本、名稱、函數回傳類型、確認與取消的 Win32 control ID。避免使用固定螢幕座標。
7. 對五種腳本及函數三種回傳類型執行 `xq_prepare_script.py --dry-run`；工具會驗證選項後按取消，不留下測試文件。再至少實際建立並編譯一份安全的最小腳本，確認開啟、建檔、寫入與編譯能串接。
8. 先以不含交易指令的最小測試碼測試每一類。確認工具能讀到真實的成功與完整錯誤訊息後，才把 `calibrated` 改為 `true`。在自動建立動作完成前保留 `requires_preopened_script: true`；完成後才改為 `false`。

   驗證尚未列入 `verified_preopened_types` 的類型時，在編譯命令加入 `--calibration-mode`；成功、錯誤、修復三段測試皆通過後，再把該類型加入清單。正式腳本工作流不得使用這個旗標繞過校準保護。

## 每類應錄下的穩定流程

對指標、選股、警示、函數、自動交易各做一次相同示範：開啟 XScript 編譯器、新增對應類型、聚焦編輯區、貼上最小測試碼、按編譯、確認結果區。不要錄登入、下單、帳號切換或任何密碼輸入。這裡的「錄製」是儲存選單與 control ID，不是錄製滑鼠座標影片。

## 失效時

XQ 更新後若按鈕或控制項改名，將 `calibrated` 改回 `false`，重新執行探測並更新選擇器。不要用「等幾秒後沒看到錯誤」取代成功訊息判定。
