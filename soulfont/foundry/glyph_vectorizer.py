"""Turn cleaned glyph rasters into TrueType outlines made of real curves.

The previous tracer (generateTTF.js, ImageTracer) walks the pixel grid and emits mostly
straight segments: 87% of its points are on-curve, against 35-41% in commercial Korean
fonts. That ratio *is* the faceted look — a font whose outlines are polygons rather than
curves, and no amount of parameter tuning changes it, because that tracer never fits
curves in the first place.

This module replaces it with the three stages a vector tracer actually needs:

  1. Sub-pixel contours. Marching squares interpolates the level set of the anti-aliased
     raster, so an edge is located to a fraction of a pixel instead of being snapped to the
     pixel grid. That alone removes the stair-stepping at the source.
  2. Corner-aware smoothing. Taubin smoothing (an inward Laplacian pass alternating with an
     outward one) removes tracing wobble without the shrinkage plain Laplacian smoothing
     causes, and corners are detected first so the pen's sharp turns survive it.
  3. Least-squares quadratic fitting, subdividing only where the error exceeds tolerance.
     TrueType stores quadratics, so fitting them directly avoids a lossy cubic conversion.

Everything is measured in font units at UNITS_PER_EM, never in pixels, so the same
settings hold whatever resolution the rasters arrive at.

Usage (code): from glyph_vectorizer import build_ttf; build_ttf(glyph_dir, out_path)
Usage (CLI):  python glyph_vectorizer.py <glyph_dir> <out_path> [font_name]
"""
import math
import os
import re
import sys

import numpy as np
from PIL import Image
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from skimage import measure

UNITS_PER_EM = 1000
# The raster frame maps onto the em with this much of it below the baseline, matching the
# convention refine_metrics expects.
DESCENT = 200

# --- tracing parameters, all in font units -------------------------------------------
CONTOUR_LEVEL = 127.5        # the ink/paper boundary in the 0-255 raster
RESAMPLE_STEP = 4.0          # spacing of the points the curve is fitted through
TAUBIN_PASSES = 6            # more passes = smoother outline, less faithful detail
CORNER_WINDOW = 12.0         # arc length either side of a point used to measure its turn
CORNER_ANGLE = math.radians(48)   # a turn sharper than this is a pen corner, not a curve
FIT_TOLERANCE = 6.0          # max distance a fitted curve may stray from the outline
MAX_SUBDIVISIONS = 12
# Noise is judged against the glyph it sits in, never against a fixed size: a period is a
# legitimately tiny contour, and a flat threshold big enough to drop tracing dirt from a
# Hangul syllable deletes it outright. A speck is a contour that is negligible next to the
# rest of the glyph's ink; a period, having no rest, is all of it.
MIN_CONTOUR_INK_FRAC = 0.004
MIN_CONTOUR_AREA = 40        # below this a contour is degenerate at any size

GLYPH_FILE_RE = re.compile(r'inferred_([0-9A-Fa-f]+)\.png$')

# The .notdef box, drawn so its advance leaves an even bearing on both sides.
NOTDEF_LEFT, NOTDEF_RIGHT = 80, 520


# ---------------------------------------------------------------------------
# Contours
# ---------------------------------------------------------------------------
def _extract_contours(gray):
    """Sub-pixel outlines of the ink, as (row, col) float arrays."""
    ink = 255.0 - np.asarray(gray, dtype=np.float64)
    # Pad with paper so shapes touching the frame edge still close into a loop.
    padded = np.pad(ink, 1, mode='constant', constant_values=0.0)
    return [c - 1.0 for c in measure.find_contours(padded, CONTOUR_LEVEL)]


def _signed_area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _contains(poly, pt):
    """Ray-cast point-in-polygon, used to work out which contours are holes."""
    x, y = pt
    px, py = poly[:, 0], poly[:, 1]
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    crosses = (py > y) != (qy > y)
    if not crosses.any():
        return False
    with np.errstate(divide='ignore', invalid='ignore'):
        xint = px + (y - py) * (qx - px) / (qy - py)
    return bool(np.count_nonzero(crosses & (xint > x)) % 2)


def _resample(contour, step):
    """Uniform arc-length resampling — the corner test needs a predictable stride."""
    p = contour[:-1] if np.allclose(contour[0], contour[-1]) else contour
    if len(p) < 4:
        return p
    closed = np.vstack([p, p[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total = s[-1]
    if total <= 1e-9:
        return p
    n = max(8, int(round(total / step)))
    t = np.linspace(0.0, total, n, endpoint=False)
    return np.column_stack([np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])])


def _taubin(p, passes=TAUBIN_PASSES, lamb=0.5, mu=-0.53):
    """Smooth without shrinking: each inward pass is undone by a slightly larger outward one."""
    if len(p) < 6 or passes <= 0:
        return p
    q = np.asarray(p, dtype=np.float64).copy()
    for i in range(passes):
        k = lamb if i % 2 == 0 else mu
        q += k * ((np.roll(q, 1, 0) + np.roll(q, -1, 0)) / 2.0 - q)
    return q


def _find_corners(p, span, alpha_max=CORNER_ANGLE):
    """Indices where the outline turns sharply enough to be a deliberate corner."""
    n = len(p)
    k = max(1, int(span))
    if n < 3 * k:
        return []
    a = p - np.roll(p, k, 0)
    b = np.roll(p, -k, 0) - p
    ang = np.abs(np.arctan2(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0], (a * b).sum(1)))
    corners = []
    for i in np.where(ang > alpha_max)[0]:
        # Keep only the sharpest point of each cluster, so one corner yields one index.
        if ang[i] < ang[np.arange(i - k, i + k + 1) % n].max() - 1e-12:
            continue
        if corners and min((i - corners[-1]) % n, (corners[-1] - i) % n) < k:
            continue
        corners.append(int(i))
    return corners


# ---------------------------------------------------------------------------
# Quadratic fitting
# ---------------------------------------------------------------------------
def _fit_one(pts):
    """The single quadratic through fixed endpoints that best fits the points between."""
    p0, pn = pts[0], pts[-1]
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] <= 1e-9:
        return (p0 + pn) / 2.0, 0.0, len(pts) // 2
    t = s / s[-1]
    w = 2.0 * (1.0 - t) * t
    denom = float((w * w).sum())
    if denom < 1e-12:
        return (p0 + pn) / 2.0, 0.0, len(pts) // 2
    residual = pts - ((1 - t) ** 2)[:, None] * p0 - (t ** 2)[:, None] * pn
    ctrl = (w[:, None] * residual).sum(0) / denom
    fitted = ((1 - t) ** 2)[:, None] * p0 + w[:, None] * ctrl + (t ** 2)[:, None] * pn
    err = np.linalg.norm(fitted - pts, axis=1)
    worst = int(np.argmax(err))
    return ctrl, float(err[worst]), worst


def _fit_arc(pts, tol, depth=0):
    """Fit an arc with as few quadratics as the tolerance allows."""
    if len(pts) < 3:
        return [((pts[0] + pts[-1]) / 2.0, pts[-1])]
    ctrl, err, worst = _fit_one(pts)
    if err <= tol or depth >= MAX_SUBDIVISIONS or worst <= 0 or worst >= len(pts) - 1:
        return [(ctrl, pts[-1])]
    return (_fit_arc(pts[:worst + 1], tol, depth + 1) +
            _fit_arc(pts[worst:], tol, depth + 1))


def _fit_closed(p, corners, tol):
    """Fit a closed contour as a chain of quadratics running corner to corner."""
    n = len(p)
    if not corners:
        # A contour with no corners (a bowl, a dot) still needs cut points to fit through.
        corners = [0, n // 4, n // 2, (3 * n) // 4]
    corners = sorted(set(corners))
    segments = []
    for a, b in zip(corners, corners[1:] + [corners[0] + n]):
        segments.extend(_fit_arc(p[np.arange(a, b + 1) % n], tol))
    return p[corners[0]], segments


# ---------------------------------------------------------------------------
# Glyph assembly
# ---------------------------------------------------------------------------
def outline_glyph(gray, fit_scale=1.0):
    """Trace one raster into a TrueType glyph.

    ``fit_scale`` is how much refine_metrics will enlarge this glyph afterwards. Every
    tolerance below is quoted in *finished font* units, so it has to be divided by that
    before use — otherwise a script that gets magnified is also fitted that much more
    loosely. Latin is scaled about 3.4x where Hangul is scaled 1.06x, which was giving the
    Latin 20 units of allowed deviation against the Hangul's 6: loose enough to smooth away
    a whole weight step, which is why Light and Bold barely moved the English.
    """
    gray = np.asarray(gray)
    height = gray.shape[0]
    scale = UNITS_PER_EM / float(height)     # raster pixels -> font units
    fit_scale = max(1e-3, float(fit_scale))
    baseline = UNITS_PER_EM - DESCENT

    found = [(c, abs(_signed_area(c)) * scale * scale)
             for c in _extract_contours(gray) if len(c) >= 8]
    # Outer contours enclose the holes inside them, so their areas already bound the ink.
    total = max((a for _, a in found), default=0.0)
    floor = max(MIN_CONTOUR_AREA, MIN_CONTOUR_INK_FRAC * total)
    polys = [c for c, area in found if area >= floor]

    step = (RESAMPLE_STEP / fit_scale) / scale
    span = max(1, int(round(CORNER_WINDOW / RESAMPLE_STEP)))
    tol = (FIT_TOLERANCE / fit_scale) / scale

    pen = TTGlyphPen(None)
    for contour in polys:
        # Holes sit inside an odd number of other contours and must wind the other way.
        is_hole = sum(1 for other in polys
                      if other is not contour and _contains(other, contour[0])) % 2 == 1
        p = _taubin(_resample(contour, step))
        start, segments = _fit_closed(p, _find_corners(p, span), tol)

        # Marching squares winds every contour the same way; flip the ones that need it so
        # outer contours run clockwise in font space and holes run counter-clockwise.
        if (_signed_area(p) > 0) == is_hole:
            ends = [start] + [e for _, e in segments]
            ctrls = [c for c, _ in segments]
            segments = [(ctrls[i], ends[i]) for i in range(len(ctrls) - 1, -1, -1)]
            start = ends[-1]

        def to_font(q):
            return (int(round(q[1] * scale)), int(round(baseline - q[0] * scale)))

        pen.moveTo(to_font(start))
        for ctrl, end in segments:
            pen.qCurveTo(to_font(ctrl), to_font(end))
        pen.closePath()
    return pen.glyph()


def _codepoint_of(filename):
    m = GLYPH_FILE_RE.search(filename)
    if not m:
        return None
    try:
        return int(m.group(1), 16)
    except ValueError:
        return None


def _notdef_glyph():
    """A hollow box, so a character the font does not have is visible rather than absent.

    An empty .notdef makes missing characters disappear silently, which reads as text the
    app lost rather than a character it never had.
    """
    pen = TTGlyphPen(None)
    left, right = NOTDEF_LEFT, NOTDEF_RIGHT
    bottom, top = 0, 660
    bar = 60
    for box in ((left, bottom, right, top),
                (left + bar, bottom + bar, right - bar, top - bar)):
        x0, y0, x1, y1 = box
        corners = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        # The counter runs the other way round so it knocks a hole in the frame.
        if box[0] != left:
            corners.reverse()
        pen.moveTo(corners[0])
        for point in corners[1:]:
            pen.lineTo(point)
        pen.closePath()
    return pen.glyph()


def build_ttf(glyph_dir, out_path, font_name='SoulFont', fit_scales=None):
    """Vectorize every glyph PNG in glyph_dir and write a TTF.

    Advances are placeholders: refine_metrics fits the real spacing afterwards, the same
    way it does for any other tracer's output. ``fit_scales`` is the {'hangul': x,
    'latin': y} that refine_metrics will apply, from font_processor._script_fit_scales; it
    keeps the fitting tolerances equal in the delivered font rather than in the raster.
    """
    fit_scales = fit_scales or {}
    files = sorted(f for f in os.listdir(glyph_dir) if f.lower().endswith('.png'))
    order = ['.notdef']
    glyphs = {'.notdef': _notdef_glyph()}
    metrics = {'.notdef': (NOTDEF_RIGHT + NOTDEF_LEFT, NOTDEF_LEFT)}
    cmap = {}
    blank = []

    for fname in files:
        cp = _codepoint_of(fname)
        if cp is None:
            continue
        name = 'uni%04X' % cp
        if name in glyphs:
            continue
        gray = Image.open(os.path.join(glyph_dir, fname)).convert('L')
        fit_scale = fit_scales.get('hangul' if cp >= 0x1100 else 'latin', 1.0)
        glyph = outline_glyph(np.asarray(gray, dtype=np.float64), fit_scale)
        if glyph.numberOfContours <= 0:
            # An unwritten template cell traces to nothing. Shipping it would map the
            # character to an invisible glyph, so the text silently vanishes wherever it
            # is typed; leaving it out lets the reader's system substitute another font.
            blank.append(cp)
            continue
        glyphs[name] = glyph
        order.append(name)
        metrics[name] = (UNITS_PER_EM, 0)
        cmap[cp] = name

    if blank:
        shown = ' '.join(f'U+{cp:04X}' for cp in blank[:12])
        print(f'[vectorize] {len(blank)} blank cell(s) left out of the font: {shown}'
              + ('...' if len(blank) > 12 else ''))
    if not cmap:
        raise ValueError(f'No glyph PNGs found in {glyph_dir}')

    fb = FontBuilder(unitsPerEm=UNITS_PER_EM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=UNITS_PER_EM - DESCENT, descent=-DESCENT)
    fb.setupNameTable({
        'familyName': font_name,
        'styleName': 'Regular',
        'psName': re.sub(r'[^A-Za-z0-9]', '', font_name) or 'SoulFont',
    })
    fb.setupOS2()
    fb.setupPost()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fb.save(out_path)
    print(f'[vectorize] {len(cmap)} glyphs -> {out_path}')
    return out_path


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python glyph_vectorizer.py <glyph_dir> <out_path> [font_name]')
        sys.exit(1)
    build_ttf(sys.argv[1], sys.argv[2],
              sys.argv[3] if len(sys.argv) > 3 else 'SoulFont')
