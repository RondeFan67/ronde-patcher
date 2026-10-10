# Status-page section headers: WIN_HED1.DG2 (headerless; the name is misleading, it is a VDP1 sprite pack).
# 11 sprites, 8bpp, 10 rows each, packed back to back. Widths 48 x 8, 72 x 2, 80 (the content is 4 px narrower,
# then 0 = transparent padding). Row 0 and 9 and the 2 edge columns are the frame; the inside is a repeating
# 8-px texture (0xFF + indices 6-11) with the text drawn in index 22 (plus anti-alias 13-21).
# The palette is not in the file (the game supplies it), so the redraw only reuses indices already there.
# The hand-drawn font below has a 7-px cap height so the longest labels fit.
#
# STAT.BIN holds a second set of the same headers (plus そうび), 8 rows each on a transparent background (index 0):
# 9 x 48 px at 0x18000, then 3 x 64 px at 0x18D80. Drawn in index 20 with index 181 as the dark edge.
# Its palette is not the one at the start of the file either, so again only existing indices are used.
#
#   python sprite_labels.py         write build/Disc1/WIN_HED1.DG2 + STAT.BIN (+ previews in build/preview)
import os
from collections import Counter

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
H = 10
TEXT = 22          # stroke colour of the original labels
SHADOW = 0xFF      # the darkest texture colour, used as a 1-px drop shadow
# (offset, width, Japanese, English)
SPRITES = [
    (0, 48, 'マジック', 'Magic'),
    (480, 48, 'サマナー', 'Summoner'),
    (960, 48, 'けいやく', 'Contract'),
    (1440, 48, 'ストック', 'Stock'),
    (1920, 48, 'すてる', 'Dismiss'),
    (2400, 48, 'アルカナ', 'Arcana'),
    (2880, 48, 'アイテム', 'Items'),
    (3360, 48, 'デビル', 'Devil'),
    (3840, 72, 'けいやくまほう', 'Contract Magic'),
    (4560, 72, 'マジカルレジスト', 'Magic Resist'),
    (5280, 80, 'ダメージコントロール', 'Damage Control'),
]

STAT_H = 8
STAT_TEXT, STAT_EDGE = 20, 181
# (offset, width, Japanese, English)
STAT_SPRITES = [(0x18000 + i * 48 * STAT_H, 48, jp, en) for i, (jp, en) in enumerate([
    ('マジック', 'Magic'), ('サマナー', 'Summoner'), ('けいやく', 'Contract'), ('ストック', 'Stock'),
    ('すてる', 'Dismiss'), ('アイテム', 'Items'), ('デビル', 'Devil'), ('アルカナ', 'Arcana'), ('そうび', 'Equip')])]
STAT_SPRITES += [(0x18D80 + i * 64 * STAT_H, 64, jp, en) for i, (jp, en) in enumerate([
    ('マジカルレジスト', 'Magic Resist'), ('けいやくまほう', 'Contract Magic'), ('ダメージコントロール', 'Damage Control')])]

# 8 rows: cap height rows 0-6, x-height rows 2-6, descender row 7
GLYPHS = {
    'A': ['.##.', '#..#', '#..#', '####', '#..#', '#..#', '#..#', '....'],
    'C': ['.###', '#...', '#...', '#...', '#...', '#...', '.###', '....'],
    'E': ['####', '#...', '#...', '###.', '#...', '#...', '####', '....'],
    'D': ['###.', '#..#', '#..#', '#..#', '#..#', '#..#', '###.', '....'],
    'I': ['###', '.#.', '.#.', '.#.', '.#.', '.#.', '###', '...'],
    'M': ['#...#', '##.##', '#.#.#', '#.#.#', '#...#', '#...#', '#...#', '.....'],
    'R': ['###.', '#..#', '#..#', '###.', '#.#.', '#..#', '#..#', '....'],
    'S': ['.###', '#...', '#...', '.##.', '...#', '...#', '###.', '....'],
    'a': ['....', '....', '.##.', '...#', '.###', '#..#', '.###', '....'],
    'c': ['...', '...', '.##', '#..', '#..', '#..', '.##', '...'],
    'e': ['....', '....', '.##.', '#..#', '####', '#...', '.###', '....'],
    'g': ['....', '....', '.###', '#..#', '#..#', '.###', '...#', '.##.'],
    'i': ['#', '.', '#', '#', '#', '#', '#', '.'],
    'k': ['#...', '#...', '#..#', '#.#.', '##..', '#.#.', '#..#', '....'],
    'l': ['#', '#', '#', '#', '#', '#', '#', '.'],
    'm': ['.....', '.....', '####.', '#.#.#', '#.#.#', '#.#.#', '#.#.#', '.....'],
    'n': ['....', '....', '###.', '#..#', '#..#', '#..#', '#..#', '....'],
    'o': ['....', '....', '.##.', '#..#', '#..#', '#..#', '.##.', '....'],
    'p': ['....', '....', '###.', '#..#', '#..#', '###.', '#...', '#...'],
    'q': ['....', '....', '.###', '#..#', '#..#', '.###', '...#', '...#'],
    'r': ['...', '...', '#.#', '##.', '#..', '#..', '#..', '...'],
    's': ['...', '...', '.##', '#..', '.#.', '..#', '##.', '...'],
    't': ['...', '.#.', '###', '.#.', '.#.', '.#.', '..#', '...'],
    'u': ['....', '....', '#..#', '#..#', '#..#', '#..#', '.###', '....'],
    'v': ['.....', '.....', '#...#', '#...#', '.#.#.', '.#.#.', '..#..', '.....'],
    ' ': ['..', '..', '..', '..', '..', '..', '..', '..'],
}


def text_bits(text):
    """Rows of 0/1 for `text`, 1 px between letters."""
    rows = [[] for _ in range(8)]
    for i, ch in enumerate(text):
        for r in range(8):
            rows[r] += ([0] if i else []) + [int(c == '#') for c in GLYPHS[ch][r]]
    return rows


def texture(d):
    """The clean background colour for each (row, column mod 8), voted over every sprite's non-text pixels."""
    votes = {}
    for off, w, _, _ in SPRITES:
        for y in range(1, H - 1):
            for x in range(6, w - 10):
                v = d[off + y * w + x]
                if v == 0xFF or 6 <= v <= 11:
                    votes.setdefault((y, x % 8), Counter())[v] += 1
    return {k: c.most_common(1)[0][0] for k, c in votes.items()}


def redraw(d):
    tex = texture(d)
    out = bytearray(d)
    for off, w, _, text in SPRITES:
        inner = w - 4 - 4                  # content width minus the 2-px frame on each side
        for y in range(1, H - 1):
            for x in range(2, inner + 2):
                if d[off + y * w + x] >= 13:
                    out[off + y * w + x] = tex[(y, x % 8)]
        bits = text_bits(text)
        tw = len(bits[0])
        if tw > inner:
            raise ValueError(f'{text!r} is {tw} px, room for {inner}')
        x0 = 2 + (inner - tw) // 2
        for r in range(8):
            for c, b in enumerate(bits[r]):
                if b:
                    out[off + (1 + r) * w + x0 + c] = TEXT
        for r in range(7):                 # shadow one pixel down-right of each stroke pixel
            for c in range(tw):
                if bits[r][c] and not (c + 1 < tw and bits[r + 1][c + 1]) and x0 + c + 1 < inner + 2:
                    out[off + (2 + r) * w + x0 + c + 1] = SHADOW
    return bytes(out)


def stat_redraw(d):
    """STAT.BIN: clear each label and draw the English centred, with a 1-px edge down-right."""
    out = bytearray(d)
    for off, w, _, text in STAT_SPRITES:
        out[off:off + w * STAT_H] = bytes(w * STAT_H)
        bits = text_bits(text)
        tw = len(bits[0])
        if tw + 1 > w:
            raise ValueError(f'{text!r} is {tw} px, room for {w - 1}')
        x0 = (w - tw - 1) // 2
        for r in range(STAT_H):
            for c, b in enumerate(bits[r]):
                if b:
                    out[off + r * w + x0 + c] = STAT_TEXT
                elif r and c and bits[r - 1][c - 1]:
                    out[off + r * w + x0 + c] = STAT_EDGE
            if r and bits[r - 1][-1]:
                out[off + r * w + x0 + tw] = STAT_EDGE
    return bytes(out)


def stat_preview(d, path):
    col = {0: (144, 248, 0), STAT_TEXT: (8, 16, 48), STAT_EDGE: (120, 120, 140)}
    im = Image.new('RGB', (64, len(STAT_SPRITES) * (STAT_H + 2)), (144, 248, 0))
    for k, (off, w, _, _) in enumerate(STAT_SPRITES):
        s = Image.new('RGB', (w, STAT_H))
        s.putdata([col.get(b, (200, 0, 200)) for b in d[off:off + w * STAT_H]])
        im.paste(s, (0, k * (STAT_H + 2)))
    im.resize((im.width * 6, im.height * 6), Image.NEAREST).save(path)


def preview(d, path):
    grey = {0xFF: (24, 24, 64), 0: (0, 90, 0)}
    im = Image.new('RGB', (80, len(SPRITES) * (H + 2)), (0, 90, 0))
    for k, (off, w, _, _) in enumerate(SPRITES):
        s = Image.new('RGB', (w, H))
        s.putdata([grey.get(b, (min(255, b * 11),) * 3) for b in d[off:off + w * H]])
        im.paste(s, (0, k * (H + 2)))
    im.resize((im.width * 6, im.height * 6), Image.NEAREST).save(path)


def main():
    d = open(os.path.join(HERE, 'Disc1', 'WIN_HED1.DG2'), 'rb').read()
    assert sum(w * H for _, w, _, _ in SPRITES) == len(d)
    new = redraw(d)
    os.makedirs(os.path.join(HERE, 'build', 'Disc1'), exist_ok=True)
    os.makedirs(os.path.join(HERE, 'build', 'preview'), exist_ok=True)
    open(os.path.join(HERE, 'build', 'Disc1', 'WIN_HED1.DG2'), 'wb').write(new)
    preview(new, os.path.join(HERE, 'build', 'preview', 'WIN_HED1.DG2.png'))
    print(f'WIN_HED1.DG2: {len(SPRITES)} headers redrawn')
    st = stat_redraw(open(os.path.join(HERE, 'Disc1', 'STAT.BIN'), 'rb').read())
    open(os.path.join(HERE, 'build', 'Disc1', 'STAT.BIN'), 'wb').write(st)
    stat_preview(st, os.path.join(HERE, 'build', 'preview', 'STAT.BIN.png'))
    print(f'STAT.BIN: {len(STAT_SPRITES)} headers redrawn')


if __name__ == '__main__':
    main()
