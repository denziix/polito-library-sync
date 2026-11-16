"""PoliTO Sync - a small window around polito_sync.py.

Double-click "Sync PoliTO.bat" (or run: .venv\\Scripts\\pythonw.exe polito_gui.pyw).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import polito_sync as ps

ACCENT = "#0B3C6E"      # deep PoliTO-style blue
ACCENT_LIGHT = "#E8F0F9"
GREEN = "#1E7B34"
ORANGE = "#B35C00"
RED = "#B3261E"
MUTED = "#5F6B7A"
FONT = "Segoe UI"


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


class QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue) -> None:
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(("log", (record.levelno, record.getMessage())))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PoliTO Sync")
        self.geometry("860x600")
        self.minsize(700, 480)
        self.configure(bg="white")
        icon = ps.HERE / "assets" / "icon.ico"
        if icon.exists():
            try:
                self.iconbitmap(default=str(icon))
            except tk.TclError:
                pass

        self.cfg = ps.Config()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.last_file = self.cfg.state_dir / "last_run.json"
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.dry = False
        self.total_missing = 0
        self.new_files: list[str] = []
        self.row_folder: dict[str, str] = {}

        self._setup_logging()
        self._style()
        self._build()
        self._show_last_run()
        self.after(100, self._poll)

    # ------------------------------------------------------------------ setup
    def _setup_logging(self) -> None:
        ps.log.setLevel(logging.INFO)
        ps.log.propagate = False
        fh = logging.FileHandler(self.cfg.state_dir / "sync.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        ps.log.addHandler(fh)
        ps.log.addHandler(QueueHandler(self.q))

    def _style(self) -> None:
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", font=(FONT, 10), background="white")
        st.configure("TFrame", background="white")
        st.configure("Header.TFrame", background=ACCENT)
        st.configure("Title.TLabel", background=ACCENT, foreground="white", font=(FONT, 18, "bold"))
        st.configure("Sub.TLabel", background=ACCENT, foreground="#C9D8EA", font=(FONT, 9))
        st.configure("Status.TLabel", background=ACCENT_LIGHT, foreground=MUTED, padding=(12, 6))
        st.configure("Section.TLabel", foreground=MUTED, font=(FONT, 9, "bold"))
        st.configure("TButton", padding=(14, 7), font=(FONT, 10))
        st.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT)
        st.map("Accent.TButton", background=[("active", "#155A9E"), ("disabled", "#8FA6BF")])
        st.configure("Treeview", rowheight=30, font=(FONT, 10), borderwidth=0)
        st.configure("Treeview.Heading", font=(FONT, 9, "bold"), foreground=MUTED,
                     background=ACCENT_LIGHT, relief="flat", padding=(6, 6))
        st.map("Treeview", background=[("selected", "#CFE0F3")], foreground=[("selected", "black")])
        st.configure("Horizontal.TProgressbar", troughcolor=ACCENT_LIGHT, background=ACCENT,
                     bordercolor=ACCENT_LIGHT, lightcolor=ACCENT, darkcolor=ACCENT)

    def _build(self) -> None:
        # Header
        head = ttk.Frame(self, style="Header.TFrame", padding=(18, 14))
        head.pack(fill="x")
        ttk.Label(head, text="PoliTO Sync", style="Title.TLabel").pack(anchor="w")
        ttk.Label(head, text=f"Course files  →  {self.cfg.download_dir}", style="Sub.TLabel").pack(anchor="w")

        # Status bar (packed early so it always stays visible at the bottom)
        self.status = ttk.Label(self, text="Ready.", style="Status.TLabel", anchor="w")
        self.status.pack(fill="x", side="bottom")

        # Toolbar
        bar = ttk.Frame(self, padding=(16, 12, 16, 6))
        bar.pack(fill="x")
        self.btn_check = ttk.Button(bar, text="🔍  Check", command=lambda: self.run(dry=True))
        self.btn_sync = ttk.Button(bar, text="⬇  Sync now", style="Accent.TButton", command=lambda: self.run(dry=False))
        self.btn_open = ttk.Button(bar, text="📂  Open folder", command=lambda: open_path(self.cfg.download_dir))
        self.btn_sync.pack(side="left")
        self.btn_check.pack(side="left", padx=8)
        self.btn_open.pack(side="left")
        self.progress = ttk.Progressbar(bar, length=200, mode="determinate")
        self.progress.pack(side="right")

        # Course table
        ttk.Label(self, text="COURSES", style="Section.TLabel", padding=(18, 8, 0, 2)).pack(anchor="w")
        tbl = ttk.Frame(self, padding=(16, 0))
        tbl.pack(fill="both", expand=True)
        cols = ("course", "have", "new", "skipped", "status")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings", selectmode="browse", height=6)
        for col, text, width, anchor in (
            ("course", "Course", 360, "w"), ("have", "Already have", 100, "center"),
            ("new", "New", 70, "center"), ("skipped", "Skipped", 80, "center"),
            ("status", "Status", 170, "w"),
        ):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "course"))
        self.tree.tag_configure("odd", background="#F7F9FC")
        self.tree.tag_configure("new", foreground=GREEN, font=(FONT, 10, "bold"))
        self.tree.tag_configure("warn", foreground=ORANGE)
        self.tree.tag_configure("err", foreground=RED)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tbl, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", self._open_course)

        # Activity log
        ttk.Label(self, text="ACTIVITY  (double-click a course to open its folder)", style="Section.TLabel",
                  padding=(18, 10, 0, 2)).pack(anchor="w")
        logf = ttk.Frame(self, padding=(16, 0, 16, 10))
        logf.pack(fill="x")
        self.text = tk.Text(logf, height=8, wrap="word", relief="flat", bg="#FAFBFD", fg="#222",
                            font=("Consolas", 9), padx=8, pady=6, borderwidth=1, highlightthickness=1,
                            highlightbackground="#DDE3EA")
        self.text.pack(fill="x")
        for tag, color in (("ok", GREEN), ("warn", ORANGE), ("err", RED), ("muted", MUTED)):
            self.text.tag_configure(tag, foreground=color)
        self.text.configure(state="disabled")


    # ---------------------------------------------------------------- helpers
    def _log(self, msg: str, tag: str = "") -> None:
        self.text.configure(state="normal")
        self.text.insert("end", f"{datetime.now():%H:%M:%S}  {msg}\n", tag)
        self.text.see("end")
        self.text.configure(state="disabled")

    def _show_last_run(self) -> None:
        try:
            last = json.loads(self.last_file.read_text(encoding="utf-8"))
            when = datetime.fromisoformat(last["at"]).strftime("%d %b %Y, %H:%M")
            self.status.configure(text=f"Last sync: {when}  ·  {last['new']} new file(s)")
        except (OSError, ValueError, KeyError):
            self.status.configure(text="Not synced yet. Click Check to preview, or Sync now.")

    def _open_course(self, _event: object) -> None:
        sel = self.tree.selection()
        folder = self.row_folder.get(sel[0]) if sel else None
        if folder:
            new = Path(folder) / self.cfg.new_subdir if self.cfg.new_subdir else Path(folder)
            open_path(new if new.is_dir() else Path(folder))

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_check, self.btn_sync):
            b.configure(state=state)
        self.configure(cursor="watch" if busy else "")

    # ------------------------------------------------------------------- work
    def run(self, dry: bool) -> None:
        if self.busy:
            return
        self.dry = dry
        self.total_missing = 0
        self.new_files.clear()
        self.row_folder.clear()
        self.tree.delete(*self.tree.get_children())
        self.progress.configure(value=0, maximum=1)
        self._set_busy(True)
        self.status.configure(text="Checking PoliTO…" if dry else "Syncing…")
        self._log("Checking for new files (preview, nothing is downloaded)…" if dry else "Sync started…", "muted")
        threading.Thread(target=self._work, args=(dry,), daemon=True).start()

    def _work(self, dry: bool) -> None:
        try:
            api = ps.PolitoApi(self.cfg)
            new = ps.sync(api, self.cfg, dry_run=dry, progress=lambda ev, data: self.q.put((ev, data)))
            self.q.put(("done", new))
        except ps.AuthError as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:  # noqa: BLE001 - show anything to the user
            self.q.put(("error", f"{type(exc).__name__}: {exc}"))

    def _poll(self) -> None:
        try:
            while True:
                event, data = self.q.get_nowait()
                getattr(self, f"_on_{event}")(data)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _on_courses(self, n: int) -> None:
        self.progress.configure(maximum=max(n, 1), value=0)

    def _on_course(self, c: dict) -> None:
        idx = len(self.tree.get_children())
        tags = ["odd"] if idx % 2 else []
        if c.get("folder") is None:
            status, tags = "⚠  No matching folder", tags + ["warn"]
        elif c.get("error"):
            status, tags = "✖  Could not read", tags + ["err"]
        elif c["missing"]:
            status = f"⬇  {c['missing']} to download" if self.dry else f"✔  {c['missing']} downloaded"
            tags.append("new")
        else:
            status = "✔  Up to date"
        self.total_missing += c.get("missing", 0)
        iid = self.tree.insert("", "end", values=(c["name"], c["present"], c["missing"], c["skipped"], status),
                               tags=tags)
        if c.get("folder"):
            self.row_folder[iid] = c["folder"]
        self.progress.step(1)

    def _on_file(self, path: str) -> None:
        self.new_files.append(path)
        self.status.configure(text=f"Downloading…  {len(self.new_files)} file(s) so far")

    def _on_log(self, data: tuple[int, str]) -> None:
        level, msg = data
        if msg.startswith("Downloaded "):
            self._log("⬇  " + Path(msg[len("Downloaded "):]).name, "ok")
        elif level >= logging.ERROR:
            self._log(msg, "err")
        elif level >= logging.WARNING:
            self._log(msg, "warn")
        elif msg.startswith("Missing (would download): "):
            self._log("•  " + Path(msg.split(": ", 1)[1]).name, "muted")

    def _on_done(self, new: list) -> None:
        self._set_busy(False)
        self.progress.configure(value=self.progress["maximum"])
        if self.dry:
            n = self.total_missing
            msg = f"Preview done: {n} file(s) to download. Click Sync now to get them." if n else \
                "Preview done: everything is up to date."
            self.status.configure(text=msg)
            self._log(msg, "muted")
            return
        self.last_file.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                                              "new": len(new)}), encoding="utf-8")
        ps.notify(new)
        self._show_last_run()
        self._log(f"Done: {len(new)} new file(s)." if new else "Done: nothing new.", "ok" if new else "muted")

    def _on_error(self, msg: str) -> None:
        self._set_busy(False)
        self.status.configure(text="Something went wrong. See the activity box.")
        self._log(msg, "err")
        messagebox.showerror("PoliTO Sync", msg)


if __name__ == "__main__":
    App().mainloop()
