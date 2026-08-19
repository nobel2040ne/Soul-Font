"""Generate the SoulFont handwriting template PDF.

Produces an A4 sheet — a 10x13 grid, 130 cells — whose cells follow the order fixed in
``char_layout.py``:

    cells 0..27    -> KOR_STYLE_CHARS (Korean style references, read by the model)
    cells 28..124  -> EXTRA_CHARS     (English, digits and symbols, traced directly)
    the rest       -> blank, and mapped to nothing

The grid is read back by ``foundry/crop.py``, which locates the printed border and divides
it by the same rows and columns, so cell order here and cell order there are the same list.

The one thing this file has to get right on its own is the guide glyph. It is printed
inside the cell, and the cropper removes the top ``GUIDE_BAND_FRAC`` of every cell to get
rid of it; a guide that reaches past that band is traced into the font as though the writer
had drawn it. So the band is not assumed here — ``verify_guides_fit`` measures the rendered
glyphs and refuses to write a sheet that would leak.

The output overwrites ``static/templates/soulfont_template.pdf`` (the file served by
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
from foundry.char_layout import (  # noqa: E402
    EXTRA_CHARS,
    GUIDE_BAND_FRAC,
    KOR_STYLE_CHARS,
    TEMPLATE_CELLS_PER_PAGE,
    TEMPLATE_COLS,
    TEMPLATE_LAYOUT_VERSION,
    TEMPLATE_ROWS,
)

PAGE_W_IN, PAGE_H_IN = 8.27, 11.69           # A4 portrait

# --- grid geometry ---
# The grid now uses the whole page rather than its top half, and the cell is close to
# square: about 18.1 x 20.6 mm, against 25.8 x 40.8 mm before. A Hangul syllable is
# roughly square, so a tall letterbox cell only ever invited writing that had to be
# squashed back into shape later — and the smaller cell is what fits the whole set on
# one sheet instead of four.
ROWS, COLS = TEMPLATE_ROWS, TEMPLATE_COLS
CELLS_PER_PAGE = TEMPLATE_CELLS_PER_PAGE
GRID_LEFT, GRID_RIGHT = 0.07, 0.93
GRID_TOP, GRID_BOTTOM = 0.95, 0.05
CELL_W = (GRID_RIGHT - GRID_LEFT) / COLS
CELL_H = (GRID_TOP - GRID_BOTTOM) / ROWS

# The guide glyph, printed inside the band the cropper throws away.
#
# Every guide used to be set at one size, which is the wrong rule once the set is mostly
# punctuation. A period at 7pt is a single grey speck, and there are now seven marks that
# reduce to a speck at that size — ' and ` and , and . and ° among them — so the sheet
# stopped being able to tell you which one a cell wanted.
#
# So the guides share one baseline, set from the font's own ascent so the em fills the
# band — and any glyph whose ink would come out shorter than GUIDE_MIN_INK_PT is magnified
# about that baseline until it is not.
#
# The shared baseline is what makes the magnification safe. Sizing every glyph to fill the
# band instead was tried, and it is worse: the hyphen and the underscore are both a
# horizontal bar, and the only thing that tells them apart is that one sits at mid-height
# and the other on the floor. Fill the band with each and they become the same picture.
# Growing a mark about the baseline it belongs on keeps that cue: - stays high, _ stays
# low, ' stays at the top, and the period is finally a dot you can see.
GUIDE_BAND_USE = 0.92                        # share of the band the em may fill
GUIDE_MIN_INK_PT = 1.9                       # a mark thinner than this cannot be read
GUIDE_MAX_PT = 22.0
GUIDE_TOP_OFFSET = 0.0015                    # ink top, in page units, below each cell top
GUIDE_COLOR = "0.42"                         # grey: clearly a printed guide, not your ink
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


def missing_glyphs(font_path, chars):
    """Characters the guide font has no glyph for. They would print as empty boxes."""
    try:
        from fontTools.ttLib import TTFont
        cmap = TTFont(font_path, fontNumber=0).getBestCmap()
    except Exception as e:
        print(f"[template] could not read the font's character map ({e}); skipping the check")
        return []
    return [c for c in chars if ord(c) not in cmap]


def ink_bounds(font_path, chars):
    """Each character's ink box plus the face's vertical extent, all in em units.

    matplotlib can only report the *line* box, which is one height for every character in
    the face — a period and a Hangul syllable measure the same. Sizing a guide needs the
    ink, so it is taken from the outlines directly. A BoundsPen rather than the glyf table,
    so this works whether the face is TrueType or CFF.

    Returns (boxes, ascent_em, descent_em) with descent positive.
    """
    from fontTools.ttLib import TTFont
    from fontTools.pens.boundsPen import BoundsPen

    font = TTFont(font_path, fontNumber=0)
    upem = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    glyphs = font.getGlyphSet()

    try:
        hhea = font["hhea"]
        ascent, descent = hhea.ascent / upem, abs(hhea.descent) / upem
    except Exception:
        ascent, descent = 0.8, 0.2

    boxes = {}
    for ch in chars:
        name = cmap.get(ord(ch))
        if not name or name not in glyphs:
            continue
        pen = BoundsPen(glyphs)
        glyphs[name].draw(pen)
        if pen.bounds is None:          # a blank glyph, e.g. space
            continue
        _, y_min, _, y_max = pen.bounds
        boxes[ch] = (y_min / upem, y_max / upem)
    return boxes, ascent, descent


def plan_guides(chars, boxes, ascent, descent):
    """Point size and baseline for every guide.

    One size for the face, so every guide keeps its natural height and sits on a shared
    baseline; then any mark too small to read is grown about that baseline, and shrunk
    again only if growing it would push its ink out of the band.

    Returns {char: (fontsize_pt, baseline_below_cell_top_in_page_units)}.
    """
    pt_per_unit = PAGE_H_IN * 72.0                        # page units -> points
    band_pt = GUIDE_BAND_FRAC * CELL_H * pt_per_unit
    usable_pt = band_pt * GUIDE_BAND_USE - GUIDE_TOP_OFFSET * pt_per_unit

    base_size = usable_pt / max(ascent + descent, 1e-6)   # the whole em inside the band
    baseline_pt = GUIDE_TOP_OFFSET * pt_per_unit + ascent * base_size

    plan = {}
    for ch in chars:
        box = boxes.get(ch)
        if not box:
            continue
        y_min, y_max = box
        ink_em = max(y_max - y_min, 1e-6)

        size = base_size
        if ink_em * size < GUIDE_MIN_INK_PT:              # a speck: grow it
            size = min(GUIDE_MAX_PT, GUIDE_MIN_INK_PT / ink_em)

        # Grown about the shared baseline, the ink can reach past either end of the band.
        # Back the size off until it does not, rather than sliding the mark off its line.
        for _ in range(24):
            top = baseline_pt - y_max * size
            bottom = baseline_pt - y_min * size
            if top >= 0 and bottom <= band_pt:
                break
            size *= 0.94
            if size <= base_size:
                size = base_size
                break

        plan[ch] = (size, baseline_pt / pt_per_unit)
    return plan


def verify_plan(plan, boxes):
    """Confirm every planned guide's ink stays inside the band the cropper removes.

    A guide that overruns is not a cosmetic problem: the cropper hands that strip to the
    tracer, and the printed guide is welded into the writer's own letter. Returns the worst
    offender's share of the band.
    """
    band = GUIDE_BAND_FRAC * CELL_H
    pt_per_unit = PAGE_H_IN * 72.0

    worst, worst_char = 0.0, ""
    for ch, (size, drop) in plan.items():
        y_min, y_max = boxes[ch]
        # ink bottom, measured down from the cell top
        reach = drop - (y_min * size) / pt_per_unit
        if reach > worst:
            worst, worst_char = reach, ch
    ratio = worst / band if band else 0.0
    print(f"[template] guide fit: deepest {worst_char!r} reaches "
          f"{worst / CELL_H * 100:.1f}% into the cell against a "
          f"{GUIDE_BAND_FRAC * 100:.0f}% band ({ratio * 100:.0f}% of it used)")
    return ratio


def draw_page(pdf, chars, font_prop, plan):
    fig = plt.figure(figsize=(PAGE_W_IN, PAGE_H_IN))   # A4 portrait, inches
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
            ch = chars[idx]
            size, drop = plan.get(ch, (7.0, GUIDE_TOP_OFFSET))
            # va="baseline": the plan already worked out where the baseline has to sit for
            # this glyph's ink to hang from the top of the band.
            ax.text(x + CELL_W / 2, y_top - drop, ch,
                    fontproperties=font_prop, fontsize=size,
                    color=GUIDE_COLOR, ha="center", va="baseline")

    pdf.savefig(fig)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Generate the SoulFont handwriting template PDF.")
    ap.add_argument("--font", default=None, help="Korean-capable TTF/OTF for the guide glyphs.")
    ap.add_argument("--out", default=os.path.join(PROJ_ROOT, "static", "templates", "soulfont_template.pdf"))
    ap.add_argument("--force", action="store_true",
                    help="write the sheet even if a guide glyph overruns the trimmed band")
    args = ap.parse_args()

    font_path = resolve_font(args.font)
    font_prop = fm.FontProperties(fname=font_path)

    all_chars = list(KOR_STYLE_CHARS) + list(EXTRA_CHARS)
    pages = list(chunk(all_chars, CELLS_PER_PAGE))

    absent = missing_glyphs(font_path, all_chars)
    if absent:
        sys.exit(f"[template] {os.path.basename(font_path)} has no glyph for "
                 f"{''.join(absent)} — those cells would print as empty boxes and nobody "
                 f"could tell what to write in them. Pass a font that covers them with --font.")

    boxes, ascent, descent = ink_bounds(font_path, all_chars)
    plan = plan_guides(all_chars, boxes, ascent, descent)
    ratio = verify_plan(plan, boxes)
    if ratio >= 1.0 and not args.force:
        sys.exit("[template] a guide glyph reaches past the band the cropper trims, so it "
                 "would be traced into the font as the writer's own ink. Lower "
                 "GUIDE_FONTSIZE, or raise TOP_EXTRA_FRAC in foundry/char_layout.py so the "
                 "cropper removes more. Use --force to write the sheet anyway.")

    sizes = sorted(size for size, _ in plan.values())
    print(f"[template] guide sizes: {sizes[0]:.1f}-{sizes[-1]:.1f}pt "
          f"(one baseline; the small marks grown until they read)")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with PdfPages(args.out) as pdf:
        for page_chars in pages:
            draw_page(pdf, page_chars, font_prop, plan)

    print(f"[template] font: {font_path}")
    print(f"[template] layout: {TEMPLATE_LAYOUT_VERSION}")
    cell_w_mm = CELL_W * PAGE_W_IN * 25.4
    cell_h_mm = CELL_H * PAGE_H_IN * 25.4
    print(f"[template] {len(all_chars)} guides over {len(pages)} page(s), "
          f"{COLS}x{ROWS} = {CELLS_PER_PAGE} cells each "
          f"({len(KOR_STYLE_CHARS)} Korean + {len(EXTRA_CHARS)} extra, "
          f"{len(pages) * CELLS_PER_PAGE - len(all_chars)} left blank)")
    print(f"[template] cell {cell_w_mm:.1f} x {cell_h_mm:.1f} mm, "
          f"of which {(1 - GUIDE_BAND_FRAC - 0.06) * cell_h_mm:.1f} mm tall is yours to write in")
    print(f"[template] wrote {args.out}")


if __name__ == "__main__":
    main()
