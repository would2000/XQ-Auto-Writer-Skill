#!/usr/bin/env python3
"""Shared one-shot XQ backtest start and late-report monitor."""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import asdict
from typing import Any, Callable

import xq_backtest


MONITOR_POLL_SECONDS = 0.25
LATE_REPORT_MIN_GRACE_SECONDS = 30.0
LATE_REPORT_MAX_GRACE_SECONDS = 120.0
BM_CLICK = 0x00F5


def post_start_once(settings_window: Any) -> dict[str, Any]:
    """Post one semantic Start command without waiting on XQ's GUI thread."""
    guard = xq_backtest.ensure_window_foreground(settings_window)
    start = xq_backtest.control_by_id(settings_window, 2033)
    if not start.is_visible() or not start.is_enabled():
        raise RuntimeError("The XQ backtest Start control is not usable")
    xq_backtest.ui_action_pause()
    if sys.platform != "win32":
        raise RuntimeError("The XQ backtest Start command requires Windows")
    accepted = bool(
        ctypes.windll.user32.PostMessageW(int(start.handle), BM_CLICK, 0, 0)
    )
    if not accepted:
        raise RuntimeError("Windows did not accept the XQ backtest Start command")
    return {
        "command": "BM_CLICK_PostMessageW",
        "control_id": 2033,
        "control_handle": int(start.handle),
        "posted_once": True,
        "foreground_guard": guard,
    }


def settings_window_visible(settings_window: Any) -> bool:
    handle = int(settings_window.handle)
    if sys.platform == "win32":
        return bool(
            ctypes.windll.user32.IsWindow(handle)
            and ctypes.windll.user32.IsWindowVisible(handle)
        )
    return bool(settings_window.is_visible())


def new_report_candidates(
    baseline_handles: set[int],
    expected_marker: str,
) -> list[dict[str, Any]]:
    normalized_marker = xq_backtest.normalized(expected_marker).casefold()
    candidates: list[dict[str, Any]] = []
    for window, elements in xq_backtest.visible_report_records(baseline_handles):
        try:
            title = xq_backtest.normalized(window.window_text())
            candidates.append(
                {
                    "window": window,
                    "window_handle": int(window.handle),
                    "window_title": title,
                    "marker_expected": expected_marker,
                    "marker_matched": normalized_marker in title.casefold(),
                    "summary": xq_backtest.report_summary(elements),
                }
            )
        except Exception:
            continue
    return candidates


def run_report_monitor(
    settings_window: Any,
    timeout: float,
    expected_marker: str,
    *,
    runtime_probe: Callable[[], xq_backtest.RuntimeSnapshot] | None = None,
    checkpoint_callback: Callable[[str, int | None, bool], None] | None = None,
    baseline_report_handles: set[int] | None = None,
    baseline_progress_handles: set[int] | None = None,
    late_report_grace_seconds: float | None = None,
    start_action: Callable[[Any], dict[str, Any]] = post_start_once,
    progress_probe: Callable[[], list[Any]] | None = None,
    report_probe: Callable[[set[int], str], list[dict[str, Any]]] = (
        new_report_candidates
    ),
    settings_visible_probe: Callable[[Any], bool] = settings_window_visible,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    poll_seconds: float = MONITOR_POLL_SECONDS,
) -> tuple[str, dict[str, Any]]:
    """Start once and accept only one marker-matched conclusive report."""
    baseline = set(baseline_report_handles or ())
    progress_baseline = set(baseline_progress_handles or ())
    grace = late_report_grace_seconds
    if grace is None:
        grace = max(
            LATE_REPORT_MIN_GRACE_SECONDS,
            min(LATE_REPORT_MAX_GRACE_SECONDS, timeout),
        )
    if grace < 0 or poll_seconds <= 0:
        raise ValueError("Backtest monitoring intervals must be positive")
    progress_probe = progress_probe or (
        lambda: xq_backtest.progress_windows(include_hidden=True)
    )

    state = "starting"
    transitions: list[dict[str, Any]] = [
        {"stage": state, "observed_at_seconds": 0.0}
    ]
    progress_handle: int | None = None
    progress_seen = False
    hidden_progress_seen = False
    settings_poll_count = 0
    settings_ever_closed = False
    report_decision = "not_seen"
    started_at = monotonic()
    regular_deadline = started_at + timeout
    hard_deadline = regular_deadline + grace
    next_runtime_heartbeat = started_at

    def transition(next_stage: str) -> None:
        nonlocal state
        if state == next_stage:
            return
        state = next_stage
        transitions.append(
            {
                "stage": next_stage,
                "observed_at_seconds": round(monotonic() - started_at, 3),
            }
        )
        if checkpoint_callback is not None:
            checkpoint_callback(next_stage, progress_handle, False)

    start_evidence = start_action(settings_window)
    while monotonic() < hard_deadline:
        now = monotonic()
        if runtime_probe is not None and now >= next_runtime_heartbeat:
            snapshot = runtime_probe()
            failure_kind = xq_backtest.classify_runtime_interruption(snapshot)
            if failure_kind is not None:
                transition("interrupted")
                return "environment_interruption", {
                    "failure_kind": failure_kind,
                    "last_safe_stage": transitions[-2]["stage"],
                    "start_input": start_evidence,
                    "state_transitions": transitions,
                    "progress_seen": progress_seen,
                    "recovery_checkpoint_retained": True,
                    "runtime": xq_backtest.runtime_evidence(snapshot),
                }
            next_runtime_heartbeat = now + xq_backtest.RUNTIME_HEARTBEAT_SECONDS

        settings_poll_count += 1
        settings_visible = settings_visible_probe(settings_window)
        if not settings_visible:
            settings_ever_closed = True

        progress_matches = []
        for progress in progress_probe():
            handle = int(progress.handle)
            try:
                visible = bool(progress.is_visible())
            except Exception:
                visible = True
            if handle not in progress_baseline or visible:
                progress_matches.append(progress)
        if len(progress_matches) > 1:
            return "indeterminate_timeout", {
                "start_input": start_evidence,
                "state_transitions": transitions,
                "progress_seen": progress_seen,
                "report_decision": "progress_not_unique",
                "progress_candidate_count": len(progress_matches),
                "manual_review_required": True,
            }
        if len(progress_matches) == 1:
            progress = progress_matches[0]
            progress_seen = True
            progress_handle = int(progress.handle)
            try:
                hidden_progress_seen = hidden_progress_seen or not bool(
                    progress.is_visible()
                )
            except Exception:
                hidden_progress_seen = True
            transition("running")
        elif not settings_visible and state == "starting":
            transition("running")

        candidates = report_probe(baseline, expected_marker)
        if len(candidates) > 1:
            return "indeterminate_timeout", {
                "start_input": start_evidence,
                "state_transitions": transitions,
                "progress_seen": progress_seen,
                "hidden_progress_seen": hidden_progress_seen,
                "report_decision": "report_not_unique",
                "new_report_count": len(candidates),
                "new_report_handles": sorted(
                    int(candidate["window_handle"]) for candidate in candidates
                ),
                "manual_review_required": True,
            }
        if len(candidates) == 1:
            candidate = candidates[0]
            if candidate.get("marker_matched") is not True:
                return "indeterminate_timeout", {
                    "start_input": start_evidence,
                    "state_transitions": transitions,
                    "progress_seen": progress_seen,
                    "report_decision": "marker_mismatch",
                    "new_report_count": 1,
                    "report_window_handle": int(candidate["window_handle"]),
                    "marker_expected": expected_marker,
                    "marker_actual": candidate.get("window_title"),
                    "manual_review_required": True,
                }
            summary = candidate.get("summary")
            if summary is not None:
                if state == "starting":
                    transition("running")
                transition("late_report")
                transition("completed")
                status = xq_backtest.classify_report(summary)
                evidence: dict[str, Any] = {
                    "report_window_handle": int(candidate["window_handle"]),
                    "report_window_title": candidate.get("window_title"),
                    "success_count": summary.success_count,
                    "failure_count": summary.failure_count,
                    "total_trades": summary.total_trades,
                    "progress_seen": progress_seen,
                    "hidden_progress_seen": hidden_progress_seen,
                    "progress_window_handle": progress_handle,
                    "settings_window_delayed_close": settings_poll_count > 1,
                    "settings_window_closed": settings_ever_closed,
                    "start_input": start_evidence,
                    "state_transitions": transitions,
                    "report_decision": "unique_new_report_and_marker_matched",
                    "new_report_count": 1,
                    "marker_expected": expected_marker,
                    "marker_actual": candidate.get("window_title"),
                    "marker_matched": True,
                }
                if summary.failure_count > 0:
                    try:
                        details = xq_backtest.extract_failure_details(
                            candidate["window"], summary.failure_count
                        )
                        evidence["failure_details"] = [
                            asdict(item) for item in details
                        ]
                    except Exception as exc:
                        evidence["failure_details"] = []
                        evidence["failure_detail_capture_error"] = (
                            f"{type(exc).__name__}: {exc}"
                        )
                return status, evidence
            report_decision = "summary_not_yet_conclusive"

        if now >= regular_deadline and state != "late_report":
            if state == "starting":
                transition("running")
            transition("late_report")
        elif state == "running" and progress_seen and not progress_matches:
            transition("late_report")
        sleeper(poll_seconds)

    if state == "starting":
        transition("running")
    transition("late_report")
    return "indeterminate_timeout", {
        "start_input": start_evidence,
        "state_transitions": transitions,
        "progress_seen": progress_seen,
        "hidden_progress_seen": hidden_progress_seen,
        "progress_window_handle": progress_handle,
        "settings_window_delayed_close": settings_poll_count > 1,
        "settings_window_closed": settings_ever_closed,
        "settings_window_visible_at_timeout": not settings_ever_closed,
        "report_decision": report_decision,
        "new_report_count": 0,
        "manual_review_required": True,
        "timeout_seconds": timeout,
        "late_report_grace_seconds": grace,
    }
