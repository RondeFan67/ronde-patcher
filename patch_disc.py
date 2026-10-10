# Write replacement files into a copy of a MODE1/2352 disc image, recomputing EDC/ECC.
# Replacement files must be the same size as the originals (no ISO9660 rebuild).
#
#   python patch_disc.py "<source track1.bin>" "<output track1.bin>" EVENT.BIN=build/Disc1/EVENT.BIN FONT16.BIN=...
#   python patch_disc.py --selftest "<track1.bin>"     check EDC/ECC code against the original sectors
import os
import shutil
import struct
import sys

SECTOR = 2352
DATA = 16          # user data offset in a MODE1 sector
USER = 2048

# --- EDC/ECC (CD-ROM mode 1), as in the ECMA-130 standard ---
ECC_F = [0] * 256
ECC_B = [0] * 256
EDC_LUT = [0] * 256
for i in range(256):
    j = ((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF
    ECC_F[i] = j
    ECC_B[i ^ j] = i
    edc = i
    for _ in range(8):
        edc = (edc >> 1) ^ (0xD8018001 if edc & 1 else 0)
    EDC_LUT[i] = edc


def edc(buf):
    e = 0
    for b in buf:
        e = (e >> 8) ^ EDC_LUT[(e ^ b) & 0xFF]
    return e


def ecc_block(sec, major_count, minor_count, major_mult, minor_inc, dest):
    src = 0xC
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = sec[src + index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = ECC_F[a]
        a = ECC_B[ECC_F[a] ^ b]
        sec[dest + major] = a
        sec[dest + major + major_count] = a ^ b


def fix_sector(sec):
    """Recompute EDC and P/Q parity of a mode 1 sector (bytearray of 2352)."""
    struct.pack_into('<I', sec, 0x810, edc(sec[0:0x810]))
    sec[0x814:0x81C] = bytes(8)
    ecc_block(sec, 86, 24, 2, 86, 0x81C)
    ecc_block(sec, 52, 43, 86, 88, 0x8C8)


# --- ISO9660 ---
def read_user(f, lba, count=1, sector=SECTOR, data=DATA):
    """User data of `count` sectors. sector/data = 2048/0 for a plain .iso image."""
    out = bytearray()
    for i in range(count):
        f.seek((lba + i) * sector + data)
        out += f.read(USER)
    return bytes(out)


def find_files(f, sector=SECTOR, data=DATA):
    """Return {NAME: (lba, size)} for every file in the image (walks all directories)."""
    pvd = read_user(f, 16, 1, sector, data)
    assert pvd[1:6] == b'CD001', 'no ISO9660 volume descriptor'
    files = {}

    def walk(lba, size, prefix):
        recs = read_user(f, lba, (size + USER - 1) // USER, sector, data)
        pos = 0
        while pos < size:
            ln = recs[pos]
            if ln == 0:
                pos = (pos // USER + 1) * USER
                continue
            rec = recs[pos:pos + ln]
            ext, sz, flags, nlen = struct.unpack_from('<I', rec, 2)[0], struct.unpack_from('<I', rec, 10)[0], rec[25], rec[32]
            name = rec[33:33 + nlen]
            if name not in (b'\0', b'\1'):
                nm = name.decode('ascii').split(';')[0]
                if flags & 2:
                    walk(ext, sz, prefix + nm + '/')
                else:
                    files[prefix + nm] = (ext, sz)
            pos += ln

    root = pvd[156:156 + 34]
    walk(struct.unpack_from('<I', root, 2)[0], struct.unpack_from('<I', root, 10)[0], '')
    return files


def selftest(path, n=40):
    with open(path, 'rb') as f:
        files = find_files(f)
        lba = files['EVENT.BIN'][0]
        ok = 0
        for s in range(lba, lba + n):
            f.seek(s * SECTOR)
            orig = f.read(SECTOR)
            sec = bytearray(orig)
            fix_sector(sec)
            ok += sec == orig
    print(f'{len(files)} files found; EDC/ECC recomputed identically for {ok}/{n} sectors')
    return ok == n


def main():
    if sys.argv[1] == '--selftest':
        sys.exit(0 if selftest(sys.argv[2]) else 1)
    src, dst, repl = sys.argv[1], sys.argv[2], sys.argv[3:]
    if os.path.abspath(src) == os.path.abspath(dst):
        sys.exit('refusing to overwrite the source image')
    shutil.copyfile(src, dst)
    with open(dst, 'r+b') as f:
        files = find_files(f)
        for spec in repl:
            name, path = spec.split('=', 1)
            lba, size = files[name]
            new = open(path, 'rb').read()
            if len(new) != size:
                sys.exit(f'{name}: size {len(new)} differs from original {size}')
            changed = 0
            for i in range(0, size, USER):
                chunk = new[i:i + USER]
                s = lba + i // USER
                f.seek(s * SECTOR)
                sec = bytearray(f.read(SECTOR))
                if sec[DATA:DATA + len(chunk)] == chunk:
                    continue
                sec[DATA:DATA + len(chunk)] = chunk
                fix_sector(sec)
                f.seek(s * SECTOR)
                f.write(sec)
                changed += 1
            print(f'{name}: LBA {lba}, {changed} sectors rewritten')


if __name__ == '__main__':
    main()
