# Run the whole pipeline: translation tables -> patched files -> both disc images -> (optionally) a .rondepatch.
#
#   python build_all.py build001 "what changed"                     test discs in build/
#   python build_all.py build001 "what changed" --release 1.0       ... and build/release/Ronde-English-1.0.rondepatch
#
# Needs Disc1/ and Disc2/ (python extract_discs.py) and the Japanese Track 1 .bin files in this folder.
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ['insert_msg.py', 'all'],                  # battle dialogue (Disc 1)
    ['insert_event.py', 'all'],                # cutscenes, town talk, tutorials
    ['ui_tool.py', 'insert'],                  # small-font UI
    ['sys_tool.py', 'insert'],                 # big-font system text
    ['kai_tool.py', 'insert'],                 # demon talk
    ['dg2_labels.py'],                         # images (Pillow + Windows fonts)
    ['disc2_tool.py'],                         # Disc 2: shared files from the Disc 1 output
    ['insert_msg.py', 'all', '--disc', 'D2'],  # battle dialogue (Disc 2)
    ['insert_event.py', 'all', '--end'],       # ending (Disc 2)
]


def run(args):
    print('>', ' '.join(args), flush=True)
    subprocess.check_call([sys.executable, '-I', '-X', 'utf8'] + [os.path.join(HERE, args[0])] + args[1:],
                          cwd=HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('name', help='build name, e.g. build001')
    ap.add_argument('note', help='one line on what changed (build/notes.txt)')
    ap.add_argument('--release', metavar='VERSION', help='also write build/release/Ronde-English-VERSION.rondepatch')
    ap.add_argument('--title', default='Ronde English Translation')
    ap.add_argument('--clean', action='store_true', help='empty build/Disc1 and build/Disc2 first')
    args = ap.parse_args()
    for d in ('Disc1', 'Disc2'):
        if not os.path.isdir(os.path.join(HERE, d)):
            sys.exit(f'{d}/ is missing: run python extract_discs.py first')
    for n in (1, 2):
        if not os.path.exists(os.path.join(HERE, f'Ronde (Japan) (Disc {n}) (Track 1).bin')):
            sys.exit(f'Ronde (Japan) (Disc {n}) (Track 1).bin is missing: put your Redump files in {HERE}')
    if args.clean:
        for d in ('Disc1', 'Disc2'):
            shutil.rmtree(os.path.join(HERE, 'build', d), ignore_errors=True)
    for d in ('Disc1', 'Disc2'):
        os.makedirs(os.path.join(HERE, 'build', d), exist_ok=True)
    for step in STEPS:
        run(step)
    run(['ui_tool.py', 'check'])
    run(['sys_tool.py', 'check'])
    run(['make_build.py', args.name, args.note, '--disc2'])
    if args.release:
        run(['patcher/make_release.py', args.name, '--version', args.release, '--title', args.title])


if __name__ == '__main__':
    main()
