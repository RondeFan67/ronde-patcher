# UI text (1 byte per char = FONT8.2D tile - 0x100; 0xEB space, 0xFD nn layout code, 0xFE line break,
# 0xFF end of string). Finds string pools by splitting on 0xFF and keeping chunks that decode cleanly.
#   python ui_text.py Disc1/0.BIN [min_len]   -> prints offset<TAB>text
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KANA = set('ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろわをんゔ'
           'ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロワヲンヴー')


def load_table():
    t = {}
    for line in open(os.path.join(HERE, 'font8.tbl'), encoding='utf-8'):
        k, v = line.rstrip('\n').split('=', 1)
        t[int(k, 16)] = v
    t[0xEB] = ' '
    return t


def decode(chunk, t):
    s, i = '', 0
    while i < len(chunk):
        b = chunk[i]
        if b == 0xFD and i + 1 < len(chunk):
            s += f'{{FD{chunk[i+1]:02X}}}'; i += 2; continue
        if b == 0xFE:
            s += '{NL}'; i += 1; continue
        if 0xF0 <= b <= 0xFC and b not in t:   # value placeholders, e.g. 0xFB inserts a name
            s += f'{{{b:02X}}}'; i += 1; continue
        if b not in t:
            return None
        s += t[b]; i += 1
    return s


def strings(data, t, min_len=2):
    pos = 0
    for part in data.split(b'\xff'):
        start = pos
        pos += len(part) + 1
        k = 0
        while k < len(part) and part[k] == 0:   # alignment padding left from the previous string
            k += 1
        chunk = part[k:]
        if len(chunk) < min_len or len(chunk) > 400:
            continue
        s = decode(chunk, t)
        if s is None:
            continue
        good = sum(1 for c in s if c in KANA or c == ' ' or c.isascii() and c.isalnum())
        if sum(1 for c in s if c in KANA) >= 2 and good >= 0.8 * len(s.replace('{NL}', '')):
            yield start + k, s


if __name__ == '__main__':
    t = load_table()
    data = open(sys.argv[1], 'rb').read()
    for off, s in strings(data, t, int(sys.argv[2]) if len(sys.argv) > 2 else 2):
        print(f'{off:05X}\t{s}')
