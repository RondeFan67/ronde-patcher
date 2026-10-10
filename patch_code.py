# Code patches for 0.BIN (loaded at 0x06004000), assembled here with a tiny SH-2 assembler.
#
# Patch 1: font16_decode_glyph (0x060131D4) gains runtime English letter pairs.
#   tile == 0          -> blank glyph (as before)
#   tile <  0x8000     -> copy FONT16 tile from Low WRAM 0x00200000 + tile*0x80 (as before)
#   tile >= 0x8000     -> letter pair: c1 = (tile >> 7) & 0x7F, c2 = tile & 0x7F. Half-glyphs are 8x16 1bpp
#                         (16 bytes, bit 7 = left pixel) for ASCII 0x20-0x7E, stored in FONT16.BIN tiles
#                         font_en.HALF_TILE.. (rarely used kanji; the font tail is reused by battles). Each row
#                         byte is expanded to 8 pixels of colour 13 (4 bytes) for the left and right halves.
#   Glyph code in the text = tile + 1, so a pair is (0x8000 | c1<<7 | c2) + 1 (max 0xBF7F: never 0xFFxx).
#
#   python patch_code.py            patch build/Disc1/0.BIN (or a copy of Disc1/0.BIN) in place
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import font_en as fe  # noqa: E402

BASE = 0x06004000
FONT_RAM = 0x00241800         # FONT16.BIN in Low WRAM (literal in the original routine)
GLYPH_BUF = 0x060622D0
DECODE_GLYPH = 0x060131D4
DECODE_END = 0x06013318          # text_put_glyph starts here; everything before it is ours (code + pool)
HALF_BASE = FONT_RAM + fe.HALF_TILE * 0x80 - 0x20 * 16   # address of the half-glyph for char code 0


class Asm:
    """Just enough SH-2 to write the glyph routine: labels, PC-relative literals, short branches."""

    def __init__(self, org):
        self.org = org
        self.code = []           # list of (kind, payload)
        self.labels = {}
        self.literals = []       # (label, value)

    def label(self, name):
        self.code.append(('label', name))

    def op(self, word):
        self.code.append(('op', word))

    def branch(self, opcode, target):
        self.code.append(('br', (opcode, target)))

    def lit(self, rn, value):
        name = f'lit{len(self.literals)}'
        self.literals.append((name, value))
        self.code.append(('lit', (rn, name)))

    def assemble(self):
        # pass 1: addresses (all instructions are 2 bytes; literal pool 4-aligned after the code)
        addr = self.org
        for kind, payload in self.code:
            if kind == 'label':
                self.labels[payload] = addr
            else:
                addr += 2
        if addr % 4:
            addr += 2
        pool = addr
        for name, value in self.literals:
            self.labels[name] = addr
            addr += 4
        # pass 2: encode
        out = bytearray()
        pc = self.org
        for kind, payload in self.code:
            if kind == 'label':
                continue
            if kind == 'op':
                w = payload
            elif kind == 'br':
                opcode, target = payload
                disp = (self.labels[target] - (pc + 4)) // 2
                assert -128 <= disp <= 127, (target, disp)
                w = opcode | (disp & 0xFF)
            else:   # mov.l @(disp,PC),Rn
                rn, name = payload
                disp = (self.labels[name] - ((pc & ~3) + 4)) // 4
                assert 0 <= disp <= 255, name
                w = 0xD000 | (rn << 8) | disp
            out += struct.pack('>H', w)
            pc += 2
        if (self.org + len(out)) % 4:
            out += struct.pack('>H', 0x0009)          # nop pad before the pool
        for name, value in self.literals:
            out += struct.pack('>I', value)
        return bytes(out)


# instruction helpers (n, m = register numbers)
def extu_w(m, n): return 0x600D | (n << 8) | (m << 4)
def mov(m, n): return 0x6003 | (n << 8) | (m << 4)
def mov_imm(i, n): return 0xE000 | (n << 8) | (i & 0xFF)
def tst(m, n): return 0x2008 | (n << 8) | (m << 4)
def and_(m, n): return 0x2009 | (n << 8) | (m << 4)
def add(m, n): return 0x300C | (n << 8) | (m << 4)
def add_imm(i, n): return 0x7000 | (n << 8) | (i & 0xFF)
def shll(n): return 0x4000 | (n << 8)
def shll2(n): return 0x4008 | (n << 8)
def shll8(n): return 0x4018 | (n << 8)
def shll16(n): return 0x4028 | (n << 8)
def shlr(n): return 0x4001 | (n << 8)
def shlr2(n): return 0x4009 | (n << 8)
def cmp_pz(n): return 0x4011 | (n << 8)
def dt(n): return 0x4010 | (n << 8)
def movb_postinc(m, n): return 0x6004 | (n << 8) | (m << 4)     # mov.b @Rm+,Rn
def movl_postinc(m, n): return 0x6006 | (n << 8) | (m << 4)     # mov.l @Rm+,Rn
def movl_store(m, n): return 0x2002 | (n << 8) | (m << 4)       # mov.l Rm,@Rn
def movl_store_disp(m, d, n): return 0x1000 | (n << 8) | (m << 4) | (d // 4)   # mov.l Rm,@(d,Rn)
RTS, NOP = 0x000B, 0x0009
BT, BF, BF_S = 0x8900, 0x8B00, 0x8F00


def glyph_routine():
    a = Asm(DECODE_GLYPH)
    a.op(extu_w(4, 4))               # r4 = tile (u16)
    a.lit(5, GLYPH_BUF)              # r5 = destination
    a.op(tst(4, 4))
    a.branch(BT, 'clear')            # tile 0 -> blank
    a.op(mov(4, 1))
    a.op(shll16(1))
    a.op(cmp_pz(1))
    a.branch(BF, 'pair')             # bit 15 set -> letter pair
    # --- normal FONT16 tile: copy 32 longwords from FONT_RAM + tile*128
    a.op(mov(4, 1))
    for op in (shll2(1), shll2(1), shll2(1), shll(1)):
        a.op(op)
    a.lit(2, FONT_RAM)
    a.op(add(2, 1))
    a.op(mov_imm(32, 3))
    a.label('copy')
    a.op(movl_postinc(1, 2))
    a.op(movl_store(2, 5))
    a.op(dt(3))
    a.branch(BF_S, 'copy')
    a.op(add_imm(4, 5))
    a.op(RTS)
    a.op(NOP)
    # --- blank glyph
    a.label('clear')
    a.op(mov_imm(0, 2))
    a.op(mov_imm(32, 3))
    a.label('clr')
    a.op(movl_store(2, 5))
    a.op(dt(3))
    a.branch(BF_S, 'clr')
    a.op(add_imm(4, 5))
    a.op(RTS)
    a.op(NOP)
    # --- letter pair
    a.label('pair')
    a.op(mov(4, 1))
    for op in (shlr2(1), shlr2(1), shlr2(1), shlr(1)):   # r1 = tile >> 7
        a.op(op)
    a.op(mov_imm(0x7F, 0))
    a.op(and_(0, 1))                 # r1 = c1
    a.op(and_(4, 0))                 # r0 = c2
    for r in (1, 0):
        a.op(shll2(r))
        a.op(shll2(r))               # * 16
    a.lit(2, HALF_BASE)
    a.op(add(2, 1))                  # r1 -> half-glyph c1
    a.op(add(0, 2))                  # r2 -> half-glyph c2
    a.op(mov_imm(16, 3))
    a.label('row')
    for k, src in enumerate((1, 2)):
        a.op(movb_postinc(src, 6))   # r6 = row bits
        a.op(shll16(6))
        a.op(shll8(6))
        a.op(mov_imm(0, 7))
        a.op(mov_imm(8, 4))
        a.label(f'bit{k}')
        a.op(shll2(7))
        a.op(shll2(7))
        a.op(shll(6))                # T = next pixel
        a.branch(BF, f'off{k}')
        a.op(add_imm(13, 7))         # ink colour 13
        a.label(f'off{k}')
        a.op(dt(4))
        a.branch(BF, f'bit{k}')
        a.op(movl_store(7, 5) if k == 0 else movl_store_disp(7, 4, 5))
    a.op(dt(3))
    a.branch(BF_S, 'row')
    a.op(add_imm(8, 5))
    a.op(RTS)
    a.op(NOP)
    return a.assemble()


def patch(data):
    code = glyph_routine()
    off = DECODE_GLYPH - BASE
    room = DECODE_END - DECODE_GLYPH
    assert len(code) <= room, (len(code), room)
    data[off:off + room] = code + struct.pack('>H', NOP) * ((room - len(code)) // 2)
    return len(code), room


def main():
    out = os.path.join(HERE, 'build', 'Disc1', '0.BIN')
    src = out if os.path.exists(out) else os.path.join(HERE, 'Disc1', '0.BIN')
    data = bytearray(open(src, 'rb').read())
    used, room = patch(data)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'wb').write(bytes(data))
    print(f'0.BIN: font16_decode_glyph replaced ({used} of {room} bytes); half-font base {HALF_BASE:#x}')


if __name__ == '__main__':
    main()
