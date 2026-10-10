# Find pools of consecutive UI strings (FONT8 1-byte encoding, 0xFF-terminated, zero padding between).
#   python ui_pools.py Disc1/0.BIN [min_strings]
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ui_text as ut  # noqa: E402


def pools(data, t, min_strings=5):
    """Yield (start, end, [(offset, text, length)]) for runs of strings that follow each other directly."""
    run = []
    i = 0
    n = len(data)
    while i < n:
        j = data.find(b'\xff', i)
        if j < 0:
            break
        chunk = data[i:j]
        s = ut.decode(chunk, t) if chunk else None
        kana = sum(1 for c in (s or '') if c in ut.KANA)
        ok = s is not None and len(chunk) <= 240 and (kana >= 1 or (len(chunk) >= 2 and all(c.isascii() for c in s)))
        if ok:
            run.append((i, s, len(chunk)))
        else:
            if len(run) >= min_strings:
                yield run[0][0], run[-1][0] + run[-1][2] + 1, run
            run = []
        # next string starts after the terminator, skipping zero padding
        i = j + 1
        while i < n and data[i] == 0 and (not ok or True):
            i += 1
        if not ok:
            # resynchronise: a pool can't continue across garbage
            pass
    if len(run) >= min_strings:
        yield run[0][0], run[-1][0] + run[-1][2] + 1, run


if __name__ == '__main__':
    t = ut.load_table()
    data = open(sys.argv[1], 'rb').read()
    for start, end, run in pools(data, t, int(sys.argv[2]) if len(sys.argv) > 2 else 5):
        kana_ratio = sum(1 for _, s, _ in run for c in s if c in ut.KANA) / max(1, sum(len(s) for _, s, _ in run))
        print(f'{start:06X}-{end:06X} {len(run):4} strings, kana {kana_ratio:.0%}: ' + ' | '.join(s.strip() for _, s, _ in run[:6])[:110])
