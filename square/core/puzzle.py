"""多张二维码合成为一张拼图（纯逻辑，不依赖 Tk）。"""
import os
import tempfile

from PIL import Image


def make_puzzle(qr_images, cols=None, scale=15):
    """list[segno.QRCode] → PIL.Image 拼图"""
    pil_imgs = []
    tmpdir = tempfile.mkdtemp()
    for i, qr in enumerate(qr_images):
        fpath = os.path.join(tmpdir, f"_puzzle_{i}.png")
        qr.save(fpath, scale=scale)
        pil_imgs.append(Image.open(fpath).convert("RGB"))

    if cols is None:
        cols = min(4, len(pil_imgs))
    rows = (len(pil_imgs) + cols - 1) // cols
    w = max(i.width for i in pil_imgs)
    h = max(i.height for i in pil_imgs)
    canvas = Image.new("RGB", (cols * w, rows * h), "white")
    for idx, img in enumerate(pil_imgs):
        canvas.paste(img, ((idx % cols) * w, (idx // cols) * h))
    return canvas
