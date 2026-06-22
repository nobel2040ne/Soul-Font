"""Central definition of the handwriting-template cell layout.

The template is cropped cell-by-cell in row-major order (see style/crop.py), producing
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

TEMPLATE_LAYOUT_VERSION = "kor-28-plus-extra-v3-ssyweo"
TEMPLATE_ROWS = 4
TEMPLATE_COLS = 7
TEMPLATE_CELLS_PER_PAGE = TEMPLATE_ROWS * TEMPLATE_COLS

# 28 Korean style-reference characters, in template-cell order.
# The v3 template uses 쭲 at slot 14 so the medial ㅝ is present in style memory.
KOR_STYLE_CHARS = list("각깪냓댼떥렎멷볠뽉솲쐛욄죭쭲춣퀨튑퓺흣읬잉잊잋잌잍잎잏이")

# English uppercase, lowercase, digits.
ENG_CHARS = (
    [chr(c) for c in range(ord('A'), ord('Z') + 1)] +
    [chr(c) for c in range(ord('a'), ord('z') + 1)] +
    [chr(c) for c in range(ord('0'), ord('9') + 1)]
)

# Common special characters / punctuation.
SPECIAL_CHARS = list(".,!?'\"()-:;@#%&*/+=")

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
