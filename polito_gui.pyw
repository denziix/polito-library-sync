"""PoliTO Sync - a small window around polito_sync.py.

Double-click "Sync PoliTO.bat" (or run: .venv\\Scripts\\pythonw.exe polito_gui.pyw).
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import polito_sync as ps

ACCENT = "#0B3C6E"      # deep PoliTO-style blue
ACCENT_LIGHT = "#E8F0F9"
GREEN = "#1E7B34"
ORANGE = "#B35C00"
RED = "#B3261E"
MUTED = "#5F6B7A"
FONT = "Segoe UI"
ALL_COURSES = "All courses"
KIND_COLORS = {"Seminar / talk": "#6A3FB5", "Exam": RED, "Deadline": ORANGE, "Class change": "#155A9E",
               "Lab / exercise": GREEN, "Event": MUTED}


def local_date(value: str | None, long: bool = False, with_time: bool = False) -> str:
    dt = ps.parse_dt(value)
    if not dt:
        return ""
    dt = dt.astimezone()
    fmt = ("%a %d %b %Y" if long else "%d %b %Y") + (", %H:%M" if with_time else "")
    return dt.strftime(fmt)


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


ENV_PATH = ps.HERE / ".env"
PLACEHOLDERS = {"", "s123456", "your-password"}


def read_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    if ENV_PATH.is_file():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    return vals


def write_env(updates: dict[str, str]) -> None:
    """Update keys in .env, keeping every other line (comments, options) as it was."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.is_file() else []
    done = set()
    out = []
    for raw in lines:
        key = raw.split("=", 1)[0].strip().lstrip("#").strip()
        if key in updates and "=" in raw and key not in done:
            out.append(f"{key}={updates[key]}")
            done.add(key)
        else:
            out.append(raw)
    out += [f"{k}={v}" for k, v in updates.items() if k not in done]
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ.update(updates)


def needs_setup() -> bool:
    v = read_env()
    return v.get("POLITO_USERNAME", "") in PLACEHOLDERS or v.get("POLITO_PASSWORD", "") in PLACEHOLDERS


class SettingsDialog(tk.Toplevel):
    def __init__(self, master: "App", first_run: bool = False) -> None:
        super().__init__(master)
        self.app = master
        self.title("PoliTO Sync - Settings")
        self.configure(bg="white")
        self.resizable(False, False)
        self.transient(master)
        cur = read_env()
        cfg = master.cfg

        frm = ttk.Frame(self, padding=22)
        frm.pack(fill="both", expand=True)
        intro = ("Welcome! Enter your PoliTO login and choose where course files should go."
                 if first_run else "Change your login or download folder.")
        ttk.Label(frm, text=intro, wraplength=440, font=(FONT, 10)).grid(row=0, column=0, columnspan=3,
                                                                          sticky="w", pady=(0, 14))

        def label(row: int, text: str, hint: str = "") -> None:
            ttk.Label(frm, text=text, font=(FONT, 10, "bold")).grid(row=row, column=0, sticky="w", pady=(6, 0))
            if hint:
                ttk.Label(frm, text=hint, foreground=MUTED, font=(FONT, 8)).grid(row=row + 1, column=0,
                                                                                 columnspan=3, sticky="w")

        user = cur.get("POLITO_USERNAME", "")
        self.user = tk.StringVar(value="" if user in PLACEHOLDERS else user)
        pw = cur.get("POLITO_PASSWORD", "")
        self.pw = tk.StringVar(value="" if pw in PLACEHOLDERS else pw)
        self.folder = tk.StringVar(value=str(cfg.download_dir))
        self.create = tk.BooleanVar(value=cfg.create_missing or first_run)

        label(1, "Student ID", "e.g. s123456")
        ttk.Entry(frm, textvariable=self.user, width=44).grid(row=1, column=1, columnspan=2, sticky="we", pady=(6, 0))
        label(3, "Password", "Stored only on this PC, in the .env file next to the app.")
        self.pw_entry = ttk.Entry(frm, textvariable=self.pw, width=44, show="•")
        self.pw_entry.grid(row=3, column=1, sticky="we", pady=(6, 0))
        self.show = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Show", variable=self.show,
                        command=lambda: self.pw_entry.configure(show="" if self.show.get() else "•")
                        ).grid(row=3, column=2, padx=(8, 0), pady=(6, 0))
        label(5, "Download folder", "The folder that holds (or will hold) one subfolder per course.")
        ttk.Entry(frm, textvariable=self.folder, width=36).grid(row=5, column=1, sticky="we", pady=(6, 0))
        ttk.Button(frm, text="Browse…", command=self._browse).grid(row=5, column=2, padx=(8, 0), pady=(6, 0))
        ttk.Checkbutton(frm, text="Create a folder for each course automatically\n"
                                  "(untick if you already made your own course folders)",
                        variable=self.create).grid(row=7, column=0, columnspan=3, sticky="w", pady=(14, 0))
        self.had_key = "ANTHROPIC_API_KEY" in cur
        self.key = tk.StringVar(value=cur.get("ANTHROPIC_API_KEY", ""))
        label(8, "Claude API key", "Optional, for “Summarize with Claude” in the Upcoming tab. When you use it, "
                                   "your recent notice text is sent to Anthropic.")
        ttk.Entry(frm, textvariable=self.key, width=44, show="•").grid(row=8, column=1, columnspan=2,
                                                                       sticky="we", pady=(16, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, columnspan=3, sticky="e", pady=(20, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self._save).pack(side="right")
        self.bind("<Return>", lambda _e: self._save())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.focus_force()

    def _browse(self) -> None:
        start = self.folder.get() if Path(self.folder.get()).is_dir() else str(Path.home())
        chosen = filedialog.askdirectory(parent=self, initialdir=start, title="Choose your course folder")
        if chosen:
            self.folder.set(str(Path(chosen)))

    def _save(self) -> None:
        user, pw, folder = self.user.get().strip(), self.pw.get(), self.folder.get().strip()
        if not user or not pw:
            messagebox.showwarning("PoliTO Sync", "Please enter your student ID and password.", parent=self)
            return
        if not folder:
            messagebox.showwarning("PoliTO Sync", "Please choose a download folder.", parent=self)
            return
        Path(folder).mkdir(parents=True, exist_ok=True)
        updates = {
            "POLITO_USERNAME": user,
            "POLITO_PASSWORD": pw,
            "POLITO_DOWNLOAD_DIR": folder,
            "POLITO_CREATE_MISSING_COURSE_FOLDERS": "1" if self.create.get() else "0",
        }
        key = self.key.get().strip()
        if key or self.had_key:
            updates["ANTHROPIC_API_KEY"] = key
        write_env(updates)
        self.app.reload_config()
        self.destroy()


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PoliTO Sync")
        self.geometry("980x680")
        self.minsize(760, 520)
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
        self.nbusy = False
        self.aibusy = False
        self.ai_text: str | None = None
        self.notice_rows: dict[str, dict] = {}
        self.notices, self.notices_at = ps.load_cached_notices(self.cfg)

        self._setup_logging()
        self._style()
        self._build()
        self._show_last_run()
        self._render_notices()
        self.after(100, self._poll)
        if needs_setup():
            self.after(300, lambda: SettingsDialog(self, first_run=True))

    def reload_config(self) -> None:
        self.cfg = ps.Config()
        self.sub.configure(text=f"Course files  →  {self.cfg.download_dir}")
        self._log("Settings saved.", "muted")

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
        self.sub = ttk.Label(head, text=f"Course files  →  {self.cfg.download_dir}", style="Sub.TLabel")
        self.sub.pack(anchor="w")

        # Status bar (packed early so it always stays visible at the bottom)
        self.status = ttk.Label(self, text="Ready.", style="Status.TLabel", anchor="w")
        self.status.pack(fill="x", side="bottom")

        # Tabs
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        files_tab = ttk.Frame(self.nb)
        self.notices_tab = ttk.Frame(self.nb)
        self.upcoming_tab = ttk.Frame(self.nb)
        self.nb.add(files_tab, text="  📁  Files  ")
        self.nb.add(self.notices_tab, text="  📢  Notices  ")
        self.nb.add(self.upcoming_tab, text="  ✨  Upcoming  ")
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab)
        self._build_files(files_tab)
        self._build_notices(self.notices_tab)
        self._build_upcoming(self.upcoming_tab)

    def _build_files(self, tab: ttk.Frame) -> None:
        # Toolbar
        bar = ttk.Frame(tab, padding=(16, 12, 16, 6))
        bar.pack(fill="x")
        self.btn_check = ttk.Button(bar, text="🔍  Check", command=lambda: self.run(dry=True))
        self.btn_sync = ttk.Button(bar, text="⬇  Sync now", style="Accent.TButton", command=lambda: self.run(dry=False))
        self.btn_open = ttk.Button(bar, text="📂  Open folder", command=lambda: open_path(self.cfg.download_dir))
        self.btn_sync.pack(side="left")
        self.btn_check.pack(side="left", padx=8)
        self.btn_open.pack(side="left")
        self.btn_settings = ttk.Button(bar, text="⚙  Settings", command=lambda: SettingsDialog(self))
        self.btn_settings.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(bar, length=200, mode="determinate")
        self.progress.pack(side="right")

        # Course table
        ttk.Label(tab, text="COURSES", style="Section.TLabel", padding=(18, 8, 0, 2)).pack(anchor="w")
        tbl = ttk.Frame(tab, padding=(16, 0))
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
        ttk.Label(tab, text="ACTIVITY  (double-click a course to open its folder)", style="Section.TLabel",
                  padding=(18, 10, 0, 2)).pack(anchor="w")
        logf = ttk.Frame(tab, padding=(16, 0, 16, 10))
        logf.pack(fill="x")
        self.text = tk.Text(logf, height=8, wrap="word", relief="flat", bg="#FAFBFD", fg="#222",
                            font=("Consolas", 9), padx=8, pady=6, borderwidth=1, highlightthickness=1,
                            highlightbackground="#DDE3EA")
        self.text.pack(fill="x")
        for tag, color in (("ok", GREEN), ("warn", ORANGE), ("err", RED), ("muted", MUTED)):
            self.text.tag_configure(tag, foreground=color)
        self.text.configure(state="disabled")

    def _build_notices(self, tab: ttk.Frame) -> None:
        bar = ttk.Frame(tab, padding=(16, 12, 16, 6))
        bar.pack(fill="x")
        self.btn_nrefresh = ttk.Button(bar, text="⟳  Refresh notices", style="Accent.TButton",
                                       command=self.refresh_notices)
        self.btn_nrefresh.pack(side="left")
        ttk.Label(bar, text="Course").pack(side="left", padx=(16, 6))
        self.ncourse = tk.StringVar(value=ALL_COURSES)
        self.ncourse_box = ttk.Combobox(bar, textvariable=self.ncourse, state="readonly", width=34,
                                        values=[ALL_COURSES])
        self.ncourse_box.pack(side="left")
        self.ncourse_box.bind("<<ComboboxSelected>>", lambda _e: self._fill_notices())
        ttk.Label(bar, text="Search").pack(side="left", padx=(16, 6))
        self.nsearch = tk.StringVar()
        self.nsearch.trace_add("write", lambda *_: self._fill_notices())
        ttk.Entry(bar, textvariable=self.nsearch, width=18).pack(side="left")

        pane = ttk.PanedWindow(tab, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=16, pady=(4, 12))
        left = ttk.Frame(pane)
        cols = ("date", "course", "preview")
        self.ntree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for col, text, width, stretch in (("date", "Date", 95, False), ("course", "Course", 170, False),
                                          ("preview", "Notice", 260, True)):
            self.ntree.heading(col, text=text, anchor="w")
            self.ntree.column(col, width=width, anchor="w", stretch=stretch)
        self.ntree.tag_configure("odd", background="#F7F9FC")
        self.ntree.tag_configure("new", foreground=GREEN, font=(FONT, 10, "bold"))
        self.ntree.pack(side="left", fill="both", expand=True)
        nsb = ttk.Scrollbar(left, orient="vertical", command=self.ntree.yview)
        nsb.pack(side="right", fill="y")
        self.ntree.configure(yscrollcommand=nsb.set)
        self.ntree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected_notice())
        pane.add(left, weight=3)

        right = ttk.Frame(pane)
        self.ntext = tk.Text(right, wrap="word", relief="flat", bg="#FAFBFD", fg="#222", font=(FONT, 10),
                             padx=14, pady=10, borderwidth=1, highlightthickness=1,
                             highlightbackground="#DDE3EA", cursor="arrow")
        self.ntext.pack(side="left", fill="both", expand=True)
        tsb = ttk.Scrollbar(right, orient="vertical", command=self.ntext.yview)
        tsb.pack(side="right", fill="y")
        self.ntext.configure(yscrollcommand=tsb.set)
        self._text_tags(self.ntext)
        pane.add(right, weight=4)
        self._set_text(self.ntext, [("Select a notice to read it.", "muted")])

    def _build_upcoming(self, tab: ttk.Frame) -> None:
        bar = ttk.Frame(tab, padding=(16, 12, 16, 6))
        bar.pack(fill="x")
        self.btn_urefresh = ttk.Button(bar, text="⟳  Refresh", command=self.refresh_notices)
        self.btn_urefresh.pack(side="left")
        self.btn_ai = ttk.Button(bar, text="✨  Summarize with Claude", command=self.run_ai_summary)
        self.btn_ai.pack(side="left", padx=8)
        self.uinfo = ttk.Label(bar, text="", foreground=MUTED, font=(FONT, 9))
        self.uinfo.pack(side="right")
        box = ttk.Frame(tab, padding=(16, 4, 16, 12))
        box.pack(fill="both", expand=True)
        self.utext = tk.Text(box, wrap="word", relief="flat", bg="#FAFBFD", fg="#222", font=(FONT, 10),
                             padx=18, pady=12, borderwidth=1, highlightthickness=1,
                             highlightbackground="#DDE3EA", cursor="arrow")
        self.utext.pack(side="left", fill="both", expand=True)
        usb = ttk.Scrollbar(box, orient="vertical", command=self.utext.yview)
        usb.pack(side="right", fill="y")
        self.utext.configure(yscrollcommand=usb.set)
        self._text_tags(self.utext)

    def _text_tags(self, t: tk.Text) -> None:
        t.tag_configure("h1", font=(FONT, 14, "bold"), foreground=ACCENT, spacing3=4)
        t.tag_configure("h2", font=(FONT, 10, "bold"), foreground=MUTED, spacing1=14, spacing3=6)
        t.tag_configure("when", font=(FONT, 10, "bold"))
        t.tag_configure("course", foreground=MUTED)
        t.tag_configure("muted", foreground=MUTED, font=(FONT, 9))
        t.tag_configure("snippet", lmargin1=24, lmargin2=24, spacing3=8, foreground="#333")
        t.tag_configure("body", spacing1=2, spacing3=2)
        t.tag_configure("link", foreground="#155A9E", underline=True)
        t.tag_configure("new", foreground=GREEN, font=(FONT, 9, "bold"))
        for kind, color in KIND_COLORS.items():
            t.tag_configure(f"k:{kind}", foreground=color, font=(FONT, 9, "bold"))
        t.tag_bind("link", "<Enter>", lambda _e: t.configure(cursor="hand2"))
        t.tag_bind("link", "<Leave>", lambda _e: t.configure(cursor="arrow"))

    @staticmethod
    def _set_text(t: tk.Text, chunks: list[tuple[str, object]]) -> None:
        """Replace a read-only Text's content with (text, tag-or-tags) chunks."""
        t.configure(state="normal")
        t.delete("1.0", "end")
        for s, tags in chunks:
            t.insert("end", s, tags)
        t.configure(state="disabled")
        t.yview_moveto(0)

    # --------------------------------------------------------------- notices
    def _on_tab(self, _event: object) -> None:
        """Opening Notices/Upcoming refreshes automatically when the cached notices are > 30 min old."""
        if self.nb.index("current") == 0:
            return
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(self.notices_at)).total_seconds()
        except (TypeError, ValueError):
            age = None
        if (age is None or age > 1800) and not self.nbusy and not needs_setup():
            self.refresh_notices()

    def refresh_notices(self) -> None:
        if self.nbusy:
            return
        if needs_setup():
            SettingsDialog(self, first_run=True)
            return
        self.nbusy = True
        for b in (self.btn_nrefresh, self.btn_urefresh):
            b.configure(state="disabled")
        self.status.configure(text="Reading notices from PoliTO…")
        threading.Thread(target=self._notices_work, daemon=True).start()

    def _notices_work(self) -> None:
        try:
            api = ps.PolitoApi(self.cfg)
            notices = ps.fetch_notices(api, self.cfg, progress=lambda ev, data: self.q.put(("n" + ev, data)))
            self.q.put(("notices", notices))
        except Exception as exc:  # noqa: BLE001 - show anything to the user
            self.q.put(("notices_error", f"{type(exc).__name__}: {exc}" if not isinstance(exc, ps.AuthError)
                        else str(exc)))

    def _on_ncourses(self, _n: int) -> None:
        pass

    def _on_ncourse(self, name: str) -> None:
        self.status.configure(text=f"Reading notices…  {name}")

    def _notices_done(self) -> None:
        self.nbusy = False
        for b in (self.btn_nrefresh, self.btn_urefresh):
            b.configure(state="normal")

    def _on_notices(self, notices: list) -> None:
        self._notices_done()
        self.notices = notices
        self.notices_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.ai_text = None  # notices changed, an old Claude summary may be stale
        new = sum(1 for n in notices if n.get("new"))
        msg = f"Notices updated: {len(notices)} notice(s)" + (f", {new} new." if new else ".")
        self.status.configure(text=msg)
        self._log(msg, "ok" if new else "muted")
        self._render_notices()

    def _on_notices_error(self, msg: str) -> None:
        self._notices_done()
        self.status.configure(text="Could not read notices. See the Files tab activity box.")
        self._log("Notices: " + msg, "err")
        messagebox.showerror("PoliTO Sync", f"Could not read notices:\n{msg}")

    def _render_notices(self) -> None:
        names = sorted({n["course"] for n in self.notices})
        self.ncourse_box.configure(values=[ALL_COURSES] + names)
        if self.ncourse.get() not in names:
            self.ncourse.set(ALL_COURSES)
        self._fill_notices()
        self._render_upcoming()

    def _fill_notices(self) -> None:
        course, q = self.ncourse.get(), self.nsearch.get().strip().lower()
        self.ntree.delete(*self.ntree.get_children())
        self.notice_rows.clear()
        for n in self.notices:
            if course != ALL_COURSES and n["course"] != course:
                continue
            if q and q not in n["text"].lower() and q not in n["course"].lower():
                continue
            first = next((ln for ln in n["text"].splitlines() if ln.strip()), "(empty)")
            idx = len(self.notice_rows)
            tags = (["odd"] if idx % 2 else []) + (["new"] if n.get("new") else [])
            iid = self.ntree.insert("", "end", tags=tags, values=(
                local_date(n.get("publishedAt")), n["course"], ("● " if n.get("new") else "") + first[:120]))
            self.notice_rows[iid] = n

    def _show_selected_notice(self) -> None:
        sel = self.ntree.selection()
        n = self.notice_rows.get(sel[0]) if sel else None
        if not n:
            return
        chunks: list[tuple[str, object]] = [(n["course"] + "\n", "h1"),
                                            (f"Published {local_date(n.get('publishedAt'), long=True)}", "muted")]
        if n.get("expiresAt"):
            chunks.append((f"  ·  expires {local_date(n['expiresAt'], long=True)}", "muted"))
        chunks.append(("\n\n", ""))
        chunks.append((n["text"] + "\n", "body"))
        for i, url in enumerate(n.get("links", [])):
            if i == 0:
                chunks.append(("\nLinks\n", "h2"))
            tag = f"url{i}"
            chunks.append((url + "\n", ("link", tag)))
        self._set_text(self.ntext, chunks)
        for i, url in enumerate(n.get("links", [])):
            self.ntext.tag_bind(f"url{i}", "<Button-1>", lambda _e, u=url: webbrowser.open(u))

    def open_notice(self, course_id: object, notice_id: object) -> None:
        """Jump from the Upcoming tab to a notice in the Notices tab."""
        self.ncourse.set(ALL_COURSES)
        self.nsearch.set("")
        self._fill_notices()
        for iid, n in self.notice_rows.items():
            if n.get("courseId") == course_id and n.get("id") == notice_id:
                self.nb.select(self.notices_tab)
                self.ntree.selection_set(iid)
                self.ntree.see(iid)
                return

    def _render_upcoming(self) -> None:
        t = self.utext
        today = date.today()
        when = local_date(self.notices_at, long=True, with_time=True) if self.notices_at else "never"
        self.uinfo.configure(text=f"Notices updated: {when}")
        if not self.notices:
            self._set_text(t, [("Nothing here yet\n", "h1"),
                               ("Click Refresh to read your course notices from PoliTO.", "muted")])
            return
        events, heads = ps.extract_events(self.notices, today)
        courses = len({n["course"] for n in self.notices})
        chunks: list[tuple[str, object]] = [("Coming up\n", "h1")]
        summary = (f"{len(events)} upcoming item(s) found in {len(self.notices)} notices from {courses} "
                   f"course(s). Click any item to open the original notice.\n") if events else \
            "No upcoming dates found in your notices.\n"
        chunks.append((summary, "muted"))
        if self.ai_text:
            chunks += [("CLAUDE'S SUMMARY\n", "h2"), (self.ai_text.strip() + "\n", "body")]
        links: list[tuple[str, object, object]] = []

        def item(head: list[tuple[str, object]], ev: dict, snippet: str) -> None:
            tag = f"ev{len(links)}"
            links.append((tag, ev.get("courseId"), ev.get("notice_id")))
            for s, tg in head:
                chunks.append((s, (tg, tag) if tg else (tag,)))
            chunks.append(("\n" + snippet + "\n", ("snippet", tag)))

        for title, evs in ps.group_events(events, today):
            chunks.append((title.upper() + "\n", "h2"))
            for ev in evs:
                d = ev["date"]
                label = "Today" if d == today else "Tomorrow" if d == today + timedelta(days=1) else f"{d:%a %d %b}"
                head = [(label + (f"  {ev['time']}" if ev["time"] else ""), "when"),
                        ("   " + ev["kind"].upper(), f"k:{ev['kind']}"), ("   " + ev["course"], "course")]
                item(head, ev, ev["snippet"])
        if heads:
            chunks.append(("RECENT HEADS-UP  (no date found)\n", "h2"))
            for h in heads:
                head = [(h["kind"].upper(), f"k:{h['kind']}"), ("   " + h["course"], "course"),
                        ("   " + local_date(h.get("publishedAt")), "muted")]
                item(head, h, h["snippet"])
        chunks.append(("\nDates are read automatically from the notice text, so check the original notice "
                       "before you rely on one.", "muted"))
        self._set_text(t, chunks)
        for tag, cid, nid in links:
            t.tag_bind(tag, "<Button-1>", lambda _e, c=cid, n=nid: self.open_notice(c, n))
            t.tag_bind(tag, "<Enter>", lambda _e: t.configure(cursor="hand2"))
            t.tag_bind(tag, "<Leave>", lambda _e: t.configure(cursor="arrow"))

    def run_ai_summary(self) -> None:
        if self.aibusy:
            return
        if not os.environ.get("ANTHROPIC_API_KEY"):
            messagebox.showinfo("PoliTO Sync", "To get a written summary from Claude, add a Claude API key in "
                                "Settings (optional). The list below works without it.")
            return
        if importlib.util.find_spec("anthropic") is None:
            messagebox.showinfo("PoliTO Sync", "The Claude add-on is not installed. Run this once in the app "
                                "folder, then restart the app:\n\n.venv\\Scripts\\pip install anthropic")
            return
        if not self.notices:
            messagebox.showinfo("PoliTO Sync", "Refresh the notices first.")
            return
        self.aibusy = True
        self.btn_ai.configure(state="disabled", text="✨  Summarizing…")
        notices = list(self.notices)
        threading.Thread(target=self._ai_work, args=(notices,), daemon=True).start()

    def _ai_work(self, notices: list) -> None:
        try:
            self.q.put(("ai_done", ps.ai_summary(notices, date.today())))
        except Exception as exc:  # noqa: BLE001 - show anything to the user
            self.q.put(("ai_error", f"{type(exc).__name__}: {exc}"))

    def _ai_finish(self) -> None:
        self.aibusy = False
        self.btn_ai.configure(state="normal", text="✨  Summarize with Claude")

    def _on_ai_done(self, text: str) -> None:
        self._ai_finish()
        self.ai_text = text
        self._render_upcoming()

    def _on_ai_error(self, msg: str) -> None:
        self._ai_finish()
        messagebox.showerror("PoliTO Sync", f"Claude summary failed:\n{msg}")

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
        for b in (self.btn_check, self.btn_sync, self.btn_settings):
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
