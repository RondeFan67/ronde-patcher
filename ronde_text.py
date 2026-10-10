# Ronde (Saturn) MSG*.BIN text tool
#
# MSG files are 0x800-byte blocks, each ending in #Q. Text is not Shift-JIS:
# control codes are '#' + letter + fixed-size args, and #T is followed by
# big-endian u16 glyph codes (immediately after the code), terminated by 0x0000.
# Code n draws FONT16.BIN tile n-1 (16x16 4bpp, 128 bytes per tile); code 1 is a space.
# Inside #T, the bytes FF 58 nn insert a variable (nn: 00 = G amount, 01 = MAG amount, 02 = item name,
# stage number in STITLE2). parse_block returns it in the glyph list as VAR | 0x58 << 8 | nn.
#
# usage:
#   python ronde_text.py dump  Disc1/MSG01.BIN [...]  -o dump/      -> one .txt per file
#   python ronde_text.py view  Disc1/MSG01.BIN [...]  -o view.html  -> renders lines with the game font
import argparse
import base64
import html
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK_SIZE = 0x800
VAR = 0x10000   # glyph-list marker for an inline FF xx nn variable

# number of argument bytes after each control code ('T' is special: glyph stream)
ARG_LEN = {'A': 1, 'E': 1, 'O': 1, 'W': 1, 'Z': 1, 'S': 1, 'Y': 2, 'U': 3, 'J': 3,
           'H': 0, 'K': 0, 'V': 0, 'Q': 0, 'T': None}


def load_table(path):
    table = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if '=' in line:
                k, v = line.split('=', 1)
                table[int(k, 16)] = v
    return table


def parse_block(b):
    """Yield ('code', letter, args_bytes) / ('text', [glyph ids]) / ('raw', bytes) items until #Q."""
    i = 0
    while i < len(b):
        if b[i] == 0x23 and i + 1 < len(b) and chr(b[i+1]) in ARG_LEN:
            c = chr(b[i+1]); i += 2
            if c == 'T':
                glyphs = []
                while i + 1 < len(b):
                    if b[i] == 0xFF and i + 2 < len(b):   # inline variable FF xx nn
                        glyphs.append(VAR | b[i + 1] << 8 | b[i + 2]); i += 3
                        continue
                    (g,) = struct.unpack_from('>H', b, i); i += 2
                    if g == 0:
                        break
                    glyphs.append(g - 1)  # font tile index
                yield ('text', None, glyphs)
            else:
                n = ARG_LEN[c]
                yield ('code', c, b[i:i+n]); i += n
                if c == 'Q':
                    return
        else:
            # unknown byte: report it so new codes get noticed
            j = i + 1
            while j < len(b) and b[j] != 0x23:
                j += 1
            yield ('raw', b[i:j], None); i = j


def blocks(path):
    d = open(path, 'rb').read()
    for n in range(len(d) // BLOCK_SIZE):
        b = d[n*BLOCK_SIZE:(n+1)*BLOCK_SIZE]
        if any(b):
            yield n, b


# EVENT.BIN / END.BIN are SH-2 code overlays (loaded at OVERLAY_BASE) followed by
# a run of #Q-terminated messages; the code holds absolute pointers to each message.
OVERLAY_BASE = 0x06065B00


def messages(path):
    """Yield (index, file offset, bytes) for each message in a code+text overlay."""
    yield from messages_from_bytes(open(path, 'rb').read())


def messages_from_bytes(d, start=None):
    """start = offset of the first message. For a built overlay pass the original's: a rewritten pointer in the
    code can contain the bytes '#T' (e.g. 0x06082354 in the translated EVENT.BIN), and the scan would start there."""
    i = d.find(b'#T') if start is None else start
    n = 0
    while i >= 0:
        q = d.find(b'#Q', i)
        if q < 0:
            break
        yield n, i, d[i:q+2]
        n += 1
        i = q + 2
        while i < len(d) and d[i] == 0:  # alignment padding
            i += 1
        if i >= len(d) or d[i] != 0x23:
            break


def units(path):
    """Yield (id number, file offset, bytes) for MSG blocks or overlay messages."""
    name = os.path.basename(path).upper()
    if name.startswith('MSG') or name == 'DEADMSG.BIN':
        for n, b in blocks(path):
            yield n, n * BLOCK_SIZE, b
    else:
        yield from messages(path)


def glyph_text(glyphs, table):
    return ''.join(f'{{V{(g >> 8) & 0xFF:02X}:{g & 0xFF:02X}}}' if g & VAR else table.get(g, f'[{g:03X}]')
                   for g in glyphs)


def item_text(item, table):
    kind, a, b = item
    if kind == 'text':
        return '{T}' + glyph_text(b, table)
    if kind == 'code':
        return '{' + a + (' ' + b.hex(' ').upper() if b else '') + '}'
    return '{RAW ' + a.hex(' ').upper() + '}'


def cmd_dump(args, table):
    os.makedirs(args.out, exist_ok=True)
    for path in args.files:
        name = os.path.basename(path)
        out = os.path.join(args.out, name + '.txt')
        with open(out, 'w', encoding='utf-8') as o:
            for n, off, b in units(path):
                o.write(f'=== {name} block {n} (0x{off:X}) ===\n')
                line = ''
                for item in parse_block(b):
                    s = item_text(item, table)
                    # start a new line before each text run and after page/wait codes
                    if item[0] == 'text' and line:
                        o.write(line + '\n'); line = ''
                    line += s
                    if item[0] == 'code' and item[1] in 'HKQ':
                        o.write(line + '\n'); line = ''
                if line:
                    o.write(line + '\n')
                o.write('\n')
        print('wrote', out)


def font_sheet_png(font_path, cols=32):
    from PIL import Image
    d = open(font_path, 'rb').read()
    n = len(d) // 128
    rows = (n + cols - 1) // cols
    im = Image.new('RGBA', (cols*16, rows*16), (0, 0, 0, 0))
    px = im.load()
    for g in range(n):
        gx, gy = (g % cols)*16, (g // cols)*16
        for y in range(16):
            for x in range(16):
                b = d[g*128 + y*8 + x//2]
                if (b >> 4) if x % 2 == 0 else (b & 15):
                    px[gx+x, gy+y] = (255, 255, 255, 255)
    buf = io.BytesIO(); im.save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode(), cols, rows


def cmd_view(args, table):
    sheet, cols, rows = font_sheet_png(args.font)
    S = 2  # display scale
    parts = []
    for path in args.files:
        name = os.path.basename(path)
        parts.append(f'<h2>{html.escape(name)}</h2>')
        for n, off, b in units(path):
            parts.append(f'<section><h3>block {n} <span>0x{off:X}</span></h3>')
            for item in parse_block(b):
                if item[0] == 'text':
                    spans = ''.join(
                        f'<i style="background-position:-{(g % cols)*16*S}px -{(g // cols)*16*S}px" '
                        f'title="{g:03X} {html.escape(table.get(g, "?"))}"></i>' for g in item[2])
                    parts.append(f'<div class="t"><code>T</code><span class="g">{spans}</span>'
                                 f'<div class="tx">{html.escape(glyph_text(item[2], table))}</div></div>')
                else:
                    parts.append(f'<code class="c">{html.escape(item_text(item, table))}</code>')
            parts.append('</section>')
    page = f'''<!doctype html><meta charset="utf-8"><title>Ronde Script Viewer</title>
<style>
:root{{--bg:#16181d;--fg:#d8dbe2;--mut:#7d8494;--card:#1f222a;--glyph:#1a3b6e}}
body{{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;margin:16px}}
section{{background:var(--card);border-radius:6px;padding:8px 12px;margin:8px 0}}
h3{{margin:0 0 6px;font-size:13px}} h3 span{{color:var(--mut);font-weight:normal}}
code{{color:var(--mut);font-size:11px;margin-right:6px}}
.t{{margin:4px 0}} .g{{display:inline-flex;flex-wrap:wrap;background:var(--glyph);padding:2px}}
.g i{{display:block;width:{16*S}px;height:{16*S}px;image-rendering:pixelated;
  background-image:url(data:image/png;base64,{sheet});background-size:{cols*16*S}px {rows*16*S}px}}
.tx{{color:var(--mut);font-size:12px;margin-left:34px}}
</style>
<h1>Ronde script</h1><p>Hover a glyph to see its slot number.</p>
{''.join(parts)}'''
    with open(args.out, 'w', encoding='utf-8') as o:
        o.write(page)
    print('wrote', args.out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['dump', 'view'])
    ap.add_argument('files', nargs='+')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--table', default=os.path.join(HERE, 'font16.tbl'))
    ap.add_argument('--font', default=os.path.join(HERE, 'Disc1', 'FONT16.BIN'))
    args = ap.parse_args()
    table = load_table(args.table)
    {'dump': cmd_dump, 'view': cmd_view}[args.cmd](args, table)


if __name__ == '__main__':
    main()
