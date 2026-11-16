"""Pillow-drawn graphics for the PoliTO Sync window: smooth rounded shapes, gradients and colour emoji.

Tk cannot anti-alias shapes, so they are drawn here at 3x size and scaled down.
Everything is optional: without Pillow, available() is False and the window draws flat shapes instead.
"""
from __future__ import annotations

import random
from functools import lru_cache

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageTk
except ImportError:  # pragma: no cover - the GUI falls back to flat shapes
    Image = None  # type: ignore[assignment]

SS = 3  # supersampling factor
EMOJI_FONT = r"C:\Windows\Fonts\seguiemj.ttf"


def available() -> bool:
    return Image is not None


def rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _gradient(w: int, h: int, stops: tuple[str, ...]) -> "Image.Image":
    """Left-to-right gradient through the colour stops."""
    cols = [rgb(c) for c in stops]
    row = Image.new("RGB", (max(w, 2), 1))
    px = row.load()
    n = len(cols) - 1
    for x in range(row.width):
        t = x / (row.width - 1) * n
        i = min(int(t), n - 1)
        f = t - i
        a, b = cols[i], cols[i + 1]
        px[x, 0] = tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3))
    return row.resize((w, h), Image.NEAREST)


def _mask(w: int, h: int, r: int) -> "Image.Image":
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


def _rounded_pil(w: int, h: int, r: int, fill: str | None = None, gradient: tuple[str, ...] | None = None,
                 outline: str | None = None, stripe: str | None = None, stripe_w: int = 5) -> "Image.Image":
    W, H, R = w * SS, h * SS, min(r, h // 2, w // 2) * SS
    mask = _mask(W, H, R)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    body = _gradient(W, H, gradient) if gradient else Image.new("RGB", (W, H), rgb(fill or "#000000"))
    out.paste(body, (0, 0), mask)
    if stripe:
        band = Image.new("L", (W, H), 0)
        ImageDraw.Draw(band).rectangle((0, 0, stripe_w * SS, H), fill=255)
        out.paste(Image.new("RGB", (W, H), rgb(stripe)), (0, 0), ImageChops.multiply(mask, band))
    if outline:
        ImageDraw.Draw(out).rounded_rectangle((0, 0, W - 1, H - 1), R, outline=rgb(outline), width=SS)
    return out.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=600)
def rounded(w: int, h: int, r: int, fill: str | None = None, gradient: tuple[str, ...] | None = None,
            outline: str | None = None, stripe: str | None = None, stripe_w: int = 5) -> "ImageTk.PhotoImage | None":
    """A rounded rectangle (solid or gradient fill, optional 1px outline and coloured left stripe).
    For things that change size (cards, sidebar items) use corners() instead: it is far cheaper."""
    if Image is None or w < 4 or h < 4:
        return None
    return ImageTk.PhotoImage(_rounded_pil(w, h, r, fill, gradient, outline, stripe, stripe_w))


@lru_cache(maxsize=120)
def corners(r: int, fill: str, outline: str | None = None, stripe: str | None = None,
            stripe_w: int = 5) -> "dict[str, ImageTk.PhotoImage] | None":
    """The four r x r corners of a solid rounded rectangle. A card of any size is then just these
    corners plus plain rectangles and lines, so resizing it needs no new image."""
    if Image is None:
        return None
    size = 2 * r + 4
    img = _rounded_pil(size, size, r, fill, None, outline, stripe, stripe_w)
    boxes = {"nw": (0, 0, r, r), "ne": (size - r, 0, size, r),
             "sw": (0, size - r, r, size), "se": (size - r, size - r, size, size)}
    return {k: ImageTk.PhotoImage(img.crop(b)) for k, b in boxes.items()}


@lru_cache(maxsize=16)
def _corner_mask(r: int) -> "Image.Image":
    """Anti-aliased top-left quarter of a rounded mask."""
    return _mask(2 * r * SS, 2 * r * SS, r * SS).resize((2 * r, 2 * r), Image.LANCZOS).crop((0, 0, r, r))


def _round_alpha(img: "Image.Image", r: int) -> None:
    """Round the corners of an RGBA image in place (cheap: only the corners are computed)."""
    w, h = img.size
    alpha = Image.new("L", (w, h), 255)
    q = _corner_mask(r)
    alpha.paste(q, (0, 0))
    alpha.paste(q.transpose(Image.FLIP_LEFT_RIGHT), (w - r, 0))
    alpha.paste(q.transpose(Image.FLIP_TOP_BOTTOM), (0, h - r))
    alpha.paste(q.transpose(Image.ROTATE_180), (w - r, h - r))
    img.putalpha(alpha)


@lru_cache(maxsize=40)
def hero(w: int, h: int, r: int, stops: tuple[str, ...], seed: int = 7) -> "ImageTk.PhotoImage | None":
    """A soft 'mesh' gradient banner: a base gradient with blurred colour blobs and a little grain."""
    if Image is None or w < 10 or h < 10:
        return None
    sw, sh = max(w // 4, 8), max(h // 4, 8)
    base = _gradient(sw, sh, stops).convert("RGBA")
    rnd = random.Random(seed)
    blobs = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(blobs)
    n = len(stops)
    for i, c in enumerate(stops * 2):
        # Each blob sits near its colour's place in the gradient, so the last colour stays a splash on the right.
        pos = (i % n) / max(n - 1, 1)
        cx = min(max(pos + rnd.uniform(-0.12, 0.12), 0.0), 1.0) * sw
        cy = rnd.uniform(-sh * 0.3, sh * 1.3)
        rad = rnd.uniform(sh * 0.5, sh * 1.1)
        d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=rgb(c) + (150 if i % 2 else 110,))
    base = Image.alpha_composite(base, blobs.filter(ImageFilter.GaussianBlur(sh * 0.45)))
    big = base.resize((w, h), Image.BICUBIC)  # 1x: the image is soft anyway, only the corners need smoothing
    grain = _grain(w, h)
    big = Image.alpha_composite(big, grain)
    _round_alpha(big, min(r, h // 2))
    return ImageTk.PhotoImage(big)


@lru_cache(maxsize=4)
def _grain(w: int, h: int) -> "Image.Image":
    g = Image.effect_noise((w, h), 12).convert("RGBA")
    g.putalpha(12)
    return g


@lru_cache(maxsize=80)
def emoji(char: str, size: int) -> "ImageTk.PhotoImage | None":
    """A colour emoji as an image (Tk itself only draws emoji in black and white)."""
    if Image is None:
        return None
    try:
        font = ImageFont.truetype(EMOJI_FONT, size * 4)
    except OSError:
        return None
    canvas = Image.new("RGBA", (size * 6, size * 6), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((size, size), char, font=font, embedded_color=True)
    box = canvas.getbbox()
    if not box:
        return None
    img = canvas.crop(box)
    scale = size / max(img.size)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def clear_cache() -> None:
    """Drop cached images (after a theme change, or when a new Tk root is created)."""
    for fn in (rounded, corners, hero, emoji):
        fn.cache_clear()
