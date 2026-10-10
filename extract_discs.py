# Extract every file of your Japanese discs into Disc1/ and Disc2/, the read-only inputs of the build tools.
#
#   python extract_discs.py                       uses the Redump files in this folder:
#                                                 "Ronde (Japan) (Disc 1).cue", "Ronde (Japan) (Disc 2).cue"
#   python extract_discs.py --disc1 X.cue --disc2 Y.cue
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'patcher'))
import rpatch  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--disc1', default=os.path.join(HERE, 'Ronde (Japan) (Disc 1).cue'))
    ap.add_argument('--disc2', default=os.path.join(HERE, 'Ronde (Japan) (Disc 2).cue'))
    args = ap.parse_args()
    for n, path in ((1, args.disc1), (2, args.disc2)):
        try:
            disc = rpatch.Disc(path)
        except rpatch.PatchError as e:
            sys.exit(str(e))
        if disc.disc_number() != n:
            sys.exit(f'{path} is not Ronde (Japan) Disc {n}')
        out = os.path.join(HERE, f'Disc{n}')
        end = os.path.getsize(disc.data_path) // disc.sector
        # *.DA entries point into the CD audio tracks, not at data
        names = [name for name, (lba, size) in disc.dir.items() if lba < end]
        for name in sorted(names):
            dst = os.path.join(out, *name.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(disc.read_file(name))
        print(f'Disc {n}: {len(names)} files -> {out}')


if __name__ == '__main__':
    main()
