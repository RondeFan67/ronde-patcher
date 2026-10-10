# Page/line layout for English dialogue boxes.
#
# Boxes show the speaker name + 2 lines on the first page and up to 3 lines on later pages (measured from
# the Japanese script). Pages are filled sentence by sentence so breaks fall between sentences; a sentence
# that needs several pages is split at clause boundaries first and its words are spread evenly so no page
# is left with a one- or two-word orphan. Paragraphs missing end punctuation get a full stop.
import re
import textwrap

END_PUNCT = '.!?"\')~'


def punctuate(p):
    p = p.strip()
    if p and p[-1].isalnum():
        p += '.'
    return p


def wrap(text, width):
    return textwrap.wrap(text, width, break_long_words=True, break_on_hyphens=False) or ['']


def sentences(p):
    """Split a paragraph after . ! ? (keeping '...' and quotes attached)."""
    parts = re.split(r'(?<=[.!?])["\']?\s+(?=\S)', p)
    # re.split drops the matched quote; re-split more carefully to keep it
    out, i = [], 0
    for m in re.finditer(r'[.!?]+["\']?\s+(?=\S)', p):
        out.append(p[i:m.end()].strip())
        i = m.end()
    out.append(p[i:].strip())
    return [s for s in out if s] or parts


def clauses(s):
    out, i = [], 0
    for m in re.finditer(r'[,;:]\s+(?=\S)|\s+-\s+', s):
        out.append(s[i:m.end()].strip())
        i = m.end()
    out.append(s[i:].strip())
    return [c for c in out if c]


def split_even(text, width, caps):
    """Split text (too long for one page) over pages with capacities caps[0], caps[1]...; balance word counts."""
    words = text.split()
    # how many pages are needed with greedy wrapping?
    lines = wrap(text, width)
    pages, k, need = [], 0, 0
    remaining = len(lines)
    while remaining > 0:
        remaining -= caps[min(k, len(caps) - 1)]
        k += 1
    need = k
    # distribute characters evenly over `need` pages, never exceeding a page's line capacity
    total = len(text)
    start = 0
    for i in range(need):
        cap = caps[min(i, len(caps) - 1)]
        if i == need - 1:
            chunk = words[start:]
        else:
            target = total * (i + 1) / need
            end = start + 1
            # grow while the page still fits and we're below the target
            while end < len(words) and len(' '.join(words[:end + 1])) <= target and \
                    len(wrap(' '.join(words[start:end + 1]), width)) <= cap:
                end += 1
            # make sure the remaining pages can still hold the rest
            chunk = words[start:end]
            start = end
        pages.append(wrap(' '.join(chunk), width))
    # safety: if any page overflowed, fall back to plain greedy pagination
    if any(len(pg) > caps[min(i, len(caps) - 1)] for i, pg in enumerate(pages)):
        pages, lines = [], wrap(text, width)
        i = 0
        while lines:
            cap = caps[min(i, len(caps) - 1)]
            pages.append(lines[:cap])
            lines = lines[cap:]
            i += 1
    return pages


def paginate(paragraphs, width, first_cap, later_cap):
    """Return a list of pages (each a list of lines) for a speaker section."""
    pages = []

    def cap_now():
        return first_cap if not pages else later_cap

    for para in paragraphs:
        para = punctuate(para)
        cur = ''
        units = []
        for s in sentences(para):
            # a sentence that can't fit on a full later page is broken into clauses
            units += clauses(s) if len(wrap(s, width)) > later_cap else [s]
        for u in units:
            trial = (cur + ' ' + u).strip()
            if len(wrap(trial, width)) <= cap_now():
                cur = trial
                continue
            # (a short opener like "Satoshi!" or "Ahem!" may stay alone on its page: that reads as a beat. Folding
            # it into the next sentence breaks pages mid-sentence instead.)
            if cur:
                pages.append(wrap(cur, width))
                cur = ''
            if len(wrap(u, width)) <= cap_now():
                cur = u
            else:
                caps = [cap_now()] + [later_cap] * 20
                split = split_even(u, width, caps)
                pages += split[:-1]
                cur = ' '.join(split[-1])
        if cur:
            pages.append(wrap(cur, width))
    return pages
