import os

# Let any op MPS (Apple Silicon) does not implement fall back to CPU instead of
# crashing. Must be set before torch is imported.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import re
import contextlib
import threading

import torch, yaml
from torchvision import transforms
from PIL import Image
from torch.utils.data import DataLoader

from datasets import get_ma_val_dataset
from datasets.nonpaired_dataset import EncodeDataset, DecodeDataset
from datasets.style_image_dataset import StyleImageDataset


def get_device(requested=None):
    """Pick inference device.

    The HAI/DMFont web path runs on CPU. Keep CPU as the default here too because
    MPS/CUDA autocast can write valid-looking files with corrupted glyph content.
    Set SOUL_FONT_DEVICE=cuda or SOUL_FONT_DEVICE=mps only for explicit testing.
    """
    requested = (requested or os.environ.get("SOUL_FONT_DEVICE", "cpu")).lower()
    if requested == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if (
        requested == "mps" and
        getattr(torch.backends, "mps", None) is not None and
        torch.backends.mps.is_available()
    ):
        return torch.device("mps")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# Model cache: building MACore + loading the 192MB checkpoint is expensive, so
# keep the eval-ready generator in memory and reuse it across requests.
# ---------------------------------------------------------------------------
_MODEL_CACHE = {}

# The cached model carries dynamic memory that gets reset/rewritten each run, so
# concurrent generations must not share it simultaneously — serialize them.
_INFER_LOCK = threading.Lock()


def load_model(checkpoint, cfg, device):
    key = (
        os.path.abspath(checkpoint),
        cfg.get('C', 32),
        cfg.get('n_comps', 68),
        cfg.get('n_comp_types', 3),
        cfg.get('language', 'kor'),
        str(device),
    )
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    from models.ma_core import MACore

    gen = MACore(
        C_in=1,
        C=cfg.get('C', 32),
        C_out=1,
        comp_enc={
            'norm': 'none',
            'activ': 'relu',
            'pad_type': 'zero',
            'sa': {'C_qk_ratio': 0.5, 'n_heads': 2, 'area': False, 'ffn_mult': 2},
        },
        dec={'norm': 'IN', 'activ': 'relu', 'pad_type': 'zero'},
        n_comps=cfg.get('n_comps', 68),
        n_comp_types=cfg.get('n_comp_types', 3),
        language=cfg.get('language', 'kor'),
    ).to(device)

    ckpt = torch.load(checkpoint, map_location=device)
    gen.load_state_dict(ckpt["generator_ema"])
    gen.eval()

    _MODEL_CACHE[key] = gen
    return gen


# ---------------------------------------------------------------------------
# Training/evaluation helpers (used by evaluator.py / train.py, not the web app).
# Kept GPU-bound to match the upstream DMFont eval harness.
# ---------------------------------------------------------------------------
def infer(gen, loader):
    outs = []
    for style_ids, style_comp_ids, style_imgs, trg_ids, trg_comp_ids, content_imgs in loader:
        style_ids = style_ids.cuda()
        style_comp_ids = style_comp_ids.cuda()
        style_imgs = style_imgs.cuda()
        trg_ids = trg_ids.cuda()
        trg_comp_ids = trg_comp_ids.cuda()

        gen.encode_write(style_ids, style_comp_ids, style_imgs)
        out = gen.read_decode(trg_ids, trg_comp_ids)
        outs.append(out.detach().cpu())

    return torch.cat(outs)  # [B, 1, 128, 128]; B = #fonts * #chars


def get_val_loader(data, fonts, chars, style_avails, transform, content_font, language,
                   B=32, n_max_match=3, n_workers=2):
    val_dset, collate_fn = get_ma_val_dataset(
        data, fonts, chars, style_avails, n_max_match, transform=transform,
        content_font=content_font, language=language,
    )
    return DataLoader(val_dset, batch_size=B, shuffle=False,
                      num_workers=n_workers, collate_fn=collate_fn)


def get_val_encode_loader(data, font_name, encode_chars, language, transform, B=32,
                          num_workers=2, style_id=0):
    encode_dset = EncodeDataset(
        font_name, encode_chars, data, language=language, transform=transform, style_id=style_id,
    )
    return DataLoader(encode_dset, batch_size=B, shuffle=False, num_workers=num_workers)


def _autocast(device, use_amp=True):
    """fp16 autocast on GPU/MPS (big speedup on Apple Silicon); no-op on CPU."""
    if use_amp and device.type in ("cuda", "mps"):
        return torch.autocast(device_type=device.type, dtype=torch.float16)
    return contextlib.nullcontext()


def infer_2stage(gen, encode_loader, decode_loader, device=None, reset_memory=True, use_amp=True):
    """2-stage infer; encode style images into memory first, decode targets second."""
    if device is None:
        device = get_device()
    # stage 1. encode
    if reset_memory:
        gen.reset_dynamic_memory()

    with _autocast(device, use_amp):
        for style_ids, style_comp_ids, style_imgs in encode_loader:
            style_ids = style_ids.to(device)
            style_comp_ids = style_comp_ids.to(device)
            style_imgs = style_imgs.to(device)
            gen.encode_write(style_ids, style_comp_ids, style_imgs, reset_dynamic_memory=False)

        # stage 2. decode
        outs = []
        for trg_ids, trg_comp_ids in decode_loader:
            trg_ids = trg_ids.to(device)
            trg_comp_ids = trg_comp_ids.to(device)
            out = gen.read_decode(trg_ids, trg_comp_ids)
            outs.append(out.detach().float().cpu())

    return torch.cat(outs)


def get_val_decode_loader(chars, language, B=128, num_workers=2, style_id=0):
    decode_dset = DecodeDataset(chars, language=language, style_id=style_id)
    return DataLoader(decode_dset, batch_size=B, shuffle=False, num_workers=num_workers)


def get_styleimg_encode_loader(style_imgs, style_chars, language, transform,
                               style_id=0, B=64, num_workers=2):
    dset = StyleImageDataset(style_imgs, style_chars, language=language,
                             transform=transform, style_id=style_id)
    return DataLoader(dset, batch_size=B, shuffle=False, num_workers=num_workers)


def get_transform():
    return transforms.Compose([
        transforms.Grayscale(num_output_channels=1),
        transforms.Resize((128, 128)),
        transforms.ToTensor(),
        transforms.Normalize([0.5], [0.5]),
    ])


def save_single_char_tensor_as_png(tensor, path):
    """tensor: [1, 1, H, W] in [-1, 1] -> grayscale PNG."""
    img = tensor.squeeze(0).squeeze(0)          # [H, W]
    img = img.mul(0.5).add(0.5).clamp(0, 1)     # [-1,1] -> [0,1]
    img = img.mul(255).byte().cpu().numpy()
    Image.fromarray(img, mode='L').save(path)


def main(config, checkpoint, save_dir, device_name=None, use_amp=None):
    os.makedirs(save_dir, exist_ok=True)
    device = get_device(device_name)
    # Use all CPU cores for the ops that still fall back to CPU.
    try:
        torch.set_num_threads(os.cpu_count() or 1)
    except Exception:
        pass
    print(f"[inference] device={device}, threads={torch.get_num_threads()}")

    with open(config, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    gen = load_model(checkpoint, cfg, device)

    encode_loader = get_styleimg_encode_loader(
        cfg['style_imgs'], cfg['style_chars'], cfg['language'],
        transform=get_transform(), style_id=0, num_workers=0,
    )

    # The model only knows Hangul syllables; non-Korean targets (ENG/special) are
    # produced elsewhere by tracing the user's handwriting. Filter + dedupe here.
    valid_target_chars = list(dict.fromkeys(
        c for c in cfg['target_chars'] if re.match(r'[가-힣]', c)
    ))
    decode_loader = get_val_decode_loader(
        valid_target_chars, cfg['language'], style_id=0, num_workers=0,
    )

    if use_amp is None:
        use_amp = os.environ.get("SOUL_FONT_USE_AMP") == "1"
    with _INFER_LOCK, torch.inference_mode():
        try:
            outs = infer_2stage(gen, encode_loader, decode_loader, device, use_amp=use_amp)
        except RuntimeError as e:
            # fp16 can be flaky on MPS for some ops — retry in full precision.
            print(f"[inference] fp16 failed ({e}); retrying in fp32")
            outs = infer_2stage(gen, encode_loader, decode_loader, device, use_amp=False)

    for i, ch in enumerate(valid_target_chars):
        codepoint = ord(ch)
        path = os.path.join(save_dir, f"inferred_{codepoint:04X}.png")
        save_single_char_tensor_as_png(outs[i:i + 1], path)
    print(f"[inference] saved {len(valid_target_chars)} glyphs to {save_dir}")


if __name__ == '__main__':
    import fire
    fire.Fire(main)
