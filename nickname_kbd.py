# English nickname keyboard (naming a demon that becomes a Unit, in the demon menu and at the Remix station).
#
# The keyboard is a 10 x 24 grid. Two things must agree:
# - the grid table: 240 small-font bytes, row by row (0xEB = empty key), at WORLD.BIN 0x2A980 and REMIX.BIN
#   0x1F870 (identical copies);
# - the picture NIC_MJ.2D (SCR screen, taller than the screen; it scrolls). Keys sit on a 14 px grid:
#   column c at x = 154 + 14c, row r at y = 29 + 14r, 14 x 14 each.
# Nicknames only ever show in the small font (the big-font name variable FF 4E reads the fixed name tables), so
# every lowercase letter can be offered, including the ones drawn into kana slots (ui_tool.EXTRA).
# Kana keys whose slot now holds such a letter are left empty.
#
# New layout: English first (the cursor starts top-left), then the original symbols, katakana where they were,
# and the first six hiragana rows. The picture is rebuilt by erasing every key and compositing each character's
# original "ink" (its brightness over the cleaned background) at its new key; lowercase letters and the
# apostrophe have no original, so they are rendered with Tahoma in the same white.
#
#   python nickname_kbd.py      write build/Disc1/{WORLD.BIN,REMIX.BIN,NIC_MJ.2D} (+ build/preview/NIC_MJ.png)
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scr2d  # noqa: E402
import ui_tool  # noqa: E402
import ui_text as ut  # noqa: E402

TABLES = [('WORLD.BIN', 0x2A980), ('REMIX.BIN', 0x1F870)]
COLS_K, ROWS_K = 10, 24
X0, Y0, PITCH = 154, 29, 14
FONT = r'C:\Windows\Fonts\tahoma.ttf'

# the original layout (kana rows as on the disc); ' ' = empty key ('_' is the underscore key)
OLD = ['あいうえおかきくけこ', 'さしすせそたちつてと', 'なにぬねのはひふへほ', 'まみむめもや ゆ よ', 'らりるれろわ を ん',
       'がぎぐげござじずぜぞ', 'だぢづでどばびぶべぼ', 'ぱぴぷぺぽ     ', 'ぁぃぅぇぉゃゅょっ ',
       'アイウエオカキクケコ', 'サシスセソタチツテト', 'ナニヌネノハヒフヘホ', 'マミムメモヤ ユ ヨ', 'ラリルレロワ ヲ ン',
       'ガギグゲゴザジズゼゾ', 'ダヂヅデドバビブベボ', 'パピプペポ     ', 'ァィゥェォャュョッヴ',
       '0123456789', 'ABCDEFGHIJ', 'KLMNOPQRST', 'UVWXYZ    ', '?![]$ー_・. ', '=/→←↑↓%()~']
# kana keys whose small-font slot now holds a lowercase letter (ui_tool.EXTRA): found from the original table
_orig = open(os.path.join(HERE, 'Disc1', TABLES[0][0]), 'rb').read()[TABLES[0][1]:TABLES[0][1] + 240]
LOST = {OLD[i // 10][i % 10] for i, b in enumerate(_orig) if b in ui_tool.EXTRA.values()}   # ヲ ヂ ヅ ゥ ...

NEW = ['ABCDEFGHIJ', 'KLMNOPQRST', "UVWXYZ.-'!", 'abcdefghij', 'klmnopqrst', 'uvwxyz?:  ',
       '0123456789', OLD[22], OLD[23]] + \
      [''.join(' ' if ch in LOST else ch for ch in row) for row in OLD[9:18]] + OLD[0:6]


def cells(layout):
    for r, row in enumerate(layout):
        assert len(row) == COLS_K, row
        for c, ch in enumerate(row):
            yield r, c, ch


def table_bytes():
    enc = ui_tool.encoder()
    t = ut.load_table()
    dec = {}
    for b, ch in t.items():
        dec.setdefault(ch, b)
    out = bytearray()
    for r, c, ch in cells(NEW):
        if ch == ' ':
            out.append(0xEB)
        else:
            out.append(enc[ch] if ch in enc else dec[ch])
    return bytes(out)


def main():
    scr2d.COLS, scr2d.ROWS = 20, ROWS_K                    # the keyboard runs below the 240-line screen
    W, H = 20 * 16, ROWS_K * 16
    src = os.path.join(HERE, 'Disc1', 'NIC_MJ.2D')
    s = scr2d.Scr(src)
    px = s.pixels()
    pal = s.pal
    col = [scr2d.rgb(pal[p]) for p in px]

    # 1. erase every key (text pixels inside the key area, grown by 1 px) and fill from the neighbours
    box = (X0 - 2, Y0 - 2, X0 + COLS_K * PITCH + 1, Y0 + ROWS_K * PITCH + 1)
    hole = set()
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            c = col[y * W + x]
            if max(c) > 45 and max(c) - min(c) < 48:        # white text + grey anti-aliasing (as scr_labels)
                hole |= {(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    bg = list(col)                                          # smooth fill: only used under redrawn keys
    left = set(hole)
    while left:
        done = {}
        for x, y in left:
            ns = [bg[(y + dy) * W + x + dx] for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                  if (dx or dy) and (x + dx, y + dy) not in left]
            if ns:
                done[(x, y)] = tuple(sum(c[i] for c in ns) // len(ns) for i in range(3))
        for (x, y), c in done.items():
            bg[y * W + x] = c
        left -= set(done)

    # 2. each original character's ink: how far it lifts the pixel towards white over the cleaned background
    ink = {}
    for r, c, ch in cells(OLD):
        if ch == ' ':
            continue
        a = []
        for y in range(PITCH):
            for x in range(PITCH):
                i = (Y0 + r * PITCH + y) * W + X0 + c * PITCH + x
                lo, hi = sum(bg[i]) / 3, sum(col[i]) / 3
                a.append(max(0.0, min(1.0, (hi - lo) / max(1.0, 255 - lo))) if (X0 + c * PITCH + x, Y0 + r * PITCH + y) in hole else 0.0)
        ink.setdefault(ch, a)

    # 3. lowercase letters (and the apostrophe) rendered to match: Tahoma, x-height lined up with the capitals
    font = ImageFont.truetype(FONT, 13)
    base = 10                                               # baseline of the capitals inside a key (rows 0..13)
    for ch in set(''.join(NEW)) - set(ink) - {' '}:
        m = Image.new('L', (PITCH, PITCH), 0)
        d = ImageDraw.Draw(m)
        w = d.textlength(ch, font=font)
        d.text(((PITCH - w) / 2 + 0.5, base), ch, font=font, fill=255, anchor='ls')
        ink[ch] = [m.getpixel((i % PITCH, i // PITCH)) / 255 for i in range(PITCH * PITCH)]

    # 4. only keys whose character changes are redrawn (the katakana block keeps its own pixels). A key that
    #    becomes empty gets a clean patch of real backdrop from one of the original empty keys (a smooth fill
    #    would show as a flat grey box there).
    empty = [(r, c) for r, c, ch in cells(OLD) if ch == ' ']
    out = list(col)
    changed = set()
    for r, c, ch in cells(NEW):
        if ch == OLD[r][c]:
            continue
        kx, ky = X0 + c * PITCH, Y0 + r * PITCH
        blank = ch == ' '
        if blank:
            er, ec = min(empty, key=lambda e: abs(e[0] - r) * 3 + abs(e[1] - c))
            sx, sy = X0 + ec * PITCH, Y0 + er * PITCH
        for y in range(PITCH):
            for x in range(PITCH):
                i = (ky + y) * W + kx + x
                if blank:
                    out[i] = col[(sy + y) * W + sx + x]
                else:
                    k, b0 = ink[ch][y * PITCH + x], bg[i]
                    out[i] = tuple(int(255 * k + b0[j] * (1 - k)) for j in range(3))
                changed.add((kx + x, ky + y))

    cache = {}
    def nearest(c):
        if c not in cache:
            cache[c] = min(range(256), key=lambda i: sum((a - b) ** 2 for a, b in zip(scr2d.rgb(pal[i]), c)))
        return cache[c]
    for x, y in changed:
        px[y * W + x] = nearest(out[y * W + x])
    s.put(px, changed)

    out_dir = os.path.join(HERE, 'build', 'Disc1')
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, 'NIC_MJ.2D'), 'wb').write(s.raw)
    prev = os.path.join(HERE, 'build', 'preview')
    os.makedirs(prev, exist_ok=True)
    s.image(px).resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(prev, 'NIC_MJ.png'))

    tb = table_bytes()
    for f, off in TABLES:
        p = os.path.join(out_dir, f)
        data = bytearray(open(p if os.path.exists(p) else os.path.join(HERE, 'Disc1', f), 'rb').read())
        orig = open(os.path.join(HERE, 'Disc1', f), 'rb').read()[off:off + 240]
        if orig != _orig:
            sys.exit(f'{f}: the original keyboard table is not at {off:#x}')
        data[off:off + 240] = tb
        open(p, 'wb').write(bytes(data))
    scr2d.COLS, scr2d.ROWS = 20, 15                        # restore the screen size other scripts expect
    print(f'NIC_MJ.2D: {len(changed)} pixels redrawn; keyboard table written to {", ".join(f for f, _ in TABLES)}')


if __name__ == '__main__':
    main()
