"""Generate the SoulFont handwriting template PDF.

Produces a multi-page A4 sheet — every page a 4x7 grid (28 cells) — whose cells follow
the order fixed in ``char_layout.py``:

    page 1        -> KOR_STYLE_CHARS (28 Korean style references, used by the model)
    pages 2..N    -> EXTRA_CHARS     (English + digits + symbols, traced directly)

Keeping every page on the same 4x7 grid means the extraction pipeline needs no change:
``font_processor`` renders each page at 300 DPI and ``style/crop.py`` crops every page with
its default ``--rows 4 --cols 7``, so the cropped cells come out in exactly this order.

The output overwrites ``static/templates/28_template.pdf`` (the file served by
``download_template``). matplotlib embeds the guide-glyph outlines, so the resulting PDF is
self-contained and needs no font installed wherever it is opened or printed.

Usage:
    python scripts/generate_template.py [--font /path/to/korean.ttf] [--out PATH]
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

# Make the project root importable so we reuse the single source of truth for cell order.
PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)
from char_layout import (  # noqa: E402
    EXTRA_CHARS,
    KOR_STYLE_CHARS,
    TEMPLATE_CELLS_PER_PAGE,
    TEMPLATE_COLS,
    TEMPLATE_LAYOUT_VERSION,
    TEMPLATE_ROWS,
)

# --- grid geometry (cell proportions mirror the original 28_template so style/crop.py's
#     existing top/edge trim fractions keep removing the printed guide glyph) ---
ROWS, COLS = TEMPLATE_ROWS, TEMPLATE_COLS
CELLS_PER_PAGE = TEMPLATE_CELLS_PER_PAGE
GRID_LEFT, GRID_RIGHT = 0.07, 0.93
GRID_TOP, GRID_BOTTOM = 0.95, 0.40          # grid sits in the upper part of the page
CELL_W = (GRID_RIGHT - GRID_LEFT) / COLS
CELL_H = (GRID_TOP - GRID_BOTTOM) / ROWS

# The guide glyph must sit entirely inside the top band that style/crop.py trims away
# (CELL_PAD_FRAC + TOP_EXTRA_FRAC = 11% of each cell), so it never pollutes the user's
# handwriting. Keep it small and hard against the cell top; verified empirically below.
GUIDE_FONTSIZE = 7                           # small, so it stays inside the trimmed top band
GUIDE_TOP_OFFSET = 0.003                     # guide top, in page units, below each cell top
GUIDE_COLOR = "0.45"                         # grey: clearly a printed guide, not your ink
LINE_WIDTH = 1.0

# Candidate Korean-capable fonts to fall back through when --font isn't given.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    os.path.join(PROJ_ROOT, "media", "ttf_files", "MaruBuri-Regular.ttf"),
    os.path.join(PROJ_ROOT, "media", "ttf_files", "NanumBaReunJeongSin.ttf"),
    "/Library/Fonts/NanumGothic.ttf",
]


def resolve_font(explicit):
    if explicit:
        if not os.path.isfile(explicit):
            sys.exit(f"[template] --font not found: {explicit}")
        return explicit
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    sys.exit(
        "[template] No Korean font found. Pass one with --font /path/to/font.ttf "
        "(it must contain Hangul + Latin + the punctuation in char_layout.SPECIAL_CHARS)."
    )


def chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def draw_page(pdf, chars, font_prop):
    fig = plt.figure(figsize=(8.27, 11.69))           # A4 portrait, inches
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    for idx in range(CELLS_PER_PAGE):
        r, c = divmod(idx, COLS)
        x = GRID_LEFT + c * CELL_W
        y_top = GRID_TOP - r * CELL_H
        # full cell border on every cell (incl. trailing blanks) -> a clean grid border
        ax.add_patch(Rectangle((x, y_top - CELL_H), CELL_W, CELL_H,
                               fill=False, edgecolor="black", linewidth=LINE_WIDTH))
        if idx < len(chars):
            ax.text(x + CELL_W / 2, y_top - GUIDE_TOP_OFFSET, chars[idx],
                    fontproperties=font_prop, fontsize=GUIDE_FONTSIZE,
                    color=GUIDE_COLOR, ha="center", va="top")

    pdf.savefig(fig)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Generate the SoulFont handwriting template PDF.")
    ap.add_argument("--font", default=None, help="Korean-capable TTF/OTF for the guide glyphs.")
    ap.add_argument("--out", default=os.path.join(PROJ_ROOT, "static", "templates", "28_template.pdf"))
    args = ap.parse_args()

    font_path = resolve_font(args.font)
    font_prop = fm.FontProperties(fname=font_path)

    all_chars = list(KOR_STYLE_CHARS) + list(EXTRA_CHARS)
    pages = list(chunk(all_chars, CELLS_PER_PAGE))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with PdfPages(args.out) as pdf:
        for page_chars in pages:
            draw_page(pdf, page_chars, font_prop)

    print(f"[template] font: {font_path}")
    print(f"[template] layout: {TEMPLATE_LAYOUT_VERSION}")
    print(f"[template] {len(all_chars)} guides over {len(pages)} pages "
          f"({len(KOR_STYLE_CHARS)} Korean + {len(EXTRA_CHARS)} extra)")
    print(f"[template] wrote {args.out}")


if __name__ == "__main__":
    main()
