import torch
from torch.utils.data import Dataset
from PIL import Image
import numpy as np
from . import kor_decompose

class StyleImageDataset(Dataset):
    def __init__(self, style_imgs, style_chars, language='kor', transform=None, style_id=0):
        assert len(style_imgs) == len(style_chars), "style_imgs와 style_chars 길이는 같아야 합니다."
        self.style_imgs = style_imgs
        self.style_chars = style_chars
        self.language = language
        self.transform = transform
        self.style_id = style_id

        if language == 'kor':
            self.decompose = kor_decompose.decompose
        else:
            raise NotImplementedError(f"Language {language}는 지원되지 않습니다.")

    def __len__(self):
        return len(self.style_imgs)

    def __getitem__(self, idx):
        path = self.style_imgs[idx]
        char = self.style_chars[idx]
        comp_ids = self.decompose(char)

        img = Image.open(path).convert('L')  # 흑백
        if self.transform:
            img = self.transform(img)

        return (
            self.style_id,
            torch.as_tensor(comp_ids),
            img
        )
