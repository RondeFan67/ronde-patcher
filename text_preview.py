# Text preview: every dialogue box of a build, drawn in the browser with the game's own font and portraits, next
# to the Japanese, with automatic checks. It reads the files straight out of the build's disc images (what the
# emulator runs), so it also catches insertion bugs and stale build files. The output is one self-contained HTML
# page: the font (1 bit per pixel), the portraits (palette + pixels) and the messages (glyph codes) are embedded as
# data and drawn on <canvas> on demand, so the page stays a few MB and needs no image files.
#
#   python text_preview.py                 -> build/text_preview.html for the newest build
#   python text_preview.py build001        -> a named build ("Ronde (Disc 1) (Track 1) [build001].bin", + Disc 2)
#   python text_preview.py --dir build     -> the loose files in build/Disc1 and build/Disc2 instead
#   python text_preview.py --list          also print every flagged message (one line each)
#
# Window rules (same as the inserters):
# - A box is 18 cells (16 px) wide and shows 3 lines per page; a speaker name counts as a line. #T = one line,
#   #H = next page, #K = wait for a button, #S / #W = choice menu.
# - Battle boxes (MSG, DEADMSG): #A 01 = top box, portrait on the right; #A 02 = bottom box, portrait on the left
#   (lines indented by 4 blank cells). #U 01 xx / #U 02 xx show portrait xx-1 of KAO.BIN in the top / bottom box,
#   #U 03 / #U 04 hide it. With a portrait 13 text cells fit, then the wait cursor; without one 17.
# - EVENT / END windows have no box codes (the event data decides): 14 cells when the Japanese fits a portrait
#   window (insert_event.line_chars), else 18. Last words (DEADMSG) never show a portrait.
import argparse
import base64
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ronde_text as rt  # noqa: E402
import font_en as fe  # noqa: E402
import layout  # noqa: E402
import insert_event as ie  # noqa: E402
import kai_tool  # noqa: E402
import patch_disc as pd  # noqa: E402

CELLS = 18              # window width in 16-px cells; cells past this overwrite other sprites' textures
PAGE_LINES = 3
FONT_TAIL = 0x380       # FONT16 tiles >= this are overwritten in battle
VAR_CELLS = 4           # rough width of an inline variable (number / name)
KAO_STRIDE = 0x1800     # KAO.BIN: 59 'PP' images, 64x64 8bpp, one every 0x1800 bytes
FAMILIES = {'MSG': 'Battle dialogue', 'DEADMSG': 'Last words', 'EVENT': 'Cutscenes and town',
            'END': 'Ending', 'KAI': 'Demon talk'}
SEV_NAME = {2: 'error', 1: 'warning', 0: 'note'}


def family(name):
    for k in FAMILIES:
        if name.startswith(k):
            return k
    return None


def kind_of(fam):
    return {'MSG': 'battle', 'DEADMSG': 'battle', 'KAI': 'kai'}.get(fam, 'event')


# --- reading builds -------------------------------------------------------------------------------------------

class DiscImages:
    """Files of a named build, read from its track 1 images (falls back to the original disc for Disc 2)."""

    def __init__(self, build, name):
        self.images = {}
        for disc, n in (('Disc1', 1), ('Disc2', 2)):
            path = os.path.join(build, f'Ronde (Disc {n}) (Track 1) [{name}].bin')
            if os.path.exists(path):
                fh = open(path, 'rb')
                self.images[disc] = (fh, pd.find_files(fh))
        if 'Disc1' not in self.images:
            raise SystemExit(f'no disc image for build {name!r} in {build}')

    def read(self, disc, name):
        if disc not in self.images:
            return None
        fh, files = self.images[disc]
        if name not in files:
            return None
        lba, size = files[name]
        return pd.read_user(fh, lba, (size + pd.USER - 1) // pd.USER)[:size]


class LooseFiles:
    def __init__(self, build):
        self.build = build

    def read(self, disc, name):
        p = os.path.join(self.build, disc, name)
        return open(p, 'rb').read() if os.path.exists(p) else None


def current_build(build):
    """The selected build (current.txt, if an emulator shortcut uses one), else the newest in notes.txt."""
    for name, first_field in (('current.txt', False), ('notes.txt', True)):
        p = os.path.join(build, name)
        if os.path.exists(p):
            line = (open(p, encoding='utf-8-sig').read().splitlines() or [''])[0]
            return (line.split('\t')[0] if first_field else line).strip() or None
    return None


# --- decoding -------------------------------------------------------------------------------------------------

def ops_of(items):
    """Parsed items -> compact JSON ops: a list of glyph codes is a #T line, a string is a control code."""
    ops = []
    for kind, a, b in items:
        if kind == 'text':
            ops.append(list(b))
        elif kind == 'code':
            ops.append(a + b.hex().upper())
        else:
            ops.append('RAW' + a.hex().upper())
    return ops


def kai_messages(data):
    """KAI.BIN: group the #T runs into messages, keyed by the offset of the first run. A message ends at #Q, #K,
    #W (end of a choice menu) or #J; unlike kai_tool.message_starts, the options after #S stay with their question."""
    out, items, prev_end = {}, None, None
    for off, glyphs, n in kai_tool.parse(data):
        between = data[prev_end:off] if prev_end is not None else b'#Q'
        if items is None or any(c in between for c in (b'#Q', b'#K', b'#W', b'#J')):
            items = out.setdefault(off, [])
        else:
            for code in (b'#H', b'#S'):
                if code in between:
                    items.append(('code', code[1:].decode(), b'\0' if code == b'#S' else b''))
        items.append(('text', None, glyphs))
        prev_end = off + n
    return out


def units_of(data, fam, start=None):
    """{key: items} for every message (key = MSG block number, overlay message index or KAI offset).
    start: offset of the first overlay message (insert_event keeps the text region where the original has it)."""
    if data is None:
        return None
    if fam == 'KAI':
        return kai_messages(data)
    if fam in ('MSG', 'DEADMSG'):
        out = {}
        for n in range(len(data) // rt.BLOCK_SIZE):
            b = data[n * rt.BLOCK_SIZE:(n + 1) * rt.BLOCK_SIZE]
            if any(b):
                out[n] = list(rt.parse_block(b))
        return out
    return {n: list(rt.parse_block(b)) for n, _, b in rt.messages_from_bytes(data, start)}


# --- checks ---------------------------------------------------------------------------------------------------

def is_japanese(ch):
    """Kana and kanji (full-width Latin and punctuation are left alone: the credits use them)."""
    o = ord(ch)
    return 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF


def line_cells(glyphs):
    return sum(VAR_CELLS if g & rt.VAR else 1 for g in glyphs)


def line_str(glyphs, table):
    """Readable text of a #T line: English pairs decoded, Japanese via font16.tbl."""
    s = []
    for g in glyphs:
        if g & rt.VAR:
            s.append(f'{{V{(g >> 8) & 0xFF:02X}:{g & 0xFF:02X}}}')
        elif g >= 0x8000:
            s.append(chr((g >> 7) & 0x7F) + chr(g & 0x7F))
        elif g == 0:
            s.append('  ')
        else:
            s.append(table.get(g, f'[{g:03X}]'))
    return ''.join(s)


def strip_blank(g):
    """Trailing blank cells (KAI lines are padded to their original length) do not show."""
    g = list(g)
    while g and g[-1] in (0, fe.SPACE_PAIR_CODE - 1):
        g.pop()
    return g


def window_of(fam, jp_items):
    """Window for a message: kind, cap (text cells) and whether a portrait shows at the start."""
    kind = kind_of(fam)
    if fam in ('EVENT', 'END'):
        cap = ie.line_chars(jp_items) // 2
        return {'kind': kind, 'cap': cap, 'portrait': cap < CELLS - 2}
    if fam == 'MSG':
        widest = max((len(g) - next((k for k, x in enumerate(g) if x != 0), len(g))
                      for k_, _, g in jp_items if k_ == 'text'), default=0)
        # insert_msg.PORTRAIT_GLYPHS: a portrait shown by an earlier block stays up
        portrait = widest <= 14
        return {'kind': kind, 'cap': 13 if portrait else CELLS - 1, 'portrait': portrait}
    if fam == 'DEADMSG':
        return {'kind': kind, 'cap': CELLS - 1, 'portrait': False}
    return {'kind': kind, 'cap': CELLS, 'portrait': False}


def check(fam, en_items, win, table):
    """Simulate the box page by page. Returns [(severity, text)]; severity 2 = error, 1 = warning, 0 = note."""
    flags = []
    battle = win['kind'] == 'battle'
    portrait = {'top': win['portrait'], 'bottom': win['portrait']}
    box = 'top'
    pages, cur, options, ended_by_menu = [], [], False, False
    for kind, a, b in en_items:
        if kind == 'code':
            if battle and a == 'U' and b:
                which = {1: 'top', 3: 'top', 2: 'bottom', 4: 'bottom'}.get(b[0])
                if which:
                    portrait[which] = b[0] in (1, 2)
            elif a == 'A' and b:
                box = 'bottom' if b[0] == 2 else 'top'
            if a in 'HKSWQ' and cur:
                pages.append((cur, options))
                cur = []
            if a in 'SW':
                options = ended_by_menu = True
            elif a in 'HK':
                options = False
        elif kind == 'raw':
            flags.append((1, f'unknown bytes {a.hex(" ").upper()}'))
        else:
            g = strip_blank(b)
            indent = next((k for k, x in enumerate(g) if x != 0), len(g))
            shown = line_cells(g)
            text = line_str(g, table).strip()
            if battle:
                cap = indent + 13 if portrait[box] and fam == 'MSG' else CELLS - 1
            else:
                cap = win['cap']
            if shown > CELLS:
                flags.append((2, f'{shown} cells, past the window edge: "{text}"'))
            elif shown > cap:
                flags.append((1, f'{shown} cells, limit {cap}{" (portrait)" if cap < CELLS - 2 else ""}: "{text}"'))
            jp = ''.join(ch for x in g if x < 0x8000 and not x & rt.VAR for ch in table.get(x, '') if is_japanese(ch))
            if jp:
                flags.append((1, f'Japanese left: {jp}'))
            if any(FONT_TAIL <= x < 0x8000 for x in g if not x & rt.VAR) and fam != 'END':
                flags.append((2, 'uses font tiles >= 0x380 (overwritten in battle)'))
            cur.append(text)
    if cur:
        pages.append((cur, options))
    for p, (lines, _) in enumerate(pages):
        if len(lines) > PAGE_LINES:
            flags.append((2, f'page {p + 1} has {len(lines)} lines (the box shows {PAGE_LINES})'))
    story = [lines for lines, opt in pages if not opt]
    if len(story) > 1 and not pages[-1][1]:
        words = ' '.join(story[-1]).split()
        if 0 < len(words) <= 2 and not story[-1][0].startswith('['):
            flags.append((0, f'last page holds only "{" ".join(words)}"'))
    last = story[-1][-1] if story and story[-1] else ''
    if last and not ended_by_menu and last.isascii() and not last.startswith('[') \
            and last[-1] not in layout.END_PUNCT + ':-':
        flags.append((0, f'no end punctuation: "...{last[-24:]}"'))
    return flags


# --- page -----------------------------------------------------------------------------------------------------

def font_bits(font):
    """4bpp FONT16 tiles -> 1 bit per pixel (32 bytes per tile)."""
    out = bytearray()
    for t in range(len(font) // 128):
        tile = font[t * 128:(t + 1) * 128]
        for y in range(16):
            bits = 0
            for x in range(16):
                b = tile[y * 8 + x // 2]
                if (b >> 4 if x % 2 == 0 else b & 15):
                    bits |= 0x8000 >> x
            out += struct.pack('>H', bits)
    return out


def portraits(kao):
    """KAO.BIN -> per portrait 256 RGB palette entries (768 bytes) + 64x64 indices (4096 bytes)."""
    out = bytearray()
    for k in range(len(kao) // KAO_STRIDE):
        b = kao[k * KAO_STRIDE:]
        assert b[:2] == b'PP' and struct.unpack_from('>HH', b, 2) == (64, 64), k
        for i in range(256):
            v = struct.unpack_from('>H', b, 6 + i * 2)[0]
            out += bytes(((v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3))
        out += b[518:518 + 4096]
    return bytes(out)


def collect(src, table):
    files = []
    for disc in ('Disc1', 'Disc2'):
        names = sorted(n for n in os.listdir(os.path.join(HERE, disc)) if family(n) and n.endswith('.BIN'))
        for name in names:
            fam = family(name)
            if disc == 'Disc2' and fam not in ('MSG', 'END'):
                continue      # Disc 2 EVENT/KAI/DEADMSG are copies of the Disc 1 output (disc2_tool.py)
            if disc == 'Disc1' and fam == 'MSG' and os.path.exists(os.path.join(HERE, 'Disc2', name)):
                continue      # MSG20-51 are played from Disc 2
            orig = open(os.path.join(HERE, disc, name), 'rb').read()
            jp = units_of(orig, fam)
            en = units_of(src.read(disc, name), fam, orig.find(b'#T') if fam in ('EVENT', 'END') else None)
            msgs = []
            for key, jp_items in jp.items():
                if not any(k == 'text' and b for k, _, b in jp_items):
                    continue  # empty {T}{Q} placeholders (MSG25, MSG46-50)
                en_items = en.get(key) if en else None
                win = window_of(fam, jp_items)
                if en_items is None:
                    flags = [(1, 'missing from the built file')]
                elif ops_of(en_items) == ops_of(jp_items):
                    has_jp = any(is_japanese(ch) for k, _, b in jp_items if k == 'text'
                                 for ch in line_str(b, table))
                    flags = [(1, 'untranslated')] if has_jp else []
                else:
                    flags = check(fam, en_items, win, table)
                label = f'{key:05X}' if fam == 'KAI' else str(key)
                text = ' '.join(line_str(b, table).strip() for k, _, b in (en_items or []) if k == 'text')
                msgs.append({'id': label, 'jp': ops_of(jp_items), 'en': ops_of(en_items) if en_items else None,
                             'win': win, 'flags': flags, 'text': text})
            if not msgs:
                continue      # empty files (MSG24, MSG28, MSG33-36, MSG46-50: a single {T}{Q})
            files.append({'disc': disc, 'name': name, 'family': FAMILIES[fam], 'built': en is not None,
                          'msgs': msgs})
    return files


def write_page(path, title, files, font, half, kao):
    data = {'title': title, 'files': files, 'font': base64.b64encode(font).decode(),
            'half': base64.b64encode(half).decode(), 'kao': base64.b64encode(kao).decode(), 'cells': CELLS}
    page = PAGE.replace('/*DATA*/', json.dumps(data, separators=(',', ':'), ensure_ascii=False)
                        .replace('</', '<\\/'))
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('name', nargs='?', help='build name (default: the newest)')
    ap.add_argument('--build', default=os.path.join(HERE, 'build'), help='folder with the builds')
    ap.add_argument('--dir', help='read loose files from <dir>/Disc1 and <dir>/Disc2 instead of a disc image')
    ap.add_argument('--out', default=None)
    ap.add_argument('--list', action='store_true')
    args = ap.parse_args()
    table = rt.load_table(os.path.join(HERE, 'font16.tbl'))
    if args.dir:
        src, title = LooseFiles(args.dir), f'files in {args.dir}'
    else:
        name = args.name or current_build(args.build)
        src, title = DiscImages(args.build, name), name
    files = collect(src, table)
    font = open(os.path.join(HERE, 'Disc1', 'FONT16.BIN'), 'rb').read()
    built_font = src.read('Disc1', 'FONT16.BIN') or font
    half = built_font[fe.HALF_TILE * 128:(fe.HALF_TILE + fe.HALF_TILES) * 128]
    kao = portraits(open(os.path.join(HERE, 'Disc1', 'KAO.BIN'), 'rb').read())
    out = args.out or os.path.join(args.build, 'text_preview.html')
    write_page(out, title, files, font_bits(font), half, kao)
    totals = {2: 0, 1: 0, 0: 0}
    for f in files:
        for m in f['msgs']:
            for s, t in m['flags']:
                totals[s] += 1
                if args.list:
                    print(f'{f["disc"]}/{f["name"]} {m["id"]}: {SEV_NAME[s]}: {t}')
    n = sum(len(f['msgs']) for f in files)
    print(f'{title}: {n} messages in {len(files)} files: {totals[2]} errors, {totals[1]} warnings, {totals[0]} notes')
    print(f'wrote {out} ({os.path.getsize(out) // 1024} KB)')


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ronde Text Preview</title>
<style>
:root{--bg:#f4f5f7;--fg:#1d2129;--mut:#646b78;--card:#fff;--line:#d9dce2;--err:#c62828;--warn:#a35f00;--note:#3f64a0;
  --sel:#e3e9f4}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14161b;--fg:#d8dbe2;--mut:#8a91a0;
  --card:#1d2027;--line:#2c313b;--err:#ef6b6b;--warn:#e0a640;--note:#7fa2d9;--sel:#27303f}}
:root[data-theme="dark"]{--bg:#14161b;--fg:#d8dbe2;--mut:#8a91a0;--card:#1d2027;--line:#2c313b;--err:#ef6b6b;
  --warn:#e0a640;--note:#7fa2d9;--sel:#27303f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;display:flex;height:100vh}
nav{width:260px;flex:none;overflow-y:auto;border-right:1px solid var(--line);padding:8px}
nav h1{font-size:15px;margin:4px 6px 2px} nav .sub{color:var(--mut);font-size:12px;margin:0 6px 8px}
nav h2{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:12px 6px 4px}
nav button{display:flex;width:100%;justify-content:space-between;gap:6px;border:0;background:none;color:inherit;
  font:inherit;padding:3px 6px;border-radius:4px;cursor:pointer;text-align:left}
nav button:hover{background:var(--sel)} nav button.on{background:var(--sel);font-weight:600}
.cnt{font-size:12px;color:var(--mut);white-space:nowrap} .cnt b{font-weight:600}
.e{color:var(--err)} .w{color:var(--warn)} .n{color:var(--note)}
main{flex:1;overflow-y:auto;padding:0 16px 16px}
.bar{position:sticky;top:0;background:var(--bg);padding:10px 0;display:flex;gap:12px;flex-wrap:wrap;align-items:center;
  z-index:1;border-bottom:1px solid var(--line)}
.bar input[type=search]{flex:1;min-width:160px;padding:6px 8px;border:1px solid var(--line);border-radius:4px;
  background:var(--card);color:var(--fg);font:inherit}
.bar select{font:inherit;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:4px}
.msg{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:10px 0}
.msg h3{margin:0 0 6px;font-size:13px;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.msg h3 span{color:var(--mut);font-weight:normal}
.cols{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
.pages{display:flex;flex-direction:column;gap:4px;min-width:0}
.pages small{color:var(--mut);font-size:11px}
canvas{image-rendering:pixelated;max-width:100%;height:auto;display:block;border-radius:3px}
.flags{margin:6px 0 0;padding-left:18px;font-size:13px}
.codes{font:11px ui-monospace,monospace;color:var(--mut);margin-top:6px;word-break:break-all}
.empty{color:var(--mut);padding:20px}
.key{color:var(--mut);font-size:12px;margin:8px 0 0}
.key i{display:inline-block;width:10px;height:10px;vertical-align:-1px;margin:0 3px 0 8px;border-radius:2px}
@media (max-width:700px){body{flex-direction:column;height:auto}nav{width:auto;border-right:0;
  border-bottom:1px solid var(--line);max-height:40vh}main{overflow:visible;padding:0 16px 16px}}
</style></head><body>
<nav id="nav"><h1>Ronde Text Preview</h1><p class="sub" id="sub"></p></nav>
<main><div class="bar"><input type="search" id="q" placeholder="Search the English of every file">
<label><input type="checkbox" id="flagged"> Flagged only</label>
<label>View <select id="view"><option value="box">Boxes</option><option value="screen">Screen</option></select></label>
<label><input type="checkbox" id="showjp" checked> Japanese</label>
<label><input type="checkbox" id="showcodes"> Codes</label></div>
<p class="key">Box key:<i style="background:#5a2a3a"></i>past the text limit<i style="background:#33406a"></i>wait-cursor cell
<i style="background:repeating-linear-gradient(45deg,#3b4a75 0 3px,#22305a 3px 6px)"></i>portrait set by the event data.
Battle-box placement is approximate; text widths and page breaks follow the game's rules.</p>
<div id="list"></div></main>
<script>
const D = /*DATA*/;
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const FONT = b64(D.font), HALF = b64(D.half), KAO = b64(D.kao), CELLS = D.cells, SCALE = 2, VAR = 0x10000;
const SEV = ['n', 'w', 'e'], SEVNAME = ['note', 'warning', 'error'];
const $ = id => document.getElementById(id);
let cur = 0;

// --- glyphs and portraits, rendered once and cached ---
const glyphCache = new Map();
function glyph(g, color) {
  const key = g + color; if (glyphCache.has(key)) return glyphCache.get(key);
  const cv = document.createElement('canvas'); cv.width = cv.height = 16;
  const ctx = cv.getContext('2d'), id = ctx.createImageData(16, 16), px = id.data;
  const [r, gg, b] = color.match(/\w\w/g).map(h => parseInt(h, 16));
  const put = (x, y) => { const i = (y * 16 + x) * 4; px[i] = r; px[i + 1] = gg; px[i + 2] = b; px[i + 3] = 255; };
  if (g & VAR) { for (let y = 3; y < 13; y++) for (let x = 1; x < 15; x++) if ((x + y) % 4 == 0) put(x, y); }
  else if (g >= 0x8000) {   // English pair: two 8x16 half-font characters (patched font16_decode_glyph)
    [(g >> 7) & 0x7f, g & 0x7f].forEach((c, h) => { if (c < 0x20 || c > 0x7e) return;
      for (let y = 0; y < 16; y++) { const row = HALF[(c - 0x20) * 16 + y]; for (let x = 0; x < 8; x++) if (row & (0x80 >> x)) put(h * 8 + x, y); } });
  } else if (g * 32 < FONT.length) {
    for (let y = 0; y < 16; y++) { const row = FONT[g * 32 + y * 2] << 8 | FONT[g * 32 + y * 2 + 1]; for (let x = 0; x < 16; x++) if (row & (0x8000 >> x)) put(x, y); }
  }
  ctx.putImageData(id, 0, 0); glyphCache.set(key, cv); return cv;
}
const kaoCache = new Map(), KAO_N = KAO.length / 4864;
function portrait(n) {
  if (kaoCache.has(n)) return kaoCache.get(n);
  const cv = document.createElement('canvas'); cv.width = cv.height = 64;
  if (n >= 0 && n < KAO_N) {
    const ctx = cv.getContext('2d'), id = ctx.createImageData(64, 64), px = id.data, base = n * 4864;
    for (let i = 0; i < 4096; i++) { const c = KAO[base + 768 + i] * 3; px[i * 4] = KAO[base + c]; px[i * 4 + 1] = KAO[base + c + 1]; px[i * 4 + 2] = KAO[base + c + 2]; px[i * 4 + 3] = 255; }
    ctx.putImageData(id, 0, 0);
  }
  kaoCache.set(n, cv); return cv;
}

// --- simulate a message: frames of {active, top, bottom}; each box has lines and a portrait ---
// portrait: null = none, number = KAO index, '?' = shown by an earlier block, 'ev' = set by the event data
function frames(ops, win) {
  const battle = win.kind == 'battle', out = [];
  // a portrait inferred from the Japanese width belongs to the box the block writes to first
  const firstA = ops.find(o => typeof o == 'string' && o[0] == 'A');
  let active = battle ? (firstA && firstA.slice(1, 3) == '02' ? 'bottom' : 'top') : 'bottom', menu = false;
  const box = {top: {lines: [], portrait: null}, bottom: {lines: [], portrait: null}};
  if (win.portrait) box[active].portrait = battle ? '?' : 'ev';
  const snap = () => out.push({active, menu, top: {...box.top, lines: box.top.lines.slice()}, bottom: {...box.bottom, lines: box.bottom.lines.slice()}});
  for (const op of ops) {
    if (Array.isArray(op)) { box[active].lines.push(op); continue; }
    const c = op[0];
    if (battle && c == 'U') {
      const mode = parseInt(op.slice(1, 3), 16), n = parseInt(op.slice(3, 5), 16);
      if (mode == 1) box.top.portrait = n - 1; else if (mode == 2) box.bottom.portrait = n - 1;
      else if (mode == 3) box.top = {lines: [], portrait: null}; else if (mode == 4) box.bottom = {lines: [], portrait: null};
    } else if (battle && c == 'A') active = op.slice(1, 3) == '02' ? 'bottom' : 'top';
    else if ('HKSWQ'.includes(c) && box[active].lines.length) { snap(); box[active].lines = []; }
    if ('SW'.includes(c)) menu = true; else if ('HK'.includes(c)) menu = false;
  }
  if (box[active].lines.length) snap();
  return out;
}

// --- draw one box with its top-left at (x, y) ---
// Geometry from an in-game screenshot (320x240): a battle box is a translucent panel 14 cells wide plus a framed
// 64x64 portrait (top box: portrait right; bottom box: portrait left, over the 4 indent cells). Without a
// portrait the panel spans all 18 cells. Cutscene text has no panel: shadowed letters over the scene.
function boxLayout(b, side, win) {
  const battle = win.kind == 'battle', p = b.portrait != null, rows = Math.max(3, b.lines.length);
  const indent = battle && p && side == 'bottom' ? 4 : 0;
  const textX = !battle && p ? 68 : 0;              // EVENT portrait windows: text right of the portrait
  const cap = (battle ? (p ? 13 : CELLS - 1) : win.cap) + indent;
  return {battle, p, rows, indent, textX, cap, w: textX + CELLS * 16 + 8, h: Math.max(rows * 16 + 8, p ? 64 : 0)};
}
function panel(ctx, x, y, w, h) {
  const g = ctx.createLinearGradient(x, y, x + w, y + h);
  g.addColorStop(0, 'rgba(46,72,118,.88)'); g.addColorStop(1, 'rgba(28,44,82,.88)');
  ctx.fillStyle = g; ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = 'rgba(205,215,235,.75)'; ctx.lineWidth = 1; ctx.strokeRect(x + .5, y + .5, w - 1, h - 1);
}
function drawBox(ctx, x, y, b, side, win, dim, bare) {
  const L = boxLayout(b, side, win);
  ctx.save(); if (dim) ctx.globalAlpha = .45;
  const gx0 = x + 4 + L.textX, gy0 = y + 4;          // text grid origin
  if (L.battle) {
    if (!L.p) panel(ctx, x, y, CELLS * 16 + 8, L.rows * 16 + 8);
    else if (side == 'top') panel(ctx, x, y, 14 * 16 + 6, L.rows * 16 + 8);
    else panel(ctx, x + 66, y + 3, CELLS * 16 + 8 - 66, L.rows * 16 + 6);
  } else if (!bare) { ctx.fillStyle = 'rgba(16,20,30,.9)'; ctx.fillRect(x, y, L.w, L.h); }
  if (!dim) {          // text-limit shading: the wait-cursor cell, then everything past it
    ctx.fillStyle = 'rgba(110,130,200,.35)'; if (L.cap < CELLS) ctx.fillRect(gx0 + L.cap * 16, gy0, 16, 48);
    ctx.fillStyle = 'rgba(200,60,80,.35)'; if (L.cap + 1 < CELLS) ctx.fillRect(gx0 + (L.cap + 1) * 16, gy0, (CELLS - L.cap - 1) * 16, 48);
  }
  if (L.p) {
    const px = L.battle ? (side == 'bottom' ? x : x + 14 * 16 + 8) : x + 4, py = y;
    if (typeof b.portrait == 'number') ctx.drawImage(portrait(b.portrait), px, py);
    else { ctx.fillStyle = '#22305a'; ctx.fillRect(px, py, 64, 64); ctx.strokeStyle = '#3b4a75'; ctx.lineWidth = 3;
      ctx.save(); ctx.beginPath(); ctx.rect(px, py, 64, 64); ctx.clip();
      for (let k = -64; k < 64; k += 6) { ctx.beginPath(); ctx.moveTo(px + k, py + 64); ctx.lineTo(px + k + 64, py); ctx.stroke(); }
      ctx.restore(); ctx.fillStyle = '#dde3f2'; ctx.font = '10px system-ui'; ctx.fillText(b.portrait == '?' ? 'earlier' : 'event', px + 14, py + 36); }
    ctx.strokeStyle = 'rgba(205,215,235,.75)'; ctx.lineWidth = 1; ctx.strokeRect(px + .5, py + .5, 63, 63);
  }
  b.lines.forEach((ln, r) => ln.forEach((g, c) => {
    const gx = gx0 + c * 16, gy = gy0 + r * 16;
    ctx.drawImage(glyph(g, '000000'), gx + 1, gy + 1);
    ctx.drawImage(glyph(g, c >= CELLS || r >= 3 ? 'ff6b6b' : 'f0f0f0'), gx, gy);
  }));
  if (b.lines.length > 3) { ctx.strokeStyle = '#ff6b6b'; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(x, gy0 + 48.5); ctx.lineTo(x + L.w, gy0 + 48.5); ctx.stroke(); }
  ctx.restore();
}
const longest = b => Math.max(0, ...b.lines.map(l => l.length));

function frameCanvas(f, win, view) {
  const cv = document.createElement('canvas'), ctx = cv.getContext('2d');
  const a = f[f.active], extra = Math.max(0, longest(a) - CELLS) * 16;
  if (view == 'screen') {      // 320x240 screen; battle: top box at y=17, bottom box at y=157 (from a screenshot)
    cv.width = 320 + extra; cv.height = 240;
    const g = ctx.createLinearGradient(0, 0, 0, 240); g.addColorStop(0, '#1f3550'); g.addColorStop(.45, '#2f4a2c'); g.addColorStop(1, '#3d6a33');
    ctx.fillStyle = g; ctx.fillRect(0, 0, cv.width, 240);
    if (win.kind == 'battle') {
      for (const side of ['top', 'bottom']) {
        const b = f[side]; if (side != f.active && !b.lines.length && typeof b.portrait != 'number') continue;
        drawBox(ctx, 16, side == 'top' ? 17 : 157, b, side, win, side != f.active);
      }
    } else drawBox(ctx, 16, Math.min(172, 236 - boxLayout(a, 'bottom', win).h), a, 'bottom', win, false, true);
  } else {
    const L = boxLayout(a, f.active, win);
    cv.width = L.w + extra; cv.height = L.h;
    drawBox(ctx, 0, 0, a, f.active, win, false);
  }
  cv.style.width = cv.width * SCALE + 'px';
  return cv;
}

function pagesEl(ops, win, label) {
  const div = document.createElement('div'); div.className = 'pages';
  const view = $('view').value, fr = frames(ops, win);
  const s = document.createElement('small'); s.textContent = `${label} · ${fr.length} page${fr.length == 1 ? '' : 's'}`; div.append(s);
  fr.forEach(f => div.append(frameCanvas(f, win, view)));
  return div;
}

// --- list ---
const worst = m => m.flags.reduce((a, f) => Math.max(a, f[0]), -1);
function counts(msgs) { const c = [0, 0, 0]; msgs.forEach(m => m.flags.forEach(f => c[f[0]]++)); return c; }
const cntHtml = c => [2, 1, 0].filter(s => c[s]).map(s => `<b class="${SEV[s]}">${c[s]}</b>`).join(' ') || '✓';
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

function buildNav() {
  $('sub').textContent = 'Build: ' + D.title;
  const nav = $('nav'); let last = '';
  D.files.forEach((f, i) => {
    const grp = `${f.disc.replace('Disc', 'Disc ')} · ${f.family}`;
    if (grp != last) { const h = document.createElement('h2'); h.textContent = grp; nav.append(h); last = grp; }
    const b = document.createElement('button'); b.dataset.i = i;
    b.innerHTML = `<span>${f.name.replace('.BIN', '')}${f.built ? '' : ' <i class="cnt">(not built)</i>'}</span><span class="cnt">${f.msgs.length} · ${cntHtml(counts(f.msgs))}</span>`;
    b.onclick = () => { cur = i; $('q').value = ''; render(); $('list').parentElement.scrollTop = 0; try { localStorage.setItem('rtp-file', f.disc + f.name); } catch (e) {} };
    nav.append(b);
  });
}

const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { fill(e.target); io.unobserve(e.target); } }), {rootMargin: '800px'});
function fill(card) {
  const m = D.files[card.dataset.f].msgs[card.dataset.m], cols = card.querySelector('.cols');
  if (m.en) cols.append(pagesEl(m.en, m.win, 'English'));
  if ($('showjp').checked) cols.append(pagesEl(m.jp, m.win, 'Japanese'));
  if ($('showcodes').checked) { const c = document.createElement('div'); c.className = 'codes';
    c.textContent = (m.en || m.jp).filter(o => !Array.isArray(o)).join(' '); card.append(c); }
}

function render() {
  const q = $('q').value.trim().toLowerCase(), onlyF = $('flagged').checked;
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('on', +b.dataset.i == cur && !q));
  const list = $('list'); list.innerHTML = '';
  const items = [];
  D.files.forEach((f, fi) => { if (!q && fi != cur) return;
    f.msgs.forEach((m, mi) => { if (q && !m.text.toLowerCase().includes(q)) return; if (onlyF && worst(m) < 0) return; items.push([fi, mi]); }); });
  if (!items.length) { list.innerHTML = '<p class="empty">Nothing to show.</p>'; return; }
  const LIMIT = 500;
  for (const [fi, mi] of items.slice(0, LIMIT)) {
    const f = D.files[fi], m = f.msgs[mi], card = document.createElement('div');
    card.className = 'msg'; card.dataset.f = fi; card.dataset.m = mi;
    const fl = m.flags.map(x => `<li class="${SEV[x[0]]}">${SEVNAME[x[0]]}: ${esc(x[1])}</li>`).join('');
    const wdesc = m.win.kind == 'battle' ? 'battle box' : m.win.kind == 'kai' ? 'demon talk' : `window ${m.win.cap} cells${m.win.portrait ? ' + portrait' : ''}`;
    card.innerHTML = `<h3>${f.disc} ${f.name.replace('.BIN', '')} #${m.id} <span>${wdesc}</span></h3><div class="cols"></div>${fl ? `<ul class="flags">${fl}</ul>` : ''}`;
    list.append(card); io.observe(card);
  }
  if (items.length > LIMIT) list.insertAdjacentHTML('beforeend', `<p class="empty">${items.length - LIMIT} more: narrow the search or tick "Flagged only".</p>`);
}

buildNav();
try { const s = localStorage.getItem('rtp-file'); const i = D.files.findIndex(f => f.disc + f.name == s); if (i >= 0) cur = i; } catch (e) {}
// URL options, e.g. text_preview.html#f=MSG02&view=screen&flagged=1&q=Charlie
const H = new URLSearchParams(location.hash.slice(1));
if (H.get('f')) { const i = D.files.findIndex(f => f.name.startsWith(H.get('f').toUpperCase())); if (i >= 0) cur = i; }
if (H.get('view')) $('view').value = H.get('view');
if (H.get('flagged')) $('flagged').checked = true;
if (H.get('q')) $('q').value = H.get('q');
['q', 'flagged', 'showjp', 'showcodes', 'view'].forEach(id => $(id).addEventListener('input', render));
render();
</script></body></html>
'''

if __name__ == '__main__':
    main()
