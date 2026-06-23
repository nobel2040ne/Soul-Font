"""Give the traced Latin/symbol glyphs of a handwriting TTF real typographic metrics.

The glyphs come out of generateTTF.js with icon-style geometry: a tiny 128-unit em, every
glyph centred in a full-em box (so no shared baseline) and a fixed advance width (so the
text looks monospaced). For Latin that reads as raw, badly-spaced text; this post-process
fixes ONLY the Latin/symbol glyphs, before set_font_metadata runs:

  * scale the em up to 1000 units (smooth rendering, normal coordinates),
  * give Latin/symbol glyphs a proportional advance width + side bearings from their ink,
  * sit them on a real baseline (ink bottom -> baseline; known descenders drop below),
  * set sane vertical metrics so line spacing is normal.

CJK / Hangul glyphs are deliberately left exactly as the pipeline produced them (only the
neutral em scale touches them), because Korean syllables need full-block alignment, not the
ink-baseline treatment that suits Latin. So this never changes how Korean looks or spaces —
it's purely the English/symbol fix.

Usage (code): from refine_metrics import refine_metrics; refine_metrics(path)
Usage (CLI):  python refine_metrics.py <ttf_path> [out_path]
"""
import sys
from fontTools.ttLib import TTFont

TARGET_UPEM = 1000
SB_LATIN = 60          # side bearing for Latin/symbols (~6% em)
SB_CJK = 96            # roomier side bearing for Hangul/CJK
DESC_DEPTH = 200       # how far descenders drop below the baseline
SPACE_ADVANCE = 320    # advance for empty glyphs (space)
CAP_TOP = 720          # top target for quote marks and other top-hanging marks
MID_LINE = CAP_TOP // 2  # vertical center target for symmetric brackets

# Glyphs that should hang below the baseline rather than rest on it.
DESCENDERS = set(ord(c) for c in "gjpqy,;")
# Tall symmetric brackets read best centered on the text, not sitting on the baseline.
CENTERED = set(ord(c) for c in "()")
TOP_ALIGNED = set(ord(c) for c in "'\"`´‘’“”")


def _is_cjk(cp):
    # Hangul jamo/syllables and CJK live at U+1100 and up; ASCII/Latin/punct below.
    return cp is not None and cp >= 0x1100


def _scale_upem(font, new_upem):
    try:
        from fontTools.ttLib.scaleUpem import scale_upem
        if font['head'].unitsPerEm != new_upem:
            scale_upem(font, new_upem)
    except Exception as e:
        print(f"[metrics] em scale skipped ({e})")


def refine_metrics(ttf_path, out_path=None):
    out_path = out_path or ttf_path
    font = TTFont(ttf_path)
    _scale_upem(font, TARGET_UPEM)

    glyf = font['glyf']
    hmtx = font['hmtx']
    cp_of = {name: cp for cp, name in font.getBestCmap().items()}

    for name in glyf.keys():
        cp = cp_of.get(name)
        # Leave Korean/CJK (and any unmapped glyph) exactly as generated — Latin only.
        if cp is None or _is_cjk(cp):
            continue
        g = glyf[name]
        if g.numberOfContours <= 0:                 # space / empty -> just a sensible advance
            aw, lsb = hmtx[name]
            hmtx[name] = (SPACE_ADVANCE, lsb)
            continue

        g.recalcBounds(glyf)
        sb = SB_CJK if _is_cjk(cp) else SB_LATIN
        ink_w = g.xMax - g.xMin

        # horizontal: move ink to start at `sb`, advance = ink + both side bearings
        dx = sb - g.xMin
        if cp in TOP_ALIGNED:
            # Quotes/apostrophes hang near the cap-height top, not on the baseline.
            dy = CAP_TOP - g.yMax
        elif cp in CENTERED:
            # Brackets: center the ink on the text midline so they straddle the baseline.
            dy = MID_LINE - (g.yMin + g.yMax) // 2
        else:
            # vertical: rest on the baseline; descenders hang below it
            drop = DESC_DEPTH if (cp in DESCENDERS) else 0
            dy = -g.yMin - drop

        for i in range(len(g.coordinates)):
            x, y = g.coordinates[i]
            g.coordinates[i] = (x + dx, y + dy)
        g.recalcBounds(glyf)

        hmtx[name] = (max(1, round(ink_w + 2 * sb)), sb)

    # normal vertical metrics for the new em
    asc, desc = 800, -200
    font['hhea'].ascent, font['hhea'].descent, font['hhea'].lineGap = asc, desc, 0
    os2 = font['OS/2']
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = asc, desc, 0
    os2.usWinAscent, os2.usWinDescent = 900, 300

    font.save(out_path)
    print(f"[metrics] refined -> {out_path}")
    return out_path


def adjust_font_geometry(ttf_path, out_path=None, letter_spacing=0, glyph_scale=1.0):
    """Apply user editor adjustments to an already-generated TTF.

    Args:
        letter_spacing: font-unit delta added to every non-empty glyph advance.
        glyph_scale: outline scale around each glyph's own center.
    """
    out_path = out_path or ttf_path
    letter_spacing = int(letter_spacing)
    glyph_scale = max(0.5, min(1.6, float(glyph_scale)))

    font = TTFont(ttf_path)
    glyf = font['glyf']
    hmtx = font['hmtx']

    for name in glyf.keys():
        if name not in hmtx.metrics:
            continue
        g = glyf[name]
        aw, lsb = hmtx[name]

        if g.numberOfContours <= 0:
            hmtx[name] = (max(1, aw + letter_spacing), lsb)
            continue

        try:
            g.recalcBounds(glyf)
            cx = (g.xMin + g.xMax) / 2
            cy = (g.yMin + g.yMax) / 2
            coords = g.coordinates
        except Exception:
            hmtx[name] = (max(1, aw + letter_spacing), lsb)
            continue

        for i in range(len(coords)):
            x, y = coords[i]
            coords[i] = (
                round(cx + (x - cx) * glyph_scale),
                round(cy + (y - cy) * glyph_scale),
            )
        g.recalcBounds(glyf)
        hmtx[name] = (max(1, aw + letter_spacing), lsb)

    font.save(out_path)
    print(
        f"[metrics] adjusted spacing={letter_spacing}, "
        f"scale={glyph_scale:.2f} -> {out_path}"
    )
    return out_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python refine_metrics.py <ttf_path> [out_path]")
        sys.exit(1)
    refine_metrics(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
