# DG2 images.
#   'PP': u16 width, u16 height, 256 x RGB555 palette (BE, bit 15 = opaque), then 8bpp pixels.
#   'pp': u16 width, u16 height,  16 x RGB555 palette, then 4bpp pixels (high nibble = left pixel).
#   python dg2.py to-png FILE.DG2 out.png
import struct
import sys
from PIL import Image


def load(path):
    """Return (width, height, palette, pixel indices, raw bytes); pixels are one index per pixel."""
    d = open(path, 'rb').read()
    w, h = struct.unpack_from('>HH', d, 2)
    if d[:2] == b'PP':
        pal = [struct.unpack_from('>H', d, 6 + i * 2)[0] for i in range(256)]
        return w, h, pal, d[518:518 + w * h], d
    if d[:2] == b'pp':
        pal = [struct.unpack_from('>H', d, 6 + i * 2)[0] for i in range(16)]
        px = bytearray()
        for b in d[38:38 + w * h // 2]:
            px += bytes((b >> 4, b & 15))
        return w, h, pal, bytes(px), d
    raise ValueError(f'{path}: not a DG2 image')


def pixel_offset(raw):
    return 518 if raw[:2] == b'PP' else 38


def pack(raw, px):
    """Raw file bytes with the pixel data replaced."""
    out = bytearray(raw)
    if raw[:2] == b'PP':
        out[518:518 + len(px)] = px
    else:
        out[38:38 + len(px) // 2] = bytes((px[i] << 4) | px[i + 1] for i in range(0, len(px), 2))
    return bytes(out)


def rgb(v):
    return ((v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3)


def to_png(path, out, scale=1):
    w, h, pal, px, _ = load(path)
    im = Image.new('RGB', (w, h))
    im.putdata([rgb(pal[p]) for p in px])
    if scale > 1:
        im = im.resize((w * scale, h * scale), Image.NEAREST)
    im.save(out)


if __name__ == '__main__':
    if sys.argv[1] == 'to-png':
        to_png(sys.argv[2], sys.argv[3])
