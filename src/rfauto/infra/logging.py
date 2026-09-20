"""rfauto logging configuration — loguru + rich console + JSONL file sink."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from rich.console import Console

_console = Console(stderr=True)

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------
_DEFAULT_LOG_DIR = Path("logs")
_RUN_EVENTS_FILE = "run_events.jsonl"
_APP_LOG_FILE = "app.jsonl"


def _rich_format(record) -> str:  # pragma: no cover – cosmetic
    """Rich-friendly format string for the console sink."""
    return (
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>\n"
    )


# ---------------------------------------------------------------------------
# setup_logging()
# ---------------------------------------------------------------------------

def setup_logging(
    *,
    log_dir: str | Path = _DEFAULT_LOG_DIR,
    level: str = "DEBUG",
    jsonl: bool = True,
    run_id: str | None = None,
) -> None:
    """Configure loguru sinks.

    Parameters
    ----------
    log_dir:
        Directory for log files (created if needed).
    level:
        Minimum log level for both console and file sinks.
    jsonl:
        Enable the structured JSONL file sink (``logs/app.jsonl``).
    run_id:
        Optional run identifier embedded in every JSONL record as an extra
        field.  Per-run events go to ``logs/run_events.jsonl``.
    """
    logger.remove()  # drop default handler

    # ---- Console sink (rich) ------------------------------------------------
    logger.add(
        lambda msg: _console.print(msg, end=""),
        format=_rich_format,
        level=level,
        colorize=False,  # rich handles colours
    )

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # ---- Structured JSONL sink (app-wide) -----------------------------------
    if jsonl:
        logger.add(
            str(log_path / _APP_LOG_FILE),
            format="{message}",
            level=level,
            serialize=True,  # JSONL
            rotation="10 MB",
            retention="7 days",
            enqueue=True,
        )

    # ---- Per-run events sink ------------------------------------------------
    if run_id is not None:
        logger.add(
            str(log_path / _RUN_EVENTS_FILE),
            format="{message}",
            level="INFO",
            serialize=True,
            rotation="50 MB",
            retention="30 days",
            enqueue=True,
            filter=lambda record: record["extra"].get("run_id") == run_id,
        )
        # bind() 返回新 logger、不修改全局对象——丢弃返回值的写法是无效的
        # （历史缺陷：原代码导致 run_events.jsonl 永远不写入）。
        # 正确做法：configure(extra=...) 设置全局默认 extra，使 filter 能匹配。
        logger.configure(extra={"run_id": run_id})

    logger.info("Logging initialised", run_id=run_id or "N/A")
