# Make test discs from the files in build/Disc1 (and build/Disc2), log the build in build/notes.txt and write
# build/text_preview.html for it.
#
#   python make_build.py build001 "what changed" --disc2
#   python make_build.py build001 "..." --files EVENT.BIN FONT16.BIN     choose which files to replace
import argparse
import datetime
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, 'build')
SOURCE_TRACK1 = os.path.join(HERE, 'Ronde (Japan) (Disc 1) (Track 1).bin')
TRACK2 = 'Ronde (Japan) (Disc 1) (Track 2).bin'   # the unmodified audio track, straight from the original rip
# every translated file in build/Disc1
FILES = {f: os.path.join(BUILD, 'Disc1', f) for f in sorted(os.listdir(os.path.join(BUILD, 'Disc1')))}

# Testing shortcuts (off by default, --skips turns them on). Movies are swapped for the 40-frame
# EV_042.AVI by renaming them in the file that plays them; names keep the same length.
SHORT_MOVIE = b'EV_042.AVI'
SKIPS = {
    'OPEN.BIN': [(0x20, b'OPEN.AVI\0\0', SHORT_MOVIE)],          # opening poem movie
    'EVENT.BIN': [(0xC8C, b'EV_001.AVI', SHORT_MOVIE),             # "July 2008 Tokyo" + lab scene
                  (0xC98, b'EV_002.AVI', SHORT_MOVIE)],            # "August 2008" + museum scene
}


def apply_skips(files):
    """Write shortcut copies into build/common and return the file map pointing at them."""
    out = dict(files)
    os.makedirs(os.path.join(BUILD, 'common'), exist_ok=True)
    for name, patches in SKIPS.items():
        src = files.get(name, os.path.join(HERE, 'Disc1', name))
        data = bytearray(open(src, 'rb').read())
        for off, old, new in patches:
            if data[off:off + len(old)] != old:
                sys.exit(f'{name}: expected {old!r} at {off:#x}')
            data[off:off + len(new)] = new
        dst = os.path.join(BUILD, 'common', name.replace('.BIN', '.skips.BIN'))
        open(dst, 'wb').write(bytes(data))
        out[name] = dst
    return out

def apply_code(files, disc='Disc1'):
    """Code patches (patch_code.py) are always applied: the text relies on runtime letter pairs."""
    sys.path.insert(0, HERE)
    import patch_code
    out = dict(files)
    data = bytearray(open(files.get('0.BIN', os.path.join(HERE, disc, '0.BIN')), 'rb').read())
    patch_code.patch(data)
    dst = os.path.join(BUILD, 'common', '0.code.BIN' if disc == 'Disc1' else '0.code2.BIN')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, 'wb').write(bytes(data))
    out['0.BIN'] = dst
    return out


SOURCE_D2 = os.path.join(HERE, 'Ronde (Japan) (Disc 2) (Track 1).bin')
# Audio tracks are used straight from the original rip. They are hard-linked into build/ (copied if linking fails)
# so the cues hold plain file names: BizHawk does not resolve "../" paths in a cue loaded through an .m3u.
CUE_D2 = '''CATALOG 0000000000000
FILE "{track1}" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
FILE "Ronde (Japan) (Disc 2) (Track 2).bin" BINARY
  TRACK 02 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
FILE "Ronde (Japan) (Disc 2) (Track 3).bin" BINARY
  TRACK 03 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
'''

CUE = '''CATALOG 0000000000000
FILE "{track1}" BINARY
  TRACK 01 MODE1/2352
    INDEX 01 00:00:00
FILE "{track2}" BINARY
  TRACK 02 AUDIO
    INDEX 00 00:00:00
    INDEX 01 00:02:00
'''


def link_audio(*names):
    """Make the original audio tracks available in build/ next to the cues (hard link, else copy)."""
    for name in names:
        dst = os.path.join(BUILD, name)
        if not os.path.exists(dst):
            try:
                os.link(os.path.join(HERE, name), dst)
            except OSError:
                shutil.copyfile(os.path.join(HERE, name), dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('name')
    ap.add_argument('note')
    ap.add_argument('--files', nargs='+', help='only replace these files (default: all translated files)')
    ap.add_argument('--skips', action='store_true', help='swap the opening and intro movies for a short clip')
    ap.add_argument('--disc2', action='store_true',
                    help='also build Disc 2 from build/Disc2 and a "Ronde [name].m3u" listing both discs')
    args = ap.parse_args()
    if any(c in args.name for c in '[]/\\'):
        sys.exit('build name must not contain [ ] / \\')
    files = apply_code(FILES)
    files = apply_skips(files) if args.skips else files
    track1 = f'Ronde (Disc 1) (Track 1) [{args.name}].bin'
    repl = [f'{f}={files[f]}' for f in (args.files or files)]
    subprocess.check_call([sys.executable, '-I', os.path.join(HERE, 'patch_disc.py'), SOURCE_TRACK1,
                           os.path.join(BUILD, track1)] + repl)
    with open(os.path.join(BUILD, f'Ronde (Disc 1) [{args.name}].cue'), 'w', encoding='utf-8') as f:
        f.write(CUE.format(track1=track1, track2=TRACK2))
    link_audio(TRACK2)
    if args.disc2:
        d2 = {f: os.path.join(BUILD, 'Disc2', f) for f in sorted(os.listdir(os.path.join(BUILD, 'Disc2')))}
        d2 = apply_code(d2, 'Disc2')
        track1_d2 = f'Ronde (Disc 2) (Track 1) [{args.name}].bin'
        subprocess.check_call([sys.executable, '-I', os.path.join(HERE, 'patch_disc.py'), SOURCE_D2,
                               os.path.join(BUILD, track1_d2)] + [f'{f}={p}' for f, p in d2.items()])
        with open(os.path.join(BUILD, f'Ronde (Disc 2) [{args.name}].cue'), 'w', encoding='utf-8') as f:
            f.write(CUE_D2.format(track1=track1_d2))
        link_audio('Ronde (Japan) (Disc 2) (Track 2).bin', 'Ronde (Japan) (Disc 2) (Track 3).bin')
        with open(os.path.join(BUILD, f'Ronde [{args.name}].m3u'), 'w', encoding='utf-8') as f:
            f.write(f'Ronde (Disc 1) [{args.name}].cue\nRonde (Disc 2) [{args.name}].cue\n')

    notes_path = os.path.join(BUILD, 'notes.txt')
    lines = []
    if os.path.exists(notes_path):
        lines = [l for l in open(notes_path, encoding='utf-8').read().splitlines()
                 if not l.startswith(args.name + '\t')]
    lines.insert(0, f'{args.name}\t{args.note}')   # newest first
    open(notes_path, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    if os.path.exists(os.path.join(HERE, 'use_build.py')):    # optional hook: point an emulator shortcut at it
        subprocess.check_call([sys.executable, '-I', os.path.join(HERE, 'use_build.py'), args.name])
    # every dialogue box of the new discs, drawn in the browser, with the automatic checks (build/text_preview.html)
    subprocess.call([sys.executable, '-I', '-X', 'utf8', os.path.join(HERE, 'text_preview.py'), args.name,
                     '--build', BUILD])


if __name__ == '__main__':
    main()
