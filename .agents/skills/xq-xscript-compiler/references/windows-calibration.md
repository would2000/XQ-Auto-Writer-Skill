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
7. 另校準新增腳本的儲存位置路徑：儲存位置 Edit、資料夾 Button、類型限定的「選擇資料夾」TreeView、`自訂` 根節點、確認／取消，以及缺少 CODEX 時的標準內容選單與「新增資料夾」對話框。必須先選腳本類型，再進入資料夾瀏覽器；不得以自繪分類頁籤代替類型路由。
8. 對五種腳本及函數三種回傳類型執行 `xq_prepare_script.py --dry-run`；工具會驗證選項、精確 `自訂/CODEX/` 儲存位置後按取消，不留下測試文件。再至少實際建立並編譯一份安全的最小腳本，確認開啟、建檔、寫入與編譯能串接。
9. 先以不含交易指令的最小測試碼測試每一類。確認工具能讀到真實的成功與完整錯誤訊息後，才把 `calibrated` 改為 `true`。在自動建立動作完成前保留 `requires_preopened_script: true`；完成後才改為 `false`。

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

2026-07-25 針對自動切換再校正 XQ 3.19.03，結果仍為 fail-closed：

- 公式 host `1100 → 1000` 的 Win32 子窗格只有已知五個內容 pane；host 沒有原生 Menu、`WS_TABSTOP` 或 `WM_GETDLGCODE` 的方向鍵／Tab 鍵要求。
- UIA control view、Raw View 與 MSAA 皆未暴露具有「指標／選股／警示／交易／函數」名稱及 `Invoke`、`Select` 或 default action 的頁籤元素。Raw UIA 探測 129 個節點、MSAA 探測 883 個節點，匹配數都是零。
- 以正式選單快捷鍵慢速開啟「檢視(V)」，唯一選單只讀回「佈景主題、工具列、公式區、訊息區、屬性區」，沒有五類切換命令；選單已用 Esc 正常關閉。
- XQ 官方「公式區」說明只記錄頁籤與滑鼠左鍵操作，官方「工具列」快捷鍵清單也沒有分類切換快捷鍵。這是文件證據，不代表可以用滑鼠座標自動化。

因此目前 `.xq-auto-writer/xq-ui.json` 的 `formula_category_switch.method` 必須維持 `manual_only`，`automatic_switch_available` 必須維持 `false`。可執行：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_category_selector.py `
  --config .xq-auto-writer/xq-ui.json --script-type <type>
```

工具只讀回目前唯一可見 pane、TreeView 與 `自訂/CODEX` 直接階層。目標分類已在前景且 CODEX 唯一時回傳 `success`；否則回傳 `automation_error`、`manual_switch_required: true`、`input_sent: false`。不得用 `ShowWindow` 切換內容 pane、把 pane control ID 猜成 `WM_COMMAND`、嘗試未文件化快捷鍵、建立臨時空腳本或用幾何點擊補救。文件頁籤只暴露為 MDI 文件子視窗，未暴露可操作的 `TabItem`；特定分類工作一律由使用者先手動切換，再以 selector 驗證。

## 新增腳本儲存位置路徑

2026-07-25 在 XQ 3.19.03 以零座標真實讀回：

- 「新增腳本」類型 IDs：指標 `30048`、選股 `30050`、警示 `30049`、交易 `30051`、函數 `30047`；儲存位置 Edit `30023`，資料夾 Button `30003`。
- 點擊資料夾 Button 後，唯一「選擇資料夾」對話框為 `#32770`，TreeView ID `30065`，確認 `30002`、取消 `30003`。先選類型會使此 TreeView 限定在對應類型，根節點顯示精確 `自訂`。
- TreeView 內的 CODEX 顯示為精確直接子節點 `CODEX`，不是主公式樹的 `CODEX (<count>)`。缺少時，對精確 `自訂` 根節點執行控制項層級右鍵，標準 `#32768` 選單唯一讀回「新增資料夾」。
- 「新增資料夾」對話框為 `#32770`，名稱 Edit `30021`、確認 `30002`、取消 `30003`。輸入 CODEX 後，必須回到 TreeView 重新讀回唯一 `自訂 > CODEX`，選取並確認，再從新增腳本 Edit `30023` 讀回精確 `自訂/CODEX/`。
- 真實交易分支先由使用者刪除 CODEX，工具依上述路徑補建並讀回成功；函數分支讀回既有唯一 CODEX，沒有重複建立。其後正式 `xq_prepare_script.py --dry-run` 在交易與數值函數皆回傳 `success`、`readback_verified: true`、`created_folder: false`，並取消新增腳本，沒有留下測試文件。

此路徑取代「先自動切換五個自繪分類頁籤」作為新建文件的必要條件。自繪頁籤窗格 ID 仍可用於唯讀判斷目前分類與管理既有文件，但不得用於猜測切換命令。

## 失效時

XQ 更新後若按鈕或控制項改名，將 `calibrated` 改回 `false`，重新執行探測並更新選擇器。不要用「等幾秒後沒看到錯誤」取代成功訊息判定。
