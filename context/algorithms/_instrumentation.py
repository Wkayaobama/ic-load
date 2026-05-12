"""
_instrumentation.py — Logging and artifact decorators for context/algorithms.

  log_debug(fn, stat_fn=None, sample_fn=None, max_samples=200)
      → DEBUG log per call; when a session is active, accumulates aggregate stats
        via stat_fn AND appends a bounded list of (input, output) samples via sample_fn.

  log_info_with_artifact(description, builder)
      → INFO log + one JSON artifact per call (high-level orchestration functions).

  begin_session(session_id=None)  → start accumulating per-row stats + samples
  end_session()                   → flush one aggregate artifact per function, clear session
  algorithm_session(session_id)   → context manager wrapping begin/end_session

stat_fn contract:
  stat_fn(result, *original_args, **original_kwargs) → dict[str, int | float]
  Keys ending in _min → running minimum; _max → running maximum; all others → summed.
  value_mean is derived automatically at flush when value_sum and value_count are both present.

sample_fn contract:
  sample_fn(result, *original_args, **original_kwargs) → dict (JSON-serializable)
  Called per invocation; entries are collected up to max_samples, then discarded.
"""
import functools
import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable

from context.config import ARTIFACTS_DIR

_log = logging.getLogger(__name__)

_active_session: dict | None = None


# ── Session lifecycle ──────────────────────────────────────────────────────────

def begin_session(session_id: str | None = None) -> None:
    """Start accumulating per-row algorithm stats and samples. Call before a pipeline stage."""
    global _active_session
    run_id = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    _active_session = {"run_id": run_id, "functions": {}}
    _log.debug("[algorithms] session started: %s", run_id)  # dev only


def end_session() -> None:
    """Flush one aggregate artifact per function, then clear the session."""
    global _active_session
    if _active_session is None:
        return
    session = _active_session
    _active_session = None
    _flush_session(session)


@contextmanager
def algorithm_session(session_id: str | None = None):
    """Context manager: begin_session on enter, end_session on exit."""
    begin_session(session_id)
    try:
        yield
    finally:
        end_session()


# ── Internal accumulation helpers ─────────────────────────────────────────────

def _merge_stats(existing: dict, new_stats: dict) -> None:
    for key, value in new_stats.items():
        if key not in existing:
            existing[key] = value
        elif key.endswith("_min"):
            existing[key] = min(existing[key], value)
        elif key.endswith("_max"):
            existing[key] = max(existing[key], value)
        else:
            existing[key] = existing[key] + value


def _accumulate(
    fn_name: str,
    fn_qualname: str,
    stats: dict | None,
    sample: dict | None,
    max_samples: int,
) -> None:
    if _active_session is None:
        return
    funcs = _active_session["functions"]
    if fn_name not in funcs:
        funcs[fn_name] = {
            "_qualname": fn_qualname,
            "_stats": {},
            "_samples": [],
            "_total_calls": 0,
            "_max_samples": max_samples,
        }
    entry = funcs[fn_name]
    entry["_total_calls"] += 1
    if stats:
        _merge_stats(entry["_stats"], stats)
    if sample is not None and len(entry["_samples"]) < max_samples:
        entry["_samples"].append(sample)


def _flush_session(session: dict) -> None:
    run_id = session["run_id"]
    flushed = 0
    for fn_name, entry in session["functions"].items():
        stats = dict(entry["_stats"])
        total_calls = entry["_total_calls"]
        samples = entry["_samples"]
        max_samples = entry["_max_samples"]

        if total_calls == 0:
            continue

        # Derive mean when both sum and count are present
        if "value_sum" in stats and "value_count" in stats and stats["value_count"] > 0:
            stats["value_mean"] = round(stats["value_sum"] / stats["value_count"], 4)

        # Replace inf sentinels from _min/_max accumulation with no valid values
        for k, v in stats.items():
            if isinstance(v, float) and not (-1e308 < v < 1e308):
                stats[k] = None

        # Merge samples into the stats dict
        if samples:
            stats["samples"] = samples
            if total_calls > max_samples:
                stats["samples_note"] = f"First {max_samples} of {total_calls} calls"

        try:
            artifact = {
                "algorithm": entry["_qualname"],
                "run_id": run_id,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "description": "Aggregate stats and input/output samples from per-row calls in this pipeline session.",
                "data": stats,
            }
            path = ARTIFACTS_DIR / f"algorithm_{fn_name}_{run_id}.json"
            path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
            flushed += 1
            _log.debug("[algorithms] session artifact written → %s", path.name)  # dev only
            print(f"[algorithms] {fn_name}: {total_calls} calls")
        except Exception as exc:
            print(f"[algorithms] WARNING: artifact flush failed for {fn_name}: {exc}")

    print(f"[algorithms] session {run_id} closed - {flushed} aggregate artifacts written")


# ── Decorators ────────────────────────────────────────────────────────────────

def log_debug(
    fn: Callable,
    stat_fn: Callable | None = None,
    sample_fn: Callable | None = None,
    max_samples: int = 200,
) -> Callable:
    """Wrap fn with a DEBUG log per call.

    When a session is active:
    - stat_fn(result, *args, **kwargs) → dict of numeric stats to aggregate
    - sample_fn(result, *args, **kwargs) → dict snapshot of one (input, output) pair,
      collected up to max_samples entries then discarded
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _log.debug("%s called", fn.__qualname__)
        result = fn(*args, **kwargs)
        if _active_session is not None and (stat_fn is not None or sample_fn is not None):
            try:
                stats = stat_fn(result, *args, **kwargs) if stat_fn else None
                sample = sample_fn(result, *args, **kwargs) if sample_fn else None
                _accumulate(fn.__name__, fn.__qualname__, stats, sample, max_samples)
            except Exception as exc:
                _log.debug("[algorithms] accumulation failed for %s: %s", fn.__qualname__, exc)
        return result
    return wrapper


def log_info_with_artifact(description: str, artifact_builder: Callable) -> Callable:
    """Decorator factory: log at INFO on entry/exit and write a JSON artifact.

    artifact_builder(result, *original_args, **original_kwargs) → JSON-serializable dict.
    Artifact failures are caught and logged as WARNING — they never crash the pipeline.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            print(f"[algorithms] {fn.__qualname__}: {description}")
            t0 = time.perf_counter()
            result = fn(*args, **kwargs)
            elapsed = time.perf_counter() - t0
            print(f"[algorithms] {fn.__qualname__} complete in {elapsed:.3f}s")

            run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            try:
                payload = artifact_builder(result, *args, **kwargs)
                artifact = {
                    "algorithm": fn.__qualname__,
                    "run_id": run_id,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": round(elapsed, 4),
                    "description": description,
                    "data": payload,
                }
                path = ARTIFACTS_DIR / f"algorithm_{fn.__name__}_{run_id}.json"
                path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
                _log.debug("[algorithms] artifact written → %s", path.name)  # dev only
            except Exception as exc:
                print(f"[algorithms] WARNING: artifact write failed for {fn.__qualname__}: {exc}")

            return result
        return wrapper
    return decorator
