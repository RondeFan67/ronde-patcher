# Ronde English Translation

An English translation of **Ronde** (輪舞曲, Sega Saturn, Atlus 1997, T-14415G), a Megami Tensei
strategy RPG that was only released in Japan.

Translated: all dialogue on both discs (battle, cutscenes, the ending), demon negotiation, menus, items,
spells, help text, stage cards and the in-game images with text (settings, map buttons, status headers,
the nickname keyboard, backup-memory warnings). Not translated yet: the Japanese captions burned into a few
FMVs.

This repository holds **no game files** (no disc images, no extracted files). You need your own dump of the
Japanese discs.

## About this translation

The script was translated with AI (Claude), from the original Japanese, following a style guide that keeps
names and terms consistent with the rest of the Megami Tensei series (`TRANSLATION_GUIDE.md`). It has not yet
been proofread by a fluent Japanese speaker; if you spot a mistranslation, feel free to open an issue.

## Discs

The patch needs the Japanese release, **T-14415G v1.001**, both discs. It was tested against the Redump dumps:

| Disc | Redump | Tracks | Size | CRC32 |
|---|---|---|---|---|
| Disc 1 | [redump.org/disc/2900](http://redump.org/disc/2900/) | 2 | 609,704,256 bytes | `73172835` |
| Disc 2 | [redump.org/disc/2901](http://redump.org/disc/2901/) | 3 | 620,492,880 bytes | `be025846` |

Other good dumps of v1.001 should work too: the patcher checks each file it changes, not the whole image.
CHD images must be converted to `.cue`/`.bin` first (`chdman extractcd -i game.chd -o game.cue`).

## Status: public beta

Everything is translated, and the first three chapters have been play-tested. Every text box was checked
with an automated previewer, so layout problems (lines running off the box, overlapping text) should be rare.
What has not been seen in play yet: the later chapters, Disc 2, the endings, and many demon conversations. **You are the testers.** Please report anything that looks wrong:

- Japanese text that is still showing, garbled letters, or text that runs out of its box
- a line that reads wrong, a name spelled two ways, or a mistranslation
- a crash, freeze or hang (say what you did just before)

Open an issue on this repository with a screenshot, the stage (shown on the stage card) or place, and your
emulator. The more exact, the faster it gets fixed.

## Playing: patch your discs

1. Dump both discs (a Redump-style `.cue` + `.bin` set is best; a 2048-byte `.iso` of the data track also works).
2. Download `RondePatcher-<version>.exe` from the Releases page and run it.
3. Choose your **Disc 1** and **Disc 2** (`.cue` files), choose where to save, and press **Patch**.
4. Load `Ronde (English).m3u` in your emulator (Mednafen, RetroArch's Beetle Saturn) and swap discs when the
   game asks. Emulators without `.m3u` support load each `Ronde (English) (Disc N).cue` on its own.

The patcher never changes your original files. Before writing anything it checks that each file it patches
matches the Japanese release, and afterwards it reads the patched files back to verify them. It recognises
swapped discs, already patched discs and other games.

No Windows? Run it from source with Python 3.9+ (tkinter included):

```sh
python patcher/ronde_patcher.py                       # the window
python patcher/ronde_patcher.py --disc1 "Ronde (Japan) (Disc 1).cue" --disc2 "Ronde (Japan) (Disc 2).cue" \
       --patch Ronde-English-0.1.0.rondepatch --out "Ronde (English)"
```

## Making your own translation

Everything that makes this patch is here: the text as plain TSV/JSON tables, the tools that insert it, the
code patch for the English font, and the image relabelling. Change the tables, rebuild, and ship a
`.rondepatch` file that the same patcher can apply ("Patch file: Browse...").

### Setup

- Python 3.10+ with Pillow (`pip install pillow`). The image step uses Windows fonts (Arial Bold, Tahoma,
  Tahoma Bold and Times Bold from `C:\Windows\Fonts`); on another OS, point `FONT`/`W_FONT` in
  `dg2_labels.py`, `scr_labels.py` and `nickname_kbd.py` at fonts you have.
- Put your dump in this folder under the Redump names:
  `Ronde (Japan) (Disc 1).cue`, `Ronde (Japan) (Disc 1) (Track 1).bin`, `... (Track 2).bin`, and the same for
  Disc 2 (three tracks).
- Extract the discs: `python extract_discs.py` (writes `Disc1/` and `Disc2/`, the read-only inputs).

### Where the text lives

| What | File(s) | Applied by |
|---|---|---|
| Dialogue: battles (MSG), cutscenes and towns (EVENT), the ending (END) | `mapping.json` (field `en` per block, `\n` = new sentence line; layout is automatic) | `insert_msg.py`, `insert_event.py` |
| Speaker names | `names.tsv` | same |
| Demon negotiation | `kai_strings.tsv` (column `english`; `cap` = the most letters that fit) | `kai_tool.py` |
| Small-font UI (menus, panels, item names) | `ui_strings.tsv` | `ui_tool.py` |
| Big-font system text (help, stage cards, pop-ups, names) | `sys_strings.tsv` | `sys_tool.py` |
| Images | lists at the top of `dg2_labels.py`, `sprite_labels.py`, `scr_labels.py`, `nickname_kbd.py` | `dg2_labels.py` |

Style, names and terms used by this translation are in `TRANSLATION_GUIDE.md`. Every tool prints what did
not fit.

Limits to keep in mind:

- Menu and system strings are patched in place and cannot grow past the Japanese byte length
  (`ui_tool.py check` and `sys_tool.py check` must report 0 problems).
- A battle message block is at most 543 bytes. The EVENT.BIN and END.BIN text regions are fixed
  (`insert_event.py` prints the bytes left).
- Dialogue wraps automatically (`layout.py`): 26 characters per line next to a portrait, 34 without.

### Build and test

```sh
python build_all.py build001 "my first change"          # every step, then build/Ronde [build001].m3u
python text_preview.py build001                          # build/text_preview.html: every text box, with checks
```

`text_preview.html` draws every dialogue box the way the game does, the Japanese next to the English, and
flags lines that run past the window, untranslated text and leftover Japanese.

### Release

```sh
python build_all.py build001 "release" --release 1.0     # ... + build/release/Ronde-English-0.1.0.rondepatch
pip install pyinstaller
python patcher/build_exe.py build/release/Ronde-English-0.1.0.rondepatch   # RondePatcher-1.0.exe, patch inside
```

Or make a patch from any finished build: `python patcher/make_release.py build001 --version 1.0`.

A `.rondepatch` is a zip archive: `manifest.json` (title, version, notes, and for each changed file its size,
the SHA-1 before and after) plus one XOR diff per file. It holds no complete game files; it only works with
the original discs.

## Layout

```
patcher/            the player-facing patcher (rpatch.py = format + disc handling, ronde_patcher.py = window/CLI)
build_all.py        whole pipeline in order;  extract_discs.py  discs -> Disc1/, Disc2/
insert_*.py, *_tool.py, layout.py, font_*.py, patch_code.py   text insertion, fonts, the SH-2 font patch
dg2*.py, scr*.py, sprite_labels.py, nickname_kbd.py           image formats and relabelling
text_preview.py     the in-browser text checker
```

## Credits

Translation, reverse engineering and tools: RondeFan67, with Claude (Anthropic). Ronde © Atlus 1997.
This is an unofficial fan project, not affiliated with Atlus or Sega.
