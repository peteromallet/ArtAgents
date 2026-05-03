#!/usr/bin/env python3
"""Render the README banner box edges + side studs from a single spec.

Locates the ``text``-fenced banner inside README.md (the box that starts with
``┏`` and ends with ``┛``), then rewrites the four edges and the chosen
side-stud rows so every diamond is placed at exact column / row positions.

Run:

    python3 scripts/render_banner.py
    python3 scripts/render_banner.py --diamond-cols 32 47 --stud-rows 32 50

The defaults are the agreed spec — moderately spread diamonds on top/bottom
edges and matching side studs that fall on existing blank rows.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

BAR = "━"
SIDE = "┃"
TOP_LEFT, TOP_RIGHT = "┏", "┓"
BOT_LEFT, BOT_RIGHT = "┗", "┛"
DIAMOND = "◇"

BOX_RE = re.compile(r"(```text\n)(┏[^\n]*\n(?:[^\n]*\n)*?[┗][^\n]*\n)(```)")


def build_edge(left: str, right: str, width: int, diamond_cols: list[int]) -> str:
    """Build a single horizontal edge with diamonds at the given full-line columns.

    ``width`` is the full line width including the corner glyphs.
    ``diamond_cols`` are 1-indexed column positions in the full line.
    """
    chars = [left] + [BAR] * (width - 2) + [right]
    for col in diamond_cols:
        if not 2 <= col <= width - 1:
            raise ValueError(f"diamond column {col} out of inner range")
        chars[col - 1] = DIAMOND
    return "".join(chars)


def stud_row(row: str) -> str:
    """Replace the leading and trailing ┃ on a content row with ◇."""
    if not (row.startswith(SIDE) and row.endswith(SIDE)):
        raise ValueError(f"row does not have side bars: {row!r}")
    return DIAMOND + row[1:-1] + DIAMOND


def render(text: str, diamond_cols: list[int], stud_rows: list[int]) -> str:
    match = BOX_RE.search(text)
    if not match:
        raise SystemExit("Could not locate banner box in README.md")

    fence_open, box, fence_close = match.group(1), match.group(2), match.group(3)
    lines = box.splitlines()

    width = len(lines[0])
    if any(len(line) != width for line in lines):
        widths = sorted({len(line) for line in lines})
        raise SystemExit(f"Box rows have inconsistent widths: {widths}")

    # Replace top + bottom edges.
    lines[0] = build_edge(TOP_LEFT, TOP_RIGHT, width, diamond_cols)
    lines[-1] = build_edge(BOT_LEFT, BOT_RIGHT, width, diamond_cols)

    # Replace side studs. stud_rows are 1-indexed within the box (row 1 = top edge).
    for row_idx in stud_rows:
        if not 2 <= row_idx <= len(lines) - 1:
            raise SystemExit(f"stud row {row_idx} out of inner range 2..{len(lines) - 1}")
        lines[row_idx - 1] = stud_row(lines[row_idx - 1])

    new_box = "\n".join(lines) + "\n"
    return text[: match.start()] + fence_open + new_box + fence_close + text[match.end() :]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diamond-cols",
        nargs=2,
        type=int,
        default=[32, 47],
        metavar=("LEFT", "RIGHT"),
        help="Full-line column positions for the two top/bottom diamonds (default: 32 47).",
    )
    parser.add_argument(
        "--stud-rows",
        nargs=2,
        type=int,
        default=[21, 39],
        metavar=("UPPER", "LOWER"),
        help="Box-relative row indices for the two side stud rows (default: 21 39, symmetric around row 30).",
    )
    parser.add_argument("--readme", type=Path, default=README)
    args = parser.parse_args()

    diamond_cols = sorted(args.diamond_cols)
    stud_rows = sorted(args.stud_rows)

    text = args.readme.read_text(encoding="utf-8")
    new_text = render(text, diamond_cols, stud_rows)
    args.readme.write_text(new_text, encoding="utf-8")
    print(f"Wrote {args.readme} with diamond cols {diamond_cols} and stud rows {stud_rows}.")


if __name__ == "__main__":
    main()
