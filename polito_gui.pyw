"""PoliTO Sync - a small window around polito_sync.py.

Double-click "Sync PoliTO.bat" (or run: .venv\\Scripts\\pythonw.exe polito_gui.pyw).
Looks best with sv-ttk and Pillow installed (Setup.bat does that); works without them too.
"""
from __future__ import annotations

import bisect
import importlib.util
import json
import logging
import math
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
from typing import Any, Callable

import polito_sync as ps
import ui_gfx as gfx

try:  # Windows 11 style widgets; optional so older installs keep working
    import sv_ttk  # type: ignore
except ImportError:  # pragma: no cover
    sv_ttk = None

ALL_COURSES = "All courses"

# ---------------------------------------------------------------------------- look
# Main colours: navy + seal blue (#495764). Crimson pink is the splash of life (badges, hot chips,
# hover outlines, links). accent = seal blue for calm "selected" states, accent2 = crimson pink.
NAVY, SEAL, CRIMSON = "#14213D", "#495764", "#E0245E"
PALETTES: dict[str, dict[str, Any]] = {
    "light": {  # "harbor": cool paper, navy ink
        "bg": "#F2F5F9", "side": "#E4E9F0", "card": "#FFFFFF", "border": "#D5DDE8", "text": NAVY,
        "muted": "#5E6B7D", "accent": SEAL, "accent2": "#D81F5A",
        "grad": (NAVY, SEAL, "#D81F5A"),            # primary buttons, progress, nav marker
        "hot": ("#D81F5A", "#F0517F"),              # badges and "tmrw"/"today" chips
        "hero": (NAVY, "#2E4260", SEAL, CRIMSON),   # greeting banner
        "green": "#1F8A5B", "orange": "#C2410C", "red": "#C81E4A",
    },
    "dark": {  # "deep navy": navy night with seal blue surfaces
        "bg": "#0B1426", "side": "#0E1A30", "card": "#132239", "border": "#22344F", "text": "#EEF2F8",
        "muted": "#8E9DB3", "accent": "#8DA2BA", "accent2": "#FF3D73",
        "grad": ("#2B4A6F", "#5C7088", "#E8336A"),
        "hot": ("#E8336A", "#FF6B94"),
        "hero": ("#0F1D38", "#22385A", "#4F6378", "#E8336A"),
        "green": "#6FD6A6", "orange": "#F5B26B", "red": "#FF6B8B",
    },
}
KIND_COLORS = {
    "light": {"Seminar / talk": "#C0266D", "Exam": "#D7263D", "Deadline": "#C2700C", "Class change": "#2F6690",
              "Lab / exercise": "#1F8A70", "Event": "#5E6B7D"},
    "dark": {"Seminar / talk": "#FF6FAE", "Exam": "#FF5C74", "Deadline": "#F7B267", "Class change": "#7FB3E0",
             "Lab / exercise": "#5FD3B5", "Event": "#9AA8BC"},
}
KIND_EMOJI = {"Seminar / talk": "🎤", "Exam": "📝", "Deadline": "⏰", "Class change": "🔁",
              "Lab / exercise": "🧪", "Event": "📌"}
KIND_SHORT = {"Seminar / talk": "talk", "Exam": "exam", "Deadline": "deadline", "Class change": "class change",
              "Lab / exercise": "lab", "Event": "event"}
COURSE_COLORS = {
    "light": ["#2F6690", "#D81F5A", "#1F8A70", "#C2700C", "#6A4C93", "#3A7CA5", "#B23A48", "#495764"],
    "dark": ["#7FB3E0", "#FF6F9C", "#5FD3B5", "#F7B267", "#B39DDB", "#81C3E8", "#FF8A80", "#A9B8C9"],
}
THEME_CHOICES = {"system": "Match Windows", "light": "Light", "dark": "Dark"}

FONT = "Segoe UI"
FONT_SEMI = "Segoe UI Semibold"
FONT_HEAD = "Segoe UI Semibold"
FONT_MONO = "Consolas"
ICON_FONT: str | None = None
# Segoe Fluent Icons (Windows 11) / Segoe MDL2 Assets (Windows 10) glyphs, with plain fallbacks.
ICONS = {"files": ("", "▤"), "notices": ("", "✉"), "upcoming": ("", "◷"),
         "settings": ("", "⚙"), "light": ("", "☀"), "dark": ("", "☾"),
         "clock": ("", "·"), "menu": ("", "≡")}


def init_fonts(root: tk.Misc) -> None:
    global FONT, FONT_SEMI, FONT_HEAD, FONT_MONO, ICON_FONT
    fams = set(tkfont.families(root))

    def pick(*names: str) -> str | None:
        return next((n for n in names if n in fams), None)

    FONT = pick("Segoe UI Variable Text", "Segoe UI") or "TkDefaultFont"
    FONT_SEMI = pick("Segoe UI Variable Display Semib", "Segoe UI Semibold") or FONT
    FONT_HEAD = pick("Bahnschrift SemiBold", "Bahnschrift") or FONT_SEMI
    FONT_MONO = pick("Cascadia Mono", "Cascadia Code", "Consolas") or "TkFixedFont"
    ICON_FONT = pick("Segoe Fluent Icons", "Segoe MDL2 Assets")


def icon(name: str) -> str:
    glyph, fallback = ICONS[name]
    return glyph if ICON_FONT else fallback


def system_theme() -> str:
    if sys.platform != "win32":
        return "light"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "light"


def mix(a: str, b: str, t: float) -> str:
    """Blend colour a towards b by t (0..1)."""
    ca, cb = gfx.rgb(a), gfx.rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


def dark_titlebar(win: tk.Misc, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


def bind_tree(widget: tk.Misc, seq: str, fn: Callable[[Any], Any]) -> None:
    widget.bind(seq, fn, add="+")
    for child in widget.winfo_children():
        bind_tree(child, seq, fn)


def local_date(value: str | None, long: bool = False, with_time: bool = False) -> str:
    dt = ps.parse_dt(value)
    if not dt:
        return ""
    dt = dt.astimezone()
    fmt = ("%a %d %b %Y" if long else "%d %b %Y") + (", %H:%M" if with_time else "")
    return dt.strftime(fmt)


_GREETING = re.compile(r"^(dear|cari|care|carissim|gentil|hello|hi|hey|good (morning|afternoon|evening)|"
                       r"buongiorno|buonasera|salve|ciao)\b", re.I)


def notice_preview(text: str) -> str:
    """First line worth reading: skips 'Dear students,'-style greetings."""
    lines = [ln.strip(" •\t") for ln in text.splitlines() if ln.strip(" •\t")]
    for ln in lines:
        if _GREETING.match(ln):
            # "Dear students," -> skip the line; "Dear students, the lab moves..." -> keep what follows.
            ln = ln.split(",", 1)[1].strip() if "," in ln else ""
            if not ln:
                continue
        return ln[:1].upper() + ln[1:]
    return lines[0] if lines else "(empty)"


def countdown(d: date, today: date) -> str:
    days = (d - today).days
    if days <= 0:
        return "today"
    if days == 1:
        return "tmrw"
    return f"in {days}d" if days < 14 else f"in {days // 7}w"


def greeting(now: datetime) -> str:
    h = now.hour
    return ("good morning" if 5 <= h < 12 else "good afternoon" if h < 18 else
            "good evening" if h < 23 else "late night grind, huh")


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


# ---------------------------------------------------------------------- widgets
class _Canvas(tk.Canvas):
    def __init__(self, master: tk.Misc, bg: str, **kw: Any) -> None:
        kw.setdefault("width", 1)  # tk's default canvas width (~380px) would push neighbours out
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, **kw)
        self._imgs: list[Any] = []  # keep PhotoImages alive

    def image(self, x: float, y: float, img: Any, **kw: Any) -> None:
        if img is not None:
            self._imgs.append(img)
            self.create_image(x, y, image=img, **kw)

    def round_rect(self, w: int, h: int, r: int, fill: str, outline: str | None = None,
                   stripe: str | None = None, stripe_w: int = 5, tags: str = "bg") -> None:
        """A rounded rectangle made of 4 cached corner images + plain shapes: costs the same at any size,
        so cards and sidebar items can resize (or animate) without rendering new images."""
        r = max(2, min(r, w // 2, h // 2))
        c = gfx.corners(r, fill, outline, stripe, stripe_w)
        if c is None:  # no Pillow: square corners
            self.create_rectangle(0, 0, w - 1, h - 1, fill=fill, outline=outline or fill, tags=tags)
            if stripe:
                self.create_rectangle(0, 0, stripe_w, h, fill=stripe, outline="", tags=tags)
            return
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline="", tags=tags)
        if h > 2 * r:
            self.create_rectangle(0, r, r, h - r, fill=fill, outline="", tags=tags)
            self.create_rectangle(w - r, r, w, h - r, fill=fill, outline="", tags=tags)
            if stripe:
                self.create_rectangle(0, r, stripe_w, h - r, fill=stripe, outline="", tags=tags)
        if outline:
            for x0, y0, x1, y1 in ((r, 0, w - r, 0), (r, h - 1, w - r, h - 1),
                                   (0, r, 0, h - r), (w - 1, r, w - 1, h - r)):
                self.create_line(x0, y0, x1, y1, fill=outline, tags=tags)
        for key, x, y in (("nw", 0, 0), ("ne", w - r, 0), ("sw", 0, h - r), ("se", w - r, h - r)):
            self.image(x, y, c[key], anchor="nw", tags=tags)


class PillButton(_Canvas):
    """Rounded button. primary = gradient fill; otherwise an outlined 'ghost' pill."""

    def __init__(self, master: tk.Misc, app: "App", text: str, command: Callable[[], None],
                 primary: bool = False, bg: str | None = None, height: int = 38, padx: int = 20) -> None:
        super().__init__(master, bg or app.pal["bg"], height=height, width=40, cursor="hand2")
        self.app, self._text, self._cmd, self._primary = app, text, command, primary
        self._state, self._hover, self._down = "normal", False, False
        self._h, self._padx = height, padx
        self.bind("<Enter>", lambda _e: self._set(hover=True))
        self.bind("<Leave>", lambda _e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda _e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def _release(self, _e: object) -> None:
        fire = self._down and self._hover and self._state != "disabled"
        self._set(down=False)
        if fire:
            self._cmd()

    def _set(self, hover: bool | None = None, down: bool | None = None) -> None:
        if hover is not None:
            self._hover = hover
        if down is not None:
            self._down = down
        self._draw()

    def configure(self, cnf: dict | None = None, **kw: Any) -> Any:  # type: ignore[override]
        kw = {**(cnf or {}), **kw}
        changed = False
        if "state" in kw:
            self._state, changed = kw.pop("state"), True
        if "text" in kw:
            self._text, changed = kw.pop("text"), True
        result = super().configure(**kw) if kw else None
        if changed:
            self._draw()
        return result

    config = configure

    def _draw(self) -> None:
        p, h = self.app.pal, self._h
        font = (FONT_HEAD, 10)
        w = tkfont.Font(root=self, font=font).measure(self._text) + 2 * self._padx
        super().configure(width=w, cursor="arrow" if self._state == "disabled" else "hand2")
        self.delete("all")
        self._imgs.clear()
        off = self._state == "disabled"
        if self._primary and not off:
            stops = p["grad"]
            if self._hover:
                stops = tuple(mix(c, "#FFFFFF", 0.14) for c in stops)
            if self._down:
                stops = tuple(mix(c, "#000000", 0.12) for c in stops)
            img, fg, flat = gfx.rounded(w, h, h // 2, gradient=stops), "#FFFFFF", stops[1]
            outline = None
        else:
            fill = mix(p["card"], p["muted"], 0.15) if off else \
                mix(p["card"], p["accent2"], 0.07) if self._hover else p["card"]
            outline = p["border"] if off or not self._hover else p["accent2"]
            img = gfx.rounded(w, h, h // 2, fill=fill, outline=outline)
            fg, flat = (p["muted"] if off else p["text"]), fill
        if img is not None:
            self.image(0, 0, img, anchor="nw")
        else:
            self.create_rectangle(0, 0, w - 1, h - 1, fill=flat, outline=outline or flat)
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=font)


class Chip(_Canvas):
    """A small pill label, optionally with a colour emoji in front."""

    def __init__(self, master: tk.Misc, app: "App", text: str, fg: str, fill: str | None = None,
                 gradient: tuple[str, ...] | None = None, emoji: str | None = None, bg: str | None = None,
                 height: int = 24) -> None:
        font = (FONT_HEAD, 9)
        em = gfx.emoji(emoji, 14) if emoji else None
        tw = tkfont.Font(root=master, font=font).measure(text)
        w = tw + 22 + (20 if em else 0)
        super().__init__(master, bg or app.pal["card"], width=w, height=height)
        img = gfx.rounded(w, height, height // 2, fill=fill, gradient=gradient)
        if img is not None:
            self.image(0, 0, img, anchor="nw")
        else:
            self.create_rectangle(0, 0, w - 1, height - 1, fill=fill or (gradient or ["#888888"])[0], outline="")
        x = 11
        if em is not None:
            self.image(x, height / 2, em, anchor="w")
            x += 20
        self.create_text(x, height / 2, text=text, fill=fg, font=font, anchor="w")


class RoundCard(_Canvas):
    """A rounded card. Put content in .inner. expand=True fills its slot; otherwise height follows content."""

    def __init__(self, master: tk.Misc, app: "App", stripe: str | None = None, fill: str | None = None,
                 radius: int = 18, pad: tuple[int, int] = (18, 14), click: Callable[[], None] | None = None,
                 expand: bool = False, bg: str | None = None) -> None:
        p = app.pal
        super().__init__(master, bg or p["bg"], height=40)
        self.app, self.stripe, self.radius, self.expand = app, stripe, radius, expand
        self.fill = fill or p["card"]
        self.px, self.py = pad
        self.left = self.px + (6 if stripe else 0)
        self.hover, self._job = False, None
        self.inner = tk.Frame(self, bg=self.fill)
        self.win = self.create_window(self.left, self.py, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._inner_changed)
        self.bind("<Configure>", self._resized)
        if click:
            self.after_idle(lambda: self._make_clickable(click))

    def _inner_changed(self, _e: object) -> None:
        if not self.expand:
            h = self.inner.winfo_reqheight() + 2 * self.py
            if str(h) != str(self["height"]):
                super().configure(height=h)

    def _resized(self, e: tk.Event) -> None:
        self.itemconfigure(self.win, width=max(e.width - self.left - self.px, 10))
        if self.expand:
            self.itemconfigure(self.win, height=max(e.height - 2 * self.py, 10))
        self._paint()  # cheap (corner pieces), so no need to wait for the resize to settle

    def _paint(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        p = self.app.pal
        outline = p["accent2"] if self.hover else p["border"]
        self.delete("bg")
        self._imgs.clear()
        self.round_rect(w, h, self.radius, self.fill, outline, self.stripe)
        self.tag_lower("bg")

    def _make_clickable(self, click: Callable[[], None]) -> None:
        def enter(_e: object) -> None:
            if not self.hover:
                self.hover = True
                self._paint()

        def leave(e: tk.Event) -> None:
            w = self.winfo_containing(e.x_root, e.y_root)
            if w is None or not str(w).startswith(str(self)):
                self.hover = False
                self._paint()

        for seq, fn in (("<Button-1>", lambda _e: click()), ("<Enter>", enter), ("<Leave>", leave)):
            bind_tree(self, seq, fn)
        for w in [self, self.inner, *self.inner.winfo_children()]:
            try:
                w.configure(cursor="hand2")
            except tk.TclError:
                pass


class NavItem(_Canvas):
    """A sidebar entry drawn on a canvas: rounded highlight, gradient marker, icon, label, count badge.
    When the sidebar is collapsed (narrow), it shows just the icon, a dot for the badge and a tooltip."""
    H = 44
    COMPACT = 110  # narrower than this = icon-only

    def __init__(self, master: tk.Misc, app: "App", key: str, text: str,
                 on_click: Callable[[], None] | None = None) -> None:
        super().__init__(master, app.pal["side"], height=self.H, cursor="hand2")
        self.app, self.key, self.text = app, key, text
        self.active = self.hover = False
        self.count = 0
        self._tip: tk.Toplevel | None = None
        self._tip_job: str | None = None
        self.bind("<Configure>", lambda _e: self._paint())
        self.bind("<Enter>", lambda _e: self._state(hover=True))
        self.bind("<Leave>", lambda _e: self._state(hover=False))
        self.bind("<Button-1>", lambda _e: (self._hide_tip(), on_click() if on_click else app.show_page(key)))

    @property
    def compact(self) -> bool:
        return self.winfo_width() < self.COMPACT

    def _state(self, hover: bool) -> None:
        self.hover = hover
        self._paint()
        if hover and self.compact:
            self._tip_job = self.after(350, self._show_tip)
        else:
            self._hide_tip()

    def _show_tip(self) -> None:
        self._tip_job = None
        if not self.hover or not self.compact:
            return
        p = self.app.pal
        tip = self._tip = tk.Toplevel(self)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        text = self.text + (f"  ·  {self.count} new" if self.count and self.key == "notices" else
                            f"  ·  {self.count} this week" if self.count else "")
        tk.Label(tip, text=text, bg=p["card"], fg=p["text"], font=(FONT_HEAD, 10), padx=10, pady=5,
                 highlightthickness=1, highlightbackground=p["border"]).pack()
        tip.geometry(f"+{self.winfo_rootx() + self.winfo_width() + 8}+{self.winfo_rooty() + 8}")

    def _hide_tip(self) -> None:
        if self._tip_job:
            self.after_cancel(self._tip_job)
            self._tip_job = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def set_active(self, active: bool) -> None:
        self.active = active
        self._paint()

    def set_badge(self, count: int) -> None:
        self.count = count
        self._paint()

    def _paint(self) -> None:
        p, h, w = self.app.pal, self.H, self.winfo_width()
        if w < 20:
            return
        self.delete("all")
        self._imgs.clear()
        if self.active or self.hover:
            fill = mix(p["side"], p["accent"], 0.16) if self.active else mix(p["side"], p["text"], 0.06)
            self.round_rect(w, h, 14, fill, tags="hl")
        if self.active:
            self.image(6, h / 2, gfx.rounded(4, 20, 2, gradient=p["grad"]), anchor="w")
        if self.compact:  # icon only, centred; the badge becomes a dot on the icon
            self.create_text(w / 2, h / 2, text=icon(self.key), font=(ICON_FONT or FONT, 13),
                             fill=p["accent"] if self.active else p["muted"])
            if self.count:
                dot = gfx.rounded(10, 10, 5, gradient=p["hot"])
                if dot is not None:
                    self.image(w / 2 + 6, h / 2 - 13, dot, anchor="nw")
                else:
                    self.create_oval(w / 2 + 6, h / 2 - 13, w / 2 + 16, h / 2 - 3, fill=p["accent2"], outline="")
            return
        self.create_text(28, h / 2, text=icon(self.key), font=(ICON_FONT or FONT, 13),
                         fill=p["accent"] if self.active else p["muted"])
        self.create_text(52, h / 2, text=self.text, anchor="w", fill=p["text"],
                         font=(FONT_HEAD if self.active else FONT, 11))
        if self.count:
            s = str(self.count)
            bw = max(24, tkfont.Font(root=self, font=(FONT_HEAD, 9)).measure(s) + 14)
            x0 = w - 12 - bw
            img = gfx.rounded(bw, 20, 10, gradient=p["hot"])
            if img is not None:
                self.image(x0, h / 2 - 10, img, anchor="nw")
            else:
                self.create_rectangle(x0, h / 2 - 10, x0 + bw, h / 2 + 10, fill=p["accent2"], outline="")
            self.create_text(x0 + bw / 2, h / 2, text=s, fill="#FFFFFF", font=(FONT_HEAD, 9))


class Hero(_Canvas):
    """The gradient greeting banner on the Upcoming page."""

    def __init__(self, master: tk.Misc, app: "App", height: int = 150) -> None:
        super().__init__(master, app.pal["bg"], height=height)
        self.app, self.title, self.sub, self.emoji = app, "", "", None
        self._job = None
        self.bind("<Configure>", lambda _e: self._schedule())

    def set(self, title: str, sub: str, emoji: str | None) -> None:
        self.title, self.sub, self.emoji = title, sub, emoji
        self._schedule()

    def _schedule(self) -> None:
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(40, self._paint)

    def _paint(self) -> None:
        self._job = None
        p, w, h = self.app.pal, self.winfo_width(), self.winfo_height()
        if w < 50:
            return
        self.delete("all")
        self._imgs.clear()
        img = gfx.hero(w, h, 22, p["hero"])
        if img is not None:
            self.image(0, 0, img, anchor="nw")
        else:
            self.create_rectangle(0, 0, w, h, fill=p["hero"][0], outline="")
        self.create_text(32, 50, text=self.title, anchor="w", fill="#FFFFFF", font=(FONT_HEAD, 26))
        self.create_text(34, 96, text=self.sub, anchor="w", fill="#E6ECF5", font=(FONT, 11), width=w - 200)
        if self.emoji:
            self.image(w - 44, h / 2, gfx.emoji(self.emoji, 72), anchor="e")


class Meter(_Canvas):
    """Slim gradient progress bar."""

    def __init__(self, master: tk.Misc, app: "App", width: int = 220, height: int = 8) -> None:
        super().__init__(master, app.pal["bg"], width=width, height=height)
        self.app, self.value, self.maximum = app, 0.0, 1.0
        self.bind("<Configure>", lambda _e: self._paint())

    def set_max(self, n: float) -> None:
        self.maximum, self.value = max(n, 1), 0
        self._paint()

    def step(self, n: float = 1) -> None:
        self.value = min(self.value + n, self.maximum)
        self._paint()

    def fill(self) -> None:
        self.value = self.maximum
        self._paint()

    def _paint(self) -> None:
        p, w, h = self.app.pal, self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        self.delete("all")
        self._imgs.clear()
        track = gfx.rounded(w, h, h // 2, fill=mix(p["bg"], p["text"], 0.08))
        if track is not None:
            self.image(0, 0, track, anchor="nw")
        fw = int(w * self.value / self.maximum)
        if fw >= h:
            bar = gfx.rounded(fw, h, h // 2, gradient=p["grad"])
            if bar is not None:
                self.image(0, 0, bar, anchor="nw")
            else:
                self.create_rectangle(0, 0, fw, h, fill=p["accent"], outline="")


class Ripple:
    """A pixelated colour ripple that washes over the whole window, starting from a button.

    Tk can't draw see-through layers over its own widgets, so this is a short-lived borderless window
    exactly on top of the app: its background colour is keyed out (fully transparent), the whole layer
    is semi-transparent, and it ignores the mouse - so the coloured blocks tint whatever is underneath.
    Windows only (elsewhere a no-op). Set POLITO_RIPPLE=0 in .env to turn it off.
    """
    KEY = "#010203"
    BLOCK = 28          # pixel block size (big blocks = few shapes = light on the CPU)
    DURATION = 1.1      # seconds
    FRAME_MS = 33       # ~30 fps cap

    def __init__(self, app: "App", origin: tk.Misc) -> None:
        self.app, self.top = app, None
        if sys.platform != "win32" or os.environ.get("POLITO_RIPPLE", "1") == "0" or not app.winfo_viewable():
            return
        old = getattr(app, "_ripple", None)
        if old is not None:
            old.finish()
        app._ripple = self
        app.update_idletasks()
        x0, y0, w, h = app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()
        ox = origin.winfo_rootx() - x0 + origin.winfo_width() / 2
        oy = origin.winfo_rooty() - y0 + origin.winfo_height() / 2
        top = self.top = tk.Toplevel(app)
        top.withdraw()
        top.overrideredirect(True)
        top.geometry(f"{w}x{h}+{x0}+{y0}")
        top.configure(bg=self.KEY)
        try:
            top.attributes("-transparentcolor", self.KEY)
            top.attributes("-alpha", 0.0)
            top.attributes("-topmost", True)
        except tk.TclError:
            self.finish()
            return
        self.cv = tk.Canvas(top, bg=self.KEY, highlightthickness=0, bd=0, width=w, height=h)
        self.cv.pack(fill="both", expand=True)
        top.deiconify()
        self.hwnd = self._hwnd(top)

        B = self.BLOCK
        self.w, self.h = w, h
        self.cols, self.rows = -(-w // B), -(-h // B)
        rnd = random.Random(1)
        # Every block of the grid (row by row): distance from the button, sin/cos of 5x its angle (for the
        # wobble) and a dither value. Sorted by distance, so a frame only visits blocks near each wave.
        self.cells = []
        for gy in range(self.rows):
            for gx in range(self.cols):
                dx, dy = gx * B + B / 2 - ox, gy * B + B / 2 - oy
                a = math.atan2(dy, dx) * 5
                self.cells.append((math.hypot(dx, dy), math.sin(a), math.cos(a), rnd.random()))
        self.order = sorted(range(len(self.cells)), key=lambda i: self.cells[i][0])
        self.sorted_d = [self.cells[i][0] for i in self.order]
        self.items: dict[int, int] = {}   # block -> canvas rectangle (created the first time it lights up)
        self.shown: dict[int, str] = {}   # block -> colour it shows now
        self.reach = max(math.hypot(x - ox, y - oy) for x in (0, w) for y in (0, h))
        p = app.pal
        seal = "#5C7088" if app.mode == "dark" else SEAL
        plum = mix(p["accent2"], seal, 0.5)
        # Waves: (start delay as a fraction of the animation, band width, colours front -> tail, dither)
        self.waves = [
            (0.0, B * 4.5, self._ramp((p["hot"][1], p["accent2"], plum, seal, NAVY)), 0.85),
            (0.15, B * 2.5, self._ramp((mix(seal, "#FFFFFF", 0.35), seal, NAVY)), 0.7),
        ]
        # Shimmer left behind the main wave: mostly seal/navy, with the odd crimson sparkle.
        self.wash = self._ramp((NAVY, seal, mix(seal, "#FFFFFF", 0.3)), 8)
        self.spark = p["accent2"]
        self.frame_no = 0
        self.start = time.perf_counter()
        self._frame()

    @staticmethod
    def _ramp(stops: tuple[str, ...], n: int = 12) -> list[str]:
        out = []
        for i in range(n):
            t = i / (n - 1) * (len(stops) - 1)
            k = min(int(t), len(stops) - 2)
            out.append(mix(stops[k], stops[k + 1], t - k))
        return out

    @staticmethod
    def _hwnd(top: tk.Toplevel) -> int | None:
        try:
            import ctypes
            top.update_idletasks()
            return ctypes.windll.user32.GetParent(top.winfo_id())
        except Exception:  # noqa: BLE001 - cosmetic only
            return None

    def _click_through(self) -> None:
        """Let clicks pass through to the app and never take focus (re-applied: Tk may reset the style)."""
        if not self.hwnd:
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            style = u.GetWindowLongW(self.hwnd, -20)  # GWL_EXSTYLE
            want = style | 0x80000 | 0x20 | 0x08000000  # LAYERED | TRANSPARENT | NOACTIVATE
            if want != style:
                u.SetWindowLongW(self.hwnd, -20, want)
        except Exception:  # noqa: BLE001
            pass

    def _frame(self) -> None:
        if self.top is None:
            return
        frame_start = time.perf_counter()
        t = (frame_start - self.start) / self.DURATION
        if t >= 1:
            self.finish()
            return
        B, cells, order, sd = self.BLOCK, self.cells, self.order, self.sorted_d
        self.frame_no += 1
        lit: dict[int, str] = {}
        radii = []
        for delay, band, _ramp, _dither in self.waves:
            tt = max((t - delay) / (1 - delay), 0.0)
            radii.append((self.reach + band) * (1 - (1 - tt) ** 2) if tt > 0 else -1.0)  # ease-out

        # 1) Shimmer over everything the main wave has passed: dense right behind it, thinner further back.
        #    The pattern changes every fourth frame, so it twinkles.
        edge = radii[0] - self.waves[0][1]
        if edge > 0:
            twinkle, wash, last_w = (self.frame_no // 4) * 0.618, self.wash, len(self.wash) - 1
            for j in range(bisect.bisect_left(sd, edge)):
                i = order[j]
                d, _s, _c, n = cells[i]
                m = (n + twinkle) % 1.0
                if m > 0.985:
                    lit[i] = self.spark
                else:
                    cut = 0.86 + 0.11 * min((edge - d) / (B * 12), 1.0)
                    if m > cut:
                        lit[i] = wash[int((m - cut) / (0.985 - cut) * last_w)]

        # 2) The waves; the inner one first so the crimson front ends up on top.
        wob = B * 0.45
        for (delay, band, ramp, dither), r in reversed(list(zip(self.waves, radii))):
            if r < 0:
                continue
            phase = r / B * 0.2
            sp, cp, last = math.sin(phase), math.cos(phase), len(ramp) - 1
            lo, hi = bisect.bisect_left(sd, r - band - wob), bisect.bisect_right(sd, r + wob)
            for j in range(lo, hi):
                i = order[j]
                d, s5, c5, n = cells[i]
                k = r - d - (s5 * cp + c5 * sp) * wob  # wobbly wave front: sin(5*angle + phase)
                if 0 <= k <= band:
                    f = k / band  # 0 at the front, 1 at the tail
                    if n >= f ** 1.4 * dither:  # the tail dissolves into scattered pixels
                        lit[i] = ramp[int(f * last)]

        # 3) Draw only what changed: blocks are created once, then recoloured or hidden.
        cv, items, shown, cols = self.cv, self.items, self.shown, self.cols
        for i in [i for i in shown if i not in lit]:
            cv.itemconfigure(items[i], state="hidden")
            del shown[i]
        for i, c in lit.items():
            if shown.get(i) != c:
                item = items.get(i)
                if item is None:
                    x, y = (i % cols) * B, (i // cols) * B
                    items[i] = cv.create_rectangle(x + 3, y + 3, x + B, y + B, outline="", fill=c)
                else:
                    cv.itemconfigure(item, state="normal", fill=c)
                shown[i] = c
        try:
            self.top.attributes("-alpha", 0.62 * (1 - t ** 3))
        except tk.TclError:
            pass
        self._click_through()
        spent = (time.perf_counter() - frame_start) * 1000
        self.top.after(max(int(self.FRAME_MS - spent), 1), self._frame)

    def finish(self) -> None:
        if self.top is not None:
            try:
                self.top.destroy()
            except tk.TclError:
                pass
            self.top = None


class ScrollFrame(ttk.Frame):
    """A vertically scrolling area; .inner holds the content, on_width(width) fires on resize."""

    def __init__(self, master: tk.Misc, bg: str, on_width: Callable[[int], None]) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=24)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        def resized(e: tk.Event) -> None:
            self.canvas.itemconfigure(win, width=e.width - 6)
            on_width(e.width - 6)

        self.canvas.bind("<Configure>", resized)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, e: tk.Event) -> None:
        if self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-e.delta / 120) * 2, "units")

    def clear(self) -> None:
        for w in self.inner.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)


# ---------------------------------------------------------------------- settings
class SettingsDialog(tk.Toplevel):
    def __init__(self, master: "App", first_run: bool = False) -> None:
        super().__init__(master)
        self.app = master
        p = master.pal
        self.title("PoliTO Sync - Settings")
        self.configure(bg=p["bg"])
        self.resizable(False, False)
        self.transient(master)
        cur = read_env()
        cfg = master.cfg
        muted = p["muted"]

        frm = ttk.Frame(self, padding=28)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="hey, welcome 👋" if first_run else "settings",
                  font=(FONT_HEAD, 20)).grid(row=0, column=0, columnspan=3, sticky="w")
        intro = ("drop your PoliTO login and pick where course files should land."
                 if first_run else "login, download folder and vibes.")
        ttk.Label(frm, text=intro, wraplength=470, foreground=muted).grid(row=1, column=0, columnspan=3,
                                                                           sticky="w", pady=(2, 18))

        def label(row: int, text: str, hint: str = "") -> None:
            ttk.Label(frm, text=text, font=(FONT_HEAD, 10)).grid(row=row, column=0, sticky="w",
                                                                  pady=(10, 0), padx=(0, 16))
            if hint:
                ttk.Label(frm, text=hint, foreground=muted, font=(FONT, 8), wraplength=480).grid(
                    row=row + 1, column=0, columnspan=3, sticky="w")

        user = cur.get("POLITO_USERNAME", "")
        self.user = tk.StringVar(value="" if user in PLACEHOLDERS else user)
        pw = cur.get("POLITO_PASSWORD", "")
        self.pw = tk.StringVar(value="" if pw in PLACEHOLDERS else pw)
        self.folder = tk.StringVar(value=str(cfg.download_dir))
        self.create = tk.BooleanVar(value=cfg.create_missing or first_run)

        label(2, "student ID", "e.g. s123456")
        ttk.Entry(frm, textvariable=self.user, width=44).grid(row=2, column=1, columnspan=2, sticky="we",
                                                              pady=(10, 0))
        label(4, "password", "stays on this PC, in the .env file next to the app.")
        self.pw_entry = ttk.Entry(frm, textvariable=self.pw, width=36, show="•")
        self.pw_entry.grid(row=4, column=1, sticky="we", pady=(10, 0))
        self.show = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="show", variable=self.show,
                        command=lambda: self.pw_entry.configure(show="" if self.show.get() else "•")
                        ).grid(row=4, column=2, padx=(8, 0), pady=(10, 0))
        label(6, "download folder", "the folder that holds (or will hold) one subfolder per course.")
        ttk.Entry(frm, textvariable=self.folder, width=36).grid(row=6, column=1, sticky="we", pady=(10, 0))
        ttk.Button(frm, text="browse…", command=self._browse).grid(row=6, column=2, padx=(8, 0), pady=(10, 0))
        ttk.Checkbutton(frm, text="create a folder for each course automatically\n"
                                  "(untick if you already made your own course folders)",
                        variable=self.create).grid(row=8, column=0, columnspan=3, sticky="w", pady=(14, 0))
        self.had_key = "ANTHROPIC_API_KEY" in cur
        self.key = tk.StringVar(value=cur.get("ANTHROPIC_API_KEY", ""))
        label(9, "claude API key", "optional, for “ask claude” in Upcoming. when you use it, "
                                   "your recent notice text is sent to Anthropic.")
        ttk.Entry(frm, textvariable=self.key, width=44, show="•").grid(row=9, column=1, columnspan=2,
                                                                       sticky="we", pady=(10, 0))
        label(11, "theme")
        self.theme = tk.StringVar(value=THEME_CHOICES.get(master.theme_mode, THEME_CHOICES["system"]))
        ttk.Combobox(frm, textvariable=self.theme, state="readonly", width=20,
                     values=list(THEME_CHOICES.values())).grid(row=11, column=1, sticky="w", pady=(10, 0))

        btns = tk.Frame(frm, bg=p["bg"])
        btns.grid(row=13, column=0, columnspan=3, sticky="e", pady=(26, 0))
        PillButton(btns, master, "save", self._save, primary=True).pack(side="right")
        PillButton(btns, master, "cancel", self.destroy).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        dark_titlebar(self, master.mode == "dark")
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
        theme = next((k for k, v in THEME_CHOICES.items() if v == self.theme.get()), "system")
        updates = {
            "POLITO_USERNAME": user,
            "POLITO_PASSWORD": pw,
            "POLITO_DOWNLOAD_DIR": folder,
            "POLITO_CREATE_MISSING_COURSE_FOLDERS": "1" if self.create.get() else "0",
            "POLITO_THEME": theme,
        }
        key = self.key.get().strip()
        if key or self.had_key:
            updates["ANTHROPIC_API_KEY"] = key
        write_env(updates)
        self.destroy()
        self.app.reload_config()
        if theme != self.app.theme_mode:
            self.app.set_theme(theme)


# --------------------------------------------------------------------------- app
class App(tk.Tk):
    PAGES = (("files", "files"), ("notices", "notices"), ("upcoming", "upcoming"))
    TITLES = {"files": ("your files", "📂"), "notices": ("notices", "📣"), "upcoming": ("coming up", "👀")}

    def __init__(self) -> None:
        super().__init__()
        gfx.clear_cache()  # images belong to one Tk root
        self.title("PoliTO Sync")
        self.geometry("1140x760")
        self.minsize(940, 600)
        ico = ps.HERE / "assets" / "icon.ico"
        if ico.exists():
            try:
                self.iconbitmap(default=str(ico))
            except tk.TclError:
                pass
        init_fonts(self)

        self.cfg = ps.Config()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.last_file = self.cfg.state_dir / "last_run.json"
        self.q: queue.Queue = queue.Queue()
        self.busy = self.nbusy = self.aibusy = False
        self.dry = False
        self.total_missing = 0
        self.new_files: list[str] = []
        self.course_rows: list[tuple[tuple, list[str], str | None]] = []  # kept across theme rebuilds
        self.log_lines: list[tuple[str, str]] = []
        self.ai_text: str | None = None
        self.notice_rows: dict[str, dict] = {}
        self.notices, self.notices_at = ps.load_cached_notices(self.cfg)
        self.page = "files"
        # Text that must survive a rebuild of the widgets lives in variables on the root window.
        self.status_var = tk.StringVar(value="ready when you are.")
        self.ncourse = tk.StringVar(value=ALL_COURSES)
        self.nview = "subjects"  # Notices page: "subjects" (boxes) or "list" (one subject's notices)
        self.nsearch = tk.StringVar()
        self.nsearch.trace_add("write", lambda *_: self._on_search())

        self.theme_mode = os.environ.get("POLITO_THEME", "system").strip().lower()
        if self.theme_mode not in THEME_CHOICES:
            self.theme_mode = "system"
        self.side_collapsed = os.environ.get("POLITO_SIDEBAR", "open").strip().lower() == "collapsed"
        self._side_job: str | None = None
        self.bind("<Control-b>", lambda _e: self.toggle_sidebar())
        self._setup_logging()
        self._apply_theme()
        self._build()
        self.after(100, self._poll)
        if needs_setup():
            self.after(300, lambda: SettingsDialog(self, first_run=True))

    # ---------------------------------------------------------------- theming
    @property
    def mode(self) -> str:
        """The theme in use: 'light' or 'dark' (resolved when the theme is applied)."""
        return self._mode

    def _apply_theme(self) -> None:
        mode = self._mode = system_theme() if self.theme_mode == "system" else self.theme_mode
        self.pal = PALETTES[mode]
        self.kinds = KIND_COLORS[mode]
        p = self.pal
        st = ttk.Style(self)
        if sv_ttk is not None:
            sv_ttk.set_theme(mode)
        else:  # plain fallback that still follows the palette
            st.theme_use("clam")
            st.configure("TButton", padding=(14, 6))
            st.configure("TEntry", fieldbackground=p["card"])
        st.configure(".", font=(FONT, 10))
        for name in ("TFrame", "TPanedwindow"):
            st.configure(name, background=p["bg"])
        st.configure("TLabel", background=p["bg"], foreground=p["text"])
        st.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
        st.configure("Treeview", background=p["card"], fieldbackground=p["card"], foreground=p["text"],
                     rowheight=36, font=(FONT, 10), borderwidth=0)
        st.map("Treeview", background=[("selected", mix(p["card"], p["accent"], 0.28))],
               foreground=[("selected", p["text"])])
        st.configure("Treeview.Heading", font=(FONT_HEAD, 10))
        st.configure("Muted.TLabel", foreground=p["muted"], background=p["bg"])
        st.configure("Section.TLabel", foreground=p["muted"], background=p["bg"], font=(FONT_HEAD, 10))
        self.configure(bg=p["bg"])
        dark_titlebar(self, mode == "dark")

    def set_theme(self, theme: str) -> None:
        self.theme_mode = theme
        write_env({"POLITO_THEME": theme})
        for w in self.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        gfx.clear_cache()
        self._apply_theme()
        self._build()
        # Nudge Windows to repaint the title bar in the new colour.
        self.withdraw()
        self.after(10, self.deiconify)

    def toggle_theme(self) -> None:
        self.set_theme("light" if self.mode == "dark" else "dark")

    # ---------------------------------------------------------------- sidebar
    SIDE_FULL, SIDE_RAIL = 232, 68

    def _sidebar_labels(self, show: bool) -> None:
        """The wordmark and last-sync text only fit in the full sidebar."""
        if show:
            self.brand.pack(side="left", padx=(8, 0))
            self.last_label.pack(side="top", fill="x", padx=14, pady=(0, 10))
        else:
            self.brand.pack_forget()
            self.last_label.pack_forget()

    def toggle_sidebar(self) -> None:
        """Collapse to an icon rail / expand again, with a short slide. Remembered in .env."""
        if getattr(self, "_side_job", None):
            return
        self.side_collapsed = not self.side_collapsed
        write_env({"POLITO_SIDEBAR": "collapsed" if self.side_collapsed else "open"})
        start = self.side.winfo_width()
        end = self.SIDE_RAIL if self.side_collapsed else self.SIDE_FULL
        # The page slides along with the sidebar edge as it is (moving a window is cheap; re-laying it
        # out every frame is not), then changes to its final width once, at the end, with drawing paused.
        if not self.side_collapsed:
            self._sidebar_labels(True)  # show them as it opens; the sidebar clips them until there is room
        t0 = time.perf_counter()

        def step() -> None:
            t = min((time.perf_counter() - t0) / 0.2, 1.0)
            x = round(start + (end - start) * (1 - (1 - t) ** 3))  # ease-out
            self.side.place_configure(width=x)
            self.main.place_configure(x=x)
            if t < 1:
                self._side_job = self.after(12, step)
                return
            self._side_job = None
            if self.side_collapsed:
                self._sidebar_labels(False)
            self._relayout(lambda: self.main.place_configure(width=-end))

        step()

    def _relayout(self, change: Callable[[], None]) -> None:
        """Apply a layout change with drawing paused, let every widget finish redrawing, then show the
        result in one go - so you never see cards half-way through updating."""
        hwnd = self.main.winfo_id() if sys.platform == "win32" else 0
        user32 = None
        if hwnd:
            try:
                import ctypes
                user32 = ctypes.windll.user32
                user32.SendMessageW(hwnd, 0x000B, 0, 0)  # WM_SETREDRAW off
            except Exception:  # noqa: BLE001 - cosmetic only
                user32 = None
        try:
            change()
            self.update_idletasks()
            self.update()  # deliver the resulting <Configure> events (cards redraw themselves)
            pending = [self.main]
            while pending:  # the greeting banner waits a moment before redrawing; do it now
                w = pending.pop()
                pending.extend(w.winfo_children())
                if isinstance(w, Hero) and w._job:
                    w.after_cancel(w._job)
                    w._paint()
            self.update_idletasks()
        finally:
            if user32 is not None:
                user32.SendMessageW(hwnd, 0x000B, 1, 0)  # WM_SETREDRAW on
                # RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW
                user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0100)
        self.update()  # finish that repaint now, not during the first frames of the slide

    def course_color(self, name: str) -> str:
        colors = COURSE_COLORS[self.mode]
        return colors[zlib.crc32(name.encode("utf-8")) % len(colors)]

    def reload_config(self) -> None:
        self.cfg = ps.Config()
        self._update_subtitles()
        self._log("settings saved.", "muted")

    # ------------------------------------------------------------------ setup
    def _setup_logging(self) -> None:
        ps.log.setLevel(logging.INFO)
        ps.log.propagate = False
        fh = logging.FileHandler(self.cfg.state_dir / "sync.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        ps.log.addHandler(fh)
        ps.log.addHandler(QueueHandler(self.q))

    def _build(self) -> None:
        p = self.pal
        # Sidebar (collapsible: full width with labels, or a slim icon rail). Sidebar and page are both
        # placed by x position, so the slide (toggle_sidebar) can move them without re-laying out the page.
        width = self.SIDE_RAIL if self.side_collapsed else self.SIDE_FULL
        side = self.side = tk.Frame(self, bg=p["side"])
        side.place(x=0, y=0, relheight=1, width=width)
        top = tk.Frame(side, bg=p["side"])
        top.pack(fill="x", padx=(12, 8), pady=(22, 22))
        menu = tk.Label(top, text=icon("menu"), bg=p["side"], fg=p["muted"], cursor="hand2", width=2,
                        font=(ICON_FONT or FONT, 14), padx=6, pady=4)
        menu.pack(side="left")
        menu.bind("<Button-1>", lambda _e: self.toggle_sidebar())
        menu.bind("<Enter>", lambda _e: menu.configure(fg=p["accent2"]))
        menu.bind("<Leave>", lambda _e: menu.configure(fg=p["muted"]))
        self.brand = tk.Frame(top, bg=p["side"])
        for txt, fg in (("polito", p["text"]), (".sync", p["accent2"])):
            tk.Label(self.brand, text=txt, bg=p["side"], fg=fg, font=(FONT_HEAD, 21), padx=0, bd=0,
                     highlightthickness=0).pack(side="left")
        self.nav: dict[str, NavItem] = {}
        for key, text in self.PAGES:
            item = NavItem(side, self, key, text)
            item.pack(fill="x", padx=10, pady=2)
            self.nav[key] = item

        bottom = tk.Frame(side, bg=p["side"])
        bottom.pack(side="bottom", fill="x", padx=10, pady=(0, 16))
        self.last_label = tk.Label(bottom, text="", bg=p["side"], fg=p["muted"], font=(FONT, 8),
                                   justify="left", anchor="w", wraplength=190)
        other = "light" if self.mode == "dark" else "dark"
        self.theme_item = NavItem(bottom, self, other, f"{other} mode", on_click=self.toggle_theme)
        self.theme_item.pack(side="bottom", fill="x", pady=(2, 0))
        NavItem(bottom, self, "settings", "settings", on_click=self.open_settings).pack(side="bottom", fill="x")
        self._sidebar_labels(not self.side_collapsed)

        # Main area
        main = self.main = ttk.Frame(self)
        main.place(x=width, y=0, relheight=1, relwidth=1, width=-width)  # fills the window right of the sidebar
        ttk.Label(main, textvariable=self.status_var, style="Muted.TLabel", font=(FONT, 9),
                  padding=(34, 4, 34, 12)).pack(side="bottom", fill="x")
        self.pages: dict[str, ttk.Frame] = {}
        self.subtitles: dict[str, ttk.Label] = {}
        for key, _ in self.PAGES:
            page = ttk.Frame(main, padding=(34, 26, 30, 4))
            head = tk.Frame(page, bg=p["bg"])
            head.pack(fill="x")
            title, em = self.TITLES[key]
            tk.Label(head, text=title, bg=p["bg"], fg=p["text"], font=(FONT_HEAD, 30), padx=0).pack(side="left")
            em_img = gfx.emoji(em, 30)
            if em_img is not None:
                e = tk.Label(head, image=em_img, bg=p["bg"])
                e.image = em_img  # type: ignore[attr-defined]
                e.pack(side="left", padx=(12, 0), pady=(6, 0))
            sub = ttk.Label(page, text="", style="Muted.TLabel", font=(FONT, 10))
            sub.pack(anchor="w", pady=(0, 18))
            self.subtitles[key] = sub
            self.pages[key] = page
        self._build_files(self.pages["files"])
        self._build_notices(self.pages["notices"])
        self._build_upcoming(self.pages["upcoming"])
        self.side.lift()  # float above the page while sliding

        # Restore content after a rebuild
        for values, tags, folder in self.course_rows:
            iid = self.tree.insert("", "end", values=values, tags=tags)
            if folder:
                self.row_folder[iid] = folder
        for msg, tag in self.log_lines:
            self._log_insert(msg, tag)
        self._set_busy(self.busy)
        self._set_nbusy(self.nbusy)
        self._ai_button()
        self._render_notices()
        self._show_last_run()
        self.show_page(self.page, auto_refresh=False)

    def _update_subtitles(self) -> None:
        self.subtitles["files"].configure(text=f"fresh pdfs land in  {self.cfg.download_dir}")
        when = local_date(self.notices_at, with_time=True) if self.notices_at else "never"
        courses = len({n["course"] for n in self.notices})
        self.subtitles["notices"].configure(
            text=f"{len(self.notices)} notices from {courses} courses  ·  updated {when}" if self.notices
            else "what your profs have been posting")
        self.subtitles["upcoming"].configure(text="talks, exams, deadlines and class changes, pulled from your notices")

    def show_page(self, key: str, auto_refresh: bool = True) -> None:
        self.page = key
        for k, page in self.pages.items():
            if k == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        for k, item in self.nav.items():
            item.set_active(k == key)
        if auto_refresh and key != "files":
            self._maybe_refresh_notices()

    def _rippled(self, button: tk.Misc, action: Callable[[], None], busy_attr: str) -> None:
        """Start the colour ripple from `button`, then run the action (unless it's already running)."""
        if getattr(self, busy_attr):
            return
        Ripple(self, button)
        action()

    def open_settings(self) -> None:
        if self.busy:
            return
        SettingsDialog(self)

    # ------------------------------------------------------------- files page
    def _build_files(self, tab: ttk.Frame) -> None:
        p = self.pal
        self.row_folder: dict[str, str] = {}
        bar = tk.Frame(tab, bg=p["bg"])
        bar.pack(fill="x", pady=(0, 16))
        self.btn_sync = PillButton(bar, self, "sync now", lambda: self._rippled(
            self.btn_sync, lambda: self.run(dry=False), "busy"), primary=True)
        self.btn_check = PillButton(bar, self, "check first", lambda: self.run(dry=True))
        self.btn_open = PillButton(bar, self, "open folder", lambda: open_path(self.cfg.download_dir))
        self.btn_sync.pack(side="left")
        self.btn_check.pack(side="left", padx=8)
        self.btn_open.pack(side="left")
        self.progress = Meter(bar, self, width=240)
        self.progress.pack(side="right", pady=15)

        ttk.Label(tab, text="courses", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        card = RoundCard(tab, self, expand=True, pad=(10, 10))
        card.pack(fill="both", expand=True)
        cols = ("course", "have", "new", "skipped", "status")
        self.tree = ttk.Treeview(card.inner, columns=cols, show="headings", selectmode="browse", height=6)
        for col, text, width, anchor in (
            ("course", "course", 360, "w"), ("have", "already have", 110, "center"),
            ("new", "new", 70, "center"), ("skipped", "skipped", 80, "center"),
            ("status", "status", 190, "w"),
        ):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "course"))
        self.tree.tag_configure("odd", background=mix(p["card"], p["text"], 0.03))
        self.tree.tag_configure("new", foreground=p["green"], font=(FONT_SEMI, 10))
        self.tree.tag_configure("warn", foreground=p["orange"])
        self.tree.tag_configure("err", foreground=p["red"])
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(card.inner, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", self._open_course)

        ttk.Label(tab, text="activity  ·  double-click a course to open its folder",
                  style="Section.TLabel").pack(anchor="w", pady=(18, 8))
        logcard = RoundCard(tab, self, pad=(14, 10))
        logcard.pack(fill="x", pady=(0, 6))
        self.text = tk.Text(logcard.inner, height=6, wrap="word", relief="flat", bg=p["card"], fg=p["text"],
                            font=(FONT_MONO, 9), padx=4, pady=2, borderwidth=0, highlightthickness=0,
                            insertbackground=p["text"])
        self.text.pack(fill="x")
        for tag, color in (("ok", p["green"]), ("warn", p["orange"]), ("err", p["red"]), ("muted", p["muted"])):
            self.text.tag_configure(tag, foreground=color)
        self.text.configure(state="disabled")

    # ----------------------------------------------------------- notices page
    def _build_notices(self, tab: ttk.Frame) -> None:
        p = self.pal
        bar = tk.Frame(tab, bg=p["bg"])
        bar.pack(fill="x", pady=(0, 16))
        self.btn_nrefresh = PillButton(bar, self, "refresh", lambda: self._rippled(
            self.btn_nrefresh, self.refresh_notices, "nbusy"), primary=True)
        self.btn_nrefresh.pack(side="left")
        ttk.Label(bar, text="search", style="Muted.TLabel").pack(side="left", padx=(18, 6))
        ttk.Entry(bar, textvariable=self.nsearch, width=26).pack(side="left")

        # List on top, the notice you are reading underneath (drag the gap between them to resize).
        pane = ttk.PanedWindow(tab, orient="vertical")
        pane.pack(fill="both", expand=True, pady=(0, 6))
        left = RoundCard(pane, self, expand=True, pad=(10, 10))
        left.configure(height=320)  # equal starting heights + equal weights = an even split
        # The left card shows one of two views: subject boxes ("all" + one per course), or the
        # notices of the chosen subject with a back button.
        self.subject_wrap: list[tuple[tk.Label, int]] = []
        self.nsubjects = ScrollFrame(left.inner, p["card"], self._wrap_subjects)
        self.nlist = tk.Frame(left.inner, bg=p["card"])
        head = tk.Frame(self.nlist, bg=p["card"])
        head.pack(fill="x", padx=4, pady=(4, 10))
        back = PillButton(head, self, "‹  subjects", self._show_subjects, bg=p["card"], height=32, padx=14)
        back.pack(side="left", anchor="n")
        self.nlist_title = tk.Label(head, text="", bg=p["card"], fg=p["text"], font=(FONT_HEAD, 13), anchor="w",
                                    justify="left")
        self.nlist_title.pack(side="left", fill="x", expand=True, padx=(12, 0))
        head.bind("<Configure>", lambda e: self.nlist_title.configure(
            wraplength=max(e.width - back.winfo_reqwidth() - 24, 120)))
        body = tk.Frame(self.nlist, bg=p["card"])
        body.pack(fill="both", expand=True)
        cols = ("date", "course", "preview")
        self.ntree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for col, text, width, stretch in (("date", "date", 100, False), ("course", "course", 160, False),
                                          ("preview", "notice", 260, True)):
            self.ntree.heading(col, text=text, anchor="w")
            self.ntree.column(col, width=width, anchor="w", stretch=stretch)
        self.ntree.tag_configure("odd", background=mix(p["card"], p["text"], 0.03))
        self.ntree.tag_configure("new", foreground=p["accent2"], font=(FONT_SEMI, 10))
        self.ntree.pack(side="left", fill="both", expand=True)
        nsb = ttk.Scrollbar(body, orient="vertical", command=self.ntree.yview)
        nsb.pack(side="right", fill="y")
        self.ntree.configure(yscrollcommand=nsb.set)
        self.ntree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected_notice())
        pane.add(left, weight=1)

        right = RoundCard(pane, self, expand=True, pad=(8, 8))
        right.configure(height=320)
        self.ntext = tk.Text(right.inner, wrap="word", relief="flat", bg=p["card"], fg=p["text"],
                             font=(FONT, 11), padx=22, pady=18, borderwidth=0, highlightthickness=0,
                             cursor="arrow", spacing2=4)
        self.ntext.pack(side="left", fill="both", expand=True)
        tsb = ttk.Scrollbar(right.inner, orient="vertical", command=self.ntext.yview)
        tsb.pack(side="right", fill="y")
        self.ntext.configure(yscrollcommand=tsb.set)
        t = self.ntext
        t.tag_configure("h2", font=(FONT_HEAD, 10), foreground=p["muted"], spacing1=16, spacing3=4)
        t.tag_configure("muted", foreground=p["muted"], font=(FONT, 9))
        t.tag_configure("body", spacing1=2, spacing3=2)
        t.tag_configure("link", foreground=p["accent2"], underline=True)
        t.tag_bind("link", "<Enter>", lambda _e: t.configure(cursor="hand2"))
        t.tag_bind("link", "<Leave>", lambda _e: t.configure(cursor="arrow"))
        pane.add(right, weight=1)
        self._set_text(t, [("pick a notice above to read it.", "muted")])

    # ---------------------------------------------------------- upcoming page
    def _build_upcoming(self, tab: ttk.Frame) -> None:
        bar = tk.Frame(tab, bg=self.pal["bg"])
        bar.pack(fill="x", pady=(0, 14))
        self.btn_urefresh = PillButton(bar, self, "refresh", self.refresh_notices)
        self.btn_urefresh.pack(side="left")
        self.btn_ai = PillButton(bar, self, "ask claude ✦", self.run_ai_summary, primary=True)
        self.btn_ai.pack(side="left", padx=8)
        self.wrap_labels: list[tuple[tk.Label, int]] = []
        self.ucards = ScrollFrame(tab, self.pal["bg"], self._wrap_cards)
        self.ucards.pack(fill="both", expand=True)

    def _wrap_cards(self, width: int) -> None:
        for lbl, offset in self.wrap_labels:
            try:
                lbl.configure(wraplength=max(width - offset, 200))
            except tk.TclError:
                pass

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
    def _maybe_refresh_notices(self) -> None:
        """Opening Notices/Upcoming refreshes automatically when the cached notices are > 30 min old."""
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
        self._set_nbusy(True)
        self.status_var.set("pulling notices from polito…")
        threading.Thread(target=self._notices_work, daemon=True).start()

    def _set_nbusy(self, busy: bool) -> None:
        self.nbusy = busy
        for b in (self.btn_nrefresh, self.btn_urefresh):
            b.configure(state="disabled" if busy else "normal", text="refreshing…" if busy else "refresh")

    def _notices_work(self) -> None:
        try:
            api = ps.PolitoApi(self.cfg)
            notices = ps.fetch_notices(api, self.cfg, progress=lambda ev, data: self.q.put(("n" + ev, data)))
            self.q.put(("notices", notices))
        except Exception as exc:  # noqa: BLE001 - show anything to the user
            self.q.put(("notices_error", str(exc) if isinstance(exc, ps.AuthError)
                        else f"{type(exc).__name__}: {exc}"))

    def _on_ncourses(self, _n: int) -> None:
        pass

    def _on_ncourse(self, name: str) -> None:
        self.status_var.set(f"reading notices…  {name}")

    def _on_notices(self, notices: list) -> None:
        self._set_nbusy(False)
        self.notices = notices
        self.notices_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.ai_text = None  # notices changed, an old Claude summary may be stale
        new = sum(1 for n in notices if n.get("new"))
        msg = f"{new} new notice{'s' if new != 1 else ''} just dropped" if new else "notices up to date ✓"
        self.status_var.set(msg)
        self._log(f"notices: {len(notices)} total, {new} new.", "ok" if new else "muted")
        self._render_notices()

    def _on_notices_error(self, msg: str) -> None:
        self._set_nbusy(False)
        self.status_var.set("couldn't reach the notices. try again in a sec.")
        self._log("notices: " + msg, "err")
        messagebox.showerror("PoliTO Sync", f"Could not read notices:\n{msg}")

    def _render_notices(self) -> None:
        names = {n["course"] for n in self.notices}
        if self.ncourse.get() != ALL_COURSES and self.ncourse.get() not in names:
            self.ncourse.set(ALL_COURSES)
            self.nview = "subjects"
        self.nav["notices"].set_badge(sum(1 for n in self.notices if n.get("new")))
        self._render_subjects()
        self._fill_notices()
        self._show_notice_view()
        self._render_upcoming()
        self._update_subtitles()

    def _render_subjects(self) -> None:
        """The subject boxes: 'all' first, then each course, most recently active first."""
        if not hasattr(self, "nsubjects") or not self.nsubjects.winfo_exists():
            return
        p, box = self.pal, self.nsubjects
        box.clear()
        self.subject_wrap = []
        self.subject_boxes: list[RoundCard] = []
        self._subject_cols = 0
        inner = box.inner
        if not self.notices:
            tk.Label(inner, text="no notices yet", bg=p["card"], fg=p["text"],
                     font=(FONT_HEAD, 13)).pack(pady=(60, 4))
            tk.Label(inner, text="hit refresh to pull them from polito.", bg=p["card"], fg=p["muted"],
                     font=(FONT, 10)).pack()
            return
        by_course: dict[str, list[dict]] = {}
        for n in self.notices:
            by_course.setdefault(n["course"], []).append(n)

        def latest(ns: list[dict]) -> str:
            return max((n.get("publishedAt") or "" for n in ns), default="")

        courses = sorted(by_course, key=lambda c: latest(by_course[c]), reverse=True)
        self._subject_box(inner, ALL_COURSES, "all",
                          f"{len(self.notices)} notices from {len(courses)} courses",
                          sum(1 for n in self.notices if n.get("new")), p["accent2"])
        for c in courses:
            ns = by_course[c]
            when = local_date(latest(ns))[:6].lower()
            self._subject_box(inner, c, c, f"{len(ns)} notice{'s' if len(ns) != 1 else ''}  ·  latest {when}",
                              sum(1 for n in ns if n.get("new")), self.course_color(c))
        self._wrap_subjects(max(box.canvas.winfo_width() - 6, 300))

    def _subject_box(self, parent: tk.Frame, key: str, title: str, meta: str, new: int, color: str) -> None:
        p = self.pal
        fill = p["bg"]  # a shade off the card it sits on, so the boxes stand out
        card = RoundCard(parent, self, stripe=color, fill=fill, bg=p["card"], radius=16, pad=(16, 12),
                         click=lambda: self._select_subject(key))
        self.subject_boxes.append(card)  # placed in a grid by _wrap_subjects
        row = tk.Frame(card.inner, bg=fill)
        row.pack(fill="x")
        tk.Label(row, text="›", bg=fill, fg=p["muted"], font=(FONT_HEAD, 18)).pack(side="right", padx=(10, 2))
        if new:
            Chip(row, self, f"{new} new", "#FFFFFF", gradient=p["hot"], bg=fill).pack(side="right")
        text = tk.Frame(row, bg=fill)
        text.pack(side="left", fill="x", expand=True)
        name = tk.Label(text, text=title, bg=fill, fg=p["accent2"] if key == ALL_COURSES else p["text"],
                        font=(FONT_HEAD, 12), justify="left", anchor="w")
        name.pack(fill="x")
        tk.Label(text, text=meta, bg=fill, fg=p["muted"], font=(FONT, 9), anchor="w").pack(fill="x", pady=(2, 0))
        self.subject_wrap.append((name, 160 if new else 90))

    def _wrap_subjects(self, width: int) -> None:
        """Lay the subject boxes out in as many columns as fit (one box needs ~290px), then wrap names."""
        boxes = getattr(self, "subject_boxes", [])
        if not boxes:
            return
        cols = max(1, min(4, width // 290, len(boxes)))
        inner = self.nsubjects.inner
        if cols != self._subject_cols:
            self._subject_cols = cols
            for c in range(4):
                inner.columnconfigure(c, weight=1 if c < cols else 0, uniform="subjects" if c < cols else "")
            for i, card in enumerate(boxes):
                card.grid(row=i // cols, column=i % cols, sticky="nsew", padx=(0, 8), pady=(0, 8))
        col_w = width / cols - 8
        for lbl, offset in self.subject_wrap:
            try:
                lbl.configure(wraplength=max(int(col_w - offset), 100))
            except tk.TclError:
                pass

    def _select_subject(self, key: str) -> None:
        self.ncourse.set(key)
        self.nview = "list"
        self._fill_notices()
        self._show_notice_view()

    def _show_subjects(self) -> None:
        self.nview = "subjects"
        if self.nsearch.get():
            self.nsearch.set("")
        self._show_notice_view()

    def _show_notice_view(self) -> None:
        if not hasattr(self, "nlist") or not self.nlist.winfo_exists():
            return
        if self.nview == "list":
            self.nsubjects.pack_forget()
            self.nlist.pack(fill="both", expand=True)
            key = self.ncourse.get()
            everything = key == ALL_COURSES
            self.nlist_title.configure(text="all notices" if everything else key,
                                       fg=self.pal["accent2"] if everything else self.course_color(key))
            # The course column only matters when notices from several courses are mixed.
            self.ntree.configure(displaycolumns=("date", "course", "preview") if everything else ("date", "preview"))
        else:
            self.nlist.pack_forget()
            self.nsubjects.pack(fill="both", expand=True)

    def _on_search(self) -> None:
        if self.nsearch.get().strip() and self.nview != "list":
            self._select_subject(ALL_COURSES)  # typing while on the boxes searches every notice
        else:
            self._fill_notices()

    def _fill_notices(self) -> None:
        if not hasattr(self, "ntree") or not self.ntree.winfo_exists():
            return
        course, q = self.ncourse.get(), self.nsearch.get().strip().lower()
        self.ntree.delete(*self.ntree.get_children())
        self.notice_rows.clear()
        for n in self.notices:
            if course != ALL_COURSES and n["course"] != course:
                continue
            if q and q not in n["text"].lower() and q not in n["course"].lower():
                continue
            first = notice_preview(n["text"])
            idx = len(self.notice_rows)
            tags = (["odd"] if idx % 2 else []) + (["new"] if n.get("new") else [])
            iid = self.ntree.insert("", "end", tags=tags, values=(
                local_date(n.get("publishedAt")), n["course"], ("●  " if n.get("new") else "") + first[:120]))
            self.notice_rows[iid] = n

    def _show_selected_notice(self) -> None:
        sel = self.ntree.selection()
        n = self.notice_rows.get(sel[0]) if sel else None
        if not n:
            return
        t = self.ntext
        ctag = "coursetitle"  # no spaces: tk would split a tag name like "course:Fisica 1" in two
        t.tag_configure(ctag, foreground=self.course_color(n["course"]), font=(FONT_HEAD, 19), spacing3=2)
        chunks: list[tuple[str, object]] = [(n["course"] + "\n", ctag),
                                            (f"posted {local_date(n.get('publishedAt'), long=True)}", "muted")]
        if n.get("expiresAt"):
            chunks.append((f"  ·  expires {local_date(n['expiresAt'], long=True)}", "muted"))
        chunks.append(("\n\n", ""))
        chunks.append((n["text"] + "\n", "body"))
        for i, url in enumerate(n.get("links", [])):
            if i == 0:
                chunks.append(("\nlinks\n", "h2"))
            chunks.append((url + "\n", ("link", f"url{i}")))
        self._set_text(t, chunks)
        for i, url in enumerate(n.get("links", [])):
            t.tag_bind(f"url{i}", "<Button-1>", lambda _e, u=url: webbrowser.open(u))

    def open_notice(self, course_id: object, notice_id: object) -> None:
        """Jump from Upcoming to a notice, inside its course's list."""
        target = next((n for n in self.notices if n.get("courseId") == course_id and n.get("id") == notice_id),
                      None)
        if target is None:
            return
        self.nsearch.set("")
        self._select_subject(target["course"])
        self.show_page("notices", auto_refresh=False)
        for iid, n in self.notice_rows.items():
            if n is target:
                self.ntree.selection_set(iid)
                self.ntree.see(iid)
                return

    # -------------------------------------------------------------- upcoming
    def _render_upcoming(self) -> None:
        if not hasattr(self, "ucards") or not self.ucards.winfo_exists():
            return
        p, box = self.pal, self.ucards
        box.clear()
        self.wrap_labels = []
        inner = box.inner
        today = date.today()
        events, heads = ps.extract_events(self.notices, today) if self.notices else ([], [])
        week = [e for e in events if (e["date"] - today).days <= 7]
        self.nav["upcoming"].set_badge(len(week))

        hero = Hero(inner, self)
        hero.pack(fill="x")
        if not self.notices:
            hero.set(greeting(datetime.now()), "nothing loaded yet. hit refresh to pull your notices from polito.",
                     "📭")
            return
        if week:
            nxt = week[0]
            when = countdown(nxt["date"], today)
            when = {"today": "today", "tmrw": "tomorrow"}.get(when, f"{nxt['date']:%a %d %b}".lower())
            sub = (f"{len(week)} thing{'s' if len(week) != 1 else ''} on your radar this week. next up: "
                   f"{KIND_SHORT[nxt['kind']]}, {when}" + (f" at {nxt['time']}" if nxt["time"] else "") +
                   f" ({nxt['course']}).")
            emoji = "🔥" if len(week) >= 3 else "👀"
        elif events:
            nxt = events[0]
            sub = (f"quiet week. the next thing is a {KIND_SHORT[nxt['kind']]} on "
                   f"{nxt['date']:%a %d %b} ({nxt['course']}).").lower()
            emoji = "😌"
        else:
            sub, emoji = "no dates on the radar. go touch some grass.", "🌱"
        hero.set(greeting(datetime.now()), sub, emoji)

        stats = tk.Frame(inner, bg=p["bg"])
        stats.pack(fill="x", pady=(14, 0))
        for i, (num, label, color, em) in enumerate((
            (len(week), "this week", p["accent2"], "🔥"),
            (sum(e["kind"] in ("Exam", "Deadline") for e in events), "exams & deadlines", self.kinds["Exam"], "📝"),
            (sum(e["kind"] == "Seminar / talk" for e in events), "talks & seminars", self.kinds["Seminar / talk"],
             "🎤"),
        )):
            tile = RoundCard(stats, self, pad=(20, 14))
            tile.pack(side="left", fill="x", expand=True, padx=(0 if i == 0 else 12, 0))
            row = tk.Frame(tile.inner, bg=p["card"])
            row.pack(fill="x")
            tk.Label(row, text=str(num), bg=p["card"], fg=color, font=(FONT_HEAD, 30)).pack(side="left")
            em_img = gfx.emoji(em, 26)
            if em_img is not None:
                e = tk.Label(row, image=em_img, bg=p["card"])
                e.image = em_img  # type: ignore[attr-defined]
                e.pack(side="right")
            tk.Label(tile.inner, text=label, bg=p["card"], fg=p["muted"], font=(FONT, 10)).pack(anchor="w")

        if self.ai_text:
            self._section(inner, "claude's take")
            card = RoundCard(inner, self, stripe=p["accent"], pad=(20, 16))
            card.pack(fill="x", pady=4)
            lbl = tk.Label(card.inner, text=self.ai_text.strip(), bg=p["card"], fg=p["text"], font=(FONT, 10),
                           justify="left", anchor="w")
            lbl.pack(fill="x")
            self.wrap_labels.append((lbl, 70))

        names = {"Today & tomorrow": "today & tmrw", "Next 7 days": "this week", "Later": "later"}
        for title, evs in ps.group_events(events, today):
            self._section(inner, f"{names.get(title, title.lower())}  ·  {len(evs)}")
            for ev in evs:
                self._event_card(inner, ev, today)
        if heads:
            self._section(inner, f"heads-up  ·  no date given  ·  {len(heads)}")
            for h in heads:
                self._event_card(inner, h, today)
        tk.Label(inner, text="dates are auto-read from the notice text. double-check the original before you "
                             "plan your life around it. tap a card to open it.",
                 bg=p["bg"], fg=p["muted"], font=(FONT, 8)).pack(anchor="w", pady=(18, 10))
        self._wrap_cards(box.canvas.winfo_width() - 6)

    def _section(self, parent: tk.Frame, text: str) -> None:
        tk.Label(parent, text=text, bg=self.pal["bg"], fg=self.pal["muted"],
                 font=(FONT_HEAD, 11)).pack(anchor="w", pady=(22, 8))

    def _event_card(self, parent: tk.Frame, ev: dict, today: date) -> None:
        p = self.pal
        kind_color = self.kinds.get(ev["kind"], p["muted"])
        ccolor = self.course_color(ev["course"])
        card = RoundCard(parent, self, stripe=ccolor, pad=(16, 14),
                         click=lambda: self.open_notice(ev.get("courseId"), ev.get("notice_id")))
        card.pack(fill="x", pady=5)
        inn = card.inner
        # Date block
        block = tk.Frame(inn, bg=p["card"])
        block.pack(side="left", fill="y", padx=(4, 14))
        tk.Frame(block, bg=p["card"], width=64, height=0).pack()
        d = ev.get("date")
        if d:
            soon = (d - today).days <= 1
            tk.Label(block, text=f"{d:%a}".lower(), bg=p["card"], fg=p["accent2"] if soon else p["muted"],
                     font=(FONT_HEAD, 9)).pack()
            tk.Label(block, text=str(d.day), bg=p["card"], fg=p["text"], font=(FONT_HEAD, 28)).pack(pady=0)
            tk.Label(block, text=f"{d:%b}".lower(), bg=p["card"], fg=p["muted"], font=(FONT_HEAD, 9)).pack()
        else:
            em = gfx.emoji("👀", 30)
            if em is not None:
                e = tk.Label(block, image=em, bg=p["card"])
                e.image = em  # type: ignore[attr-defined]
                e.pack(pady=(4, 2))
            tk.Label(block, text=local_date(ev.get("publishedAt"))[:6].lower(), bg=p["card"], fg=p["muted"],
                     font=(FONT_HEAD, 9)).pack()
        # Body
        body = tk.Frame(inn, bg=p["card"])
        body.pack(side="left", fill="both", expand=True)
        top = tk.Frame(body, bg=p["card"])
        top.pack(fill="x")
        Chip(top, self, KIND_SHORT.get(ev["kind"], ev["kind"].lower()), kind_color,
             fill=mix(p["card"], kind_color, 0.16), emoji=KIND_EMOJI.get(ev["kind"])).pack(side="left")
        if d:
            cd = countdown(d, today)
            if (d - today).days <= 1:
                Chip(top, self, cd, "#FFFFFF", gradient=p["hot"], emoji="🔥").pack(side="left", padx=(8, 0))
            else:
                Chip(top, self, cd, p["muted"], fill=mix(p["card"], p["muted"], 0.14)).pack(side="left", padx=(8, 0))
        if ev.get("time"):
            tk.Label(top, text=icon("clock"), bg=p["card"], fg=p["muted"],
                     font=(ICON_FONT or FONT, 10)).pack(side="left", padx=(14, 4))
            tk.Label(top, text=ev["time"], bg=p["card"], fg=p["text"], font=(FONT_HEAD, 10)).pack(side="left")
        tk.Label(top, text=ev["course"], bg=p["card"], fg=ccolor, font=(FONT_HEAD, 10)).pack(side="left",
                                                                                            padx=(14, 0))
        snippet = tk.Label(body, text=ev["snippet"], bg=p["card"], fg=p["text"], font=(FONT, 10),
                           justify="left", anchor="w")
        snippet.pack(fill="x", pady=(8, 0))
        self.wrap_labels.append((snippet, 150))

    # --------------------------------------------------------------- claude
    def _ai_button(self) -> None:
        self.btn_ai.configure(state="disabled" if self.aibusy else "normal",
                              text="thinking…" if self.aibusy else "ask claude ✦")

    def run_ai_summary(self) -> None:
        if self.aibusy:
            return
        if not os.environ.get("ANTHROPIC_API_KEY"):
            messagebox.showinfo("PoliTO Sync", "To get a written summary from Claude, add a Claude API key in "
                                "Settings (optional). The cards work without it.")
            return
        if importlib.util.find_spec("anthropic") is None:
            messagebox.showinfo("PoliTO Sync", "The Claude add-on is not installed. Run this once in the app "
                                "folder, then restart the app:\n\n.venv\\Scripts\\pip install anthropic")
            return
        if not self.notices:
            messagebox.showinfo("PoliTO Sync", "Refresh the notices first.")
            return
        self.aibusy = True
        self._ai_button()
        notices = list(self.notices)
        threading.Thread(target=self._ai_work, args=(notices,), daemon=True).start()

    def _ai_work(self, notices: list) -> None:
        try:
            self.q.put(("ai_done", ps.ai_summary(notices, date.today())))
        except Exception as exc:  # noqa: BLE001 - show anything to the user
            self.q.put(("ai_error", f"{type(exc).__name__}: {exc}"))

    def _on_ai_done(self, text: str) -> None:
        self.aibusy = False
        self._ai_button()
        self.ai_text = text
        self._render_upcoming()

    def _on_ai_error(self, msg: str) -> None:
        self.aibusy = False
        self._ai_button()
        messagebox.showerror("PoliTO Sync", f"Claude summary failed:\n{msg}")

    # ---------------------------------------------------------------- helpers
    def _log(self, msg: str, tag: str = "") -> None:
        line = f"{datetime.now():%H:%M:%S}  {msg}"
        self.log_lines = (self.log_lines + [(line, tag)])[-300:]
        self._log_insert(line, tag)

    def _log_insert(self, line: str, tag: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n", tag)
        self.text.see("end")
        self.text.configure(state="disabled")

    def _show_last_run(self) -> None:
        try:
            last = json.loads(self.last_file.read_text(encoding="utf-8"))
            when = datetime.fromisoformat(last["at"]).strftime("%d %b, %H:%M").lower()
            text = f"last sync · {when}\n{last['new']} fresh file{'s' if last['new'] != 1 else ''}"
        except (OSError, ValueError, KeyError):
            text = "not synced yet"
        if hasattr(self, "last_label"):
            self.last_label.configure(text=text)

    def _open_course(self, _event: object) -> None:
        sel = self.tree.selection()
        folder = self.row_folder.get(sel[0]) if sel else None
        if folder:
            new = Path(folder) / self.cfg.new_subdir if self.cfg.new_subdir else Path(folder)
            open_path(new if new.is_dir() else Path(folder))

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn_check.configure(state=state)
        self.btn_sync.configure(state=state, text="syncing…" if busy and not self.dry else "sync now")
        self.configure(cursor="watch" if busy else "")

    # ------------------------------------------------------------------- work
    def run(self, dry: bool) -> None:
        if self.busy:
            return
        self.dry = dry
        self.total_missing = 0
        self.new_files.clear()
        self.row_folder.clear()
        self.course_rows.clear()
        self.tree.delete(*self.tree.get_children())
        self.progress.set_max(1)
        self._set_busy(True)
        self.status_var.set("peeking at polito…" if dry else "syncing…")
        self._log("checking for new files (preview, nothing is downloaded)…" if dry else "sync started…", "muted")
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
        self.progress.set_max(n)

    def _on_course(self, c: dict) -> None:
        idx = len(self.course_rows)
        tags = ["odd"] if idx % 2 else []
        if c.get("folder") is None:
            status, tags = "⚠  no matching folder", tags + ["warn"]
        elif c.get("error"):
            status, tags = "✖  couldn't read", tags + ["err"]
        elif c["missing"]:
            status = f"⬇  {c['missing']} to grab" if self.dry else f"✔  {c['missing']} downloaded"
            tags.append("new")
        else:
            status = "✔  up to date"
        self.total_missing += c.get("missing", 0)
        values = (c["name"], c["present"], c["missing"], c["skipped"], status)
        self.course_rows.append((values, tags, c.get("folder")))
        iid = self.tree.insert("", "end", values=values, tags=tags)
        if c.get("folder"):
            self.row_folder[iid] = c["folder"]
        self.progress.step(1)

    def _on_file(self, path: str) -> None:
        self.new_files.append(path)
        self.status_var.set(f"downloading…  {len(self.new_files)} file(s) so far")

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
        self.progress.fill()
        if self.dry:
            n = self.total_missing
            msg = f"{n} file{'s' if n != 1 else ''} waiting for you. hit sync now to grab them." if n else \
                "all caught up ✓"
            self.status_var.set(msg)
            self._log(msg, "muted")
            return
        self.last_file.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                                              "new": len(new)}), encoding="utf-8")
        ps.notify(new)
        self._show_last_run()
        msg = f"{len(new)} fresh file{'s' if len(new) != 1 else ''} dropped ✓" if new else "all caught up ✓"
        self.status_var.set(msg)
        self._log(msg, "ok" if new else "muted")

    def _on_error(self, msg: str) -> None:
        self._set_busy(False)
        self.status_var.set("something broke. details in the activity box.")
        self._log(msg, "err")
        messagebox.showerror("PoliTO Sync", msg)


if __name__ == "__main__":
    App().mainloop()
