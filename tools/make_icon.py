"""从 assets/icon_source.png (或旧渐变书本) 生成 icon.png + icon.ico (16/32/48/256...)."""
import os
from PIL import Image, ImageDraw

def from_source(src, out_dir):
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    side = min(w, h)
    sq = im.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [sq.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    os.makedirs(out_dir, exist_ok=True)
    imgs[-1].save(os.path.join(out_dir, "icon.png"))
    imgs[-1].save(os.path.join(out_dir, "icon.ico"), format="ICO",
                  sizes=[(s, s) for s in sizes], append_images=imgs[:-1])

def make_fallback(out_dir):
    S = 512
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(S):
        c = (int(59 + (99 - 59) * i / S), int(130 + (102 - 130) * i / S), int(246 + (241 - 246) * i / S), 255)
        d.line([(0, i), (S, i)], fill=c)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], 110, fill=255)
    img.putalpha(mask)
    d = ImageDraw.Draw(img)
    d.polygon([(96, 150), (250, 120), (250, 400), (96, 420)], fill=(255, 255, 255, 255))
    d.polygon([(262, 120), (416, 150), (416, 420), (262, 400)], fill=(232, 240, 255, 255))
    for k in range(4):
        y = 185 + k * 48
        d.line([(126, y), (225, y - 12)], fill=(147, 197, 253, 255), width=12)
    d.ellipse([300, 300, 470, 470], fill=(34, 197, 94, 255), outline=(255, 255, 255, 255), width=10)
    d.line([(340, 385), (375, 420), (435, 350)], fill=(255, 255, 255, 255), width=22)
    os.makedirs(out_dir, exist_ok=True)
    img.save(os.path.join(out_dir, "icon.png"))
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(os.path.join(out_dir, "icon.ico"), sizes=sizes)

if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "assets")
    src = os.path.join(out, "icon_source.png")
    if os.path.exists(src):
        from_source(src, out)
    else:
        make_fallback(out)
    print("wrote", out)
