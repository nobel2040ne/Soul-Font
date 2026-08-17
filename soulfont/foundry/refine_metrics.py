"""Turn the raw traced glyph set into a font with real typographic metrics.

Glyphs arrive from the vectorizer with the raster's geometry and nothing else: each one
sits wherever it was drawn in its frame and carries a placeholder full-em advance. For
Hangul that leaves ~640 units of air around a syllable only 360 wide, so Korean falls
apart into isolated characters; for Latin there is no baseline, no cap height and no
spacing at all.

This post-process runs before set_font_metadata and fits both scripts:

  * scale the em up to 1000 units (smooth rendering, normal coordinates),
  * drop speck contours left behind by the vectorizer,
  * size Latin/symbol glyphs to a real cap height, seat them on a baseline, and give them
    proportional advances + side bearings,
  * size the Hangul syllables to a consistent share of the em and give them proportional
    advances, so Korean sets with natural rhythm instead of gaps,
  * add the space glyph the traced glyph set has no cell for,
  * set vertical metrics that cover the real outlines so nothing clips.

Hangul is transformed with a *single* scale shared by every syllable, so the relative
size, slant and baseline drift of the user's handwriting survive untouched — only the
overall fit inside the em changes.

Usage (code): from refine_metrics import refine_metrics; refine_metrics(path)
Usage (CLI):  python refine_metrics.py <ttf_path> [out_path]
"""
import sys
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.pens.ttGlyphPen import TTGlyphPen

TARGET_UPEM = 1000
SPACE_ADVANCE = 320    # advance for empty glyphs (space)

# --- Latin fitting --------------------------------------------------------------------
# Each template cell is square-padded around the letter, and the whole cell maps to the em,
# so a letter written inside its cell lands at barely half the em. Fitting the capitals to
# a real cap height first is what makes a side bearing mean anything.
#
# The target is set against the Hangul, not against Latin convention alone: Korean fonts
# draw a syllable 1.2-1.5x the height of a capital (measured across Nanum 손글씨 and
# NanumBaReunJeongSin), and this cap lands in that range against KOR_TARGET_HEIGHT. Taller
# Latin makes English tower over the Korean beside it in mixed text.
LATIN_CAP_TARGET = 0.60
# Letters keep the framing of the template cell they were written in, so they sit small
# inside it and the scale needed to reach a real cap height is correspondingly large.
LATIN_SCALE_LIMITS = (0.6, 6.0)
# Side bearing as a share of the cap height, so it tracks the letters it separates.
LATIN_SB_RATIO = 0.055
LATIN_SB_LIMITS = (16, 90)

# --- Hangul fitting -------------------------------------------------------------------
# Tall syllables should reach this share of the em. The scale derived from it is applied
# to every Hangul glyph alike, so it changes the size of the script, never its proportions.
KOR_TARGET_HEIGHT = 0.80
KOR_HEIGHT_PERCENTILE = 90   # "a tall syllable" — ignores the few outliers that overshoot
KOR_SCALE_LIMITS = (0.75, 1.35)
# Side bearing as a share of the em. Nanum 손글씨, 온글잎 and NanumSeongSirCe all sit at
# ~0.023 em regardless of how wide their syllables are: Hangul gets its rhythm from the
# internal structure of the syllable, not from air around its bounding box. Anything much
# larger and Korean stops reading as words.
KOR_SB_EM = 0.025
# Floor on the advance so the narrowest syllables (이, 니) still get room to breathe.
KOR_MIN_ADVANCE = 0.28

# A contour this much smaller than the glyph's largest is tracer noise, not ink. Judged
# against the glyph rather than at a fixed size, so the two dots of a colon survive.
SPECK_AREA_FRAC = 0.004
SPECK_AREA_FLOOR = 40

# Design vertical metrics. The real ascent/descent are widened to the outlines if needed.
TYPO_ASCENDER = 800
TYPO_DESCENDER = -200
# Handwriting fills almost the whole em top to bottom, so consecutive lines would touch
# at a bare 1.0em leading. This gap is what makes multi-line Korean readable by default.
LINE_GAP = 120

# Letters whose bowl sits on the x-line and whose tail hangs below the baseline. Because
# the glyphs now carry their true relative sizes, hanging them by the top of the bowl
# derives each tail's real depth instead of dropping every one by the same guess.
DESCENDERS = set(ord(c) for c in "gjpqy")
# Marks that rest on the baseline and dip a little below it.
LOW_MARKS = set(ord(c) for c in ",;")
LOW_MARK_DROP = 0.09
# Letters whose height defines the x-line.
X_HEIGHT_LETTERS = set(ord(c) for c in "acemnorsuvwxz")
# Tall symmetric brackets read best centered on the text, not sitting on the baseline.
CENTERED = set(ord(c) for c in "()")
TOP_ALIGNED = set(ord(c) for c in "'\"`´‘’“”")

SPACE_CODEPOINTS = (0x20, 0xA0)
# Full-width space, used between Korean words in some layouts.
IDEOGRAPHIC_SPACE = 0x3000

# Marks the template has no cell for but which ordinary Korean and English text is full
# of. Each is the same shape as one the user did write, so it costs no artwork and turns
# a row of tofu into readable punctuation. Typographic quotes in particular are what most
# editors auto-insert, so a font without them looks broken the moment anyone types one.
GLYPH_ALIASES = {
    "'": (0x2018, 0x2019, 0x02BC),          # ‘ ’ and the modifier apostrophe
    '"': (0x201C, 0x201D),                  # “ ”
    '-': (0x2010, 0x2011, 0x2013, 0x2212),  # hyphen, non-breaking hyphen, en dash, minus
}
# Dashes that should be wider than the hyphen they are drawn from: em dash and the
# horizontal bar Korean uses for the same job.
WIDE_DASHES = ((0x2014, 1.9), (0x2015, 1.9))
# Marks built by repeating or shifting one the user did write.
ELLIPSIS = 0x2026        # … three periods on the baseline
MIDDLE_DOT = 0x00B7      # · a period raised to the middle of the x-height


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


def _percentile(values, pct):
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def _median(values):
    return _percentile(values, 50)


# ---------------------------------------------------------------------------
# Outline cleanup
# ---------------------------------------------------------------------------
def _contour_slices(glyph):
    start = 0
    for end in glyph.endPtsOfContours:
        yield start, end
        start = end + 1


def _signed_area(coords, start, end):
    """Shoelace area over the contour's points (on- and off-curve alike).

    Exact only for polygons, but a speck is a speck either way — this is a size filter,
    not a measurement.
    """
    total = 0
    count = end - start + 1
    for i in range(start, end + 1):
        x1, y1 = coords[i]
        x2, y2 = coords[start + ((i - start + 1) % count)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _drop_speck_contours(glyf, floor=SPECK_AREA_FLOOR):
    """Delete pinprick contours the tracer picks up from stray pixels.

    Single-contour glyphs are never touched: a period is a legitimate speck.
    """
    removed = 0
    for name in glyf.keys():
        glyph = glyf[name]
        if glyph.numberOfContours <= 1:
            continue
        coords = glyph.coordinates
        slices = list(_contour_slices(glyph))
        areas = [abs(_signed_area(coords, s, e)) for s, e in slices]
        min_area = max(floor, SPECK_AREA_FRAC * max(areas))
        keep = [sl for sl, area in zip(slices, areas) if area >= min_area]
        if len(keep) == glyph.numberOfContours or not keep:
            continue

        new_coords, new_flags, new_ends = [], [], []
        for s, e in keep:
            new_coords.extend(coords[i] for i in range(s, e + 1))
            new_flags.extend(glyph.flags[i] for i in range(s, e + 1))
            new_ends.append(len(new_coords) - 1)
        removed += glyph.numberOfContours - len(keep)
        glyph.coordinates = GlyphCoordinates(new_coords)
        glyph.flags = type(glyph.flags)(glyph.flags.typecode, new_flags) \
            if hasattr(glyph.flags, 'typecode') else bytearray(new_flags)
        glyph.endPtsOfContours = new_ends
        glyph.numberOfContours = len(new_ends)
    return removed


# ---------------------------------------------------------------------------
# Glyph-table surgery
# ---------------------------------------------------------------------------
def _rename_notdef(font):
    """Give glyph 0 its reserved name so the font matches the TrueType spec."""
    order = list(font.getGlyphOrder())
    if not order or order[0] == '.notdef' or '.notdef' in order:
        return
    old, glyf, hmtx = order[0], font['glyf'], font['hmtx']
    if old not in glyf.glyphs:
        return
    glyf.glyphs['.notdef'] = glyf.glyphs.pop(old)
    hmtx.metrics['.notdef'] = hmtx.metrics.pop(old, (0, 0))
    order[0] = '.notdef'
    _set_glyph_order(font, order)


def _set_glyph_order(font, order):
    # setGlyphOrder also refreshes the glyf table's order and drops the cached
    # name -> glyph id map; maxp is ours to keep in sync.
    font.setGlyphOrder(order)
    font['maxp'].numGlyphs = len(order)


def _ensure_space_glyphs(font, advance):
    """Add the space glyph. No template cell draws one, so the traced set has no U+0020.

    Without it, words run together in anything that does not silently substitute another
    font for the missing character.
    """
    glyf, hmtx = font['glyf'], font['hmtx']
    order = list(font.getGlyphOrder())
    if 'space' not in order:
        glyph = Glyph()
        glyph.numberOfContours = 0
        glyf.glyphs['space'] = glyph
        order.append('space')
        _set_glyph_order(font, order)
    hmtx.metrics['space'] = (max(1, int(advance)), 0)

    _map_codepoints(font, {cp: 'space' for cp in SPACE_CODEPOINTS})


def _map_codepoints(font, mapping):
    """Point codepoints at glyphs that already exist, in every usable cmap subtable."""
    for table in font['cmap'].tables:
        # Format 0 is the legacy byte-indexed Mac table: it stores glyph *ids* as single
        # bytes, and a glyph appended at the end of an 11k-glyph font can never fit.
        # Every platform that matters reads the format 4/12 tables.
        if table.format == 0:
            continue
        for cp, name in mapping.items():
            table.cmap.setdefault(cp, name)


def _add_derived_glyphs(font, upem, x_line):
    """Fill the punctuation gaps the template has no cell for.

    Everything here is a copy or a repeat of a mark the user did write, so it carries their
    hand rather than inventing a shape. Best-effort throughout: a font missing an
    apostrophe simply keeps its gap rather than failing the build.
    """
    glyf, hmtx = font['glyf'], font['hmtx']
    cmap = font.getBestCmap()
    added = []

    aliases = {}
    for source, targets in GLYPH_ALIASES.items():
        name = cmap.get(ord(source))
        if name and name in glyf.glyphs and glyf[name].numberOfContours > 0:
            for cp in targets:
                if cp not in cmap:
                    aliases[cp] = name
    if aliases:
        _map_codepoints(font, aliases)
        added.append(f'{len(aliases)} alias(es)')

    # A full-width space, sized like a Hangul syllable rather than a Latin word gap.
    if IDEOGRAPHIC_SPACE not in cmap and 'space' in glyf.glyphs:
        name = 'uni3000'
        if _add_glyph(font, name, Glyph(), (round(0.5 * upem), 0)):
            _map_codepoints(font, {IDEOGRAPHIC_SPACE: name})
            added.append('ideographic space')

    hyphen = cmap.get(ord('-'))
    if hyphen and hyphen in glyf.glyphs and glyf[hyphen].numberOfContours > 0:
        glyf[hyphen].recalcBounds(glyf)
        for cp, stretch in WIDE_DASHES:
            if cp in cmap:
                continue
            name = 'uni%04X' % cp
            pen = TTGlyphPen(glyf.glyphs)
            # Stretched horizontally only, so the dash keeps the pen's own thickness.
            pen.addComponent(hyphen, (stretch, 0, 0, 1, 0, 0))
            width = round(hmtx[hyphen][0] * stretch)
            if _add_glyph(font, name, pen.glyph(), (width, hmtx[hyphen][1])):
                _map_codepoints(font, {cp: name})
                added.append('em dash' if cp == 0x2014 else 'horizontal bar')

    period = cmap.get(ord('.'))
    if period and period in glyf.glyphs and glyf[period].numberOfContours > 0:
        glyf[period].recalcBounds(glyf)
        advance = hmtx[period][0]
        height = glyf[period].yMax - glyf[period].yMin
        if ELLIPSIS not in cmap:
            name = 'uni2026'
            pen = TTGlyphPen(glyf.glyphs)
            for i in range(3):
                pen.addComponent(period, (1, 0, 0, 1, i * advance, 0))
            if _add_glyph(font, name, pen.glyph(), (3 * advance, hmtx[period][1])):
                _map_codepoints(font, {ELLIPSIS: name})
                added.append('ellipsis')
        if MIDDLE_DOT not in cmap:
            name = 'uni00B7'
            pen = TTGlyphPen(glyf.glyphs)
            pen.addComponent(period, (1, 0, 0, 1, 0, round(x_line / 2 - height / 2)))
            if _add_glyph(font, name, pen.glyph(), hmtx[period]):
                _map_codepoints(font, {MIDDLE_DOT: name})
                added.append('middle dot')

    if added:
        print(f"[metrics] derived glyphs: {', '.join(added)}")


def _add_glyph(font, name, glyph, metrics):
    """Insert a glyph, taking its left side bearing from where the ink actually lands.

    A composite's outline moves with its transform, so copying the source glyph's bearing
    would leave hmtx disagreeing with the outline it describes.
    """
    try:
        glyf = font['glyf']
        if name in glyf.glyphs:
            return False
        glyf.glyphs[name] = glyph
        _set_glyph_order(font, list(font.getGlyphOrder()) + [name])
        lsb = int(metrics[1])
        if glyph.numberOfContours != 0:
            glyph.recalcBounds(glyf)
            lsb = glyph.xMin
        font['hmtx'].metrics[name] = (max(1, int(metrics[0])), lsb)
        return True
    except Exception as e:
        print(f'[metrics] could not add {name}: {e}')
        return False


# ---------------------------------------------------------------------------
def _shift(glyph, dx, dy, scale=1.0):
    coords = glyph.coordinates
    for i in range(len(coords)):
        x, y = coords[i]
        coords[i] = (round(x * scale + dx), round(y * scale + dy))


def _split_scripts(font, glyf):
    cp_of = {name: cp for cp, name in font.getBestCmap().items()}
    kor_names, latin_names = [], []
    for name in glyf.keys():
        cp = cp_of.get(name)
        if cp is None:
            continue
        (kor_names if _is_cjk(cp) else latin_names).append(name)
    return cp_of, kor_names, latin_names


def _compute_hangul_fit(glyf, kor_names, upem):
    """How much to grow the syllables, and how much air to leave around them."""
    side_bearing = round(KOR_SB_EM * upem)
    heights = []
    for name in kor_names:
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        glyph.recalcBounds(glyf)
        heights.append(glyph.yMax - glyph.yMin)
    if not heights:
        return {'scale': 1.0, 'side_bearing': side_bearing}

    tall = _percentile(heights, KOR_HEIGHT_PERCENTILE) or 1
    scale = min(KOR_SCALE_LIMITS[1],
                max(KOR_SCALE_LIMITS[0], (KOR_TARGET_HEIGHT * upem) / tall))
    return {'scale': scale, 'side_bearing': side_bearing}


def _compute_latin_fit(glyf, cp_of, latin_names, upem):
    """Scale the capitals to a real cap height, and size the side bearing from it."""
    caps, x_heights = [], []
    for name in latin_names:
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        glyph.recalcBounds(glyf)
        cp = cp_of.get(name)
        if cp is None:
            continue
        if ord('A') <= cp <= ord('Z'):
            caps.append(glyph.yMax - glyph.yMin)
        elif cp in X_HEIGHT_LETTERS:
            x_heights.append(glyph.yMax - glyph.yMin)

    target_cap = LATIN_CAP_TARGET * upem
    scale = 1.0
    if caps:
        scale = min(LATIN_SCALE_LIMITS[1],
                    max(LATIN_SCALE_LIMITS[0], target_cap / (_median(caps) or 1)))
    side_bearing = min(LATIN_SB_LIMITS[1],
                       max(LATIN_SB_LIMITS[0], round(LATIN_SB_RATIO * target_cap)))

    # The x-line, measured rather than assumed: it is where descender bowls get hung from.
    x_height = round(_median(x_heights) * scale) if x_heights else round(0.55 * target_cap)
    return {'scale': scale, 'side_bearing': side_bearing,
            'cap_height': round(target_cap), 'x_height': x_height}


def measure_fit(ttf_path):
    """Read the Hangul and Latin fits out of a freshly traced font, without modifying it.

    Weights of one family must share a single fit. Measuring each weight separately would
    read the thinner Light strokes as a smaller script and grow it to compensate — on a
    real glyph set that is a ~15% size difference between Light and Bold, which is exactly
    the mismatch a family is supposed to avoid. Measure once on Regular, reuse everywhere.
    """
    font = TTFont(ttf_path)
    _scale_upem(font, TARGET_UPEM)
    glyf = font['glyf']
    cp_of, kor_names, latin_names = _split_scripts(font, glyf)
    upem = font['head'].unitsPerEm
    return {
        'hangul': _compute_hangul_fit(glyf, kor_names, upem),
        'latin': _compute_latin_fit(glyf, cp_of, latin_names, upem),
    }


def _set_vertical_metrics(font):
    """Design leading, with the clipping box widened to whatever the outlines need."""
    glyf = font['glyf']
    tops = [glyf[n].yMax for n in glyf.keys() if glyf[n].numberOfContours > 0]
    bottoms = [glyf[n].yMin for n in glyf.keys() if glyf[n].numberOfContours > 0]
    asc = max(TYPO_ASCENDER, max(tops) if tops else 0)
    desc = min(TYPO_DESCENDER, min(bottoms) if bottoms else 0)

    font['hhea'].ascent, font['hhea'].descent, font['hhea'].lineGap = asc, desc, LINE_GAP
    os2 = font['OS/2']
    os2.sTypoAscender = TYPO_ASCENDER
    os2.sTypoDescender = TYPO_DESCENDER
    os2.sTypoLineGap = LINE_GAP
    # usWin* is a clipping box, not a leading hint: it has to cover the real outlines.
    os2.usWinAscent, os2.usWinDescent = asc, abs(desc)


def refine_metrics(ttf_path, out_path=None, fit=None):
    """Fit outlines and metrics. Pass ``fit`` from measure_fit() to make a secondary
    weight match the size and spacing of the family's Regular."""
    out_path = out_path or ttf_path
    font = TTFont(ttf_path)
    _scale_upem(font, TARGET_UPEM)
    _rename_notdef(font)

    glyf = font['glyf']
    hmtx = font['hmtx']
    upem = font['head'].unitsPerEm
    specks = _drop_speck_contours(glyf, SPECK_AREA_FLOOR * (upem / TARGET_UPEM) ** 2)

    cp_of, kor_names, latin_names = _split_scripts(font, glyf)

    fit = fit or {}
    kor_fit = fit.get('hangul') or _compute_hangul_fit(glyf, kor_names, upem)
    lat_fit = fit.get('latin') or _compute_latin_fit(glyf, cp_of, latin_names, upem)

    # --- Hangul: one shared scale, then proportional advances --------------------------
    kor_scale, kor_sb = kor_fit['scale'], kor_fit['side_bearing']

    for name in kor_names:
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            hmtx[name] = (round(KOR_TARGET_HEIGHT * upem * 0.5), 0)
            continue
        # Scale about the baseline so the syllables keep sitting where they were drawn,
        # then centre the ink in an advance sized from its own width.
        _shift(glyph, dx=0, dy=0, scale=kor_scale)
        glyph.recalcBounds(glyf)
        ink_w = glyph.xMax - glyph.xMin
        advance = min(upem, max(KOR_MIN_ADVANCE * upem, ink_w + 2 * kor_sb))
        lsb = round((advance - ink_w) / 2)
        _shift(glyph, dx=lsb - glyph.xMin, dy=0)
        glyph.recalcBounds(glyf)
        hmtx[name] = (max(1, round(advance)), lsb)

    # --- Latin / symbols: cap-height fit, baseline + proportional advances -------------
    lat_scale, lat_sb = lat_fit['scale'], lat_fit['side_bearing']
    cap_top = lat_fit['cap_height']
    mid_line = cap_top // 2
    x_line = lat_fit.get('x_height') or round(0.55 * cap_top)
    for name in latin_names:
        glyph = glyf[name]
        cp = cp_of[name]
        if glyph.numberOfContours <= 0:                 # space / empty
            _, lsb = hmtx[name]
            hmtx[name] = (SPACE_ADVANCE, lsb)
            continue

        _shift(glyph, dx=0, dy=0, scale=lat_scale)
        glyph.recalcBounds(glyf)
        ink_w = glyph.xMax - glyph.xMin

        # horizontal: move ink to start at the side bearing; advance = ink + both bearings
        dx = lat_sb - glyph.xMin
        if cp in TOP_ALIGNED:
            # Quotes/apostrophes hang near the cap-height top, not on the baseline.
            dy = cap_top - glyph.yMax
        elif cp in CENTERED:
            # Brackets: center the ink on the text midline so they straddle the baseline.
            dy = mid_line - (glyph.yMin + glyph.yMax) // 2
        elif cp in DESCENDERS:
            # Hang the bowl from the x-line so the tail's depth comes from the letter's
            # own proportions rather than one fixed drop for every descender.
            dy = x_line - glyph.yMax
        elif cp in LOW_MARKS:
            dy = -glyph.yMin - round(LOW_MARK_DROP * upem)
        else:
            dy = -glyph.yMin          # rest on the baseline

        _shift(glyph, dx, dy)
        glyph.recalcBounds(glyf)
        hmtx[name] = (max(1, round(ink_w + 2 * lat_sb)), lat_sb)

    _ensure_space_glyphs(font, SPACE_ADVANCE)
    try:
        _add_derived_glyphs(font, upem, x_line)
    except Exception as e:
        # Extra punctuation is a bonus; never let it cost the caller the whole font.
        print(f'[metrics] derived glyphs skipped: {e}')

    _set_vertical_metrics(font)

    font.save(out_path)
    print(
        f"[metrics] refined -> {out_path} "
        f"(hangul scale={kor_scale:.3f}/sb={kor_sb}, "
        f"latin scale={lat_scale:.3f}/sb={lat_sb}, specks removed={specks})"
    )
    return out_path


def adjust_font_geometry(ttf_path, out_path=None, letter_spacing=0, glyph_scale=1.0):
    """Apply user editor adjustments to an already-generated TTF.

    Args:
        letter_spacing: font-unit delta added to every non-empty glyph advance.
        glyph_scale: outline scale, taken about the baseline.

    Scaling about each glyph's own centre would move every glyph a different distance off
    the baseline — at scale 1.2 the capitals sink 61 units and the lowercase 35, which is a
    font whose letters no longer sit on a line. The baseline is the fixed point; the extra
    width is shared evenly on both sides so glyphs stay centred in their advances.
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

        if g.numberOfContours <= 0 or not hasattr(g, 'coordinates'):
            hmtx[name] = (max(1, aw + letter_spacing), lsb)
            continue

        try:
            g.recalcBounds(glyf)
            cx = (g.xMin + g.xMax) / 2.0
            coords = g.coordinates
        except Exception:
            hmtx[name] = (max(1, aw + letter_spacing), lsb)
            continue

        for i in range(len(coords)):
            x, y = coords[i]
            coords[i] = (round(cx + (x - cx) * glyph_scale), round(y * glyph_scale))
        g.recalcBounds(glyf)
        advance = max(1, aw + letter_spacing)
        # Re-seat the ink in its advance so the wider outline does not run into the
        # neighbour on one side while leaving a gap on the other.
        shift = round((advance - (g.xMax - g.xMin)) / 2.0) - g.xMin
        if shift:
            for i in range(len(coords)):
                x, y = coords[i]
                coords[i] = (x + shift, y)
            g.recalcBounds(glyf)
        hmtx[name] = (advance, g.xMin)

    _set_vertical_metrics(font)
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
