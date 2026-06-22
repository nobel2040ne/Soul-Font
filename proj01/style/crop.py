"""Crop a filled handwriting template into one image per cell.

Robust to:
  * different page sizes / scan resolutions — the grid is located from the printed
    table border instead of assuming the cells fill the whole page, and cells are
    derived from the detected region.
  * stray notes written outside the template — anything outside the detected table
    border is ignored (notes don't form full-length grid lines).

Falls back to a simple equal division of the page if no grid border is detected,
so it degrades gracefully instead of crashing.
"""
import os
import argparse
import numpy as np
from PIL import Image, ImageChops, ImageOps

parser = argparse.ArgumentParser()
parser.add_argument("--src_dir", required=True)
parser.add_argument("--dst_dir", required=True)
parser.add_argument("--rows", type=int, default=4)
parser.add_argument("--cols", type=int, default=7)
args = parser.parse_args()

ROWS, COLS = args.rows, args.cols
START_UNICODE = 0xAC00  # filenames are positional (sort order), not literal codepoints
CELL_PAD_FRAC = 0.06    # trim this fraction off each cell edge to drop grid lines
TOP_EXTRA_FRAC = 0.05   # extra trim off each cell top (drops the printed guide glyph)
OUT_SIZE = 512

os.makedirs(args.dst_dir, exist_ok=True)


def detect_grid_bbox(gray):
    """Find the table border via projection profiles. Returns (left, top, right, bottom).

    Full-length horizontal/vertical lines (the table border) show up as columns/rows
    that are mostly ink. Stray notes outside the table don't span the full width/height,
    so they're excluded. Returns None if no grid is found.
    """
    arr = np.asarray(gray)
    ink = arr < 128  # dark pixels
    h, w = ink.shape

    col_ink = ink.sum(axis=0)
    row_ink = ink.sum(axis=1)

    cols_line = np.where(col_ink > 0.4 * h)[0]   # near-full-height vertical lines
    rows_line = np.where(row_ink > 0.4 * w)[0]   # near-full-width horizontal lines

    if cols_line.size >= 2 and rows_line.size >= 2:
        left, right = int(cols_line[0]), int(cols_line[-1])
        top, bottom = int(rows_line[0]), int(rows_line[-1])
        # sanity: the region must be a meaningful fraction of the page
        if (right - left) > 0.3 * w and (bottom - top) > 0.3 * h:
            return (left, top, right, bottom)
    return None


def process_cell(cell):
    """Trim whitespace, square-pad and resize a single cell image."""
    bg = Image.new("L", cell.size, 255)
    diff = ImageChops.difference(cell, bg)
    bbox = diff.getbbox()
    if bbox:
        cell = cell.crop(bbox)

    cell = ImageOps.expand(cell, border=30, fill=255)
    side = max(cell.size)
    square = Image.new("L", (side, side), 255)
    square.paste(cell, ((side - cell.width) // 2, (side - cell.height) // 2))
    return square.resize((OUT_SIZE, OUT_SIZE), Image.BICUBIC)


count = 0
for fname in sorted(os.listdir(args.src_dir)):
    if not fname.lower().endswith((".png", ".jpg", ".jpeg")):
        continue

    img = Image.open(os.path.join(args.src_dir, fname)).convert("L")

    bbox = detect_grid_bbox(img)
    if bbox is None:
        # Fallback: use the whole page (old behaviour).
        left, top, right, bottom = 0, 0, img.width, img.height
        print(f"[crop] {fname}: no grid border detected, using full page")
    else:
        left, top, right, bottom = bbox
        print(f"[crop] {fname}: grid at {bbox}")

    grid_w = right - left
    grid_h = bottom - top
    cell_w = grid_w / COLS
    cell_h = grid_h / ROWS
    pad_x = cell_w * CELL_PAD_FRAC
    pad_y = cell_h * CELL_PAD_FRAC

    top_skip = cell_h * TOP_EXTRA_FRAC
    for r in range(ROWS):
        for c in range(COLS):
            l = int(left + c * cell_w + pad_x)
            u = int(top + r * cell_h + pad_y + top_skip)
            rt = int(left + (c + 1) * cell_w - pad_x)
            lo = int(top + (r + 1) * cell_h - pad_y)
            if rt <= l or lo <= u:
                continue
            cell = process_cell(img.crop((l, u, rt, lo)))
            out_name = f"uni{START_UNICODE + count:04X}.png"
            cell.save(os.path.join(args.dst_dir, out_name))
            count += 1

print(f"complete {count} cells are saved: {args.dst_dir}")
