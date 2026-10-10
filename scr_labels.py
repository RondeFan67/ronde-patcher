# Redraw the Japanese text on SCR screens (.2D) in English.
# The KEI_* screens are the backup-RAM warnings shown at boot. Their white text sits on a painted background:
# the old text is masked (bright, unsaturated pixels inside the text bands, grown by 1 px), filled in from
# the surrounding pixels, and the English is drawn anti-aliased in white, using only the screen's own palette.
#
#   python scr_labels.py            write build/Disc1/<screen>.2D + preview PNGs in build/preview/
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scr2d import Scr, rgb, COLS, ROWS  # noqa: E402

FONT = r'C:\Windows\Fonts\timesbd.ttf'
W, H = COLS * 16, ROWS * 16

# text bands (y0, y1) of the original Japanese, found by scanning for white pixels
TITLE = (35, 52)
OPTIONS = [(164, 174), (184, 194)]      # はい / いいえ; the game draws its cursor next to these
OPT_X = 131


def sysmem(mem):
    return {
        'ready': ([f'{mem} is not yet set up', 'to hold save data.',
                   f'All data in {mem} will be erased.', 'Is that OK?'], True),
        'erased': ([f'All data in {mem} has been erased.'], False),
        'failed': ([f'The data in {mem}', 'could not be erased.',
                    "Please erase all data using the", "Sega Saturn's Memory Manager."], False),
    }


SYS, CART = sysmem('System Memory'), sysmem('Cartridge Memory')
# screen -> (Japanese, body line tops, English lines, has Yes/No)
SCREENS = {
    'KEI_1A.2D': ('本体ＲＡＭのバックアップの準備が／まだできていません。／本体ＲＡＭの全ての記録を消します。／よろしいですか？',
                  [73, 91, 109, 127], *SYS['ready']),
    'KEI_1B.2D': ('カートリッジＲＡＭのバックアップの準備が／まだできていません。／カートリッジＲＡＭの全ての記録を消します。／よろしいですか？',
                  [74, 92, 110, 128], *CART['ready']),
    'KEI_2A.2D': ('本体ＲＡＭの全ての記録を消しました。', [83], *SYS['erased']),
    'KEI_2B.2D': ('カートリッジＲＡＭの全ての記録を消しました。', [85], *CART['erased']),
    'KEI_3A.2D': ('本体ＲＡＭの全ての記録を消すことが／できませんでした。／セガサターン本体の保存データ管理画面で、／全ての記録を消してください。',
                  [79, 97, 115, 133], *SYS['failed']),
    'KEI_3B.2D': ('カートリッジＲＡＭの全ての記録を消すことが／できませんでした。／セガサターン本体の保存データ管理画面で、／全ての記録を消してください。',
                  [72, 90, 108, 126], *CART['failed']),
    'KEI_4AB.2D': ('容量が足りません。／175ブロック必要です。／このままゲームを開始した場合、／記録を保存することはできません。／ゲームを開始しますか？',
                   [65, 83, 101, 119, 137],
                   ['Not enough free memory.', '175 blocks are required.', 'If you start the game now,',
                    'you will not be able to save.', 'Start the game anyway?'], True),
}
# '警告' -> 'WARNING', 'はい' -> 'Yes', 'いいえ' -> 'No'


def texty(c):
    """White text and its grey anti-aliasing: brighter than the dark backdrop, close to neutral."""
    c = rgb(c)
    return max(c) > 45 and max(c) - min(c) < 48


def nearest(pal, c, cache={}):
    key = (tuple(pal), c)
    if key not in cache:
        cache[key] = min(range(256), key=lambda i: sum((a - b) ** 2 for a, b in zip(rgb(pal[i]), c)))
    return cache[key]


def erase(px, pal, bands):
    """Fill the text pixels inside the bands from their neighbours; returns RGB rows and the changed set."""
    col = [rgb(pal[p]) for p in px]
    hole = set()
    for y0, y1 in bands:
        for y in range(y0 - 2, y1 + 3):
            for x in range(W):
                if texty(pal[px[y * W + x]]):
                    hole |= {(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                             if 0 <= x + dx < W and 0 <= y + dy < H}
    left = set(hole)
    while left:
        done = {}
        for x, y in left:
            ns = [col[(y + dy) * W + x + dx] for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                  if (dx or dy) and 0 <= x + dx < W and 0 <= y + dy < H and (x + dx, y + dy) not in left]
            if ns:
                done[(x, y)] = tuple(sum(c[i] for c in ns) // len(ns) for i in range(3))
        for (x, y), c in done.items():
            col[y * W + x] = c
        left -= set(done)
    return col, hole


def text_mask(lines, font):
    """Anti-aliased coverage image of `lines` [(x, top, text)] with each glyph box top at `top`."""
    m = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(m)
    for x, top, text in lines:
        d.text((x, top), text, font=font, fill=255, anchor='lt')
    return m


def render(name, tops, english, yes_no):
    s = Scr(os.path.join(HERE, 'Disc1', name))
    px = s.pixels()
    bands = [TITLE] + [(t, t + 12) for t in tops] + (OPTIONS if yes_no else [])
    col, changed = erase(px, s.pal, bands)
    body = ImageFont.truetype(FONT, 14)
    widest = max(body.getbbox(t, anchor='lt')[2] for t in english)
    if widest > W - 24:
        raise ValueError(f'{name}: line too wide ({widest}px)')
    x0 = (W - widest) // 2
    title = ImageFont.truetype(FONT, 18)
    tw = title.getbbox('WARNING', anchor='lt')[2]
    m = [text_mask([((W - tw) // 2 - 12, TITLE[0] + 1, 'WARNING')], title),
         text_mask([(x0, t, e) for t, e in zip(tops, english)], body)]
    if yes_no:
        m.append(text_mask([(OPT_X, y0, t) for (y0, _), t in zip(OPTIONS, ('Yes', 'No'))], body))
    for mk in m:
        a = mk.load()
        for y in range(H):
            for x in range(W):
                if a[x, y]:
                    k = a[x, y] / 255
                    c = col[y * W + x]
                    col[y * W + x] = tuple(int(255 * k + c[i] * (1 - k)) for i in range(3))
                    changed.add((x, y))
    for x, y in changed:
        px[y * W + x] = nearest(s.pal, col[y * W + x])
    s.put(px, changed)
    return s, px


def main():
    out_dir = os.path.join(HERE, 'build', 'Disc1')
    prev = os.path.join(HERE, 'build', 'preview')
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(prev, exist_ok=True)
    for name, (_jp, tops, english, yes_no) in SCREENS.items():
        s, px = render(name, tops, english, yes_no)
        open(os.path.join(out_dir, name), 'wb').write(s.raw)
        s.image(px).resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(prev, name + '.png'))
        print(f'{name}: {len(english)} lines redrawn')


if __name__ == '__main__':
    main()
