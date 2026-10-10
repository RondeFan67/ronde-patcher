# SEGA SATURN SCR screens (.2D files: KEI_*, TITLE, HARDEASY, NEWGAME, shop backgrounds, ...).
#   Header: 'SEGA SATURN SCR', then at 0x10 five (u32 offset, u32 size) entries: map info, pattern names,
#   character data, palette, attributes. Every section starts with a 16-byte header of its own.
#   Pattern names: 32x32 u16 cells (1-word). Full screens use 16x16 cells (2x2 chars, flag byte 0x11):
#   cell n -> 256 bytes at chars + (n >> 1) * 256, as four 8x8 8bpp tiles TL, TR, BL, BR.
#   Palette: 256 RGB555 entries. Visible area: 20 x 15 cells = 320x240.
#   (FONT8.2D uses 8x8 cells, flag 0x10; see ui_tool.py.)
#
#   python scr2d.py to-png FILE.2D out.png
import struct
import sys

from PIL import Image

COLS, ROWS = 20, 15


def rgb(v):
    return ((v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3)


class Scr:
    def __init__(self, path):
        self.raw = bytearray(open(path, 'rb').read())
        if self.raw[:15] != b'SEGA SATURN SCR':
            raise ValueError(f'{path}: not an SCR file')
        sec = [struct.unpack_from('>II', self.raw, 0x10 + i * 16) for i in range(5)]
        if self.raw[sec[1][0] + 1] != 0x11:
            raise ValueError(f'{path}: only 16x16-cell screens are supported')
        self.pn, self.ch, self.pal_off = sec[1][0] + 16, sec[2][0] + 16, sec[3][0] + 16
        self.pal = [struct.unpack_from('>H', self.raw, self.pal_off + i * 2)[0] for i in range(256)]
        self.cells = [[struct.unpack_from('>H', self.raw, self.pn + (r * 32 + c) * 2)[0] & 0x3FF
                       for c in range(COLS)] for r in range(ROWS)]

    def _addr(self, x, y):
        n = self.cells[y // 16][x // 16]
        t = ((y % 16) // 8) * 2 + (x % 16) // 8
        return self.ch + (n >> 1) * 256 + t * 64 + (y % 8) * 8 + x % 8

    def pixels(self):
        """320x240 palette indices, row-major."""
        return bytearray(self.raw[self._addr(x, y)] for y in range(ROWS * 16) for x in range(COLS * 16))

    def put(self, px, changed):
        """Write back the pixels whose positions are in `changed`; refuses cells used more than once."""
        uses = {}
        for row in self.cells:
            for n in row:
                uses[n] = uses.get(n, 0) + 1
        for x, y in changed:
            n = self.cells[y // 16][x // 16]
            if uses[n] > 1:
                raise ValueError(f'pixel {x},{y} is in shared cell {n:#x}')
            self.raw[self._addr(x, y)] = px[y * COLS * 16 + x]

    def image(self, px=None):
        px = self.pixels() if px is None else px
        im = Image.new('RGB', (COLS * 16, ROWS * 16))
        im.putdata([rgb(self.pal[p]) for p in px])
        return im


if __name__ == '__main__':
    if sys.argv[1] == 'to-png':
        Scr(sys.argv[2]).image().save(sys.argv[3])
