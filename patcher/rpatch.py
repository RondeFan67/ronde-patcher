# Ronde patch files (.rondepatch): make them from a finished build, apply them to a player's own discs.
#
# A .rondepatch is a zip archive:
#   manifest.json        title, version, notes, and per disc the files it changes:
#                        {name: {size, src_sha1, dst_sha1, diff}}
#   disc1/EVENT.BIN ...  new file XOR original file (same size; the zip's deflate squeezes the zero runs)
#
# Only the files are patched, not whole images, so any dump of the Japanese discs works as long as those
# files match: a Redump .cue with its .bin tracks, a single-file .bin/.cue, or a 2048-byte .iso of track 1.
# Files are checked against src_sha1 before and dst_sha1 after patching.
import hashlib
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import patch_disc as pd  # noqa: E402

FORMAT = 1
PRODUCT = b'T-14415G'          # Ronde (Japan), both discs; the Saturn header says CD-1/2 or CD-2/2
SYNC = b'\x00' + b'\xff' * 10 + b'\x00'
COPY_CHUNK = 8 << 20


class PatchError(Exception):
    """A problem the player can fix (wrong disc, already patched, unreadable file): shown as is."""


def sha1(data):
    return hashlib.sha1(data).hexdigest()


def xor(a, b):
    return (int.from_bytes(a, 'little') ^ int.from_bytes(b, 'little')).to_bytes(len(a), 'little')


# --- disc images ---

class Track:
    def __init__(self, path, number, mode):
        self.path, self.number, self.mode = path, number, mode     # mode: 'MODE1/2352', 'AUDIO', ...


class Disc:
    """A disc image: the tracks of a .cue, or one .bin / .iso file. Track 1 is the ISO9660 data track."""

    def __init__(self, path):
        self.path = path
        if not os.path.isfile(path):
            raise PatchError(f'File not found: {path}')
        self.cue_lines = None
        if path.lower().endswith('.cue'):
            self.files = self._parse_cue(path)          # [(path, [Track, ...]), ...] in cue order
        else:
            self.files = [(path, [Track(path, 1, 'MODE1/?')])]
        self.data_path = self.files[0][0]
        with open(self.data_path, 'rb') as f:
            head = f.read(16)
        if head[:12] == SYNC:
            self.sector, self.data = 2352, 16
        else:
            self.sector, self.data = 2048, 0
        try:
            with open(self.data_path, 'rb') as f:
                self.header = pd.read_user(f, 0, 1, self.sector, self.data)
                self.dir = pd.find_files(f, self.sector, self.data)
        except Exception:
            raise PatchError(f'{os.path.basename(self.data_path)} is not a readable Saturn data track. '
                             'Pick the .cue file (or the Track 1 .bin) of your dump.')

    def _parse_cue(self, path):
        base = os.path.dirname(path)
        self.cue_lines = open(path, encoding='utf-8-sig', errors='replace').read().splitlines()
        files = []
        for line in self.cue_lines:
            m = re.match(r'\s*FILE\s+"(.+)"\s+\S+', line, re.I) or re.match(r'\s*FILE\s+(\S+)\s+\S+', line, re.I)
            if m:
                p = os.path.join(base, m.group(1))
                if not os.path.isfile(p):
                    raise PatchError(f'{os.path.basename(path)} lists "{m.group(1)}", which is not in the same '
                                     'folder.')
                files.append((p, []))
                continue
            m = re.match(r'\s*TRACK\s+(\d+)\s+(\S+)', line, re.I)
            if m and files:
                files[-1][1].append(Track(files[-1][0], int(m.group(1)), m.group(2).upper()))
        if not files or not files[0][1] or files[0][1][0].mode == 'AUDIO':
            raise PatchError(f'{os.path.basename(path)}: the first track is not a data track.')
        return files

    def disc_number(self):
        """1 or 2 from the Saturn header, None if this is not Ronde."""
        if self.header[:16] != b'SEGA SEGASATURN ' or self.header[0x20:0x28] != PRODUCT:
            return None
        m = re.match(rb'CD-(\d)/2', self.header[0x38:0x40])
        return int(m.group(1)) if m else None

    def title(self):
        return self.header[0x60:0xD0].decode('ascii', 'replace').strip() if self.header[:4] == b'SEGA' else '?'

    def read_file(self, name):
        lba, size = self.dir[name]
        with open(self.data_path, 'rb') as f:
            return pd.read_user(f, lba, (size + pd.USER - 1) // pd.USER, self.sector, self.data)[:size]


def write_file(f, disc, lba, old, new):
    """Write `new` over the file at `lba` in an open copy of the data track; returns sectors rewritten."""
    changed = 0
    for i in range(0, len(new), pd.USER):
        chunk = new[i:i + pd.USER]
        if old[i:i + pd.USER] == chunk:
            continue
        s = lba + i // pd.USER
        f.seek(s * disc.sector)
        sec = bytearray(f.read(disc.sector))
        sec[disc.data:disc.data + len(chunk)] = chunk
        if disc.sector == 2352:
            pd.fix_sector(sec)
        f.seek(s * disc.sector)
        f.write(sec)
        changed += 1
    return changed


def copy_file(src, dst, progress=None, done=0, total=0):
    with open(src, 'rb') as fi, open(dst, 'wb') as fo:
        while True:
            buf = fi.read(COPY_CHUNK)
            if not buf:
                break
            fo.write(buf)
            done += len(buf)
            if progress:
                progress(done, total)
    return done


# --- patch files ---

class Patch:
    def __init__(self, path):
        self.path = path
        try:
            self.zip = zipfile.ZipFile(path)
            self.manifest = json.loads(self.zip.read('manifest.json'))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            raise PatchError(f'{os.path.basename(path)} is not a Ronde patch file.')
        if self.manifest.get('format') != FORMAT:
            raise PatchError(f'{os.path.basename(path)} needs a newer patcher (format {self.manifest.get("format")}).')

    @property
    def title(self):
        return self.manifest.get('title', 'Ronde patch')

    @property
    def version(self):
        return self.manifest.get('version', '')

    def discs(self):
        return sorted(int(n) for n in self.manifest['discs'])

    def files(self, n):
        return self.manifest['discs'][str(n)]['files']


def make_patch(out_path, discs, title, version, notes='', credits=''):
    """discs = {1: (original Disc, patched Disc), 2: ...}: store every file that differs."""
    manifest = {'format': FORMAT, 'game': 'Ronde (Japan)', 'product': PRODUCT.decode(), 'title': title,
                'version': version, 'notes': notes, 'credits': credits, 'discs': {}}
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n, (orig, new) in sorted(discs.items()):
            files = {}
            for name in sorted(new.dir):
                if name not in orig.dir:
                    raise PatchError(f'Disc {n}: {name} is not on the original disc')
                if new.dir[name] != orig.dir[name]:
                    raise PatchError(f'Disc {n}: {name} moved or changed size (only in-place patches are supported)')
                a, b = orig.read_file(name), new.read_file(name)
                if a == b:
                    continue
                diff = f'disc{n}/{name}'
                z.writestr(diff, xor(a, b))
                files[name] = {'size': len(a), 'src_sha1': sha1(a), 'dst_sha1': sha1(b), 'diff': diff}
            manifest['discs'][str(n)] = {'files': files}
        z.writestr('manifest.json', json.dumps(manifest, indent=1))
    return manifest


# --- applying ---

def check_disc(patch, n, disc):
    """Raise PatchError unless `disc` is Disc n with every file the patch changes in its original state.
    Returns {name: original bytes}."""
    got = disc.disc_number()
    label = os.path.basename(disc.path)
    if got is None:
        raise PatchError(f'{label} is not Ronde (Japan): the disc header says "{disc.title()}".')
    if got != n:
        raise PatchError(f'{label} is Disc {got}, not Disc {n}. Swap the two boxes.')
    orig = {}
    for name, info in patch.files(n).items():
        if name not in disc.dir:
            raise PatchError(f'{label}: {name} is missing; this is not a dump of the Japanese release.')
        data = disc.read_file(name)
        h = sha1(data)
        if h == info['dst_sha1']:
            raise PatchError(f'{label} is already patched ({name}). Use your original Japanese dump.')
        if h != info['src_sha1']:
            raise PatchError(f'{label}: {name} does not match the Japanese release (bad dump or another '
                             'patch already applied).')
        orig[name] = data
    return orig


def out_names(n, disc):
    """Output file name for each input file of the disc: 'Ronde (English) (Disc 1) (Track 1).bin', ..."""
    names = {}
    for path, tracks in disc.files:
        ext = os.path.splitext(path)[1].lower() or '.bin'
        if len(disc.files) == 1:
            names[path] = f'Ronde (English) (Disc {n}){ext}'
        else:
            names[path] = f'Ronde (English) (Disc {n}) (Track {tracks[0].number if tracks else 1}){ext}'
    return names


def apply(patch, inputs, out_dir, log=print, progress=None):
    """inputs = {1: path, 2: path}. Writes the patched discs into out_dir; returns the files written."""
    log(f'{patch.title} {patch.version}')
    discs = {}
    for n, path in sorted(inputs.items()):
        if str(n) not in patch.manifest['discs']:
            raise PatchError(f'This patch has nothing for Disc {n}.')
        log(f'Checking Disc {n}: {os.path.basename(path)}')
        disc = Disc(path)
        discs[n] = (disc, check_disc(patch, n, disc))
    os.makedirs(out_dir, exist_ok=True)
    inputs_abs = {os.path.normcase(os.path.abspath(p)) for d, _ in discs.values() for p, _ in d.files}
    total = sum(os.path.getsize(p) for d, _ in discs.values() for p, _ in d.files)
    done = 0
    written = []
    cues = {}
    for n, (disc, orig) in sorted(discs.items()):
        names = out_names(n, disc)
        for src, _ in disc.files:
            dst = os.path.join(out_dir, names[src])
            if os.path.normcase(os.path.abspath(dst)) in inputs_abs:
                raise PatchError(f'The output would overwrite your original {names[src]}; choose another folder.')
        log(f'Writing Disc {n}')
        for src, _ in disc.files:
            dst = os.path.join(out_dir, names[src])
            done = copy_file(src, dst, progress, done, total)
            written.append(dst)
        dst = os.path.join(out_dir, names[disc.data_path])
        with open(dst, 'r+b') as f:
            for name, info in sorted(patch.files(n).items()):
                new = xor(orig[name], patch.zip.read(info['diff']))
                if sha1(new) != info['dst_sha1']:
                    raise PatchError(f'The patch file is damaged ({info["diff"]}). Download it again.')
                write_file(f, disc, disc.dir[name][0], orig[name], new)
        # read the written track back: the patched files must come out exactly as built
        check = Disc(dst)
        for name, info in patch.files(n).items():
            if sha1(check.read_file(name)) != info['dst_sha1']:
                raise PatchError(f'Disc {n}: {name} did not verify after writing. Is the disk full?')
        log(f'  {len(patch.files(n))} files patched and verified')
        cue = os.path.join(out_dir, f'Ronde (English) (Disc {n}).cue')
        if disc.cue_lines is not None or disc.sector == 2352:
            write_cue(cue, disc, names)
            written.append(cue)
            cues[n] = cue
        else:
            cues[n] = dst
    if len(cues) == 2:
        m3u = os.path.join(out_dir, 'Ronde (English).m3u')
        with open(m3u, 'w', encoding='utf-8') as f:
            f.write(''.join(os.path.basename(cues[n]) + '\n' for n in sorted(cues)))
        written.append(m3u)
    if progress:
        progress(total, total)
    log('Done.')
    return written


def write_cue(path, disc, names):
    if disc.cue_lines is None:          # a lone raw track 1: write a cue for it
        lines = [f'FILE "{names[disc.data_path]}" BINARY', '  TRACK 01 MODE1/2352', '    INDEX 01 00:00:00']
    else:
        lines = []
        it = iter(disc.files)
        for line in disc.cue_lines:
            if re.match(r'\s*FILE\s', line, re.I):
                src, _ = next(it)
                ftype = line.rstrip().split()[-1]
                line = f'FILE "{names[src]}" {ftype}'
            lines.append(line)
    with open(path, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write('\n'.join(lines) + '\n')


def default_patch():
    """The patch file shipped with the patcher: inside the .exe (PyInstaller), else next to it / this script."""
    dirs = [getattr(sys, '_MEIPASS', None), os.path.dirname(os.path.abspath(sys.argv[0])), HERE]
    for d in dirs:
        if d and os.path.isdir(d):
            found = sorted(f for f in os.listdir(d) if f.lower().endswith('.rondepatch'))
            if found:
                return os.path.join(d, found[-1])
    return None


def describe(patch):
    lines = [f'{patch.title} {patch.version}']
    for n in patch.discs():
        lines.append(f'Disc {n}: {len(patch.files(n))} files: {", ".join(sorted(patch.files(n)))}')
    return '\n'.join(lines)
