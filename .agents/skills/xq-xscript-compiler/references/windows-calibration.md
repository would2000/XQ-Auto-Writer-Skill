# Windows 校準與「錄製」方式

## 為何不能直接錄製 Codex skill

OpenAI 的 Codex Record & Replay 目前只在 macOS 提供，且需啟用 Computer Use。XQ 全球贏家是 Windows 軟體，因此本專案採用 UI Automation 控制項校準，而不是螢幕座標巨集。所有 XQ 視窗都禁止固定、相對、矩形計算或猜測座標，也不得傳入 `coords`；必須使用可讀回且唯一的控制項或正式命令。

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
6. 校準 `launcher`：確認 XQ 主視窗的「策略」選單可開啟 XScript。校準 `new_script_dialog`：記錄「新增腳本」對話框內五種腳本、名稱、函數回傳類型、確認與取消的 Win32 control ID。不得使用固定、相對或矩形計算座標；缺少穩定控制項時停止校正。
7. 對五種腳本及函數三種回傳類型執行 `xq_prepare_script.py --dry-run`；工具會驗證選項後按取消，不留下測試文件。再至少實際建立並編譯一份安全的最小腳本，確認開啟、建檔、寫入與編譯能串接。
8. 先以不含交易指令的最小測試碼測試每一類。確認工具能讀到真實的成功與完整錯誤訊息後，才把 `calibrated` 改為 `true`。在自動建立動作完成前保留 `requires_preopened_script: true`；完成後才改為 `false`。

   驗證尚未列入 `verified_preopened_types` 的類型時，在編譯命令加入 `--calibration-mode`；成功、錯誤、修復三段測試皆通過後，再把該類型加入清單。正式腳本工作流不得使用這個旗標繞過校準保護。

## 每類應錄下的穩定流程

對指標、選股、警示、函數、自動交易各做一次相同示範：開啟 XScript 編譯器、新增對應類型、聚焦編輯區、貼上最小測試碼、按編譯、確認結果區。不要錄登入、下單、帳號切換或任何密碼輸入。這裡的「錄製」是儲存選單與 control ID，不是錄製滑鼠座標影片。

## XScript 自訂資料夾觀察

使用者可連續手動操作，代理則以唯讀觀察器記錄白名單控制項，不必要求使用者把右鍵選單固定在畫面：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_folder_observer.py `
  --events .xq-auto-writer/codex-folder-learning/<run>-events.jsonl `
  --status .xq-auto-writer/codex-folder-learning/<run>-status.json `
  --timeout-seconds 300 --poll-seconds 0.25
```

若要校正五個自繪公式分類頁籤，先啟動另一個只記錄穩定窗格切換的觀察器，再請使用者依序停留「指標 → 選股 → 警示 → 交易 → 函數」，每類至少三秒：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_category_observer.py `
  --events .xq-auto-writer/codex-folder-learning/<run>-category-events.jsonl `
  --status .xq-auto-writer/codex-folder-learning/<run>-category-status.json `
  --timeout-seconds 300 --poll-seconds 0.5 --stable-seconds 1.5
```

此觀察器只保存可見公式窗格 control ID、對應 TreeView handle、精確 `自訂`／`CODEX` 計數及 XScript 健康，不送輸入且不保存其他樹節點名稱。第一筆是啟動前基準，只有其後與使用者指定順序一致的五筆穩定切換才能建立分類對照。

觀察器不取得焦點、不送鍵盤或滑鼠輸入、不使用座標，只保存白名單系統文字與控制項 metadata；其他文字不落地。2026-07-24 在 XQ 3.19.03 的真實觀察取得：

- 公式區樹狀控制項為 Win32 `SysTreeView32`／control ID `45242`。
- 「自訂」根節點顯示為 `自訂 (<數量>)`；精確 CODEX 直接子節點顯示為 `CODEX (<數量>)`。授權位置必須由父子階層推導為 `自訂/CODEX/`，不得只因名稱含 `CODEX` 就通過。
- 右鍵內容選單是標準 Windows `#32768`，不是 `XTPPopupBar`；同一選單實際讀到「新增資料夾」。
- 使用者手動重新命名時，對話框類別為 `#32770`；舊名稱欄位 ID `30021` 為 disabled，新名稱欄位 ID `30022` 為 enabled，確認／取消 ID 分別為 `30001`／`30002`。輸入 `CODEX` 後，樹狀控制項精確讀回唯一 `CODEX (0)`。
- 使用者依序手動切換五類後，唯一可見公式窗格／TreeView 的對照為：指標 `1`／`661964`、選股 `4`／`1382856`、警示 `2`／`15139136`、交易 `7`／`662272`、函數 `3`／`6227360`。這些 handle 只屬於當次 XQ 行程；可攜識別應使用窗格 control ID、父層 `1000 → 1100` 與 TreeView control ID `45242`。

使用者說明的建立流程是：在「自訂」根節點開啟右鍵選單、選「新增資料夾」、輸入精確 `CODEX` 並確認。觀察器捕捉到該選單及最終父子讀回，但原始建立動作發生在觀察器啟動前；上述對話框 ID 是重新命名流程的真實證據，不得推測建立對話框必然完全相同。自動建立仍須另做一次完整、無座標、從命令到最終讀回的校正。

上述切換觀察已證明 XQ 3.19.03 當次行程的五種腳本類型窗格對照，但沒有證明自繪頁籤提供 UIA／MSAA `Invoke`／`Select` 或正式切換命令。不得把 control ID 對照直接當成可送出的 `WM_COMMAND`，也不得改用頁籤幾何位置。該次觀察只有指標分類讀回唯一 `CODEX (0)`；其餘四類仍為零個 CODEX 直接子節點。

## 失效時

XQ 更新後若按鈕或控制項改名，將 `calibrated` 改回 `false`，重新執行探測並更新選擇器。不要用「等幾秒後沒看到錯誤」取代成功訊息判定。
