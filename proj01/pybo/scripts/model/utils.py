# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import absolute_import

import os
import glob

import imageio
import numpy as np
# import scipy.misc as misc
from io import BytesIO
from PIL import Image

def pad_seq(seq, batch_size):
    # pad the sequence to be the multiples of batch_size
    seq_len = len(seq)
    if seq_len % batch_size == 0:
        return seq
    padded = batch_size - (seq_len % batch_size)
    seq.extend(seq[:padded])
    return seq


def bytes_to_file(bytes_img):
    return BytesIO(bytes_img)


def normalize_image(img):
    """
    Make image zero centered and in between (-1, 1)
    """
    normalized = (img / 127.5) - 1.
    return normalized


def read_split_image(img):
    # mat = misc.imread(img).astype(np.float)
    mat = imageio.imread(img).astype(np.float)
    side = int(mat.shape[1] / 2)
    assert side * 2 == mat.shape[1]
    img_A = mat[:, :side]  # target
    img_B = mat[:, side:]  # source

    return img_A, img_B


def shift_and_resize_image(img, shift_x, shift_y, nw, nh):
#    w, h, _ = img.shape
    # w, h = img.shape
    # enlarged = misc.imresize(img, [nw, nh])
    # return enlarged[shift_x:shift_x + w, shift_y:shift_y + h]
    pil_img = Image.fromarray(img.astype(np.uint8))
    resized = pil_img.resize((nh, nw), Image.BILINEAR)
    resized_np = np.array(resized)
    return resized_np[shift_x:shift_x + img.shape[0], shift_y:shift_y + img.shape[1]]



def scale_back(images):
    return (images + 1.) / 2.


def merge(images, size):
    h, w = images.shape[1], images.shape[2]
    img = np.zeros((h * size[0], w * size[1], 3))
    for idx, image in enumerate(images):
        i = idx % size[1]
        j = idx // size[1]
        img[j * h:j * h + h, i * w:i * w + w, :] = image

    return img


def save_concat_images(imgs, img_path):
    concated = np.concatenate(imgs, axis=1) # concat simply link data x axis axis
    # misc.imsave(img_path, concated)
    # imageio.imsave(img_path, concated)

    # ✅ float64 → uint8 로 바꿔주기 (0~255 범위 스케일링도 필요할 수 있음)
    if concated.dtype != np.uint8:
        concated = np.clip(concated, 0.0, 1.0)  # 먼저 범위 자르기
        concated = (concated * 255).astype(np.uint8)

    imageio.imsave(img_path, concated)    


def compile_frames_to_gif(frame_dir, gif_file):
    # frames = sorted(glob.glob(os.path.join(frame_dir, "*.png")))
    # print(frames)
    # images = [misc.imresize(imageio.imread(f), interp='nearest', size=0.33) for f in frames]
    # imageio.mimsave(gif_file, images, duration=0.1)
    # return gif_file
    frames = sorted(glob.glob(os.path.join(frame_dir, "*.png")))
    print(frames)
    images = []

    for f in frames:
        img = Image.open(f)
        new_size = (int(img.width * 0.33), int(img.height * 0.33))
        resized = img.resize(new_size, Image.NEAREST)
        images.append(np.array(resized))

    imageio.mimsave(gif_file, images, duration=0.1)
    return gif_file