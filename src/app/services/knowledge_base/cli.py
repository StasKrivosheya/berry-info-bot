from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from app.services.knowledge_base.ingest.parser import parse_knowledge_base
from app.services.knowledge_base.types import SelectableSourceFormat

DEFAULT_INPUT_DIR = Path("data/knowledge_base/raw_sources")
DEFAULT_OUTPUT_DIR = Path("data/knowledge_base/processed")
DEFAULT_CONFIG_PATH = Path("data/knowledge_base/parser_config.toml")

logger = logging.getLogger(__name__)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse exported Google Sheets CSV/XLSX files into Markdown "
            "knowledge-base files."
        ),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory with source CSV/XLSX files (default: {DEFAULT_INPUT_DIR.as_posix()})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for markdown + manifest output (default: {DEFAULT_OUTPUT_DIR.as_posix()})",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to parser config TOML (default: {DEFAULT_CONFIG_PATH.as_posix()})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    parser.add_argument(
        "--source-format",
        action="append",
        choices=("csv", "xlsx"),
        help="Limit parsing to one or more source formats. Repeat to select multiple formats.",
    )
    return parser


def configure_cli_logging(log_level: str) -> None:
    logging.basicConfig(
        level=(log_level or "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _normalize_source_formats(
    source_formats: Sequence[str] | None,
) -> tuple[SelectableSourceFormat, ...] | None:
    if not source_formats:
        return None
    normalized: list[SelectableSourceFormat] = []
    for source_format in source_formats:
        if source_format not in normalized:
            normalized.append(source_format)  # type: ignore[arg-type]
    return tuple(normalized)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    configure_cli_logging(args.log_level)

    try:
        result = parse_knowledge_base(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            config_path=args.config,
            source_formats=_normalize_source_formats(args.source_format),
        )
    except Exception:
        logger.exception("kb_parser_run_failed")
        return 1

    if result.errors:
        logger.warning(
            "kb_parser_completed_with_errors discovered=%s succeeded=%s failed=%s",
            result.discovered_source_count,
            result.success_count,
            result.failure_count,
        )
        for error in result.errors:
            logger.warning(
                "kb_parser_file_error source=%s error_type=%s message=%s",
                error.source_ref,
                error.error_type,
                error.message,
            )
    else:
        logger.info(
            "kb_parser_completed discovered=%s succeeded=%s",
            result.discovered_source_count,
            result.success_count,
        )

    return 1 if result.all_files_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

