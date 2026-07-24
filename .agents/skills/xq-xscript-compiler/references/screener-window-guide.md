# 選股中心實際執行與結果擷取指南

本文件只記錄在 Windows、XQ 全球贏家個人版 3.19.03（260608）真實驗證過的選股中心流程。它是 UI 自動化證據，不是選股績效或未來版本相容性的保證。

## 已驗證入口與物件層級

- 主程式入口是 `策略(D) → 選股中心(S)...`；`選股(B) → 台股即時選股` 是盤中訊號頁，不是 XScript 選股策略的執行中心。
- 選股中心是獨立頂層視窗，標題以 `選股中心` 開頭，類別為 `AfxFrameOrView140`。
- 上方工具列為 `ToolbarWindow32`。正式選擇器使用 command ID，不使用固定螢幕座標：新增策略 `17551`、啟動 `17554`、停止 `17555`。
- 策略搜尋框 control ID 為 `17786`；策略清單是 `MFCGridCtrl`、control ID `20200`。自繪表格不提供可靠儲存格文字，因此先以唯一策略名稱搜尋，再相對於已驗證表格選取唯一列。
- 結果工具列也是 `ToolbarWindow32`；原生匯出 command ID 為 `20616`。結果類型下拉 control ID `20665`，目前確認包含 `符合條件商品`，介面也提供切換至執行錯誤商品的提示。
- `啟動腳本內Print指令` 核取方塊 control ID 為 `17540`，確認了官方文件所述的選股中心 Print 開關確實存在；除錯完成後應關閉，避免雲端執行時間增加。

## 腳本到結果的必要層次

已編譯的選股腳本不會自動成為可執行策略。必須在選股中心新增策略、指定公開選股範圍，於 `選股腳本` 頁籤加入該腳本，再完成策略建立。新增策略視窗已驗證：

- 策略名稱 `20067`、市場 `20853`、方向 `20011`、範圍 `20069`。
- `選股腳本` 頁籤 `20014`、腳本搜尋 `17053`、腳本清單 `20000`、已加入腳本名稱 `18710`、完成 `1`、取消 `2`。
- 測試應使用唯一的 Codex 名稱與公開系統範圍；不得讀取或執行使用者既有自選群組或私人策略。

## 結果擷取契約

### 從程式碼到結果的一鍵管線

`xq_screener_pipeline.py` 依序呼叫建檔、編譯及選股執行工具，所有階段只輸出一個頂層 JSON：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_screener_pipeline.py `
  --config .xq-auto-writer/xq-ui.json `
  --source generated/example.xs `
  --script-name CodexScreenPipeline `
  --strategy-name CodexScreenPipeline `
  --universe '台灣五十成分股(系統)' `
  --direction unspecified
```

- 先驗證校正檔、UTF-8 程式碼、名稱、逾時與輸出路徑，無效輸入不接觸 XQ。
- 以 `screener` 類型建立全新文件；只有當次 `xq_compile.py` 回傳 `success` 才能進入策略建立，`compile_error` 原樣保留 `compiler_output` 並停止。
- 每個子工具必須只輸出一個有效 JSON，退出碼與 `status` 必須同時成功；否則管線保留失敗階段與已完成階段證據。
- XQ 3.19.03 實測新增策略腳本搜尋框首次偶爾不產生無結果狀態。只有子工具明確回傳 `strategy_created: false` 且錯誤來自 control `17053` 初始化時，管線才重新開啟乾淨流程並限重試一次；其他錯誤一律不重播。
- 編譯成功後，只關閉本次新增且標題符合 `[<指定名稱>(選股)]` 的 XScript 編輯器。Windows handle 已銷毀或視窗已隱藏都代表使用者畫面已收尾；既有編輯器、名稱不符的視窗及編譯錯誤文件不得關閉。

2026-07-22 以 `CodexScreenPipelineV2` 在真實 XQ 3.19.03 完成整條路徑：建檔成功、編譯回報 0 項錯誤與 0 項警告、建立公開台灣 50 策略、命中 50 筆，並從原生 CSV 擷取 `Close` 與 `Volume`。本次首次搜尋初始化失敗，符合安全條件的第二次嘗試成功，證明有限重試路徑可用。

### 已編譯策略的建立與執行

`xq_screener.py` 可建立新的台股策略，或執行已存在且以名稱唯一搜尋到的策略。建立時只接受公開的 XQ `(系統)` 範圍，不接受使用者 `(自選)` 清單；它不覆寫或修改同名策略。

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_screener.py `
  --config .xq-auto-writer/xq-ui.json `
  --strategy-name CodexCaptureAuto `
  --create-strategy `
  --script-name CodexCompiledScreener `
  --universe '台灣五十成分股(系統)' `
  --direction unspecified
```

建立流程會先用必定無結果的哨兵文字確認 XQ 搜尋真的刷新，再搜尋目標腳本；因為只用 `WM_SETTEXT` 實測可能不觸發新增策略視窗的篩選。加入後還要從 `18710` 讀回條件列，要求完整名稱與請求完全相同，才可按完成。目標不存在或讀回不符時必須按取消並關閉新增視窗，不能沿用上一個可見腳本。成功建立後，工具按下啟動、等待短任務完成或停止鍵狀態復原，再用 XQ 原生 `匯出選股結果` 取得 CSV，最後輸出單一 JSON。

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_screener.py `
  --config .xq-auto-writer/xq-ui.json `
  --strategy-name CodexCapturePositive `
  --max-rows 100
```

- XQ 3.19.03 的 CSV 是 CP950，前三列依序為結果種類、資料日期與策略，第四列是欄位名稱。
- 資料列的第一個分隔符實測為 TAB 加逗號，其餘欄位遵循 CSV 引號規則；解析器先正規化第一個分隔符，再交由 CSV parser 處理，不能用單純 `split(',')`。
- 0 筆不是錯誤。XQ 會輸出 `無任何符合選股條件的商品`，工具回傳 `status: success`、`matched_count: 0`、`rows: []`。
- 匯出內的策略名稱必須與請求完全相同，否則結果視為自動化錯誤，避免把上一個策略結果誤認為本次執行。
- `--create-strategy` 必須與 `--script-name` 一起提供；成功結果回傳 `strategy_created: true`、腳本、市場、方向與範圍。重名或找不到腳本回傳 `failure`、退出碼 2。
- 預設原生 CSV 只存在於暫存目錄，解析後刪除；若明確傳入 `--native-export` 才保留，且拒絕覆寫既有檔案。
- `--max-rows` 只限制 JSON 回傳列數；`matched_count` 仍是原生結果的完整筆數，並以 `truncated` 揭露是否截斷。
- 工具自行開啟選股中心時，結束後會關閉；新增與匯出對話框在成功或失敗後都不得殘留。既有的選股中心不由工具擅自關閉。

## 執行錯誤明細

結果類型 ComboBox control ID `20665` 的索引 `3` 是 `執行錯誤的商品`。完成一次執行後，工具先匯出索引 `0` 的符合商品，再切換索引 `3` 匯出錯誤商品，最後恢復呼叫前的索引。兩份檔案都必須回讀策略名稱與結果類型，避免把舊結果當成當次結果。

XQ 3.19.03 的錯誤 CSV 欄位為 `序號`、`代碼`、`商品`、`錯誤訊息`。`RaiseRunTimeError("CODEX_SCREENER_RUNTIME_DETAIL_V1")` 實測只輸出自訂訊息，沒有附帶 `1301`；因此結構化資料保留 `error_code: null`。只有目前錯誤訊息自身含 `(數字)` 時才擷取代碼，不得由自動交易錯誤碼表反推。沒有錯誤時，XQ 的資料列是 `所有商品都已正常執行!!`，解析為空陣列。

分類契約：

- `success`：錯誤 0 筆；命中可以是 0 筆或多筆。
- `failure`：有執行錯誤且沒有命中。
- `partial_failure`：同時有命中與執行錯誤。
- `error_count` 永遠是錯誤 CSV 完整筆數；`--max-error-rows` 只限制回傳明細，並由 `errors_truncated` 揭露截斷。

## 逾時中止及復原

啟動 command ID 是 `17554`，停止 command ID 是 `17555`。逾時處理必須先讀取按鈕狀態；只有停止鍵仍啟用才送出停止。之後在獨立的 `--stop-recovery-seconds` 期限內，要求啟動鍵啟用且停止鍵停用：

- 已恢復：回傳 `cancelled`、`timed_out: true`、`stop_requested: true`、`recovery_complete: true`，並略過結果匯出，避免擷取前一次執行資料。
- 在逾時邊界已自行完成：啟動鍵已啟用且停止鍵停用，依完成路徑擷取結果，不誤報取消。
- 未恢復：回傳 `automation_error` 與最後按鈕狀態，不關閉選股中心，供人工確認；不得聲稱停止成功。

2026-07-22 以 `CodexScreenTimeoutAllV1`、公開 `普通股全部(系統)` 和安全錯誤腳本實測：工具觀察到執行中、按下停止，沒有額外確認窗，接著讀回啟動可用、停止停用，回傳 `cancelled` 且沒有匯出結果。

## 真實控制測試

2026-07-22 以兩個新建、已編譯的最小腳本和公開的 `台灣五十成分股(系統)` 驗證：

- 固定 `ret = 1`：XQ 實際回傳 50 筆，原生 CSV 含 `Close`、`Volume` 兩個 `OutputField` 欄位，工具成功轉為 JSON。
- 固定 `ret = 0`：XQ 實際回傳 0 筆，工具保留成功終態並輸出空陣列。
- 不存在的策略名稱：工具不執行其他策略，回傳 `failure` 與退出碼 2。
- 自動建立策略：加入固定命中腳本後得到 50 筆；加入固定空結果腳本後得到 0 筆。重名建立被拒絕且不覆寫。
- 缺少腳本：在搜尋刷新修正後回傳 `failure`，新增對話框取消且沒有建立半成品策略。
- 執行錯誤：`CodexScreenErrorDetailV1` 對台灣 50 實際得到錯誤 50、命中 0；錯誤訊息完整保留固定標記，代碼維持空值。
- 正常錯誤檢查：`CodexScreenPipelineV2` 實際得到命中 50、錯誤 0。
- 逾時停止：`CodexScreenTimeoutAllV1` 在普通股全部範圍觀察到執行中，停止後控制項完整復原。

這些結果證明當時版本中的執行與擷取鏈路，不證明使用者條件的投資合理性、資料正確性、獲利能力或未來版本 UI 相容性。
