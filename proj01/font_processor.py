import os, shutil, sys, yaml, subprocess
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageChops
from scipy import ndimage
from pdf2image import convert_from_path  # type: ignore

from inference import main as inference_main
from char_layout import (
    ALLOWED_TEMPLATE_CELL_COUNTS,
    FULL_TEMPLATE_CELL_COUNT,
    KOR_STYLE_CELL_COUNT,
    KOR_STYLE_CHARS,
    TEMPLATE_LAYOUT_VERSION,
    split_cells,
)

# --- Korean style reference characters, in the same order as the template cells ---
STYLE_CHARS = KOR_STYLE_CHARS

# --- Model architecture constants (must match the checkpoint) ---
MODEL_C = 32
MODEL_N_COMPS = 68
MODEL_N_COMP_TYPES = 3
LANGUAGE = 'kor'
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Default target set: KS X 1001 common-use 2,350 Hangul (much faster than the full
# 11,170 and covers everyday Korean). Swap to korean11172.txt for full coverage.
DEFAULT_CHARSET = os.path.join(PROJECT_ROOT, 'data', 'charset', 'korean2350.txt')
INK_PIXEL_THRESHOLD = 20

# The model emits 128x128 glyphs. The vectorizer reads edges from the anti-aliased raster
# at sub-pixel accuracy, so it does not need a big grid — but the cleanup below works on
# whole pixels, and a little headroom keeps it from eating real detail. Rasters already
# larger than this (the ENG/special cells come from the 512px template crops) keep their
# own resolution; real detail always beats interpolated detail.
TRACE_IMAGE_SIZE = int(os.environ.get('SOULFONT_TRACE_SIZE', 256))

# --- raster cleanup ------------------------------------------------------------------
# Every threshold below is a multiple of the glyph's own stroke width, never a fraction of
# the frame. The pen is the only scale that means anything here: a Hangul syllable fills
# three quarters of its frame while a lowercase 'o' fills a tenth of its own, so a single
# frame-relative threshold that removes pinholes from one will swallow the other's counter
# whole. Sizing by the pen also makes the cleanup identical whatever resolution a raster
# arrives at.
#
# A gap narrower than the pen cannot be something the pen drew around, so it is a hole in
# the ink rather than a counter — but a tightly written 'e' has a counter barely wider than
# the pen, so that test alone closes it up. A real counter is also a meaningful share of
# the glyph's ink; a pinhole is not. Both conditions have to hold before a gap is filled.
PINHOLE_STROKE_FRAC = 1.2
PINHOLE_INK_FRAC = 0.04
# Detached ink much smaller than the pen's own footprint is speckle.
SPECK_STROKE_FRAC = 0.6
# How far the outline is smoothed, via its distance field. Blurring a distance field moves
# the boundary toward the local mean curvature — notches fill and burrs flatten while
# stroke width survives, which is not true of blurring the image itself.
SMOOTH_STROKE_FRAC = 0.13
# How far stroke width is pulled toward its local average. Smoothing the outline above
# fixes ragged edges but makes width *less* even -- blurring a distance field thins convex
# places and thickens concave ones, so stroke ends get thinner and junctions fatter. This
# undoes that and the wobble the generator adds on top. At 0 the step is off; at 1 every
# stroke is a constant width, which is no longer handwriting.
STROKE_EVENNESS = float(os.environ.get('SOULFONT_STROKE_EVENNESS', 0.6))
UNITS_PER_EM = 1000


def _flatten_to_grayscale(path):
    img = Image.open(path)
    if img.mode == 'RGBA':
        bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        return bg.convert('L')
    return img.convert('L')


def _fill_pinholes(mask, max_area):
    """Close enclosed paper regions that are both smaller than max_area pixels and a
    negligible share of the glyph's own ink."""
    paper = ~mask
    labels, count = ndimage.label(paper)
    if count == 0:
        return mask
    edge = np.unique(np.concatenate([labels[0, :], labels[-1, :],
                                     labels[:, 0], labels[:, -1]]))
    sizes = ndimage.sum(paper, labels, np.arange(1, count + 1))
    ceiling = min(max_area, PINHOLE_INK_FRAC * float(mask.sum()))
    fill = np.zeros(count + 1, dtype=bool)
    interior = np.setdiff1d(np.arange(1, count + 1), edge)
    fill[interior] = sizes[interior - 1] <= ceiling
    return mask | fill[labels]


def _drop_speckle(mask, min_area):
    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    sizes = ndimage.sum(mask, labels, np.arange(1, count + 1))
    keep = np.concatenate([[False], sizes >= min_area])
    return keep[labels]


def _signed_distance(mask):
    """Distance to the ink boundary: negative inside the ink, positive outside."""
    return (ndimage.distance_transform_edt(~mask) -
            ndimage.distance_transform_edt(mask))


def _render_field(field, edge=1.2):
    """Draw a distance field back out as a glyph raster with an anti-aliased edge."""
    coverage = np.clip(0.5 - field / (2.0 * edge), 0.0, 1.0)
    return np.uint8(np.clip(255.0 * (1.0 - coverage), 0, 255))


def _smooth_outline(mask, sigma):
    """Smooth the boundary through its signed distance field."""
    if sigma <= 0:
        return _render_field(_signed_distance(mask))
    return _render_field(ndimage.gaussian_filter(_signed_distance(mask), sigma))


def _offset_outline(gray, delta_px):
    """Move every ink edge in (positive) or out (negative) by delta_px.

    Offsetting the distance field is a true parallel offset of the outline, so it changes
    stroke weight without the axis bias and integer-pixel quantization a rank filter has.
    """
    if abs(delta_px) < 1e-3:
        return np.asarray(gray, dtype=np.uint8)
    return _render_field(_signed_distance(np.asarray(gray) < 128) + float(delta_px))


def _mean_stroke_px(mask):
    """Mean stroke width, from the ribbon approximation area = width x length/2."""
    ink = int(mask.sum())
    if not ink:
        return 0.0
    edge = int((mask & ~ndimage.binary_erosion(mask)).sum())
    return 2.0 * ink / edge if edge else 0.0


def _even_stroke_width(gray, strength=STROKE_EVENNESS):
    """Take the wobble out of stroke width without moving where the strokes go.

    The generator draws strokes that swell and pinch along their length -- measured against
    the writers' own cells, about a third more variation than their pens had. The distance
    field's ridge *is* the stroke's half-width, so pulling that ridge toward a single width
    and redrawing the shape from it evens the stroke out, while the ridge itself -- the
    letterform, and every place the pen went -- stays exactly where it was.

    The target is the glyph's own median half-width, and the shape is redrawn as the reach
    of that width around the ridge. Two apparently better formulations were measured over
    all 15 handwriting samples and both lost, so they are recorded here rather than tried
    again (stroke spread, lower is better; fidelity to the writer in brackets):

        this, at strength 0.6                   0.197  (IoU 0.478)
        pull toward a *local* width average     0.271  (IoU 0.483)
        push the existing outline by its error  0.218  (IoU 0.480), roughest edges of the three

    The local average fails because the wobble's wavelength is close to any sensible
    window, so the average tracks the wobble instead of removing it. Modulating the
    existing outline fails because each pixel takes the error of its nearest ridge point,
    which is discontinuous across the glyph and shows up as rougher edges.

    `strength` below 1 is what leaves the writer's own variation in.
    """
    from skimage.morphology import skeletonize

    mask = np.asarray(gray) < 128
    if strength <= 0 or mask.sum() < 64:
        return np.asarray(gray, dtype=np.uint8)
    spine = skeletonize(mask)
    if spine.sum() < 8:
        return np.asarray(gray, dtype=np.uint8)

    half_width = ndimage.distance_transform_edt(mask)
    local = half_width * spine
    target = float(np.median(half_width[spine]))
    wanted = np.where(spine, (1.0 - strength) * local + strength * target, 0.0)

    reach = ndimage.distance_transform_edt(~spine)
    radius = ndimage.grey_dilation(wanted, size=max(3, int(2 * target + 5)))
    return _render_field(reach - radius)


def prepare_trace_images(src_dir, dst_dir, target_size=TRACE_IMAGE_SIZE):
    """Clean up glyph rasters so the vectorizer traces ink rather than generator noise.

    The model output stays untouched in ``src_dir``. Each glyph gets its pinholes closed
    and its speckle dropped — surgical, area-based edits that leave the rest of the shape
    exactly as drawn — then its outline smoothed through a distance field to take out the
    frayed edges, and finally its stroke width evened along the stroke.

    Each glyph's own stroke width sets every threshold, so a Hangul syllable filling its
    frame and a lowercase 'o' sitting small inside its own are cleaned to the same standard.
    """
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir, exist_ok=True)
    target_size = max(64, int(target_size))

    def prepare(fname):
        img = _flatten_to_grayscale(os.path.join(src_dir, fname))
        if img.width < target_size:
            img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)
        mask = np.asarray(img) < 128
        stroke = _mean_stroke_px(mask)
        if stroke > 0:
            mask = _drop_speckle(
                _fill_pinholes(mask, (PINHOLE_STROKE_FRAC * stroke) ** 2),
                (SPECK_STROKE_FRAC * stroke) ** 2)
        out = _smooth_outline(mask, SMOOTH_STROKE_FRAC * stroke)
        out = _even_stroke_width(out)
        Image.fromarray(out).save(os.path.join(dst_dir, fname))

    names = [f for f in os.listdir(src_dir) if f.lower().endswith('.png')]
    # A full Hangul set is 11k images and the filters release the GIL, so threads pay off.
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 1))) as pool:
        list(pool.map(prepare, names))
    harmonize_stroke_weight(dst_dir)
    return dst_dir


# One unit of `amount` moves each ink edge by this many font units, so a stroke gets twice
# this much thinner or thicker. Calibrated by building real weights and measuring them:
# 6.0 puts Hangul at 0.82 of Regular for Light and 1.43 for Bold, which is the 300/400/700
# spread a family wants.
WEIGHT_STEP_UNITS = 6.0
WEIGHT_MAX_UNITS = 30.0
# Latin needs a bigger nominal step than Hangul to move the same relative amount, and only
# when thinning. Its glyphs are small in their frame and then magnified, so an offset that
# is a comfortable fraction of a pixel for Hangul is a fraction of the anti-aliased edge
# ramp for Latin and mostly lost in the re-render -- but that only bites when the edge is
# pulled inward. Thickening has no such loss, and boosting it as hard overshot. Both
# numbers come from building the weights and measuring the finished fonts against the
# Latin/Hangul ratio the Regular weight settles at.
WEIGHT_LATIN_BOOST_LIGHT = 1.65
WEIGHT_LATIN_BOOST_BOLD = 1.1
# Bold sits twice as far from Regular as Light does, matching the 300 / 400 / 700 spread.
AUTO_LIGHT_AMOUNT = 1.0
AUTO_BOLD_AMOUNT = 1.5


def make_weight_variant(src_dir, dst_dir, weight='bold', amount=1.0):
    """Create a synthetic weight of every glyph PNG in src_dir into dst_dir.

    Glyphs are dark ink on white; a 'bold' weight pushes each ink edge outward and a
    'light' weight pulls it in. Run this on the *prepared* trace images: the offset is
    applied to the outline's distance field, so the step is a fraction of a pixel rather
    than the whole pixel a rank filter is stuck with — at the model's own 128px resolution
    a whole pixel is a third of a stroke, which is what used to erase thin strokes from
    the Light weight entirely.

    The step is stated in *finished font* units and converted per script, because the two
    are scaled by very different amounts afterwards: Hangul arrives near its final size and
    Latin gets magnified more than three times. Applying one raster-space step to both put
    three times as much weight change into the Latin, so Light came out with spindly
    English beside barely-changed Korean, and Bold the other way about.
    """
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir, exist_ok=True)
    amount = max(0.0, float(amount))
    direction = {'bold': -1.0, 'light': 1.0}.get(weight, 0.0)
    delta_units = direction * min(WEIGHT_MAX_UNITS, WEIGHT_STEP_UNITS * amount)
    scales = script_fit_scales(src_dir) if delta_units else {}

    def variant(fname):
        img = Image.open(os.path.join(src_dir, fname)).convert('L')
        if delta_units:
            cp = _glyph_codepoint(fname)
            is_hangul = (cp or 0) >= 0x1100
            boost = 1.0 if is_hangul else (
                WEIGHT_LATIN_BOOST_BOLD if weight == 'bold' else WEIGHT_LATIN_BOOST_LIGHT)
            scale = scales['hangul' if is_hangul else 'latin']
            px = (delta_units * boost / scale) * img.width / float(UNITS_PER_EM)
            img = Image.fromarray(_offset_outline(np.asarray(img), px))
        img.save(os.path.join(dst_dir, fname))

    names = [f for f in os.listdir(src_dir) if f.lower().endswith('.png')]
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 1))) as pool:
        list(pool.map(variant, names))
    return dst_dir


# Commercial Korean handwriting families keep Latin within 1.05-1.10x the Hangul stroke
# (measured on Nanum 손글씨 and NanumBaReunJeongSin). Ours arrived at ~2x, because the two
# scripts reach the em by different routes and are scaled to different targets.
CROSS_SCRIPT_WEIGHT_RATIO = 1.05
# Never take more than this share of the group's stroke width off. Letters written small
# and then scaled up to a real cap height legitimately need most of a stroke removed, so
# the ceiling has to be generous; past it, thin features start disappearing and something
# upstream is more likely wrong than the pen.
MAX_WEIGHT_CORRECTION = 0.70


def _glyph_codepoint(fname):
    stem = os.path.splitext(fname)[0]
    if '_' not in stem:
        return None
    try:
        return int(stem.rsplit('_', 1)[1], 16)
    except ValueError:
        return None


def _split_by_script(trace_dir):
    """Group the prepared rasters into Hangul and everything else."""
    hangul, latin = [], []
    for name in os.listdir(trace_dir):
        if not name.lower().endswith('.png'):
            continue
        cp = _glyph_codepoint(name)
        if cp is None:
            continue
        (hangul if cp >= 0x1100 else latin).append(os.path.join(trace_dir, name))
    return hangul, latin


def script_fit_scales(trace_dir, sample=200):
    """How much refine_metrics will scale each script when it fits them into the em.

    Hangul is sized so a tall syllable reaches KOR_TARGET_HEIGHT; Latin so a capital
    reaches LATIN_CAP_TARGET. Both are predictable from the rasters, and anything measured
    in raster space has to be divided by them to mean anything in the finished font.
    """
    from refine_metrics import (KOR_HEIGHT_PERCENTILE, KOR_TARGET_HEIGHT, LATIN_CAP_TARGET)

    def height_share(paths, percentile, only_caps=False):
        shares = []
        if len(paths) > sample:
            step = len(paths) / float(sample)
            paths = [paths[int(i * step)] for i in range(sample)]
        for path in paths:
            cp = _glyph_codepoint(os.path.basename(path))
            if only_caps and not (cp is not None and ord('A') <= cp <= ord('Z')):
                continue
            img = Image.open(path).convert('L')
            mask = np.asarray(img) < 128
            if not mask.any():
                continue
            rows = np.flatnonzero(mask.any(axis=1))
            shares.append((rows[-1] - rows[0] + 1) / float(img.height))
        return float(np.percentile(shares, percentile)) if shares else 0.0

    hangul, latin = _split_by_script(trace_dir)
    kor = height_share(sorted(hangul), KOR_HEIGHT_PERCENTILE)
    cap = height_share(sorted(latin), 50, only_caps=True)
    return {
        'hangul': KOR_TARGET_HEIGHT / kor if kor > 0 else 1.0,
        'latin': LATIN_CAP_TARGET / cap if cap > 0 else 1.0,
    }


def _skeleton_stroke_px(mask):
    """Stroke width as twice the distance from the skeleton to the nearest edge.

    Unlike the area-over-perimeter estimate this is not thrown off by junctions, which
    matters here: a Hangul syllable is mostly crossings and a Latin letter is mostly not,
    so an estimator that reacts to them would read the two scripts on different scales.
    """
    from skimage.morphology import skeletonize
    if mask.sum() < 32:
        return 0.0
    spine = skeletonize(mask)
    if spine.sum() < 4:
        return 0.0
    return 2.0 * float(np.median(ndimage.distance_transform_edt(mask)[spine]))


def _rendered_stroke_units(font_path, script, size=500, limit=110):
    """Median stroke width of one script in a finished font, in font units.

    Characters are taken from the font's own cmap rather than a fixed list: anything it
    does not have would render as .notdef, and measuring that reports the width of the
    notdef box instead of any handwriting.
    """
    from PIL import ImageDraw, ImageFont
    from fontTools.ttLib import TTFont
    try:
        face = ImageFont.truetype(font_path, size)
        covered = sorted(TTFont(font_path).getBestCmap())
    except Exception:
        return 0.0

    if script == 'hangul':
        points = [cp for cp in covered if cp >= 0x1100]
    else:
        points = [cp for cp in covered if cp < 0x1100 and chr(cp).isalnum()]
    if not points:
        return 0.0
    if len(points) > limit:
        step = len(points) / float(limit)
        points = [points[int(i * step)] for i in range(limit)]

    widths = []
    for cp in points:
        canvas = Image.new('L', (size * 3, size * 3), 255)
        ImageDraw.Draw(canvas).text((size // 2, size // 2), chr(cp), font=face, fill=0)
        mask = np.asarray(canvas) < 128
        width = _skeleton_stroke_px(mask)
        if width > 0:
            widths.append(width * UNITS_PER_EM / size)
    return float(np.median(widths)) if widths else 0.0


def _probe_font(paths, work_dir, name):
    """Build and fit a throwaway font from a handful of glyphs, to measure the real thing.

    Every stage between a raster and a finished outline moves stroke weight a little —
    the distance-field smoothing, the contour smoothing, the curve fit, the scale the fit
    applies. Predicting the sum of that in closed form kept missing by 15-25%, so measure
    it instead: this is the same font the pipeline would produce, just smaller.
    """
    import contextlib
    import io

    from glyph_vectorizer import build_ttf
    from refine_metrics import refine_metrics
    sample_dir = os.path.join(work_dir, name + '_glyphs')
    if os.path.isdir(sample_dir):
        shutil.rmtree(sample_dir)
    os.makedirs(sample_dir)
    for path in paths:
        shutil.copyfile(path, os.path.join(sample_dir, os.path.basename(path)))
    out = os.path.join(work_dir, name + '.ttf')
    with contextlib.redirect_stdout(io.StringIO()):
        build_ttf(sample_dir, out, 'Probe')
        refine_metrics(out)
    shutil.rmtree(sample_dir, ignore_errors=True)
    return out


# Give up after this many measure-and-correct rounds; it converges in one or two.
WEIGHT_ROUNDS = 5
# Stop once the two scripts are this close in weight.
WEIGHT_TOLERANCE = 0.04


def harmonize_stroke_weight(trace_dir, target_ratio=CROSS_SCRIPT_WEIGHT_RATIO):
    """Match the traced ENG/special glyphs to the Hangul's pen weight.

    Hangul reaches the em through the model and is scaled to fill a target syllable
    height; Latin is traced from the page and scaled to a target cap height. Two different
    scales applied to two different sources leave the two scripts at visibly different
    weights in the same line of text, however faithful each is on its own: this handwriting
    arrived at 2x, where commercial Korean families sit within 1.0-1.1x.

    Rather than predict where a raster edge ends up after four stages of processing, build
    a small probe font, measure both scripts in it, correct, and check again.
    """
    names = [f for f in os.listdir(trace_dir) if f.lower().endswith('.png')]
    hangul, latin = [], []
    for name in names:
        cp = _glyph_codepoint(name)
        if cp is None:
            continue
        (hangul if cp >= 0x1100 else latin).append(os.path.join(trace_dir, name))
    if not hangul or not latin:
        return 0.0

    # A big enough Hangul sample that the probe's pen width matches the finished font's:
    # at 48 glyphs it read 3% heavy, which the loop then chased in the wrong direction.
    step = max(1, len(hangul) // 140)
    sample = sorted(hangul)[::step][:140] + latin
    work_dir = os.path.join(trace_dir, '_weight_probe')
    os.makedirs(work_dir, exist_ok=True)
    applied = 0.0
    kor = 0.0
    try:
        for attempt in range(WEIGHT_ROUNDS):
            probe = _probe_font(sample, work_dir, 'probe')
            if not kor:
                # The Hangul is never touched, so measure it once: re-reading it every
                # round only feeds the loop the estimator's own noise.
                kor = _rendered_stroke_units(probe, 'hangul')
            lat = _rendered_stroke_units(probe, 'latin')
            if kor <= 0 or lat <= 0:
                break
            ratio = lat / kor
            if abs(ratio - target_ratio) <= WEIGHT_TOLERANCE * target_ratio:
                break

            # Thinning also shrinks the capitals, and the fit then scales the smaller
            # letters up harder, putting some of the weight straight back. Solve for both
            # at once rather than stepping into it: with pre-fit stroke w and cap h, and a
            # correction u taken off each, the finished weight goes as (w-u)/(h-u).
            target = kor * target_ratio
            w, h = _latin_raster_shape(latin)
            if w <= 0 or h <= 0:
                break
            denom = w * target - lat * h
            raw = h * w * (target - lat) / denom if abs(denom) > 1e-6 else 0.0
            limit = MAX_WEIGHT_CORRECTION * w
            raster_delta = max(-limit, min(limit, raw)) / 2.0
            if abs(raster_delta) < 0.5:
                break
            applied += raster_delta

            def adjust(path, shift=raster_delta):
                img = Image.open(path).convert('L')
                px = shift * img.width / float(UNITS_PER_EM)
                Image.fromarray(_offset_outline(np.asarray(img), px)).save(path)

            with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 1))) as pool:
                list(pool.map(adjust, latin))
            print(f"[trace] stroke weight round {attempt + 1}: hangul {kor:.0f}u, "
                  f"latin {lat:.0f}u (x{ratio:.2f})")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return applied


def _latin_raster_shape(latin_paths):
    """Pre-fit stroke width and cap height of the Latin rasters, against a 1000-unit frame."""
    strokes, heights = [], []
    for path in latin_paths:
        cp = _glyph_codepoint(os.path.basename(path))
        if cp is None:
            continue
        img = Image.open(path).convert('L')
        mask = np.asarray(img) < 128
        if not mask.any():
            continue
        frame = float(img.height)
        width = _skeleton_stroke_px(mask)
        if width > 0:
            strokes.append(width * UNITS_PER_EM / frame)
        if ord('A') <= cp <= ord('Z'):
            rows = np.flatnonzero(mask.any(axis=1))
            heights.append((rows[-1] - rows[0] + 1) * UNITS_PER_EM / frame)
    if not strokes or not heights:
        return 0.0, 0.0
    return float(np.median(strokes)), float(np.median(heights))


class FontStyleProcessor:
    def __init__(self, pdf_path, charset_path=DEFAULT_CHARSET, device_name='auto', use_amp=False):
        self.pdf_path = pdf_path
        self.base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        self.output_dir = os.path.join(PROJECT_ROOT, "style", self.base_name)
        self.cropped_dir = os.path.join(self.output_dir, "cropped")
        # Same cells, kept in their original framing instead of trimmed to each mark.
        self.framed_dir = os.path.join(self.output_dir, "framed")
        self.cleaned_dir = os.path.join(self.output_dir, "cleaned")
        self.yaml_path = os.path.join(PROJECT_ROOT, "configs", f"{self.base_name}.yaml")
        self.checkpoint = os.path.join(PROJECT_ROOT, "checkpoints", "korean-handwriting.pth")
        self.save_dir = os.path.join(PROJECT_ROOT, "static", "outputs", self.base_name)
        self.charset_path = charset_path
        self.device_name = device_name
        self.use_amp = use_amp
        os.makedirs(self.output_dir, exist_ok=True)

    def reset_intermediates(self):
        """Drop stale generated files that can outlive a template layout change."""
        for dirname in (self.cropped_dir, self.framed_dir, self.cleaned_dir, self.save_dir):
            if os.path.isdir(dirname):
                shutil.rmtree(dirname)

        for fname in os.listdir(self.output_dir):
            if fname.lower().endswith((".png", ".jpg", ".jpeg")):
                os.remove(os.path.join(self.output_dir, fname))

    def convert_pdf_to_images(self):
        images = convert_from_path(self.pdf_path, dpi=300)
        for i, img in enumerate(images):
            fname = (f"{self.output_dir}/{self.base_name}_p{i+1}.png"
                     if len(images) > 1 else f"{self.output_dir}/{self.base_name}.png")
            img.save(fname, dpi=(300, 300))
            print(f"[SAVE] {fname}")

    def trim_and_save_images(self):
        def trim_whitespace(path):
            img = Image.open(path)
            bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
            diff = ImageChops.difference(img, bg)
            bbox = diff.getbbox()
            if bbox:
                img.crop(bbox).save(path)

        for fname in os.listdir(self.output_dir):
            if fname.lower().endswith((".png", ".jpg", ".jpeg")):
                trim_whitespace(os.path.join(self.output_dir, fname))

        subprocess.run([
            sys.executable, os.path.join(PROJECT_ROOT, "style", "crop.py"),
            f"--src_dir={self.output_dir}",
            f"--dst_dir={self.cropped_dir}",
            f"--frame_dir={self.framed_dir}",
        ], check=True)

    def clean_images(self):
        os.makedirs(self.cleaned_dir, exist_ok=True)
        for fname in os.listdir(self.cropped_dir):
            if fname.endswith(".png"):
                img = Image.open(os.path.join(self.cropped_dir, fname)).convert("L")
                img_np = np.array(img)
                img_bin = np.where(img_np > 200, 255, 0).astype(np.uint8)
                img_cleaned = Image.fromarray(img_bin).resize((128, 128), Image.Resampling.LANCZOS)
                img_cleaned.save(os.path.join(self.cleaned_dir, fname))

    def _load_target_chars(self):
        with open(self.charset_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    def _cleaned_paths(self):
        return [
            os.path.join(self.cleaned_dir, f)
            for f in sorted(os.listdir(self.cleaned_dir)) if f.endswith(".png")
        ]

    @staticmethod
    def _ink_pixels(path):
        img = Image.open(path).convert("L")
        return sum(img.histogram()[:128])

    def _validated_cleaned_paths(self):
        cleaned_paths = self._cleaned_paths()
        count = len(cleaned_paths)
        if count not in ALLOWED_TEMPLATE_CELL_COUNTS:
            expected = ", ".join(str(n) for n in sorted(ALLOWED_TEMPLATE_CELL_COUNTS))
            raise ValueError(
                "Template crop count mismatch: "
                f"expected {expected} cells, got {count}. "
                "Use the current downloaded template or the original 28-cell Korean template."
            )

        style_paths = cleaned_paths[:KOR_STYLE_CELL_COUNT]
        blank_cells = [
            i + 1 for i, path in enumerate(style_paths)
            if self._ink_pixels(path) < INK_PIXEL_THRESHOLD
        ]
        if blank_cells:
            raise ValueError(
                "Korean style reference cells are blank or unreadable: "
                f"{blank_cells}. Fill all first-page Korean cells and upload again."
            )

        return cleaned_paths

    def generate_yaml(self, target_chars):
        # Only the first 28 cells are Korean style references for the model; any extra
        # cells are English/special glyphs handled by copy_traced_glyphs().
        cleaned_paths = self._validated_cleaned_paths()
        style_imgs, _ = split_cells(cleaned_paths)
        if len(style_imgs) != len(STYLE_CHARS):
            raise ValueError(
                f"Expected {len(STYLE_CHARS)} Korean style images, got {len(style_imgs)}"
            )
        cfg = {
            'template_layout_version': TEMPLATE_LAYOUT_VERSION,
            'template_cell_count': len(cleaned_paths),
            'template_full_cell_count': FULL_TEMPLATE_CELL_COUNT,
            'style_imgs': style_imgs,
            'style_chars': STYLE_CHARS,
            'charset_path': self.charset_path,
            'output_dir': self.save_dir,
            'checkpoint': self.checkpoint,
            'num_font_samples': 1,
            'target_chars': target_chars,
            'C': MODEL_C,
            'n_comps': MODEL_N_COMPS,
            'n_comp_types': MODEL_N_COMP_TYPES,
            'language': LANGUAGE,
        }
        os.makedirs(os.path.dirname(self.yaml_path), exist_ok=True)
        with open(self.yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, allow_unicode=True)

    def run_inference(self):
        target_chars = self._load_target_chars()
        os.makedirs(self.save_dir, exist_ok=True)
        self.generate_yaml(target_chars)
        print(f"[INFO] Generating {len(target_chars)} Korean characters")
        inference_main(
            self.yaml_path,
            self.checkpoint,
            self.save_dir,
            device_name=self.device_name,
            use_amp=self.use_amp,
        )
        print("[INFO] All Korean characters generated successfully.")

    def copy_traced_glyphs(self):
        """Embed English/special glyphs by tracing the user's own handwriting.

        The model only knows Hangul, so these cells bypass it: each handwriting image is
        written into the output as inferred_<CODEPOINT>.png, which generateTTF.js then
        vectorizes into the font like any other glyph.

        These glyphs never go through the 128x128 model, so they are taken from the
        full-resolution template crop instead of the downsampled model input — four times
        the detail, straight from the user's pen — and from the *framed* crop, which keeps
        each mark at the size and height it was actually written at, so 'a' stays smaller
        than 'b' and one pen width stays one pen width across the whole alphabet.
        """
        _, traced_glyphs = split_cells(self._validated_cleaned_paths())
        os.makedirs(self.save_dir, exist_ok=True)
        for char, src in traced_glyphs:
            dst = os.path.join(self.save_dir, f"inferred_{ord(char):04X}.png")
            framed = os.path.join(self.framed_dir, os.path.basename(src))
            if os.path.exists(framed):
                # Same ink/paper split as clean_images; prepare_trace_images does the
                # smoothing, so this only has to separate pen from paper.
                img = Image.open(framed).convert("L")
                img.point(lambda v: 255 if v > 200 else 0).save(dst)
            else:
                shutil.copyfile(src, dst)
        if traced_glyphs:
            print(f"[INFO] Embedded {len(traced_glyphs)} traced ENG/special glyphs")

    def run_all(self):
        self.reset_intermediates()
        self.convert_pdf_to_images()
        self.trim_and_save_images()
        self.clean_images()
        self.run_inference()
        self.copy_traced_glyphs()
