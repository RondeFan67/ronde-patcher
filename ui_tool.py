# UI text (FONT8.2D font, 1 byte per char = tile - 0x100) extraction, insertion and font patching.
#
#   python ui_tool.py extract     (re)build ui_strings.tsv from the game files, keeping English already written
#   python ui_tool.py insert      write English into build/Disc1/<file> (in place, same length) + FONT8.2D
#   python ui_tool.py check       report strings whose English is missing, too long or not encodable
#
# ui_strings.tsv columns: id, file, offset (hex), max (bytes before the 0xFF), kind, japanese, english, src, note
#   kind rec  = fixed-size name record (padded with spaces 0xEB, 0xFF at the end)
#   kind str  = variable string in a pool (shorter English ends with 0xFF and is zero-filled)
# Control codes are written as in the Japanese: {FDxx} (layout code + argument), {NL} (line break).
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ui_text as ut  # noqa: E402
import ui_pools as up  # noqa: E402
import font8_en as f8  # noqa: E402

TSV = os.path.join(HERE, 'ui_strings.tsv')
FIELDS = ['id', 'file', 'offset', 'max', 'kind', 'japanese', 'english', 'src', 'note']
SPACE = 0xEB

# fixed-size name tables in 0.BIN
RECORD_TABLES = [('0.BIN', 0x4560B, 9, 1001), ('0.BIN', 0x4793C, 7, 43)]
# variable-length string pools: (file, start, end); obvious non-text inside them is filtered by decode()
POOLS = [('0.BIN', 0x3C6C0, 0x3CA30), ('0.BIN', 0x4D234, 0x4D330), ('0.BIN', 0x4E3A0, 0x4E3A8),
         ('SMAP.BIN', 0x50548, 0x50710), ('SMAP.BIN', 0x51FA8, 0x51FF4), ('SMAP.BIN', 0x52020, 0x52044), ('SMAP.BIN', 0x52044, 0x5217C),
         ('FIGHT.BIN', 0x17E2C, 0x17E34),  # battle scene status: こうか (magic effect) line
         ('SMAP.BIN', 0x51B9C, 0x51BA8),   # MAG/Items choice when passing in a stage (copy of 0.BIN 0x3C8D4)
         ('REMIX.BIN', 0x1F7EB, 0x1F832), ('REMIX.BIN', 0x1F964, 0x1FBB0),
         ('WORLD.BIN', 0x2A8C0, 0x2A942),
         # unit detail panel, gem list, demon status page
         ('0.BIN', 0x3C7B8, 0x3C7FC), ('0.BIN', 0x4E3AC, 0x4E3F0), ('SMAP.BIN', 0x52E8C, 0x52F70),
         ('WORLD.BIN', 0x2AE00, 0x2B210)]
SKIP_TEXT = re.compile(r'^(\{FD..\}|[ /~0-9]|\{NL\})*$')   # pure layout placeholders: nothing to translate

# Missing lowercase letters (+ apostrophe) drawn into rarely used kana slots (byte = tile - 0x100).
EXTRA = {'u': 0x6D, 'p': 0x80, 'b': 0x81, 'y': 0x82, 'w': 0xB1, 'k': 0xBE, 'f': 0xBF, 'x': 0x6E,
         'j': 0x83, 'q': 0x84, 'z': 0xD3, "'": 0x7B}
INK = 0x0D
FONT8_CHARS = 0x2140   # character data offset in FONT8.2D (8bpp 8x8 tiles, 64 bytes each)


def encoder():
    t = ut.load_table()
    enc = {}
    for b, ch in t.items():
        if ch != ' ':
            enc.setdefault(ch, b)
    for ch, b in EXTRA.items():
        enc[ch] = b
    enc[' '] = SPACE
    enc['-'] = 0xDC   # the long bar
    return enc


def encode(text, enc):
    out = bytearray()
    for tok in re.findall(r'\{FD[0-9A-F]{2}\}|\{NL\}|\{F[0-9A-C]\}|.', text):
        if tok == '{NL}':
            out.append(0xFE)
        elif re.fullmatch(r'\{F[0-9A-C]\}', tok):
            out.append(int(tok[1:3], 16))
        elif tok.startswith('{FD'):
            out += bytes([0xFD, int(tok[3:5], 16)])
        elif tok in enc:
            out.append(enc[tok])
        else:
            raise ValueError(f'no UI glyph for {tok!r}')
    return bytes(out)


def scan():
    """Yield dicts for every UI string in the game files (Disc 1), each id once."""
    seen = set()
    for r in _scan():
        if r['id'] not in seen:
            seen.add(r['id'])
            yield r


def _scan():
    t = ut.load_table()
    cache = {}
    for f, base, size, count in RECORD_TABLES:
        d = cache.setdefault(f, open(os.path.join(HERE, 'Disc1', f), 'rb').read())
        for i in range(count):
            off = base + i * size
            raw = d[off:off + size - 1]
            jp = ut.decode(raw.rstrip(bytes([SPACE, 0])), t)
            yield dict(id=f'{f}:{off:05X}', file=f, offset=f'{off:05X}', max=str(size - 1), kind='rec',
                       japanese=(jp or '').strip(), note=f'name #{i}' if size == 9 else f'short name #{i}')
    for f, a, b in POOLS:
        d = cache.setdefault(f, open(os.path.join(HERE, 'Disc1', f), 'rb').read())
        for s, e, run in up.pools(d[a:b], t, 1):
            for off, txt, ln in run:
                if not txt.strip() or SKIP_TEXT.match(txt):
                    continue
                yield dict(id=f'{f}:{a + off:05X}', file=f, offset=f'{a + off:05X}', max=str(ln), kind='str',
                           japanese=txt, note='')


def load():
    if not os.path.exists(TSV):
        return {}
    with open(TSV, encoding='utf-8', newline='') as fh:
        return {r['id']: r for r in csv.DictReader(fh, delimiter='\t')}


def save(rows):
    with open(TSV, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, FIELDS, delimiter='\t', lineterminator='\n')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in FIELDS})


def cmd_extract():
    old = load()
    rows = []
    for r in scan():
        prev = old.get(r['id'], {})
        for k in ('english', 'src', 'note'):
            if prev.get(k):
                r[k] = prev[k]
        rows.append(r)
    save(rows)
    print(f'{len(rows)} UI strings in {TSV} ({sum(1 for r in rows if r.get("english"))} with English)')


def problems(rows, enc):
    for r in rows:
        if not r.get('english'):
            continue
        try:
            b = encode(r['english'], enc)
        except ValueError as ex:
            yield r, str(ex)
            continue
        if len(b) > int(r['max']):
            yield r, f'{len(b)} bytes > max {r["max"]}'


def cmd_check():
    rows = list(load().values())
    enc = encoder()
    bad = list(problems(rows, enc))
    print(f'{sum(1 for r in rows if r.get("english"))}/{len(rows)} translated, {len(bad)} problems')
    for r, why in bad:
        print(f'  {r["id"]} {r["japanese"]!r} -> {r["english"]!r}: {why}')


def cmd_insert():
    rows = list(load().values())
    enc = encoder()
    files = {}
    out_dir = os.path.join(HERE, 'build', 'Disc1')
    os.makedirs(out_dir, exist_ok=True)
    skipped = {r['id'] for r, why in problems(rows, enc)}
    n = 0
    for r in rows:
        if not r.get('english') or r['id'] in skipped:
            continue
        f = r['file']
        if f not in files:
            built = os.path.join(out_dir, f)
            files[f] = bytearray(open(built if os.path.exists(built) else os.path.join(HERE, 'Disc1', f), 'rb').read())
        d, off, mx = files[f], int(r['offset'], 16), int(r['max'])
        b = encode(r['english'], enc)
        if r['kind'] == 'rec':
            d[off:off + mx] = b + bytes([SPACE]) * (mx - len(b))
        else:
            d[off:off + mx + 1] = b + b'\xff' + bytes(mx - len(b))
        n += 1
    for f, d in files.items():
        open(os.path.join(out_dir, f), 'wb').write(bytes(d))
    # Redraw every Latin glyph (digits, A-Z, a-z, apostrophe) with the upright font8_en designs;
    # letters the game lacks go into the kana slots listed in EXTRA.
    font = bytearray(open(os.path.join(HERE, 'Disc1', 'FONT8.2D'), 'rb').read())
    # FONT8 holds two sets: tiles 0x100+ (clear background: field panels) and tiles 0x00+ (drawn over the
    # menu window texture: Load/Save, Unit, Item menus, bank 0). Set 0 glyphs reuse the texture of its
    # space tile (0xEB) as background.
    space0 = font[FONT8_CHARS + 0xEB * 64:FONT8_CHARS + 0xEC * 64]
    for ch in f8.ALL:
        for bank in (0x100, 0x000):
            tile = bank + enc[ch]
            for y, row in enumerate(f8.bitmap(ch)):
                for x, px in enumerate(row):
                    bg = 0 if bank else space0[y * 8 + x]
                    font[FONT8_CHARS + tile * 64 + y * 8 + x] = INK if px else bg
    open(os.path.join(out_dir, 'FONT8.2D'), 'wb').write(bytes(font))
    print(f'inserted {n} UI strings into {", ".join(sorted(files))}; FONT8.2D: {len(f8.ALL)} upright Latin glyphs; '
          f'{len(skipped)} skipped (see check)')


if __name__ == '__main__':
    {'extract': cmd_extract, 'insert': cmd_insert, 'check': cmd_check}[sys.argv[1]]()
