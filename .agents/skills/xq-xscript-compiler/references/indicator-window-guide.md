# 指標實際繪圖結果擷取指南

本文件記錄 XQ 3.19.03（260608）在 Windows 上實際驗證過的指標加入、原生資料匯出、數值比對與復原流程。這些證據證明指定商品、頻率、圖表期間與公式的 Plot 輸出；不等同策略獲利、所有商品／頻率相容或視覺樣式正確。

## 使用前提

- 指標腳本已在當次任務取得真實 XScript `success`。
- XQ 已登入、桌面解鎖，且 `.xq-auto-writer/xq-ui.json` 的 `calibrated` 為 `true`。
- 目前作用頁包含技術分析圖。若同頁有多個 control ID `101` 的 `AfxWnd140` 圖表，以面積最大的可見且啟用控制項作為主技術圖。
- 必須指定一個目前可見且可唯一辨識的書籤，供臨時頁完成後復原。工具會在任何成功或失敗路徑嘗試恢復該書籤；無法預先確認書籤時不得開始修改圖表。
- 指數日線書籤本身可能無法輸出資料。實測成功案例先開啟台股個股技術分析頁，再由工具複製成臨時頁；跨商品與跨頻率自動設定仍屬後續項目。

## 已驗證的 UI 路徑

1. 從 `自訂頁面(U)` 選取 `複製成新頁面(R)`，在未儲存的臨時副本操作，不覆寫原頁。
2. 在主技術圖的控制項內以相對位置開啟內容選單，選取 `增加副圖`。
3. 在 `新增副圖指標設定` 對話框中：
   - 使用左半部、control ID `1122` 的可見搜尋框；同一對話框也可能有參數欄位使用相同 ID，因此不能只靠 ID 選取。
   - 搜尋後只接受 `XS指標 > 自訂 > <精確腳本名稱>` 的唯一命中。
   - 選取後按 control ID `1` 的完成按鈕；失敗時以 control ID `2` 取消對話框。
4. 再次開啟圖表內容選單，選取 `輸出到Excel`。XQ 會直接建立未儲存活頁簿，不會先詢問檔名。
5. Excel 活頁簿建立早於資料填入；必須等到 UsedRange 至少含標題與一筆資料，不能在偵測到活頁簿後立即讀取。
6. 讀取第一張工作表的標題與資料列後，只關閉本次新增的活頁簿且不儲存。若 Excel 是本次啟動且沒有其他活頁簿，才結束該 Excel 實例；不得關閉使用者原有 Excel。
7. 點擊預先驗證的書籤並讀回頁面標題，證明臨時頁已復原。復原失敗時整體結果為 `automation_error`，即使數值已擷取也不得宣稱完成。

## Excel 多執行個體

`GetActiveObject("Excel.Application")` 只會回傳其中一個 Excel 實例，可能連到背景或舊實例。工具透過 Running Object Table 列舉所有可用 Excel Application，並以 Application HWND、活頁簿名稱及完整名稱建立前後快照；只有快照後新增的活頁簿可視為本次 XQ 匯出。

如果 XQ 啟動的 Excel 顯示 `取得正版 Office` 通知，只有在確認該 Excel 實例由本次操作啟動後，工具才會在關閉活頁簿後收尾該通知。

## 數值證據與狀態

`xq_indicator.py` 讀取 XQ 原生圖表匯出，不以螢幕像素估算 Plot 值。它支援兩種模式：

- 只指定 `--plot-label`：確認匯出存在該 Plot 欄位並回傳資料，狀態為 `success`。
- 另指定 `--expected-column`、乘數與偏移：逐列計算 `expected_column * multiplier + offset`，以絕對容許誤差比對 Plot 欄位。

狀態契約：

- `success`／退出碼 `0`：資料已擷取，且有設定期望值時全部列均相符。
- `mismatch`／退出碼 `2`：資料已擷取，但至少一列超出容許誤差；回傳總錯配數、最大絕對誤差及最多十筆明細。
- `automation_error`／退出碼 `3`：UI、Excel、欄位、資料格式或復原未能證明完成。

`--max-rows` 只限制 JSON 回傳的資料列，不限制實際比較列數。比較永遠涵蓋完整匯出資料。

同一使用者圖表可能已有兩個同名的非受測欄位。工具會保留第一欄名稱，並把後續重名欄依序標成 `名稱 [2]`、`名稱 [3]`，同時記錄原始重名清單；這可避免無關的重名指標阻擋指定 Plot 驗證。若 `--plot-label` 或 `--expected-column` 本身重名，來源即無法唯一判定，仍必須回傳 `automation_error`，不得任選其中一欄。

## 已驗證案例

在台積電 `2330` 日線圖加入下列已編譯指標：

```xs
{@type:indicator}

Plot1(Close * 2 + 7, "CodexPlot");
```

XQ 原生匯出共 179 列；以 `收盤價 * 2 + 7` 獨立驗算，179 列全數相符，最大絕對誤差為 `0`。將期望偏移刻意改成 `8` 時，工具回報 `mismatch`、179 列錯配、每列差值 `-1`，並仍完成書籤復原。這一組正反控制證明工具不會固定回報成功。

## 命令

先讓台股個股技術分析圖成為作用頁，再執行：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_indicator.py `
  --config .xq-auto-writer/xq-ui.json `
  --script-name CodexIndicatorCaptureV1 `
  --plot-label CodexPlot `
  --restore-bookmark '指數日線圖' `
  --expected-column '收盤價' `
  --expected-multiplier 2 `
  --expected-offset 7
```

不要把使用者自訂頁、私人商品清單、活頁簿內容或完整交易策略寫入共用知識庫。本文件只保存可泛化的 UI 契約與已公開商品的最小驗證結果。
