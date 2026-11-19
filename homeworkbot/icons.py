"""图标字体: 用 Windows 自带的 Segoe Fluent Icons / Segoe MDL2 Assets 渲染图标为图片 (不用 emoji).
找不到字体时返回 None (界面只显示文字)."""
import os, sys

GLYPHS = {
    "home": "\uE80F", "history": "\uE81C", "plug": "\uE703", "send": "\uE724", "robot": "\uE99A",
    "log": "\uE8A5", "info": "\uE946", "play": "\uE768", "stop": "\uE71A", "refresh": "\uE72C",
    "search": "\uE721", "save": "\uE74E", "download": "\uE896", "folder": "\uE838", "photo": "\uEB9F",
    "clock": "\uE823", "check": "\uE73E", "warning": "\uE7BA", "link": "\uE71B", "settings": "\uE713",
    "edit": "\uE70F", "cancel": "\uE711", "bell": "\uE7ED", "globe": "\uE774", "copy": "\uE8C8",
    "chat": "\uE8BD", "people": "\uE716", "calendar": "\uE787", "book": "\uE82D", "eye": "\uE7B3",
    "test": "\uE9D5", "dot": "\uEA3B", "help": "\uE897", "list": "\uEA37", "chevl": "\uE76B", "chevr": "\uE76C", "add": "\uE710",
}
FONT_FILES = ["SegoeIcons.ttf", "segmdl2.ttf"]

def font_path():
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name in FONT_FILES:
        for base in (os.path.join(windir, "Fonts"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")):
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
    return None

_cache = {}

def glyph_image(name, size=18, color=(60, 60, 60), scale=2):
    """渲染单个图标为 RGBA PIL 图片; 失败返回 None."""
    key = (name, size, color, scale)
    if key in _cache:
        return _cache[key]
    img = None
    fp = font_path()
    if fp and name in GLYPHS:
        from PIL import Image, ImageDraw, ImageFont
        px = size * scale
        font = ImageFont.truetype(fp, int(px * 0.9))
        img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        l, t, r, b = d.textbbox((0, 0), GLYPHS[name], font=font)
        d.text(((px - (r - l)) / 2 - l, (px - (b - t)) / 2 - t), GLYPHS[name], font=font, fill=color)
    _cache[key] = img
    return img

def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def icon(name, size=18, light="#374151", dark="#E5E7EB"):
    """customtkinter 图标 (随浅色/深色主题变色)."""
    import customtkinter as ctk
    li = glyph_image(name, size, hex2rgb(light))
    di = glyph_image(name, size, hex2rgb(dark))
    if li is None:
        return None
    return ctk.CTkImage(light_image=li, dark_image=di, size=(size, size))
