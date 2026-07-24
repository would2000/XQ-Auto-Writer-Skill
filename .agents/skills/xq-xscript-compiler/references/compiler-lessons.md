# 已由 XQ 編譯器驗證的規則

Only append short rules that were demonstrated by a failed compile followed by a successful compile. Record the category and a minimal before/after pattern. Do not store whole strategies or unverified assumptions.

<!-- Example format:
## YYYY-MM-DD — category
- Diagnostic: normalized compiler message
- Rule: concise reusable rule
- Before: minimal invalid form
- After: minimal compiler-verified form
-->

## 2026-07-19 — alert

- Diagnostic: 在「警示」腳本中無法使用 `Alert`。
- Rule: 以條件成立時設定 `ret = 1` 觸發警示，不要在警示腳本中使用 `Alert` 關鍵字。
- Before: `Alert`
- After: `if condition then ret = 1;`

## 2026-07-19 — alert

- Diagnostic: 識別字以 `Session` 開頭時，編譯器回報 `Session` 是目前版本不支援的保留字，並可能連帶產生布林運算型態錯誤。
- Rule: 自訂輸入與變數名稱不要以 `Session` 開頭，改用不衝突的名稱。
- Before: `input: SessionStart(090000);`
- After: `input: MarketStartTime(090000);`

## 2026-07-19 — function (number)

- Diagnostic: 函數腳本名稱含中文時，將名稱直接寫成回傳變數會產生無法辨認的字與未知關鍵字錯誤。
- Rule: 使用通用 `retval` 指定函數回傳值，尤其是腳本名稱不是合法 XScript 識別字時。
- Before: `含中文的函數名稱 = close - open;`
- After: `retval = close - open;`

## 2026-07-19 — autotrade

- Diagnostic: `腳本內容不可為空白或只含註解。`
- Rule: 新的自動交易腳本優先使用官方 preset 與目前編譯器皆驗證通過的 `{@type:autotrade}`，且標頭之外必須包含至少一個可執行陳述式；只放類型標頭仍會被視為空白。目前編譯器也接受 `{@type:strategy}`，但匯入的官方 preset 沒有使用此別名。
- Before: `{@type:autotrade}`
- After: `variable: calibrationValue(0); calibrationValue = close;`

## 2026-07-22 — indicator

- Diagnostic: 指標腳本中，變數名稱以 `Exp` 開頭時，編譯器回報 `"Exp" 不允許當成變數開頭` 及保留字錯誤，並產生未宣告變數等連鎖錯誤。
- Rule: 指標自訂變數不要以 `Exp` 開頭；改用不與目前保留字前綴衝突的名稱。
- Before: `variable: ExpectedValue(0);`
- After: `variable: TargetValue(0);`

## 2026-07-22 — screener

- Diagnostic: `OutputField` 第 3 個參數超出範圍時，編譯器回報應為 integer `0 ~ 4`。
- Rule: 選股腳本的 `OutputField` 第 3 個小數位參數只能使用 0 至 4 的整數。
- Before: `OutputField(1, value1, 6, "Value");`
- After: `OutputField(1, value1, 4, "Value");`

## 2026-07-22 — autotrade

- Diagnostic: 自動交易 caller 的變數名稱以 `Daily` 開頭時，編譯器回報 `"Daily" 不允許當成變數開頭`，並產生保留字、未宣告變數與型態不符等連鎖錯誤。
- Rule: 自訂變數不要以 `Daily` 開頭；跨頻率日資料變數改用不衝突的 `Xf` 或 `PriorDay` 前綴。
- Before: `variable: DailyCurrent(0);`
- After: `variable: XfCurrentValue(0);`
