# Ronde English patcher: pick your Japanese Disc 1 and Disc 2 images, press Patch.
#
#   python ronde_patcher.py                                  window
#   python ronde_patcher.py --disc1 "Ronde (Japan) (Disc 1).cue" --disc2 "Ronde (Japan) (Disc 2).cue" --out out
#   python ronde_patcher.py ... --patch other.rondepatch     apply another translation
#
# Standard library only (tkinter for the window), so it also runs from source on macOS and Linux.
import argparse
import os
import queue
import sys
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rpatch  # noqa: E402

DISC_TYPES = [('Disc images', '*.cue *.bin *.iso'), ('All files', '*.*')]


def run_cli(args):
    path = args.patch or rpatch.default_patch()
    if not path:
        sys.exit('No .rondepatch file found; pass one with --patch.')
    inputs = {n: p for n, p in ((1, args.disc1), (2, args.disc2)) if p}
    if not inputs:
        sys.exit('Give --disc1 and/or --disc2.')
    try:
        patch = rpatch.Patch(path)
        out = args.out or os.path.join(os.path.dirname(os.path.abspath(next(iter(inputs.values())))),
                                       'Ronde (English)')
        last = [-1]

        def progress(done, total):
            pct = done * 100 // max(total, 1)
            if pct // 10 != last[0]:
                last[0] = pct // 10
                print(f'  {pct}%')
        written = rpatch.apply(patch, inputs, out, progress=progress)
    except rpatch.PatchError as e:
        sys.exit(f'Error: {e}')
    print('\n'.join(['Wrote:'] + ['  ' + w for w in written]))


class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.root = tk, root
        self.queue = queue.Queue()
        self.patch = None
        root.title('Ronde English Patcher')
        root.minsize(560, 420)
        frm = ttk.Frame(root, padding=12)
        frm.pack(fill='both', expand=True)
        frm.columnconfigure(1, weight=1)

        self.heading = ttk.Label(frm, font=('TkDefaultFont', 12, 'bold'))
        self.heading.grid(row=0, column=0, columnspan=3, sticky='w')
        self.notes = ttk.Label(frm, wraplength=520, foreground='#555')
        self.notes.grid(row=1, column=0, columnspan=3, sticky='w', pady=(2, 10))

        self.vars = {}
        rows = [('disc1', 'Disc 1 (.cue/.bin/.iso):', self.browse_disc),
                ('disc2', 'Disc 2 (.cue/.bin/.iso):', self.browse_disc),
                ('out', 'Save patched discs in:', self.browse_out),
                ('patch', 'Patch file:', self.browse_patch)]
        for r, (key, label, cmd) in enumerate(rows, start=2):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky='w', pady=3)
            self.vars[key] = tk.StringVar()
            # the patch box only shows which patch is loaded; Browse... changes it
            ttk.Entry(frm, textvariable=self.vars[key], state='readonly' if key == 'patch' else 'normal').grid(
                row=r, column=1, sticky='ew', padx=6)
            ttk.Button(frm, text='Browse...', command=lambda k=key, c=cmd: c(k)).grid(row=r, column=2)

        self.button = ttk.Button(frm, text='Patch', command=self.start)
        self.button.grid(row=6, column=0, columnspan=3, pady=(12, 6), ipadx=20)
        self.bar = ttk.Progressbar(frm, maximum=1000)
        self.bar.grid(row=7, column=0, columnspan=3, sticky='ew')
        self.log = tk.Text(frm, height=10, wrap='word', state='disabled', relief='flat',
                           background=root.cget('background'), font='TkDefaultFont')
        self.log.grid(row=8, column=0, columnspan=3, sticky='nsew', pady=(8, 0))
        frm.rowconfigure(8, weight=1)

        default = rpatch.default_patch()
        if default:
            self.load_patch(default)
        else:
            self.heading.config(text='Ronde patcher')
            self.notes.config(text='Choose a .rondepatch file below.')
        self.say('Choose your Japanese Ronde discs (the .cue files of a Redump-style dump work best), '
                 'then press Patch. Your original files are not changed.')
        root.after(100, self.poll)

    def say(self, text):
        self.log.config(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.config(state='disabled')

    def load_patch(self, path):
        try:
            self.patch = rpatch.Patch(path)
        except rpatch.PatchError as e:
            self.say(f'Error: {e}')
            return
        bundled = getattr(sys, '_MEIPASS', None)
        inside = bundled and os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(bundled)
        # a patch inside the .exe lives in a temporary unpack folder; show its name, not that path
        self.vars['patch'].set(f'built in: {os.path.basename(path)}' if inside else path)
        self.heading.config(text=f'{self.patch.title} {self.patch.version}')
        self.notes.config(text=self.patch.manifest.get('notes', ''))

    def browse_disc(self, key):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title=f'Ronde (Japan) Disc {key[-1]}', filetypes=DISC_TYPES)
        if p:
            self.vars[key].set(os.path.normpath(p))
            if not self.vars['out'].get():
                self.vars['out'].set(os.path.join(os.path.dirname(os.path.normpath(p)), 'Ronde (English)'))

    def browse_out(self, key):
        from tkinter import filedialog
        p = filedialog.askdirectory(title='Folder for the patched discs')
        if p:
            self.vars[key].set(os.path.normpath(p))

    def browse_patch(self, key):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title='Patch file', filetypes=[('Ronde patch', '*.rondepatch')])
        if p:
            self.load_patch(os.path.normpath(p))

    def start(self):
        from tkinter import messagebox
        inputs = {n: self.vars[f'disc{n}'].get().strip().strip('"') for n in (1, 2)}
        inputs = {n: p for n, p in inputs.items() if p}
        out = self.vars['out'].get().strip().strip('"')
        if not self.patch:
            messagebox.showerror('Ronde patcher', 'Choose a .rondepatch file first.')
            return
        if not inputs:
            messagebox.showerror('Ronde patcher', 'Choose your Disc 1 and Disc 2 images.')
            return
        if len(inputs) == 1 and not messagebox.askyesno(
                'Ronde patcher', f'Only Disc {next(iter(inputs))} was chosen. Patch just that disc?'):
            return
        if not out:
            messagebox.showerror('Ronde patcher', 'Choose a folder for the patched discs.')
            return
        if os.path.isdir(out) and any(f.startswith('Ronde (English)') for f in os.listdir(out)) and \
                not messagebox.askyesno('Ronde patcher', f'{out} already has patched discs. Replace them?'):
            return
        self.button.config(state='disabled')
        self.bar['value'] = 0
        threading.Thread(target=self.work, args=(inputs, out), daemon=True).start()

    def work(self, inputs, out):
        q = self.queue
        try:
            rpatch.apply(self.patch, inputs, out, log=lambda s: q.put(('log', s)),
                         progress=lambda d, t: q.put(('progress', d * 1000 // max(t, 1))))
            q.put(('done', out))
        except rpatch.PatchError as e:
            q.put(('error', str(e)))
        except Exception:
            q.put(('error', 'Unexpected error:\n' + traceback.format_exc()))

    def poll(self):
        from tkinter import messagebox
        try:
            while True:
                kind, val = self.queue.get_nowait()
                if kind == 'log':
                    self.say(val)
                elif kind == 'progress':
                    self.bar['value'] = val
                elif kind == 'done':
                    self.button.config(state='normal')
                    self.say(f'Patched discs are in {val}. Load "Ronde (English).m3u" (or the Disc 1 .cue) '
                             'in your emulator.')
                    messagebox.showinfo('Ronde patcher', f'Done! The patched discs are in:\n{val}')
                elif kind == 'error':
                    self.button.config(state='normal')
                    self.say(f'Error: {val}')
                    messagebox.showerror('Ronde patcher', val)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def main():
    ap = argparse.ArgumentParser(description='Ronde English patcher (no arguments: open the window)')
    ap.add_argument('--disc1', help='Japanese Disc 1: .cue, .bin or .iso')
    ap.add_argument('--disc2', help='Japanese Disc 2: .cue, .bin or .iso')
    ap.add_argument('--out', help='output folder (default: "Ronde (English)" next to Disc 1)')
    ap.add_argument('--patch', help='.rondepatch file (default: the one shipped with the patcher)')
    ap.add_argument('--info', action='store_true', help='show what the patch changes and exit')
    args = ap.parse_args()
    if args.info:
        path = args.patch or rpatch.default_patch()
        print(rpatch.describe(rpatch.Patch(path)) if path else 'No .rondepatch file found.')
        return
    if args.disc1 or args.disc2:
        run_cli(args)
        return
    import tkinter as tk
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
