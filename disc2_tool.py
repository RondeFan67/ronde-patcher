# Build the Disc 2 data files (build/Disc2) from the finished Disc 1 output.
#
#   python disc2_tool.py        run after the whole Disc 1 pipeline, before insert_msg.py all --disc D2
#
# Disc 2 shares most files with Disc 1:
# - byte-identical files (fonts, KAI, help, title cards, images...) are copied from build/Disc1;
# - 0.BIN, WORLD.BIN, REMIX.BIN, EVENT.BIN differ from Disc 1 by a few bytes of code (disc number, movie
#   names); every string is at the same offset, so the Disc 1 output is taken and those Disc 2 bytes are put
#   back (checked: the translation never touches them);
# - SMAP.BIN is laid out differently (Disc 2's MSG tables and field data), but holds the same 38 messages and
#   UI pools at other offsets: each translated row is moved to where its original bytes are on Disc 2.
#   Rows whose original bytes occur more than once take the offset shift of the nearest unique row.
import csv
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
D1, D2 = os.path.join(HERE, 'Disc1'), os.path.join(HERE, 'Disc2')
B1, B2 = os.path.join(HERE, 'build', 'Disc1'), os.path.join(HERE, 'build', 'Disc2')
PATCHED = ['0.BIN', 'WORLD.BIN', 'REMIX.BIN', 'EVENT.BIN']


def read(*p):
    return open(os.path.join(*p), 'rb').read()


def rows(tsv):
    with open(os.path.join(HERE, tsv), encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh, delimiter='\t'))


def main():
    os.makedirs(B2, exist_ok=True)
    copied = []
    for f in sorted(os.listdir(B1)):
        if f in PATCHED or f == 'SMAP.BIN' or not os.path.exists(os.path.join(D2, f)):
            continue
        if hashlib.md5(read(D1, f)).digest() == hashlib.md5(read(D2, f)).digest():
            shutil.copyfile(os.path.join(B1, f), os.path.join(B2, f))
            copied.append(f)
    print(f'copied {len(copied)} identical files')

    for f in PATCHED:
        o1, o2, b1 = read(D1, f), read(D2, f), bytearray(read(B1, f))
        diff = [i for i in range(len(o1)) if o1[i] != o2[i]]
        touched = [i for i in diff if b1[i] != o1[i]]
        if touched:
            sys.exit(f'{f}: the translation changed bytes Disc 2 differs in: {[hex(i) for i in touched[:8]]}')
        for i in diff:
            b1[i] = o2[i]
        open(os.path.join(B2, f), 'wb').write(bytes(b1))
        print(f'{f}: Disc 1 output + {len(diff)} Disc 2 bytes')

    s1, s2, sb = read(D1, 'SMAP.BIN'), read(D2, 'SMAP.BIN'), read(B1, 'SMAP.BIN')
    out = bytearray(s2)
    todo = []
    for tsv in ('sys_strings.tsv', 'ui_strings.tsv'):
        for r in rows(tsv):
            if r['file'] == 'SMAP.BIN' and r['english']:
                off, mx = int(r['offset'], 16), int(r['max'])
                if sb[off:off + mx] != s1[off:off + mx]:
                    todo.append((off, mx, r['id']))
    shifts = {}
    for off, mx, rid in todo:
        i = s2.find(s1[off:off + mx])
        if i >= 0 and s2.find(s1[off:off + mx], i + 1) < 0:
            shifts[off] = i - off
    moved = 0
    for off, mx, rid in todo:
        if off in shifts:
            to = off + shifts[off]
        else:
            near = min(shifts, key=lambda k: abs(k - off))
            to = off + shifts[near]
            if s2[to:to + mx] != s1[off:off + mx]:
                sys.exit(f'SMAP {rid}: no unique Disc 2 position')
        out[to:to + mx] = sb[off:off + mx]
        moved += 1
    open(os.path.join(B2, 'SMAP.BIN'), 'wb').write(bytes(out))
    print(f'SMAP.BIN: {moved} translated strings placed (shifts used: {sorted(set(shifts.values()))[:6]})')


if __name__ == '__main__':
    main()
