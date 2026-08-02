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
- For historical backtests, follow [backtest-configuration-contract.md](backtest-configuration-contract.md) and [screener-backtest-product-guide.md](screener-backtest-product-guide.md): screener backtests are daily-or-higher only. Read back the default market/range as `台股` / `普通股全部(系統)` unless the user specifies otherwise; take-profit, stop-loss, maximum holding period (days), rebalancing, exits, holdings, and allocation require the user's explicit definition.

## 警示 (`alert`)

- Express the event condition and any cooldown or repeated-trigger behavior.
- Make cross-over versus level conditions unambiguous.
- Avoid placing orders unless the user changes the category to automatic trading.
- For historical backtests, follow [backtest-configuration-contract.md](backtest-configuration-contract.md) and [alert-backtest-product-guide.md](alert-backtest-product-guide.md): alerts can use daily or minute frequency, but exits, take-profit, stop-loss, and holding rules are backtest settings rather than script-controlled behavior. Default to the public `商品` source only when the user has not specified another source; take-profit and stop-loss require the user's explicit definition.

## 函數 (`function`)

- Require one return subtype: 數值 (`number`, `{@type:function}`), 邏輯值 (`boolean`, `{@type:function_bool}`), or 字串 (`string`, `{@type:function_string}`).
- Read [function-guide.md](function-guide.md), then define the function name, ordered parameter contract, return meaning/unit, edge cases, calculation mode, and supported callers/products/frequencies.
- Generated functions assign their result through `retval`; do not use filter/sensor `ret` or a localized XQ display name as the return variable.
- Keep the function reusable and free of unnecessary chart or order side effects.
- Run `xq_function_preflight.py`, create a new XQ function document with the matching return subtype, and obtain a real compiler `success` result.
- Confirm the calling convention using a verified local example or compiler output. For end-to-end reuse proof, also compile a minimal caller.

## 自動交易 (`autotrade`)

- Before designing an automatic trading script, read [autotrade-official-guide.md](autotrade-official-guide.md) for the `Position`/`Filled` state model and transaction semantics, then read [autotrade-learning-guide.md](autotrade-learning-guide.md) for strategy setup, wash modes, backtesting, inventory integration, monitoring, scheduling, and debugging contracts.
- Prefer the official preset header `{@type:autotrade}`. The current local compiler has also accepted `{@type:strategy}`, but the imported official preset contains no `strategy` headers.
- Separate entry, exit, position sizing, and risk controls.
- State assumptions about bar frequency, order timing, and existing positions.
- Require explicit confirmation before adding live-account identifiers or broker-specific behavior.
- Treat a successful compilation as syntax validation only; recommend simulation/backtesting before live use.
- For historical backtests, follow [backtest-configuration-contract.md](backtest-configuration-contract.md) and [autotrade-backtest-product-guide.md](autotrade-backtest-product-guide.md): obtain the user's explicit frequency, take-profit, stop-loss, product/session, date range, position, and minute-bar closeout choices before running; before starting, also read back the selected product and verify the script has entry plus exit (or explicit position-adjustment) actions.
