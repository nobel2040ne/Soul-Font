import torch, yaml, os, re
from torchvision import transforms
from torch.utils.data import DataLoader
from PIL import Image
import numpy as np
from datasets import get_ma_val_dataset
from datasets.nonpaired_dataset import EncodeDataset, DecodeDataset
from datasets.style_image_dataset import StyleImageDataset

def infer(gen, loader):
    outs = []
    for style_ids, style_comp_ids, style_imgs, trg_ids, trg_comp_ids, content_imgs \
            in loader:
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
        content_font=content_font, language=language
    )
    loader = DataLoader(val_dset, batch_size=B, shuffle=False,
                        num_workers=n_workers, collate_fn=collate_fn)

    return loader


def infer_2stage(gen, encode_loader, decode_loader, reset_memory=True):
    """ 2-stage infer; encode first, decode second """
    # stage 1. encode
    if reset_memory:
        gen.reset_dynamic_memory()

    for style_ids, style_comp_ids, style_imgs in encode_loader:
        style_ids = style_ids.to("cpu")
        style_comp_ids = style_comp_ids.to("cpu")
        style_imgs = style_imgs.to("cpu")

        gen.encode_write(style_ids, style_comp_ids, style_imgs, reset_dynamic_memory=False)

    # stage 2. decode
    outs = []
    for trg_ids, trg_comp_ids in decode_loader:
        trg_ids = trg_ids.to("cpu")
        trg_comp_ids = trg_comp_ids.to("cpu")

        out = gen.read_decode(trg_ids, trg_comp_ids)

        outs.append(out.detach().cpu())

    return torch.cat(outs)


def get_val_encode_loader(data, font_name, encode_chars, language, transform, B=32, num_workers=2,
                          style_id=0):
    encode_dset = EncodeDataset(
        font_name, encode_chars, data, language=language, transform=transform, style_id=style_id
    )
    loader = DataLoader(encode_dset, batch_size=B, shuffle=False, num_workers=num_workers)

    return loader


def get_val_decode_loader(chars, language, B=32, num_workers=2, style_id=0):
    decode_dset = DecodeDataset(chars, language=language, style_id=style_id)
    loader = DataLoader(decode_dset, batch_size=B, shuffle=False, num_workers=num_workers)

    return loader


def get_styleimg_encode_loader(style_imgs, style_chars, language, transform, style_id=0, B=32, num_workers=2):
    dset = StyleImageDataset(style_imgs, style_chars, language=language, transform=transform, style_id=style_id)
    return DataLoader(dset, batch_size=B, shuffle=False, num_workers=num_workers)


def get_transform():
    return transforms.Compose([
        transforms.Grayscale(num_output_channels=1),
        transforms.Resize((128, 128)),
        transforms.ToTensor(),
        transforms.Normalize([0.5], [0.5])
    ])


def save_single_char_tensor_as_png(tensor, path):
    """
    tensor: [1, 1, H, W]
    path: 저장할 PNG 경로
    """
    img = tensor.squeeze(0).squeeze(0)  # [1,1,H,W] → [H,W]
    img = img.mul(0.5).add(0.5).clamp(0, 1)  # [-1,1] → [0,1]
    img = img.mul(255).byte().cpu().numpy()
    Image.fromarray(img, mode='L').save(path)


def main(config, checkpoint, save_dir):
    from models.ma_core import MACore
    from inference import infer_2stage, get_val_decode_loader

    os.makedirs(save_dir, exist_ok=True)
    device = torch.device("cpu")

    with open(config, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    # Generator 정의
    gen = MACore(
        C_in=1,
        C=cfg.get('C', 32),
        C_out=1,
        comp_enc={
            'norm': 'none',
            'activ': 'relu',
            'pad_type': 'zero',
            'sa': {
                'C_qk_ratio': 0.5,
                'n_heads': 2,
                'area': False,
                'ffn_mult': 2
            }
        },
        dec={
            'norm': 'IN',
            'activ': 'relu',
            'pad_type': 'zero'
        },
        n_comps=cfg.get('n_comps', 68),
        n_comp_types=cfg.get('n_comp_types', 3),
        language=cfg.get('language', 'kor')
    ).to(device)

    # Checkpoint 로드
    ckpt = torch.load(checkpoint, map_location=device)
    gen.load_state_dict(ckpt["generator_ema"])
    gen.eval()

    # Encode/Decode 로더 준비
    encode_loader = get_styleimg_encode_loader(
        cfg['style_imgs'], cfg['style_chars'], cfg['language'],
        transform=get_transform(), style_id=0
    )

    valid_target_chars = [c for c in cfg['target_chars'] if re.match(r'[가-힣]', c)]
    decode_loader = get_val_decode_loader(valid_target_chars, cfg['language'], style_id=0)

    # 추론
    with torch.no_grad():
        outs = infer_2stage(gen, encode_loader, decode_loader)

    # 저장
    os.makedirs(save_dir, exist_ok=True)
    for i, ch in enumerate(valid_target_chars):
        char_tensor = outs[i:i+1]  # [1,1,H,W]
        codepoint = ord(ch)
        filename = f"inferred_{codepoint:04X}.png"
        path = os.path.join(save_dir, filename)
        save_single_char_tensor_as_png(char_tensor, path)

if __name__ == '__main__':
    import fire
    fire.Fire(main)