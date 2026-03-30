from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.services.knowledge_base.retrieval import KnowledgeBaseRetrievalService  # noqa: E402

DEFAULT_MANIFEST_PATH = Path("data/knowledge_base/processed/manifest.json")

logger = logging.getLogger(__name__)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize markdown knowledge-base files into an OpenAI vector store.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help=f"Path to parser manifest JSON (default: {DEFAULT_MANIFEST_PATH.as_posix()})",
    )
    parser.add_argument(
        "--replace",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Replace existing files by logical_id before upload (default: enabled).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned operations without mutating the vector store.",
    )
    parser.add_argument(
        "--only-logical-id",
        type=str,
        default=None,
        help="Sync only manifest rows with this logical_id.",
    )
    parser.add_argument(
        "--only-category",
        type=str,
        default=None,
        help="Sync only manifest rows with this category.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    return parser


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=(log_level or "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    try:
        service = KnowledgeBaseRetrievalService()
        report = service.sync_from_manifest(
            manifest_path=args.manifest,
            replace=args.replace,
            dry_run=args.dry_run,
            only_logical_id=args.only_logical_id,
            only_category=args.only_category,
        )
    except Exception:
        logger.exception("kb_sync_failed")
        return 1

    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True))

    if report.has_failures:
        logger.error(
            "kb_sync_completed_with_failures failed=%s uploaded=%s deleted=%s",
            report.failed_count,
            report.uploaded_count,
            report.deleted_count,
        )
        return 1

    logger.info(
        "kb_sync_completed scanned=%s selected=%s uploaded=%s deleted=%s dry_run=%s",
        report.scanned_count,
        report.selected_count,
        report.uploaded_count,
        report.deleted_count,
        report.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
