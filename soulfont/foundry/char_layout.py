"""Central definition of the handwriting-template cell layout.

The template is cropped cell-by-cell in row-major order (see foundry/crop.py), producing
one cleaned 128x128 image per cell. This module fixes the *order* of those cells so the
pipeline knows which image is which character.

Layout contract (the physical template must follow this order):

    cells[0 : 28]                -> KOR_STYLE_CHARS   (Korean style references -> model)
    cells[28 : 28+len(EXTRA)]    -> EXTRA_CHARS       (English/digits/special -> traced
                                                       directly into the font, no model)

If a template only has the original 28 Korean cells, EXTRA_CHARS simply maps to nothing
and the pipeline behaves exactly as before (backward compatible).
"""
import math

TEMPLATE_LAYOUT_VERSION = "kor-28-plus-ascii-v4-10x13"

# The printed grid. 10x13 on A4 gives a cell of about 18.1 x 20.6 mm, against the 25.8 x
# 40.8 mm of the 4x7 sheet it replaces — roughly a third of the area, and close to square
# rather than a tall letterbox, which is the shape a Hangul syllable actually wants.
#
# The whole set now lands on a single page. That is the point of the smaller cell: 125
# guides at 4x7 took four sheets to print, fill and scan, and every extra sheet is another
# chance for one to be missed, fed in crooked, or scanned at a different exposure.
TEMPLATE_ROWS = 13
TEMPLATE_COLS = 10
TEMPLATE_CELLS_PER_PAGE = TEMPLATE_ROWS * TEMPLATE_COLS

# How much of each cell crop.py throws away, as a fraction of the cell.
#
# These live here rather than in crop.py because they are a contract between two files
# that never import each other: the cropper trims this much, and the template generator
# has to keep the printed guide glyph inside the trimmed band or the guide ends up traced
# into the font as though the user had drawn it. With the band expressed here, the
# generator can check its own artwork against the number the cropper will actually use
# (see scripts/generate_template.py, which refuses to write a sheet that would leak).
CELL_PAD_FRAC = 0.06     # trimmed off every cell edge — drops the printed grid line
TOP_EXTRA_FRAC = 0.14    # trimmed off the cell top as well — drops the printed guide glyph
# The band the guide has to fit inside, measured from the very top of the cell.
GUIDE_BAND_FRAC = CELL_PAD_FRAC + TOP_EXTRA_FRAC

# 28 Korean style-reference characters, in template-cell order.
# The v3 template uses 쭲 at slot 14 so the medial ㅝ is present in style memory.
KOR_STYLE_CHARS = list("각깪냓댼떥렎멷볠뽉솲쐛욄죭쭲춣퀨튑퓺흣읬잉잊잋잌잍잎잏이")

# English uppercase, lowercase, digits.
ENG_CHARS = (
    [chr(c) for c in range(ord('A'), ord('Z') + 1)] +
    [chr(c) for c in range(ord('a'), ord('z') + 1)] +
    [chr(c) for c in range(ord('0'), ord('9') + 1)]
)

# Punctuation and symbols.
#
# The whole of printable ASCII, rather than a hand-picked twenty. Completing it is the
# boundary worth drawing: what fell outside the old set was $ < > [ \ ] ^ _ ` { | } ~ —
# the characters addresses, prices, file paths, code and emoticons are made of, so a font
# that stopped short of them dropped a glyph in the middle of ordinary writing.
ASCII_PUNCTUATION = list("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

# The marks everyday Korean writing needs that ASCII has no room for: the won sign, the
# reference mark that heads a note in almost every Korean form or notice, and the degree
# sign. Both candidate guide fonts carry all three.
KOREAN_DAILY_MARKS = list("\u20a9\u203b\u00b0")

# Deliberately absent, because refine_metrics derives each one from a mark the writer has
# already drawn — asking for them again would cost cells and buy nothing:
#   ‘ ’ from '     “ ” from "     – — ― − from -     … and · from .
SPECIAL_CHARS = ASCII_PUNCTUATION + KOREAN_DAILY_MARKS

# Everything produced by tracing the user's own handwriting (not the model), in order.
EXTRA_CHARS = ENG_CHARS + SPECIAL_CHARS

KOR_STYLE_CELL_COUNT = len(KOR_STYLE_CHARS)
FULL_TEMPLATE_GUIDE_COUNT = KOR_STYLE_CELL_COUNT + len(EXTRA_CHARS)
FULL_TEMPLATE_CELL_COUNT = (
    math.ceil(FULL_TEMPLATE_GUIDE_COUNT / TEMPLATE_CELLS_PER_PAGE) *
    TEMPLATE_CELLS_PER_PAGE
)
ALLOWED_TEMPLATE_CELL_COUNTS = {KOR_STYLE_CELL_COUNT, FULL_TEMPLATE_CELL_COUNT}


def split_cells(cleaned_paths):
    """Split ordered cleaned-cell image paths into (style_imgs, traced_glyphs).

    Args:
        cleaned_paths: image paths sorted in template-cell order.
    Returns:
        style_imgs: list of paths for the Korean style references (<= 28).
        traced_glyphs: list of (char, path) for ENG/special glyphs to embed directly.
    """
    n_style = len(KOR_STYLE_CHARS)
    style_imgs = cleaned_paths[:n_style]
    extra_imgs = cleaned_paths[n_style:]
    traced_glyphs = list(zip(EXTRA_CHARS, extra_imgs))  # truncates to shortest
    return style_imgs, traced_glyphs
