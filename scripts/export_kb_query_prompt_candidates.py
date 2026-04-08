from __future__ import annotations

import argparse
from pathlib import Path

PATTERNS = (
    "поні",
    "ферма",
    "тварин",
    "ранчо",
    "трансфер",
    "альтан",
    "послуг",
    "харч",
    "обід",
)


def iter_candidates(markdown_dir: Path) -> list[str]:
    candidates: list[str] = []
    for markdown_path in sorted(markdown_dir.glob("*.md")):
        for line_no, raw_line in enumerate(markdown_path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#") or any(pattern in line.casefold() for pattern in PATTERNS):
                candidates.append(f"{markdown_path.name}:{line_no}: {line}")
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print compact KB prompt-candidate lines from processed markdown."
    )
    parser.add_argument(
        "--markdown-dir",
        type=Path,
        default=Path("data/knowledge_base/processed/markdown"),
        help="Directory with processed markdown files.",
    )
    args = parser.parse_args()
    markdown_dir = args.markdown_dir.resolve()
    if not markdown_dir.exists():
        print(f"Markdown directory not found: {markdown_dir}")
        return 1

    for line in iter_candidates(markdown_dir):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
