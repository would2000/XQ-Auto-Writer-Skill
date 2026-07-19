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
