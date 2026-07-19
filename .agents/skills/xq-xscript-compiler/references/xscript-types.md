# XScript 類型契約

Use this file to keep the generated program aligned with the selected XQ compiler category. Exact XScript syntax must come from repository examples or real compiler feedback; do not invent APIs.

## 指標 (`indicator`)

- Produce the requested plotted or reported series.
- Expose user-tunable periods and thresholds as inputs when appropriate.
- Avoid order placement and position mutation.

## 選股 (`screener`)

- Express a deterministic inclusion condition for the current symbol.
- Keep ranking, filters, and required data frequency explicit.
- Avoid stateful trade execution.

## 警示 (`alert`)

- Express the event condition and any cooldown or repeated-trigger behavior.
- Make cross-over versus level conditions unambiguous.
- Avoid placing orders unless the user changes the category to automatic trading.

## 函數 (`function`)

- Require one return subtype: 數值 (`number`, `{@type:function}`), 邏輯值 (`boolean`, `{@type:function_bool}`), or 字串 (`string`, `{@type:function_string}`).
- Define the function name, parameters, return meaning, and edge cases.
- Keep the function reusable and free of unnecessary chart or order side effects.
- Confirm the calling convention using a verified local example or compiler output.

## 自動交易 (`autotrade`)

- Prefer the official preset header `{@type:autotrade}`. The current local compiler has also accepted `{@type:strategy}`, but the imported official preset contains no `strategy` headers.
- Separate entry, exit, position sizing, and risk controls.
- State assumptions about bar frequency, order timing, and existing positions.
- Require explicit confirmation before adding live-account identifiers or broker-specific behavior.
- Treat a successful compilation as syntax validation only; recommend simulation/backtesting before live use.
