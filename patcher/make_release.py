# Make a .rondepatch from a finished build (the disc images make_build.py wrote, i.e. exactly what was tested).
#
#   python patcher/make_release.py build001 --version 1.0
#   python patcher/make_release.py build001 --version 1.0 --title "Ronde English (my edit)" --out my.rondepatch
#
# Compares each build's track 1 with the original Japanese track 1 (Redump names, in the repository folder) file by file.
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import rpatch  # noqa: E402

ORIGINAL = 'Ronde (Japan) (Disc {n}) (Track 1).bin'
BUILT = 'Ronde (Disc {n}) (Track 1) [{name}].bin'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('build', help='build name, e.g. build001')
    ap.add_argument('--version', required=True)
    ap.add_argument('--title', default='Ronde English Translation')
    ap.add_argument('--notes', default='', help='shown in the patcher (what this release is)')
    ap.add_argument('--credits', default='')
    ap.add_argument('--out', help='output file (default build/release/Ronde-English-<version>.rondepatch)')
    ap.add_argument('--build-dir', default=os.path.join(ROOT, 'build'))
    ap.add_argument('--originals', default=ROOT, help='folder holding the Japanese Track 1 .bin files')
    args = ap.parse_args()

    discs = {}
    for n in (1, 2):
        new = os.path.join(args.build_dir, BUILT.format(n=n, name=args.build))
        if not os.path.exists(new):
            if n == 1:
                sys.exit(f'not found: {new}')
            print(f'no Disc 2 in build {args.build}; patching Disc 1 only')
            continue
        discs[n] = (rpatch.Disc(os.path.join(args.originals, ORIGINAL.format(n=n))), rpatch.Disc(new))
    out = args.out or os.path.join(args.build_dir, 'release', f'Ronde-English-{args.version}.rondepatch')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    m = rpatch.make_patch(out, discs, args.title, args.version,
                          notes=args.notes or f'Made from build {args.build}.', credits=args.credits)
    for n, d in sorted(m['discs'].items()):
        print(f'Disc {n}: {len(d["files"])} files changed: {", ".join(sorted(d["files"]))}')
    print(f'{out}: {os.path.getsize(out):,} bytes')


if __name__ == '__main__':
    main()
