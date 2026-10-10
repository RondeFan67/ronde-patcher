# Redraw Japanese label sprites in DG2 sheets with English.
# CONFIG cells have a transparent background, so the text is drawn as the original label's fill colour
# with a mid-tone anti-alias edge and a 1-pixel dark drop shadow (down-right, like the Japanese labels),
# using only colours already in the sheet's palette. A full outline made the small text blobby.
#
#   python dg2_labels.py            write build/Disc1/<sheet>.DG2 + preview PNGs in build/preview/
import os
import sys
from collections import Counter

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dg2  # noqa: E402

FONT = r'C:\Windows\Fonts\arialbd.ttf'

# sheet -> list of (x, y, w, h, english)
SHEETS = {
    'CONFIG.DG2': [(0, 0, 72, 16, 'Settings')] + [
        (x, 16 * (i + 1), 72, 16, t)
        for i, t in enumerate(['Battle Anim', 'Demon Talk', 'Commands', 'BGM', 'Sound FX', 'Base Cursor',
                               'Msg Speed', 'On', 'Off', 'A Button', 'Japanese', 'English', 'Stereo', 'Mono',
                               'Fast', 'Normal', 'Slow', 'Skip', 'Free'])
        for x in (0, 72)],
}
# per sheet and column x: brightness percentile for the fill colour (selected labels stay green)
PCT = {'CONFIG.DG2': {0: 0.5, 72: 0.75}}
SIZE = {'CONFIG.DG2': (13, 11)}   # (title, labels)


def lum(c):
    r, g, b = c
    return 0.3 * r + 0.59 * g + 0.11 * b


def fit_size(text, cw, ch):
    for size in range(15, 7, -1):
        l, t, r, b = ImageFont.truetype(FONT, size).getbbox(text)
        if r - l + 2 <= cw and b - t + 2 <= ch:
            return size
    raise ValueError(f'{text!r} does not fit {cw}x{ch}')


def colours(px, w, pal, x0, y0, cw, ch, text=None, pct=0.75):
    """(outline, fill) palette indices of an original label cell."""
    cell = [[px[(y0 + y) * w + x0 + x] for x in range(cw)] for y in range(ch)]
    used = Counter(v for row in cell for v in row if v)
    if not used:
        raise ValueError(f'empty cell at {x0},{y0}')
    by_l = sorted(used, key=lambda i: lum(dg2.rgb(pal[i])))
    outline = max(by_l[:max(1, len(by_l) // 3)], key=lambda i: used[i])
    dark = lum(dg2.rgb(pal[outline]))
    # fill: the colour at percentile `pct` (by brightness) of the original label's fill pixels
    fills = sorted((lum(dg2.rgb(pal[v])), v) for row in cell for v in row if v and lum(dg2.rgb(pal[v])) > dark + 24)
    return outline, fills[int(len(fills) * pct)][1]


def nearest(pal, c, among):
    return min(among, key=lambda i: sum((a - b) ** 2 for a, b in zip(dg2.rgb(pal[i]), c)))


def redraw(px, w, pal, x0, y0, cw, ch, text, size, outline, solid):
    font = ImageFont.truetype(FONT, size)
    l, t, r, b = font.getbbox(text)
    if r - l + 2 > cw:
        raise ValueError(f'{text!r} does not fit {cw} px at size {size}')
    im = Image.new('L', (cw, ch), 0)
    ImageDraw.Draw(im).text((1 - l, (ch - (b - t)) // 2 - t), text, font=font, fill=255)
    m = im.load()
    used = sorted({v for v in px if v})
    fill_c, dark_c = dg2.rgb(pal[solid]), dg2.rgb(pal[outline])
    mid = nearest(pal, tuple((a + b) // 2 for a, b in zip(fill_c, dark_c)), used)
    shadow = nearest(pal, tuple(c // 4 for c in dark_c), used)
    for y in range(ch):
        for x in range(cw):
            a = m[x, y]
            v = 0
            if a >= 150:
                v = solid   # one fill colour reads better than the original gradient at this size
            elif a >= 70:
                v = mid
            elif x and y and m[x - 1, y - 1] >= 110:
                v = shadow
            px[(y0 + y) * w + x0 + x] = v
    return size


# ---- W_WIND.DG2: world-map district and realm buttons (64x24, pink = selectable, dark = not) ----
# Each button is redrawn on a clean button: the median-brightness colour at each pixel over all buttons
# of the same kind (the text is the darkest/brightest colour and sits in different places, so the median
# is the bare button; a plain vote fails because the button gradient is dithered).
DISTRICTS = [  # (Japanese, English), in sheet order, 4 per row
    ('銀座', 'Ginza'), ('渋谷', 'Shibuya'), ('新宿', 'Shinjuku'), ('目黒', 'Meguro'),
    ('有明', 'Ariake'), ('代々木', 'Yoyogi'), ('池袋', 'Ikebukuro'), ('中野', 'Nakano'),
    ('品川', 'Shinagawa'), ('本郷', 'Hongo'), ('多摩川', 'Tamagawa'), ('川崎', 'Kawasaki'),
    ('荻窪', 'Ogikubo'), ('鎌倉', 'Kamakura'), ('吉祥寺', 'Kichijoji'), ('茅ヶ崎', 'Chigasaki'),
    ('横浜', 'Yokohama'), ('横須賀', 'Yokosuka'), ('八王子', 'Hachioji'), ('立川', 'Tachikawa'),
    ('足柄', 'Ashigara'), ('山中湖', 'Yamanaka'), ('北富士', 'Kita-Fuji'), ('魔神殿', 'Demon Hall'),
]
REALMS = [  # short forms of the stage-card names (sys_strings STITLE.BIN)
    ('憤怒界', 'Wrath'), ('暗冥界', 'Netherworld'), ('冥殺界', 'Slaughter'), ('異端界', 'Heresy'),
    ('屍魔空', 'Corpse Sky'), ('相模原', 'Sagamihara'),
]
W_WIND = {   # group -> (cells (x, y, english), dark text on light button?, button height)
    'light': ([(64 * (i % 4), 272 + 24 * (i // 4), e) for i, (_, e) in enumerate(DISTRICTS)]
              + [(152, 96 + 24 * i, e) for i, (_, e) in enumerate(REALMS)], True, 24),
    'dark': ([(64 * (i % 4), 416 + 25 * (i // 4), e) for i, (_, e) in enumerate(DISTRICTS + REALMS)], False, 25),
}
BTN_W = 64

# ---- HARD.DG2 (4bpp): save rules shown on the difficulty screen ----
# セーブ　ワールドマップ○　ステージマップ○ (Normal) / ...ステージマップ× (Hard)
HARD = [(33, [(24, 'Save', 'y'), (76, 'World Map', 'w'), (144, 'OK', 'y'), (192, 'Stage Map', 'w'), (260, 'OK', 'y')]),
        (59, [(24, 'Save', 'y'), (76, 'World Map', 'w'), (144, 'OK', 'y'), (192, 'Stage Map', 'w'), (260, 'No', 'y')])]
HARD_RAMP = {'w': [3, 2, 5, 4], 'y': [14, 11, 7, 8]}   # dark -> bright palette indices

# ---- Command buttons: the game has an English set built in (Settings -> Commands -> English). ----
# Copy it over the Japanese set, so the commands read English with either setting.
COPY_FILES = {'JAPCOM.DG2': 'ENGCOM.DG2'}
COPY_RECTS = {  # sheet -> (x, y, w, h) of the English buttons, copied onto (dx, dy)
    'WMAP_COM.DG2': [((64, 0, 64, 192), (0, 0))],
    'WMAP_CM1.DG2': [((128, 0, 128, 272), (0, 0))],
    'REMCMD.DG2': [((128, 0, 128, 272), (0, 0))],
    'SHOPCMD.DG2': [((128, 0, 128, 96), (0, 0))],
    'TALK_COM.DG2': [((0, 0, 64, 32), (0, 32))],
}


def save(name, raw, px, w, h, pal, out_dir, prev):
    open(os.path.join(out_dir, name), 'wb').write(dg2.pack(raw, px))
    im = Image.new('RGB', (w, h))
    im.putdata([dg2.rgb(pal[p]) for p in px])
    im.resize((w * 2, h * 2), Image.NEAREST).save(os.path.join(prev, name + '.png'))


def bare_button(px, w, pal, x0, y0, bh, light, keep):
    """The button at x0,y0 without its text: neutral (text) pixels inside the text area, grown by 1 px, are
    filled from their neighbours and mapped to the nearest colour in `keep` (the buttons' own colours)."""
    def is_text(i):
        c = dg2.rgb(pal[i])
        return max(c) - min(c) < 40 and (light or lum(c) > 70)
    col = {(dx, dy): dg2.rgb(pal[px[(y0 + dy) * w + x0 + dx]]) for dy in range(bh) for dx in range(BTN_W)}
    hole = set()
    for dy in range(3, bh - 3):
        for dx in range(4, BTN_W - 4):      # the text area; the bevel at the edges is neutral too
            if is_text(px[(y0 + dy) * w + x0 + dx]):
                hole |= {(dx + i, dy + j) for i in (-1, 0, 1) for j in (-1, 0, 1)}
    left = set(hole)
    while left:
        done = {}
        for dx, dy in left:
            ns = [col[(dx + i, dy + j)] for i in (-1, 0, 1) for j in (-1, 0, 1)
                  if (i or j) and (dx + i, dy + j) in col and (dx + i, dy + j) not in left]
            if ns:
                done[(dx, dy)] = tuple(sum(c[k] for c in ns) // len(ns) for k in range(3))
        col.update(done)
        left -= set(done)
    out = [px[(y0 + dy) * w + x0 + dx] for dy in range(bh) for dx in range(BTN_W)]
    for dx, dy in hole:
        c = col[(dx, dy)]
        out[dy * BTN_W + dx] = min(keep, key=lambda i: sum((a - b) ** 2 for a, b in zip(dg2.rgb(pal[i]), c)))
    return out


W_FONT = r'C:\Windows\Fonts\tahomabd.ttf'   # hinted for small sizes; reads better than Arial here


def w_size(text, bh):
    """Largest size from 11 down that fits the button (long names get a smaller size)."""
    for size in (11, 10, 9):
        l, t, r, b = ImageFont.truetype(W_FONT, size).getbbox(text)
        if r - l <= BTN_W - 4 and b - t <= bh - 6:
            return size
    raise ValueError(f'{text!r} does not fit a {BTN_W}x{bh} button')


def w_wind(out_dir, prev):
    w, h, pal, px, raw = dg2.load(os.path.join(HERE, 'Disc1', 'W_WIND.DG2'))
    px = bytearray(px)
    sizes = Counter()
    for cells, light, bh in W_WIND.values():
        used = Counter(px[(y + dy) * w + x + dx] for x, y, _ in cells for dy in range(bh) for dx in range(BTN_W))
        by_l = sorted(used, key=lambda i: lum(dg2.rgb(pal[i])))
        ink = by_l[0] if light else by_l[-1]
        keep = [i for i in used if max(dg2.rgb(pal[i])) - min(dg2.rgb(pal[i])) >= 40 or not light and lum(dg2.rgb(pal[i])) <= 70]
        for x0, y0, text in cells:
            bare = bare_button(px, w, pal, x0, y0, bh, light, keep)
            size = w_size(text, bh)
            sizes[size] += 1
            font = ImageFont.truetype(W_FONT, size)
            l, t, r, b = font.getbbox(text)
            im = Image.new('L', (BTN_W, bh), 0)
            ImageDraw.Draw(im).text(((BTN_W - (r - l)) // 2 - l, (bh - (b - t)) // 2 - t), text, font=font, fill=255)
            m = im.load()
            ic = dg2.rgb(pal[ink])
            for dy in range(bh):
                for dx in range(BTN_W):
                    v = bare[dy * BTN_W + dx]
                    k = m[dx, dy] / 255
                    if k:   # anti-aliased: blend ink over the button, then the nearest colour the sheet has
                        bg = dg2.rgb(pal[v])
                        v = nearest(pal, tuple(int(ic[i] * k + bg[i] * (1 - k)) for i in range(3)), list(used))
                    px[(y0 + dy) * w + x0 + dx] = v
    save('W_WIND.DG2', raw, px, w, h, pal, out_dir, prev)
    print(f'W_WIND.DG2: {sum(sizes.values())} buttons redrawn (font sizes {dict(sorted(sizes.items()))})')


def hard(out_dir, prev):
    w, h, pal, px, raw = dg2.load(os.path.join(HERE, 'Disc1', 'HARD.DG2'))
    px = bytearray(px)
    font = ImageFont.truetype(FONT, 11)
    for top, parts in HARD:
        for y in range(top, top + 11):
            px[y * w:(y + 1) * w] = bytes(w)
        im = Image.new('L', (w, 11), 0)
        d = ImageDraw.Draw(im)
        colour = {}
        for x, text, c in parts:
            d.text((x, 0), text, font=font, fill=255, anchor='lt')
            colour.update({xx: c for xx in range(x, x + int(font.getlength(text)) + 2)})
        m = im.load()
        for y in range(11):
            for x in range(w):
                if m[x, y] >= 48:
                    ramp = HARD_RAMP[colour.get(x, 'w')]
                    px[(top + y) * w + x] = ramp[min(3, m[x, y] * 4 // 256)]
    save('HARD.DG2', raw, px, w, h, pal, out_dir, prev)
    print('HARD.DG2: 2 lines redrawn')


def copies(out_dir, prev):
    for name, src in COPY_FILES.items():
        open(os.path.join(out_dir, name), 'wb').write(open(os.path.join(HERE, 'Disc1', src), 'rb').read())
        print(f'{name}: copy of {src}')
    for name, rects in COPY_RECTS.items():
        w, h, pal, px, raw = dg2.load(os.path.join(HERE, 'Disc1', name))
        px = bytearray(px)
        for (x0, y0, cw, ch), (dx, dy) in rects:
            for y in range(ch):
                px[(dy + y) * w + dx:(dy + y) * w + dx + cw] = px[(y0 + y) * w + x0:(y0 + y) * w + x0 + cw]
        save(name, raw, px, w, h, pal, out_dir, prev)
        print(f'{name}: English buttons copied over the Japanese ones')


def main():
    out_dir = os.path.join(HERE, 'build', 'Disc1')
    prev = os.path.join(HERE, 'build', 'preview')
    os.makedirs(prev, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    w_wind(out_dir, prev)
    hard(out_dir, prev)
    copies(out_dir, prev)
    for sheet, cells in SHEETS.items():
        w, h, pal, px, raw = dg2.load(os.path.join(HERE, 'Disc1', sheet))
        px = bytearray(px)
        # one size for the whole sheet; a first cell at y=0 is a title
        title_size, size = SIZE[sheet]
        # same outline/fill colour for every label in a column (the column's most common choice)
        col = {}
        for c in cells:
            col.setdefault(c[0], []).append(colours(px, w, pal, *c, pct=PCT.get(sheet, {}).get(c[0], 0.75)))
        pick = {x: (Counter(o for o, f in v).most_common(1)[0][0], Counter(f for o, f in v).most_common(1)[0][0])
                for x, v in col.items()}
        sizes = [redraw(px, w, pal, *c, size if c[1] > 0 else title_size, *pick[c[0]])
                 for c in cells]
        open(os.path.join(out_dir, sheet), 'wb').write(dg2.pack(raw, px))
        im = Image.new('RGB', (w, h))
        im.putdata([dg2.rgb(pal[p]) for p in px])
        im.resize((w * 2, h * 2), Image.NEAREST).save(os.path.join(prev, sheet + '.png'))
        print(f'{sheet}: {len(cells)} labels redrawn (font sizes {min(sizes)}-{max(sizes)})')
    import scr_labels
    import sprite_labels
    sprite_labels.main()
    scr_labels.main()
    import nickname_kbd            # NIC_MJ.2D + the keyboard table in WORLD/REMIX (after ui_tool/sys_tool)
    nickname_kbd.main()
    write_tsv(scr_labels, sprite_labels)


def write_tsv(scr_labels, sprite_labels):
    """image_text.tsv: every Japanese text in an image and its English."""
    rows = [('W_WIND.DG2', f'{x},{y}', jp, en) for (jp, en), (x, y, _) in
            zip(DISTRICTS + REALMS, W_WIND['light'][0])]
    rows += [('W_WIND.DG2', f'{x},{y} (inactive)', jp, en) for (jp, en), (x, y, _) in zip(DISTRICTS + REALMS, W_WIND['dark'][0])]
    rows += [('HARD.DG2', 'y=33 / y=59', 'セーブ　ワールドマップ○　ステージマップ○ / ×',
              'Save  World Map OK  Stage Map OK / No')]
    rows += [('WIN_HED1.DG2', f'sprite {i} @{off:#x} ({w}x10)', jp, en)
             for i, (off, w, jp, en) in enumerate(sprite_labels.SPRITES)]
    rows += [('STAT.BIN', f'header {i} @{off:#x} ({w}x{sprite_labels.STAT_H})', jp, en)
             for i, (off, w, jp, en) in enumerate(sprite_labels.STAT_SPRITES)]
    for name, (jp, _tops, en, yes_no) in scr_labels.SCREENS.items():
        rows.append((name, 'title', '警告', 'WARNING'))
        rows.append((name, 'body', jp, ' / '.join(en)))
        if yes_no:
            rows.append((name, 'options', 'はい / いいえ', 'Yes / No'))
    rows += [('NIC_MJ.2D', 'nickname keyboard', 'hiragana / katakana first, then 0-9 A-Z symbols',
              "A-Z a-z . - ' ! ? : 0-9 symbols first, then katakana and hiragana (table: WORLD.BIN 0x2A980, "
              'REMIX.BIN 0x1F870; nickname_kbd.py)')]
    rows += [(n, 'copy', 'Japanese command buttons', f'replaced by the game\'s own English set ({s})')
             for n, s in list(COPY_FILES.items()) + [(n, 'same sheet') for n in COPY_RECTS]]
    with open(os.path.join(HERE, 'image_text.tsv'), 'w', encoding='utf-8', newline='') as f:
        f.write('file\twhere\tjapanese\tenglish\tsrc\n')
        for r in rows:
            f.write('\t'.join(r) + '\tclaude\n')
    print(f'image_text.tsv: {len(rows)} rows')


if __name__ == '__main__':
    main()
