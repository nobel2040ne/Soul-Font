import os, shutil, sys, yaml, subprocess
import numpy as np
from PIL import Image, ImageChops, ImageFilter
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


def _flatten_to_grayscale(path):
    img = Image.open(path)
    if img.mode == 'RGBA':
        bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        return bg.convert('L')
    return img.convert('L')


def stabilize_strokes(src_dir, dst_dir, median_size=3, blur_radius=0.35):
    """Copy glyph PNGs with lightly stabilized contours for TTF vector tracing.

    The model output stays untouched in ``src_dir``. This creates a separate trace input
    that removes single-pixel jitter and softens stair-stepped edges before ImageTracer
    converts PNGs into SVG paths.
    """
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir, exist_ok=True)

    median_size = max(3, int(median_size))
    if median_size % 2 == 0:
        median_size += 1
    blur_radius = max(0.0, float(blur_radius))

    for fname in os.listdir(src_dir):
        if not fname.lower().endswith('.png'):
            continue
        img = _flatten_to_grayscale(os.path.join(src_dir, fname))
        img = img.filter(ImageFilter.MedianFilter(median_size))
        if blur_radius > 0:
            img = img.filter(ImageFilter.GaussianBlur(blur_radius))
        img.save(os.path.join(dst_dir, fname))
    return dst_dir


def make_weight_variant(src_dir, dst_dir, weight='bold', amount=1.0):
    """Create a synthetic weight of every glyph PNG in src_dir into dst_dir.

    Glyphs are dark ink on white. A 'bold' weight thickens strokes by spreading the dark
    pixels (grayscale erosion via PIL's MinFilter), a 'light' weight thins them (MaxFilter).
    The amount scales with glyph size so it looks right whatever resolution inference emits.
    This runs on the final per-glyph images, so it covers Hangul + traced ENG/special alike.
    """
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir, exist_ok=True)
    amount = max(0.0, float(amount))
    if weight == 'bold':
        flt = ImageFilter.MinFilter(3)
    elif weight == 'light':
        flt = ImageFilter.MaxFilter(3)
    else:
        flt = None

    for fname in os.listdir(src_dir):
        if not fname.lower().endswith('.png'):
            continue
        img = Image.open(os.path.join(src_dir, fname)).convert('L')
        if flt is not None and amount > 0:
            base_passes = max(1, round(min(img.size) * 0.018))
            for _ in range(max(1, round(base_passes * amount))):
                img = img.filter(flt)
        img.save(os.path.join(dst_dir, fname))
    return dst_dir


class FontStyleProcessor:
    def __init__(self, pdf_path, charset_path=DEFAULT_CHARSET, device_name='cpu', use_amp=False):
        self.pdf_path = pdf_path
        self.base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        self.output_dir = os.path.join(PROJECT_ROOT, "style", self.base_name)
        self.cropped_dir = os.path.join(self.output_dir, "cropped")
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
        for dirname in (self.cropped_dir, self.cleaned_dir, self.save_dir):
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

        The model only knows Hangul, so these cells bypass it: each cleaned handwriting
        image is copied straight into the output as inferred_<CODEPOINT>.png, which
        generateTTF.js then vectorizes into the font like any other glyph.
        """
        _, traced_glyphs = split_cells(self._validated_cleaned_paths())
        os.makedirs(self.save_dir, exist_ok=True)
        for char, src in traced_glyphs:
            dst = os.path.join(self.save_dir, f"inferred_{ord(char):04X}.png")
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
