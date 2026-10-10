# Insert English from mapping.json into MSG*.BIN files (0x800-byte blocks, one dialogue box sequence each).
#
#   python insert_msg.py MSG01            build build/Disc1/MSG01.BIN (+ FONT16.BIN with all bigram tiles)
#   python insert_msg.py all              every Disc 1 MSG file that has English
#   python insert_msg.py MSG01 --preview  also print the English pages of every block
#
# Each block keeps its control codes; text runs are rebuilt. A block may have several speaker sections
# (e.g. "...#H #U #E <name> ..."); English lines starting with "<Name>:" switch to the next section.
# Every English line starts a new page, as the Japanese does for system messages.
import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ronde_text as rt  # noqa: E402
import layout  # noqa: E402
import font_en as fe  # noqa: E402
import insert_event as ie  # noqa: E402

# SMAP.BIN holds an (offset, length) table per MSG file; the game reads only `length` bytes of a block,
# so every rebuilt block's length must be written there (otherwise the text turns to garbage at the old length).
MAX_MESSAGE = 543     # longest original message on disc 1; the game's read buffer is known to cope with it
SPEAKER_LINES = 2     # name line + 2 text lines per box
MSG_LINE_CHARS = 26   # battle boxes: 13 tiles + room for the wait cursor before the portrait / window edge
FULL_LINE_CHARS = 34  # no portrait showing: 17 of the window's 18 cells (the wait cursor takes the next cell)
NARRATION_LINES = 3   # no name line
PORTRAIT_GLYPHS = 14  # Japanese lines in a box with a portrait are at most this wide (13 + wait cursor room)


# One-block files whose single (0, length) record appears several times in SMAP.BIN. MSG44 and MSG45 hold the
# same line (Saturday exercises), so their two adjacent records get the same new length either way round.
KNOWN_TABLES = {'MSG44.BIN': 0x51434, 'MSG45.BIN': 0x5143C}


def block_lengths(msg):
    lens = []
    for k in range(len(msg) // rt.BLOCK_SIZE):
        q = msg[k * rt.BLOCK_SIZE:(k + 1) * rt.BLOCK_SIZE].find(b'#Q')
        lens.append(q + 2 if q >= 0 else 0)
    return lens


def find_length_table(smap, msg):
    """Offset of the (offset, length) table for this MSG file in SMAP.BIN, or None."""
    want = b''.join(struct.pack('>II', k * rt.BLOCK_SIZE, l) for k, l in enumerate(block_lengths(msg)))
    i = smap.find(want)
    return i if i >= 0 and smap.find(want, i + 1) < 0 else None


def length_records(smap, msg, name):
    """{block number: SMAP.BIN offset of its (offset, length) record}, or None if the table can't be pinned down.
    Tables are indexed by message id, not block, and may hold dummy (offset, 0) records (MSG14 record 34)."""
    lens = block_lengths(msg)
    at = find_length_table(smap, msg)
    if at is not None:
        return {k: at + 8 * k for k in range(len(lens))}
    if name in KNOWN_TABLES:
        at = KNOWN_TABLES[name]
        return {0: at} if len(lens) == 1 and struct.unpack_from('>II', smap, at) == (0, lens[0]) else None
    need = {k for k, l in enumerate(lens) if l}
    starts = []
    i = smap.find(struct.pack('>II', 0, lens[0]))
    while i >= 0:
        starts.append(i)
        i = smap.find(struct.pack('>II', 0, lens[0]), i + 1)
    found = []
    for at in starts:
        recs, k, p = {}, 0, at
        while p + 8 <= len(smap) and k < len(lens):
            o, l = struct.unpack_from('>II', smap, p)
            blk = msg[k * rt.BLOCK_SIZE:(k + 1) * rt.BLOCK_SIZE]
            # a block may go on past its first #Q (MSG20 block 5, MSG21 block 1): the record then covers the
            # following bytes too (MSG21: '#Z 9C #Q'; MSG20: leftover digit tiles); they are kept as they are
            if o == k * rt.BLOCK_SIZE and lens[k] <= l <= rt.BLOCK_SIZE and (l == lens[k] or any(blk[lens[k]:l])):
                recs[k] = p
                k += 1
            elif l != 0:                             # (offset, 0) = dummy record for an unused message id
                break
            p += 8
        if need <= set(recs):
            found.append(recs)
    return found[0] if len(found) == 1 else None


def sections(items, table):
    """Split a parsed block into prefix codes, speaker sections and suffix codes."""
    texts = [i for i, it in enumerate(items) if it[0] == 'text']
    first, last = texts[0], texts[-1]

    def indent(i):
        """Leading blank glyphs (tile 0). Windows with the portrait on the left (#A 02) indent every line by 4."""
        g = items[i][2]
        k = 0
        while k < len(g) and g[k] == 0:
            k += 1
        return k

    def stripped(i):
        return rt.glyph_text(items[i][2][indent(i):], table)

    def is_speaker(i):
        if items[i][0] != 'text' or len(items[i][2]) - indent(i) > 10:
            return False
        nxt = i + 1 < len(items) and items[i + 1][0] == 'text' and stripped(i + 1).startswith('「')
        return nxt and not stripped(i).startswith('「')

    secs = []
    lead = []
    for i in range(first, last + 1):
        it = items[i]
        if it[0] == 'text':
            if is_speaker(i) or not secs:
                secs.append({'lead': lead, 'speaker': stripped(i) if is_speaker(i) else None, 'indent': indent(i)})
            lead = []   # codes before a continuation line are this section's own page breaks
        else:
            lead.append(it)
    return items[:first], secs, items[last + 1:]


def split_english(en, secs, names):
    """Assign English lines to speaker sections. Returns list of line lists, or raises."""
    paras = [p.strip() for p in fe.normalize(en).split('\n') if p.strip()]
    if len(secs) == 1:
        return [paras]
    out = [[] for _ in secs]
    k = 0
    for p in paras:
        m = re.match(r'^([A-Za-z][\w .-]{0,20}):\s*(.*)$', p)
        if m and k + 1 < len(secs) and names.get(secs[k + 1]['speaker']) == m.group(1):
            k += 1
            p = m.group(2).strip().strip('"')
        out[k].append(p)
    if any(not o for o in out):
        raise ValueError(f'could not match English lines to {len(secs)} speaker sections')
    return out


def build_block(orig, en, names, table, alloc):
    items = list(rt.parse_block(orig))
    prefix, secs, suffix = sections(items, table)
    for s in secs:
        if any(c[1] not in 'HUEOAZYK' for c in s['lead']):
            raise ValueError('unexpected codes between sections: ' + ' '.join(rt.item_text(c, table) for c in s['lead']))
    groups = split_english(en, secs, names)
    out = bytearray()
    pages_txt = []

    def code(it):
        out.extend(b'#' + it[1].encode() + it[2])

    def text(line, indent=0):
        out.extend(b'#T')
        out.extend(struct.pack('>H', ie.SPACE_CODE) * indent)
        for pair in fe.pairs_of(line):
            for ch in pair:
                if ch not in fe.GLYPHS:
                    raise ValueError(f'no glyph for {ch!r} in {line!r}')
            out.extend(struct.pack('>H', alloc.code(pair)))
        out.extend(b'\0\0')

    portrait = False   # {U 01 xx 00} shows a portrait, {U 03 00 00} removes it
    # A portrait shown by an earlier block stays up (MSG02 18-22: Charlie, no #U in the block), so also infer it
    # from the Japanese: lines of a portrait box never pass PORTRAIT_GLYPHS (not counting the #A 02 indent).
    widest = max((len(it[2]) - next((k for k, g in enumerate(it[2]) if g != 0), len(it[2]))
                  for it in items if it[0] == 'text'), default=0)
    if widest <= PORTRAIT_GLYPHS:
        portrait = True

    def track(it):
        nonlocal portrait
        if it[0] == 'code' and it[1] == 'U':
            portrait = {1: True, 3: False}.get(it[2][0], portrait)

    for it in prefix:
        code(it)
        track(it)
    for k, (s, paras) in enumerate(zip(secs, groups)):
        for it in s['lead']:
            code(it)
            track(it)
        width = MSG_LINE_CHARS if portrait else FULL_LINE_CHARS - 2 * s['indent']
        if s['speaker']:
            if s['speaker'] not in names:
                raise ValueError(f'no English name for speaker {s["speaker"]}')
            text('[' + names[s['speaker']] + ']', s['indent'])
        # name + 2 lines on the first page, 3 lines on later pages; sentence-aware breaks (layout.py)
        pages = layout.paginate(paras, width, SPEAKER_LINES if s['speaker'] else NARRATION_LINES,
                                NARRATION_LINES)
        for j, page in enumerate(pages):
            if j:
                out.extend(b'#H')
            for line in page:
                text(line, s['indent'])
        pages_txt.append((names.get(s['speaker']), pages))
    for it in suffix:
        code(it)
    if len(out) > rt.BLOCK_SIZE:
        raise ValueError(f'block too long: {len(out)} bytes')
    return bytes(out), pages_txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file', help='e.g. MSG01, or all')
    ap.add_argument('--disc', default='D1')
    ap.add_argument('--preview', action='store_true')
    args = ap.parse_args()
    src_dir = os.path.join(HERE, 'Disc1' if args.disc == 'D1' else 'Disc2')
    mapping = json.load(open(os.path.join(HERE, 'mapping.json'), encoding='utf-8'))
    if args.file.lower() == 'all':
        # every MSG file with English (MSG24/MSG28 are empty and have no length table)
        names = [f for f in sorted(os.listdir(src_dir)) if re.fullmatch(r'MSG\d+\.BIN', f)
                 and any(k.startswith(f'{args.disc}/{f}:') and e.get('en') and e.get('status') != 'skip'
                         for k, e in mapping.items())]
    else:
        names = [args.file.upper().removesuffix('.BIN') + '.BIN']
    for name in names:
        insert_file(name, args, mapping)


def insert_file(name, args, mapping):
    src_dir = os.path.join(HERE, 'Disc1' if args.disc == 'D1' else 'Disc2')
    out_dir = os.path.join(HERE, 'build', 'Disc1' if args.disc == 'D1' else 'Disc2')
    table = rt.load_table(os.path.join(HERE, 'font16.tbl'))
    names = ie.load_names()
    alloc = ie.TileAllocator(table)
    data = bytearray(open(os.path.join(src_dir, name), 'rb').read())
    smap_out = os.path.join(out_dir, 'SMAP.BIN')
    smap = bytearray(open(smap_out if os.path.exists(smap_out) else os.path.join(src_dir, 'SMAP.BIN'), 'rb').read())
    smap_orig = open(os.path.join(src_dir, 'SMAP.BIN'), 'rb').read()
    records = length_records(smap_orig, bytes(data), name)
    if records is None:
        print(f'{name}: NOT INSERTED - no message length table in SMAP.BIN, not safe to insert')
        return
    done, kept, errors = 0, 0, []
    for n, off, b in rt.units(os.path.join(src_dir, name)):
        e = mapping.get(f'{args.disc}/{name}:{n}', {})
        if not e.get('en') or e.get('status') == 'skip':
            kept += 1
            continue
        try:
            new, pages = build_block(b, e['en'], names, table, alloc)
        except ValueError as ex:
            errors.append(f'block {n}: {ex}')
            kept += 1
            continue
        if len(new) > MAX_MESSAGE:
            errors.append(f'block {n}: {len(new)} bytes is longer than the longest original message ({MAX_MESSAGE})')
            kept += 1
            continue
        rec = records.get(n)
        rec_off, rec_len = struct.unpack_from('>II', smap_orig, rec) if rec is not None else (None, 0)
        if rec is None or rec_off != off or rec_len < b.find(b'#Q') + 2:
            errors.append(f'block {n}: SMAP record does not hold the original offset/length')
            kept += 1
            continue
        new += b[b.find(b'#Q') + 2:rec_len]   # keep any segment after the first #Q that the record covers
        data[off:off + rt.BLOCK_SIZE] = new + bytes(rt.BLOCK_SIZE - len(new))
        struct.pack_into('>I', smap, rec + 4, len(new))   # the game reads only this many bytes of the block
        done += 1
        if args.preview:
            print(f'--- block {n}')
            for who, pg in pages:
                for page in pg:
                    print(f'  [{who or "-"}] ' + ' / '.join(page))
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, name), 'wb').write(bytes(data))
    open(smap_out, 'wb').write(bytes(smap))
    font = bytearray(open(os.path.join(HERE, 'Disc1', 'FONT16.BIN'), 'rb').read())
    fe.install_half_font(font)   # letter pairs are composed at run time (patch_code.py)
    open(os.path.join(HERE, 'build', 'Disc1', 'FONT16.BIN'), 'wb').write(bytes(font))
    alloc.save()
    print(f'{name}: {done} blocks in English, {kept} left as they were; {len(alloc.map)} bigram tiles in use')
    for err in errors:
        print('  NOT INSERTED', err)


if __name__ == '__main__':
    main()
