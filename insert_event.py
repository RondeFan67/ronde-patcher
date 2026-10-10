# Insert English text from mapping.json into EVENT.BIN and draw the needed bigram tiles into FONT16.BIN.
#
#   python insert_event.py 1-16            insert EVENT messages 1..16 (Disc 1 files)
#   python insert_event.py all             insert every EVENT message that has English (the normal build)
#   python insert_event.py all --end       Disc 2 END.BIN -> build/Disc2/END.BIN
#
# The text region is full (68,534 bytes, globals right after it): padding is dropped before messages that have
# a pointer, and developer dummy messages (DUMMIES) are shrunk. Messages with codes between text runs (#K pause,
# #S choice menu) take English parts separated by '|' (build_segments); #J jumps in choice menus are re-aimed.
#
# Output goes to build/Disc1/{EVENT.BIN,FONT16.BIN}. Tile allocation (letter pair -> font tile)
# is kept in en_tiles.json so later builds reuse the same tiles.
import json
import os
import struct
import sys
import textwrap
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ronde_text as rt  # noqa: E402
import layout  # noqa: E402
import font_en as fe  # noqa: E402

SRC = os.path.join(HERE, 'Disc1')
OUT = os.path.join(HERE, 'build', 'Disc1')
TILES_FILE = os.path.join(HERE, 'en_tiles.json')
LINE_CHARS = 34           # 17 of the 18 tiles: on a full last line the wait cursor wraps onto the first letter
                          # (seen on EVENT 5 "opens"); same rule as insert_msg FULL_LINE_CHARS
# Windows with a portrait on the left (e.g. the tutorials) show only 15 tiles; the Japanese then never has a
# line over 15 glyphs. The portrait comes from the event data, so the width is inferred from the Japanese.
PORTRAIT_GLYPHS = 15
PORTRAIT_LINE_CHARS = 28  # 14 tiles: the wait cursor needs the 15th


def line_chars(items):
    """Portrait window if the Japanese fits one: 15 glyphs, or 16 on a line that does not end a page (only the
    last line of a page needs the wait-cursor column). The 16 case only counts without a speaker line: the
    tutorials and demon farewells have none, story dialogue with an occasional 16-glyph line is a wide window."""
    pages, cur = [], []
    for kind, a, g in items:
        if kind == 'text':
            cur.append(len(g))
        elif a == 'H' and cur:
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    widest = max((w for p in pages for w in p), default=0)
    if widest <= PORTRAIT_GLYPHS:
        return PORTRAIT_LINE_CHARS
    if all(max(p) <= PORTRAIT_GLYPHS + 1 and p[-1] <= PORTRAIT_GLYPHS for p in pages) and not has_speaker(items):
        return PORTRAIT_LINE_CHARS
    return LINE_CHARS


def has_speaker(items):
    t = [g for kind, _, g in items if kind == 'text']
    if len(t) < 2:
        return False
    table = _table()
    return looks_like_name(rt.glyph_text(t[0], table)) and rt.glyph_text(t[1], table).startswith('「')


def _table(cache=[]):
    if not cache:
        cache.append(rt.load_table(os.path.join(HERE, 'font16.tbl')))
    return cache[0]
LINES_PER_PAGE = 2        # dialogue box: name line + 2 text lines
NARRATION_LINES = 3
SPACE_CODE = 1            # glyph code 1 = blank tile 0
FIRST_KANJI_TILE = 0xDA
PROTECTED = set(range(0x385, 0x387)) | set(range(0x3EB, 0x3F4))  # ♪♡ and STR..MD stat tiles
# Font slots 0x380-0x3BF and 0x3E0+ are (almost) never used by battle text; the battle scene seems to
# reuse that part of the font's RAM, so English pairs placed there show garbage.
PROTECTED |= set(range(0x380, 0x3C0)) | set(range(0x3E0, 0x403))


# Developer dummy messages (text ダミー / 未使用 "unused", speaker カシウス（ダミー）). None has a pointer, so the game
# never shows them; they are shrunk to their control codes and one blank glyph to free text-region space.
DUMMIES = {233, 234, 264, 265, 266, 267, 268, 269, 270, 363, 364, 365, 434, 435, 436, 452, 453, 454}


def shrink_dummy(orig):
    out = bytearray()
    blank = False
    for kind, a, c in rt.parse_block(orig):
        if kind == 'text':
            if not blank:
                out.extend(b'#T' + struct.pack('>H', SPACE_CODE) + b'\0\0')
                blank = True
        elif kind == 'code':
            out.extend(b'#' + a.encode() + c)
    return bytes(out)


def load_names():
    names = {}
    with open(os.path.join(HERE, 'names.tsv'), encoding='utf-8') as f:
        for line in f:
            if '\t' in line:
                jp, en = line.rstrip('\n').split('\t')
                names[jp] = en
    return names


def tile_usage(table):
    """How often each font tile is used across all game text (to pick tiles to overwrite)."""
    use = Counter()
    paths = [os.path.join(HERE, 'Disc1', f) for f in os.listdir(SRC) if f.startswith('MSG') or f == 'EVENT.BIN']
    paths += [os.path.join(HERE, 'Disc2', f) for f in os.listdir(os.path.join(HERE, 'Disc2'))
              if f.startswith('MSG') or f in ('DEADMSG.BIN', 'END.BIN')]
    for p in paths:
        for _, _, b in rt.units(p):
            for kind, _, g in rt.parse_block(b):
                if kind == 'text':
                    use.update(g)
    return use


class TileAllocator:
    """Glyph codes for English letter pairs. Pairs are now composed at run time by the patched
    font16_decode_glyph (patch_code.py), so no font slots are allocated; `map` stays empty."""

    def __init__(self, table):
        self.map = {}
        self.use = tile_usage(table)

    def code(self, pair):
        return fe.pair_code(pair)

    def save(self):
        pass


def wrap(text, width):
    lines = []
    for para in text.split('\n'):
        lines += textwrap.wrap(para, width, break_long_words=True) or ['']
    return lines


def looks_like_name(text):
    """A speaker line: short, no sentence punctuation (tutorial lines such as 'それと「レベルアップ」と' are
    followed by a line starting with 「 too)."""
    return len(text) <= 12 and not text.startswith('・') and not any(c in text for c in '「」、。！')


def build_message(orig, en, names, table, alloc):
    """Return new message bytes: original control codes kept, text runs replaced."""
    items = list(rt.parse_block(orig))
    texts = [i for i, it in enumerate(items) if it[0] == 'text']
    first, last = texts[0], texts[-1]
    middle = [it for it in items[first:last + 1] if it[0] != 'text']
    if any(it[1] != 'H' for it in middle):
        return build_segments(items, first, last, en, names, table, alloc)
    speaker = None
    first_text = rt.glyph_text(items[first][2], table)
    if len(texts) > 1 and looks_like_name(first_text):
        second = rt.glyph_text(items[texts[1]][2], table)
        if second.startswith('「'):
            speaker = first_text
    en = fe.normalize(en)
    # name + 2 lines on the first page, 3 on later pages; sentence-aware breaks (layout.py)
    pages = layout.paginate(en.split('\n'), line_chars(items), LINES_PER_PAGE if speaker else NARRATION_LINES,
                            NARRATION_LINES)
    out = bytearray()

    def code(it):
        out.extend(b'#' + it[1].encode() + it[2])

    def text(line):
        out.extend(b'#T')
        for pair in fe.pairs_of(line):
            for ch in pair:
                if ch not in fe.GLYPHS:
                    raise ValueError(f'no glyph for {ch!r} in {line!r}')
            out.extend(struct.pack('>H', alloc.code(pair)))
        out.extend(b'\0\0')

    for it in items[:first]:
        code(it)
    if speaker:
        if speaker not in names:
            raise ValueError(f'no English name for speaker {speaker}')
        text('[' + names[speaker] + ']')
    for i, page in enumerate(pages):
        if i:
            out.extend(b'#H')
        for line in page:
            text(line)
    for it in items[last + 1:]:
        code(it)
    return bytes(out)


def code_offsets(msg):
    """[(offset, code letter)] for every control code in a message, in order (#T runs skipped)."""
    out, i = [], 0
    for kind, a, c in rt.parse_block(msg):
        if kind == 'text':
            j = i + 2
            while msg[j:j + 2] != b'\0\0':
                j += 3 if msg[j] == 0xFF else 2
            i = j + 2
        else:
            out.append((i, a))
            i += 2 + len(c)
    return out


def fix_jumps(orig, new):
    """#J 00 nnnn jumps to (address of its argument bytes) + nnnn (choice menus 475/511: 'yes' goes to a code
    inside the message, 'no' to the next message). Re-aim each jump at the same control code in the rebuilt
    message, or past its end. #H codes are regenerated, so they are not counted."""
    oc = [(o, a) for o, a in code_offsets(orig) if a != 'H']
    nc = [(o, a) for o, a in code_offsets(new) if a != 'H']
    if [a for _, a in oc] != [a for _, a in nc]:
        raise ValueError('control codes changed; cannot re-aim #J jumps')
    out = bytearray(new)
    for (o, a), (p, _) in zip(oc, nc):
        if a != 'J':
            continue
        target = o + 2 + struct.unpack_from('>H', orig, o + 3)[0]
        k = [q for q, _ in oc].index(target) if target < len(orig) else None
        new_target = nc[k][0] if k is not None else len(new) + target - len(orig)
        struct.pack_into('>H', out, p + 3, new_target - (p + 2))
    return bytes(out)


def build_segments(items, first, last, en, names, table, alloc):
    """Messages with codes other than #H between text runs (#K pauses, a system line after dialogue, #S choice
    menus). The English gives one part per segment, separated by '|'. A segment after #S is a choice menu:
    one #T per English line, no pagination."""
    segs = [[[], []]]          # [lead codes, text items]
    for it in items[first:last + 1]:
        if it[0] == 'text':
            segs[-1][1].append(it)
        elif it[1] == 'H' and segs[-1][1]:
            segs[-1][1].append(it)
        else:
            if segs[-1][1]:
                segs.append([[], []])
            segs[-1][0].append(it)
    parts = fe.normalize(en).split('|')
    if len(parts) != len(segs):
        raise ValueError(f'English has {len(parts)} parts separated by | but the message has {len(segs)} segments')
    out = bytearray()

    def code(it):
        out.extend(b'#' + it[1].encode() + it[2])

    def text(line):
        out.extend(b'#T')
        for pair in fe.pairs_of(line):
            for ch in pair:
                if ch not in fe.GLYPHS:
                    raise ValueError(f'no glyph for {ch!r} in {line!r}')
            out.extend(struct.pack('>H', alloc.code(pair)))
        out.extend(b'\0\0')

    for it in items[:first]:
        code(it)
    for k, ((lead, runs), part) in enumerate(zip(segs, parts)):
        for it in lead:
            code(it)
        lines = [l.strip() for l in part.strip().split('\n') if l.strip()]
        if any(it[1] == 'S' for it in lead):
            for line in lines:
                text(line)
            continue
        texts = [r for r in runs if r[0] == 'text']
        speaker = None
        if k == 0 and len(texts) > 1:
            t0 = rt.glyph_text(texts[0][2], table)
            if looks_like_name(t0) and rt.glyph_text(texts[1][2], table).startswith('「'):
                speaker = t0
        if speaker:
            if speaker not in names:
                raise ValueError(f'no English name for speaker {speaker}')
            text('[' + names[speaker] + ']')
        pages = layout.paginate(lines, line_chars(items), LINES_PER_PAGE if speaker else NARRATION_LINES,
                                NARRATION_LINES)
        for i, page in enumerate(pages):
            if i:
                out.extend(b'#H')
            for line in page:
                text(line)
        if runs and runs[-1][0] == 'code' and runs[-1][1] == 'H':
            out.extend(b'#H')     # page break before the next segment's codes (EVENT 215: "...." #H #E 0C system line)
    for it in items[last + 1:]:
        code(it)
    return bytes(out)


def rebuild_event(data, new_msgs):
    """Repack the text region with replacements and fix every pointer to moved messages."""
    msgs = list(rt.messages_from_bytes(data))
    start = msgs[0][1]
    # The zeros after the text are NOT free: the code keeps global variables there
    # (0x289E4... in EVENT.BIN), so the region ends at the first referenced address after the text.
    text_end = msgs[-1][1] + len(msgs[-1][2])
    region_end = text_end
    while region_end < len(data) and data[region_end] == 0:
        region_end += 1
    B0 = rt.OVERLAY_BASE
    for i in range(0, len(data) - 3, 2):
        v = struct.unpack_from('>I', data, i)[0] - B0
        if text_end <= v < region_end:
            region_end = v
    B = rt.OVERLAY_BASE
    targets = {struct.unpack_from('>I', data, i)[0] - B for i in range(0, start - 3, 4)}
    text = bytearray()
    moves = {}
    prev_off = None
    for n, off, b in msgs:
        # Messages without a pointer are reached as "next message" after the previous one: keep their original
        # 4-byte alignment, and so does the message after one (it may continue the same chain). Other messages
        # need no padding (text is read byte-wise: the original has #T runs at odd addresses and messages
        # 476/512 start unaligned); this frees ~500 bytes of padding.
        keep = off not in targets or (prev_off is not None and prev_off not in targets)
        while keep and off % 4 == 0 and (start + len(text)) % 4:
            text.append(0)
        prev_off = off
        moves[off] = start + len(text)
        text.extend(new_msgs.get(n, b))
    if start + len(text) > region_end:
        raise ValueError(f'text region overflows by {start + len(text) - region_end} bytes')
    out = bytearray(data)
    out[start:region_end] = bytes(text) + bytes(region_end - start - len(text))
    B = rt.OVERLAY_BASE
    patched = 0
    for i in range(0, start - 3, 4):
        v = struct.unpack_from('>I', data, i)[0]
        if B <= v < B + len(data) and (v - B) in moves and moves[v - B] != v - B:
            struct.pack_into('>I', out, i, B + moves[v - B])
            patched += 1
    return bytes(out), region_end - start - len(text), patched


def main():
    sel = sys.argv[1] if len(sys.argv) > 1 else '1-16'
    end = '--end' in sys.argv          # Disc 2 END.BIN (ending: demon farewells + credits), same overlay format
    src, out, fname = (os.path.join(HERE, 'Disc2'), os.path.join(HERE, 'build', 'Disc2'), 'END.BIN') if end         else (SRC, OUT, 'EVENT.BIN')
    key = ('D2/' if end else 'D1/') + fname + ':'
    with open(os.path.join(HERE, 'mapping.json'), encoding='utf-8') as f:
        mapping = json.load(f)
    table = rt.load_table(os.path.join(HERE, 'font16.tbl'))
    names = load_names()
    data = open(os.path.join(src, fname), 'rb').read()
    msgs = {n: b for n, _, b in rt.messages_from_bytes(data)}
    if sel == 'all':
        wanted = [n for n in msgs if mapping.get(f'{key}{n}', {}).get('en')]
    else:
        a, _, b = sel.partition('-')
        wanted = [n for n in range(int(a), int(b or a) + 1)
                  if mapping.get(f'{key}{n}', {}).get('en')]
    alloc = TileAllocator(table)
    new, errors = {}, []
    for n in wanted:
        try:
            new[n] = build_message(msgs[n], mapping[f'{key}{n}']['en'], names, table, alloc)
            if any(a == 'J' for _, a in code_offsets(msgs[n])):
                new[n] = fix_jumps(msgs[n], new[n])
        except ValueError as ex:
            errors.append(f'message {n}: {ex}')
    wanted = [n for n in wanted if n in new]
    for n in ([] if end else DUMMIES):
        new[n] = shrink_dummy(msgs[n])
    event, slack, patched = rebuild_event(data, new)

    font = bytearray(open(os.path.join(SRC, 'FONT16.BIN'), 'rb').read())
    fe.install_half_font(font)   # letter pairs are composed at run time (patch_code.py)

    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, fname), 'wb').write(event)
    open(os.path.join(out, 'FONT16.BIN'), 'wb').write(bytes(font))
    alloc.save()
    old = sum(len(msgs[n]) for n in wanted); now = sum(len(new[n]) for n in wanted)
    overwritten = [t for t in alloc.map.values()]
    print(f'inserted {len(wanted)} messages ({old} -> {now} bytes), {patched} pointers updated, {slack} bytes free')
    print(f'{len(alloc.map)} bigram tiles in use; overwritten kanji were used {sum(alloc.use[t] for t in overwritten)} '
          f'times in the Japanese script')
    for err in errors:
        print('  NOT INSERTED', err)


if __name__ == '__main__':
    main()
