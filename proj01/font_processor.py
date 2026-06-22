import os, shutil, yaml, subprocess
import numpy as np
from PIL import Image, ImageChops
from pdf2image import convert_from_path  # type: ignore

from inference import main as inference_main
from char_layout import KOR_STYLE_CHARS, split_cells

# --- Korean style reference characters, in the same order as the template cells ---
STYLE_CHARS = KOR_STYLE_CHARS

# --- Model architecture constants (must match the checkpoint) ---
MODEL_C = 32
MODEL_N_COMPS = 68
MODEL_N_COMP_TYPES = 3
LANGUAGE = 'kor'

# Default target set: KS X 1001 common-use 2,350 Hangul (much faster than the full
# 11,170 and covers everyday Korean). Swap to korean11172.txt for full coverage.
DEFAULT_CHARSET = 'data/charset/korean2350.txt'


class FontStyleProcessor:
    def __init__(self, pdf_path, charset_path=DEFAULT_CHARSET):
        self.pdf_path = pdf_path
        self.base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        self.output_dir = f"style/{self.base_name}"
        self.cropped_dir = os.path.join(self.output_dir, "cropped")
        self.cleaned_dir = os.path.join(self.output_dir, "cleaned")
        self.yaml_path = f"configs/{self.base_name}.yaml"
        self.checkpoint = "checkpoints/korean-handwriting.pth"
        self.save_dir = f"static/outputs/{self.base_name}"
        self.charset_path = charset_path
        os.makedirs(self.output_dir, exist_ok=True)

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
            "python", "style/crop.py",
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

    def generate_yaml(self, target_chars):
        # Only the first 28 cells are Korean style references for the model; any extra
        # cells are English/special glyphs handled by copy_traced_glyphs().
        style_imgs, _ = split_cells(self._cleaned_paths())
        cfg = {
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
        inference_main(self.yaml_path, self.checkpoint, self.save_dir)
        print("[INFO] All Korean characters generated successfully.")

    def copy_traced_glyphs(self):
        """Embed English/special glyphs by tracing the user's own handwriting.

        The model only knows Hangul, so these cells bypass it: each cleaned handwriting
        image is copied straight into the output as inferred_<CODEPOINT>.png, which
        generateTTF.js then vectorizes into the font like any other glyph.
        """
        _, traced_glyphs = split_cells(self._cleaned_paths())
        os.makedirs(self.save_dir, exist_ok=True)
        for char, src in traced_glyphs:
            dst = os.path.join(self.save_dir, f"inferred_{ord(char):04X}.png")
            shutil.copyfile(src, dst)
        if traced_glyphs:
            print(f"[INFO] Embedded {len(traced_glyphs)} traced ENG/special glyphs")

    def run_all(self):
        self.convert_pdf_to_images()
        self.trim_and_save_images()
        self.clean_images()
        self.run_inference()
        self.copy_traced_glyphs()
