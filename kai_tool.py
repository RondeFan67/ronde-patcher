# KAI.BIN: demon conversation scripts (talking to demons in battle). The file is one continuous script:
# #T text, #S/#W choice menus, #J 24-bit relative jumps (target = address of the argument bytes + offset),
# #C conditions, and more codes than the dialogue files (ARG below). Jumps cross between conversations and the
# game enters the script at fixed offsets, so NOTHING may move: every #T line is rewritten in place and padded
# with blank tiles to its original byte length. An English line can therefore hold 2 letters per Japanese glyph,
# and must keep the same inline variables ({V4D:01} = amount of G, {V4D:02} = MAG, {V4E:..} = names).
#
#   python kai_tool.py extract     (re)build kai_strings.tsv, keeping English already written
#   python kai_tool.py check       lines that are too long / unencodable / have the wrong variables
#   python kai_tool.py insert      write build/Disc1/KAI.BIN
#
# kai_strings.tsv: id (offset of the #T), msg (offset of the line that starts its message), cap (letters that
# fit), japanese, english, src (who translated it), note.
import csv
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ronde_text as rt  # noqa: E402
import font_en as fe  # noqa: E402

SRC = os.path.join(HERE, 'Disc1', 'KAI.BIN')
OUT = os.path.join(HERE, 'build', 'Disc1', 'KAI.BIN')
TSV = os.path.join(HERE, 'kai_strings.tsv')
FIELDS = ['id', 'msg', 'cap', 'japanese', 'english', 'src', 'note']
ARG = {'A': 1, 'C': 1, 'D': 1, 'E': 1, 'I': 1, 'M': 1, 'O': 1, 'P': 1, 'S': 1, 'W': 1, 'Z': 1, 'Y': 2,
       'J': 3, 'U': 3, 'F': 0, 'H': 0, 'K': 0, 'Q': 0, 'V': 0}
SPACE = 1    # glyph code of a blank tile
VAR_RE = r'\{V[0-9A-F]{2}:[0-9A-F]{2}\}'


def parse(data):
    """Walk the whole script. Returns [(offset, glyph list)] for every #T run; raises on anything unknown."""
    runs, i = [], 0
    while i < len(data):
        if data[i] == 0:                       # padding between conversations
            i += 1
            continue
        if data[i] != 0x23 or i + 1 >= len(data):
            # stray glyph data without a #T (e.g. 0x3AD70: blank tiles after a #H); left as it is
            j = data.find(b'#', i)
            i = len(data) if j < 0 else j
            continue
        c = chr(data[i + 1])
        if c == 'T':
            start, j, glyphs = i, i + 2, []
            while True:
                if data[j] == 0xFF:
                    glyphs.append(rt.VAR | data[j + 1] << 8 | data[j + 2])
                    j += 3
                    continue
                (g,) = struct.unpack_from('>H', data, j)
                j += 2
                if g == 0:
                    break
                glyphs.append(g - 1)
            runs.append((start, glyphs, j - start))
            i = j
        elif c in ARG:
            i += 2 + ARG[c]
        else:
            raise ValueError(f'unknown code #{c} at {i:#x}')
    return runs


def message_starts(data, runs):
    """Offset of the first #T of each message (a message ends at #Q / #K / a choice menu)."""
    out, cur, prev_end = {}, None, None
    for off, g, n in runs:
        between = data[prev_end:off] if prev_end is not None else b'#Q'
        if cur is None or any(code in between for code in (b'#Q', b'#K', b'#W', b'#J', b'#S')):
            cur = off
        out[off] = cur
        prev_end = off + n
    return out


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
    data = open(SRC, 'rb').read()
    table = rt.load_table(os.path.join(HERE, 'font16.tbl'))
    runs = parse(data)
    starts = message_starts(data, runs)
    old = load()
    rows = []
    for off, glyphs, n in runs:
        rid = f'{off:05X}'
        r = dict(id=rid, msg=f'{starts[off]:05X}', cap=str(capacity(glyphs)),
                 japanese=rt.glyph_text(glyphs, table))
        for k in ('english', 'src', 'note'):
            r[k] = old.get(rid, {}).get(k, '')
        rows.append(r)
    save(rows)
    print(f'{len(rows)} lines, {len({r["japanese"] for r in rows})} distinct, '
          f'{sum(1 for r in rows if r["english"])} with English -> {TSV}')


def capacity(glyphs):
    """Letters that fit: 2 per glyph slot, not counting the variables (they are kept as they are)."""
    return 2 * sum(1 for g in glyphs if not g & rt.VAR)


def encode(line, orig_len, glyphs):
    """English line -> #T run of exactly orig_len bytes (blank-tile padding)."""
    want_vars = [f'{{V{(g >> 8) & 0xFF:02X}:{g & 0xFF:02X}}}' for g in glyphs if g & rt.VAR]
    if re.findall(VAR_RE, line) != want_vars:
        raise ValueError(f'variables must be {want_vars}')
    out = bytearray(b'#T')
    for part in re.split(f'({VAR_RE})', fe.normalize(line)):
        m = re.fullmatch(r'\{V([0-9A-F]{2}):([0-9A-F]{2})\}', part)
        if m:
            out += bytes((0xFF, int(m[1], 16), int(m[2], 16)))
            continue
        for pair in fe.pairs_of(part) if part else []:
            for ch in pair:
                if ch not in fe.GLYPHS:
                    raise ValueError(f'no glyph for {ch!r}')
            out += struct.pack('>H', fe.pair_code(pair))
    pad = orig_len - 2 - len(out)    # room left before the 0000 terminator
    if pad < 0 or pad % 2:
        raise ValueError(f'too long by {-pad // 2 * 2 if pad < 0 else 1} bytes')
    out += struct.pack('>H', SPACE) * (pad // 2) + b'\0\0'
    return bytes(out)


def cmd_check(insert=False):
    data = bytearray(open(SRC, 'rb').read())
    runs = {f'{off:05X}': (off, g, n) for off, g, n in parse(bytes(data))}
    ok, bad = 0, []
    for r in load().values():
        if not r['english']:
            continue
        off, glyphs, n = runs[r['id']]
        try:
            data[off:off + n] = encode(r['english'], n, glyphs)
            ok += 1
        except ValueError as ex:
            bad.append((r, str(ex)))
    print(f'{ok} lines ok, {len(bad)} problems')
    shown = set()
    for r, why in bad:
        if (r['japanese'], r['english']) not in shown:   # identical lines share one translation: show once
            shown.add((r['japanese'], r['english']))
            print(f'  {r["id"]} cap {r["cap"]} {r["japanese"]} -> {r["english"]!r}: {why}')
    if insert:
        assert len(parse(bytes(data))) == len(runs)   # still parses the same way
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        open(OUT, 'wb').write(bytes(data))
        print('written', OUT)


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'extract':
        cmd_extract()
    else:
        cmd_check(insert=(cmd == 'insert'))
