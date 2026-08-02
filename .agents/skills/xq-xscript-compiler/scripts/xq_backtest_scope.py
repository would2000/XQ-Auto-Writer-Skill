#!/usr/bin/env python3
"""Shared, fail-closed contracts for transient XQ backtest scope selection.

The module intentionally contains no desktop automation.  Each XQ feature
provides narrowly scoped callbacks for its verified controls, while this layer
enforces the common replacement/readback contract and returns privacy-safe
evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, TypeVar


T = TypeVar("T")
MAX_EXPLICIT_PRODUCTS = 20


class BacktestScopeError(ValueError):
    """A requested or read-back backtest scope is unsafe or ambiguous."""


def normalized(value: Any) -> str:
    return " ".join(str(value or "").split())


def validate_product_code(value: str) -> str:
    product = value.strip()
    if (
        not product
        or len(product) > 40
        or any(ord(char) < 32 or char.isspace() for char in product)
    ):
        raise BacktestScopeError(
            "A product code must be one non-whitespace XQ code of at most 40 characters"
        )
    return product


def validate_explicit_products(
    values: Iterable[str],
    *,
    maximum: int = MAX_EXPLICIT_PRODUCTS,
) -> tuple[str, ...]:
    products = tuple(validate_product_code(value) for value in values)
    if not products:
        raise BacktestScopeError("At least one explicit product is required")
    if len(products) > maximum:
        raise BacktestScopeError(f"At most {maximum} explicit products are supported")
    if len(set(products)) != len(products):
        raise BacktestScopeError("Duplicate explicit product codes are not allowed")
    return products


def replace_explicit_products(
    products: Sequence[str],
    *,
    read_selected_codes: Callable[[], Sequence[str]],
    clear_selected: Callable[[], None],
    wait_for_empty: Callable[[], bool],
    find_exact_matches: Callable[[str], Sequence[T]],
    add_exact_match: Callable[[str, T], None],
) -> dict[str, Any]:
    """Replace only a transient product list and prove the final exact set.

    The prior item texts never leave the adapter.  They may represent the
    user's private working state, so the evidence intentionally stores only a
    boolean indicating whether that list was non-empty.
    """

    requested = validate_explicit_products(products)
    preexisting_selection_present = bool(read_selected_codes())
    clear_selected()
    if not wait_for_empty():
        raise BacktestScopeError("XQ did not clear the transient backtest product selection")

    for product in requested:
        matches = tuple(find_exact_matches(product))
        if len(matches) != 1:
            raise BacktestScopeError(
                f"Expected one exact XQ product match for {product!r}, found {len(matches)}"
            )
        add_exact_match(product, matches[0])

    selected = tuple(validate_product_code(value) for value in read_selected_codes())
    if len(selected) != len(requested) or set(selected) != set(requested):
        raise BacktestScopeError("XQ product selection verification failed")
    return {
        "selection_mode": "explicit_products",
        "source": "product",
        "requested_product_count": len(requested),
        "preexisting_selection_present": preexisting_selection_present,
        "cleared_selection_verified": True,
        "final_selection_verified": True,
        "private_source_touched": False,
    }


def validate_system_default_scope(value: str) -> str:
    scope = normalized(value)
    if not scope:
        raise BacktestScopeError("A system screener default scope is required")
    # The documented XQ Taiwan scope marker is intentionally required.  A
    # private watchlist must be selected manually and is never named here.
    if not scope.endswith("(系統)"):
        raise BacktestScopeError(
            "Only an XQ system default scope ending in '(系統)' may be automated"
        )
    return scope


def manual_watchlist_group_evidence(selected_scope: str) -> dict[str, Any]:
    """Classify a user-selected screener group without retaining its name.

    XQ exposes user watchlist groups alongside system default scopes in the
    screener backtest range combo.  CODEX must not select, enumerate, log, or
    replace those groups.  This helper receives the current readback only to
    reject an empty/system selection, then returns no private label.
    """

    scope = normalized(selected_scope)
    if not scope:
        raise BacktestScopeError("A manually selected screener watchlist group is required")
    if scope.endswith("(系統)"):
        raise BacktestScopeError(
            "The selected screener range is a system default scope, not a manual watchlist group"
        )
    return {
        "selection_mode": "manual_watchlist_group",
        "source": "screener_watchlist_group",
        "selection_applied_by_codex": False,
        "manual_selection_present": True,
        "private_group_name_retained": False,
        "private_source_touched": False,
        "final_selection_verified": False,
    }


def apply_system_default_scope(
    market: str,
    system_scope: str,
    *,
    available_markets: Callable[[], Sequence[str]],
    select_market: Callable[[str], None],
    read_market: Callable[[], str],
    available_universes: Callable[[], Sequence[str]],
    select_universe: Callable[[str], None],
    read_universe: Callable[[], str],
) -> dict[str, Any]:
    """Apply and verify a public screener market/system-default-scope pair."""

    requested_market = normalized(market)
    requested_scope = validate_system_default_scope(system_scope)
    if not requested_market:
        raise BacktestScopeError("A screener market is required")

    market_options = {normalized(value) for value in available_markets()}
    if requested_market not in market_options:
        raise BacktestScopeError("The requested screener market is not available")
    select_market(requested_market)
    if normalized(read_market()) != requested_market:
        raise BacktestScopeError("XQ did not retain the requested screener market")

    # XQ rebuilds the range list after a market change; read it only now.
    scope_options = {normalized(value) for value in available_universes()}
    if requested_scope not in scope_options:
        raise BacktestScopeError("The requested system default scope is not available for this market")
    select_universe(requested_scope)
    if normalized(read_universe()) != requested_scope:
        raise BacktestScopeError("XQ did not retain the requested system default scope")

    return {
        "selection_mode": "system_default_scope",
        "source": "screener_system_default_scope",
        "requested_market": requested_market,
        "requested_system_default_scope": requested_scope,
        "preexisting_selection_present": None,
        "cleared_selection_verified": None,
        "final_selection_verified": True,
        "private_source_touched": False,
    }


# Kept as an internal compatibility alias for callers that have not yet been
# migrated.  New code must use the explicit "default scope" terminology.
validate_system_universe = validate_system_default_scope
apply_system_universe = apply_system_default_scope
