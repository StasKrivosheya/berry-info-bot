from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.services.knowledge_base.kb_openai_config import get_kb_openai_settings  # noqa: E402
from app.services.knowledge_base.retrieval import KnowledgeBaseRetrievalService  # noqa: E402

logger = logging.getLogger(__name__)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a smoke-test vector search query against the KB vector store.",
    )
    parser.add_argument("query", help="Natural-language query to search for.")
    parser.add_argument("--max-num-results", type=int, default=None)
    parser.add_argument("--score-threshold", type=float, default=None)
    parser.add_argument("--category", type=str, default=None)
    parser.add_argument("--logical-id", type=str, default=None)
    parser.add_argument(
        "--rewrite-query",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable query rewriting for vector search (default: disabled).",
    )
    parser.add_argument("--log-level", type=str, default="INFO")
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
        settings = get_kb_openai_settings()
        service = KnowledgeBaseRetrievalService(settings=settings)
        hits = service.search(
            query=args.query,
            max_num_results=args.max_num_results,
            rewrite_query=args.rewrite_query,
            score_threshold=args.score_threshold,
            category=args.category,
            logical_id=args.logical_id,
        )
    except Exception:
        logger.exception("kb_smoke_test_failed")
        return 1

    print(f"query: {args.query}")
    print(
        "result_count: "
        f"{len(hits.results)} "
        f"(threshold={hits.used_threshold}, top_score={hits.top_score}, "
        f"fallback_triggered={hits.fallback_triggered})"
    )
    for index, hit in enumerate(hits.results, start=1):
        logical_id = hit.attributes.get("logical_id", "")
        category = hit.attributes.get("category", "")
        excerpt = _make_excerpt(hit.text)
        print(f"{index}. score={hit.score:.4f} file={hit.filename} file_id={hit.file_id}")
        print(f"   logical_id={logical_id} category={category}")
        print(f"   excerpt={excerpt}")

    if hits.fallback_triggered:
        print(hits.fallback_message or "No relevant information found in the knowledge base.")

    return 0


def _make_excerpt(text: str, max_len: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3].rstrip() + "..."


if __name__ == "__main__":
    raise SystemExit(main())
