# Bundle the patcher and a .rondepatch into one program for players (needs `pip install pyinstaller`).
#
#   python patcher/build_exe.py build/release/Ronde-English-1.0.rondepatch
#
# Writes build/release/RondePatcher-<version>.exe (on Windows; PyInstaller builds for the OS it runs on).
# The .rondepatch is embedded; the patcher also finds one placed next to the program.
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import rpatch  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('patch', help='the .rondepatch to embed')
    ap.add_argument('--out', default=os.path.join(ROOT, 'build', 'release'))
    args = ap.parse_args()
    try:
        import tkinter  # noqa: F401  (without it the program would only work from the command line)
    except ImportError:
        sys.exit('This Python has no tkinter; build with one that does (the python.org installer includes it).')
    patch = rpatch.Patch(args.patch)
    name = f'RondePatcher-{patch.version}'
    sep = ';' if os.name == 'nt' else ':'
    with tempfile.TemporaryDirectory() as work:
        subprocess.check_call([
            sys.executable, '-m', 'PyInstaller', '--onefile', '--windowed', '--noconfirm', '--clean',
            '--name', name, '--distpath', args.out, '--workpath', work, '--specpath', work,
            '--paths', ROOT, '--hidden-import', 'patch_disc',
            '--add-data', f'{os.path.abspath(args.patch)}{sep}.',
            os.path.join(HERE, 'ronde_patcher.py')])
    print(f'wrote {os.path.join(args.out, name)}{".exe" if os.name == "nt" else ""}')


if __name__ == '__main__':
    main()
