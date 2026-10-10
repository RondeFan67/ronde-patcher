# System / menu messages in the big FONT16 dialogue encoding (#T ... #Q) embedded in program files
# (0.BIN, WORLD.BIN, REMIX.BIN). English is written IN PLACE: same codes, each #T line replaced, the
# message must not grow (English letter pairs need ~half the bytes), leftover bytes are zero-filled,
# so no pointers change.
#
#   python sys_tool.py extract     (re)build sys_strings.tsv, keeping English already written
#   python sys_tool.py check       missing / too long / unencodable
#   python sys_tool.py insert      write into build/Disc1/<file> (+ FONT16.BIN letter pairs)
#
# sys_strings.tsv: id, file, offset, max (bytes incl. #Q), lines (number of #T runs), japanese, english, src, note
# English: one line per #T run, separated by ' / ' (e.g. "Is this OK? / Yes / No").
import csv
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ronde_text as rt  # noqa: E402
import font_en as fe  # noqa: E402
import insert_event as ie  # noqa: E402

TSV = os.path.join(HERE, 'sys_strings.tsv')
FIELDS = ['id', 'file', 'offset', 'max', 'lines', 'japanese', 'english', 'src', 'note']
FILES = ['0.BIN', 'WORLD.BIN', 'REMIX.BIN', 'I_HELP.BIN', 'M_HELP.BIN', 'FIGHT.BIN', 'STITLE.BIN', 'STITLE2.BIN',
         'DEADMSG.BIN', 'SMAP.BIN']   # KAI.BIN has its own tool (kai_tool.py)
MAX_TILE = 0x402


def scan_file(data):
    """Yield (offset, bytes) of every well-formed #T...#Q message in a program file."""
    i = data.find(b'#T')
    seen = set()
    while i >= 0:
        # back up over control codes that open the message (#O/#U/#A ... right before the first #T)
        start = i
        q = data.find(b'#Q', i)
        if q < 0:
            break
        msg = data[start:q + 2]
        ok = len(msg) < 600 and start not in seen
        if ok:
            items = list(rt.parse_block(msg))
            ok = (all(it[0] != 'raw' for it in items) and items and items[-1][0] == 'code' and items[-1][1] == 'Q'
                  and any(it[0] == 'text' and it[2] for it in items)
                  and all(g <= MAX_TILE or g & rt.VAR for it in items if it[0] == 'text' for g in it[2]))
        if ok:
            seen.add(start)
            yield start, msg
            i = data.find(b'#T', q + 2)
        else:
            i = data.find(b'#T', i + 2)


def text_key(jp):
    """'{T}a {T}b {S 02} {Q}' -> 'a|b': the #T runs of an extracted message, used to match translations."""
    runs = re.findall(r'\{T\}(.*?)(?= \{|$)', jp)
    return '|'.join(r.replace('　', '').strip() for r in runs)   # blank tiles don't matter for matching


def describe(msg, table):
    return ' '.join(rt.item_text(it, table) for it in rt.parse_block(msg))


def scan():
    table = rt.load_table(os.path.join(HERE, 'font16.tbl'))
    for f in FILES:
        data = open(os.path.join(HERE, 'Disc1', f), 'rb').read()
        for off, msg in scan_file(data):
            runs = sum(1 for it in rt.parse_block(msg) if it[0] == 'text')
            yield dict(id=f'{f}:{off:05X}', file=f, offset=f'{off:05X}', max=str(len(msg)), lines=str(runs),
                       japanese=describe(msg, table))


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


def build(orig, english, alloc):
    """Rebuild a message: same codes, #T runs replaced by the English lines."""
    lines = ['' if l.strip() == '~' else l.strip() for l in fe.normalize(english).split(' / ')]   # '~' = empty #T line
    items = list(rt.parse_block(orig))
    runs = [it for it in items if it[0] == 'text']
    if len(lines) != len(runs):
        raise ValueError(f'{len(lines)} English lines for {len(runs)} #T runs')
    out = bytearray()
    k = 0
    for it in items:
        if it[0] == 'code':
            out += b'#' + it[1].encode() + it[2]
            continue
        line = lines[k]
        k += 1
        lead = 0
        while lead < len(it[2]) and it[2][lead] == 0:
            lead += 1
        trail = 0
        while trail < len(it[2]) - lead and it[2][len(it[2]) - 1 - trail] == 0:
            trail += 1
        if lead and trail and line:   # centred in the original: centre the English in the same width
            lead = max(0, (len(it[2]) - len(fe.pairs_of(line))) // 2)
        out += b'#T' + struct.pack('>H', ie.SPACE_CODE) * lead
        # {V58:00} in the English = inline variable FF 58 00 (amount / item name / stage number)
        for part in re.split(r'(\{V[0-9A-F]{2}:[0-9A-F]{2}\})', line):
            m = re.fullmatch(r'\{V([0-9A-F]{2}):([0-9A-F]{2})\}', part)
            if m:
                out += bytes((0xFF, int(m[1], 16), int(m[2], 16)))
                continue
            for pair in fe.pairs_of(part) if part else []:
                for ch in pair:
                    if ch not in fe.GLYPHS:
                        raise ValueError(f'no glyph for {ch!r}')
                out += struct.pack('>H', alloc.code(pair))
        out += b'\0\0'
    return bytes(out)


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
    from collections import Counter
    print(f'{len(rows)} messages in {TSV}:', dict(Counter(r['file'] for r in rows)),
          f'({sum(1 for r in rows if r.get("english"))} with English)')


def cmd_check(insert=False):
    rows = list(load().values())
    table = rt.load_table(os.path.join(HERE, 'font16.tbl'))
    alloc = ie.TileAllocator(table)
    files, bad, n = {}, [], 0
    out_dir = os.path.join(HERE, 'build', 'Disc1')
    for r in rows:
        if not r.get('english'):
            continue
        f = r['file']
        if f not in files:
            built = os.path.join(out_dir, f)
            files[f] = bytearray(open(built if os.path.exists(built) else os.path.join(HERE, 'Disc1', f), 'rb').read())
        off, mx = int(r['offset'], 16), int(r['max'])
        orig = open(os.path.join(HERE, 'Disc1', f), 'rb').read()[off:off + mx]
        try:
            new = build(orig, r['english'], alloc)
        except ValueError as ex:
            bad.append((r, str(ex)))
            continue
        if len(new) > mx:
            bad.append((r, f'{len(new)} bytes > {mx}'))
            continue
        files[f][off:off + mx] = new + bytes(mx - len(new))
        n += 1
    print(f'{n} messages ok, {len(bad)} problems')
    for r, why in bad:
        print(f'  {r["id"]} {r["english"]!r}: {why}')
    if insert:
        os.makedirs(out_dir, exist_ok=True)
        for f, d in files.items():
            open(os.path.join(out_dir, f), 'wb').write(bytes(d))
        font = bytearray(open(os.path.join(HERE, 'Disc1', 'FONT16.BIN'), 'rb').read())
        fe.install_half_font(font)   # letter pairs are composed at run time (patch_code.py)
        open(os.path.join(out_dir, 'FONT16.BIN'), 'wb').write(bytes(font))
        alloc.save()
        print('written:', ', '.join(sorted(files)), '+ FONT16.BIN;', len(alloc.map), 'letter-pair tiles in use')


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'extract':
        cmd_extract()
    else:
        cmd_check(insert=(cmd == 'insert'))
