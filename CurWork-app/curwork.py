"""
CurWork: a simple window for billers to get CUR workbooks from Amazon S3,
run the existing VBA macros on local copies, send the results back to S3,
and leave nothing behind on the laptop.

Version:     Beta 0.014
Status:      DRAFT - For Internal Use (FPT)
Updated:     2026-11-23 00:16 UTC
Modified by: mbitar

Run:  python curwork.py            (or the packaged CurWork.exe)
      python curwork.py --config path\\to\\curwork_admin_settings.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import curwork_core as core
import curwork_help as helptext

log = core.log
APP_NAME = "CurWork"
APP_TITLE = "CurWork - CUR files from S3"
APP_DESCRIPTION = ("CurWork downloads converted CUR workbooks from Amazon S3 to your In folder, so the existing "
                   "Excel macros can run on copies on this laptop. It saves the results from your Out folder in S3, "
                   "and cleans up your work folder when you finish.")
WINDOWS_APP_ID = "CurWork.Desktop"   # groups CurWork's windows under its own taskbar icon on Windows


def _enable_windows_dpi() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def _set_windows_app_id() -> None:
    """Give the process its own taskbar identity, so Windows shows CurWork's icon instead of Python's
    (Microsoft: SetCurrentProcessExplicitAppUserModelID, called before any window is created)."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
        except Exception:
            pass


def asset_path(name: str) -> Path:
    """Files in the assets folder: bundled inside the built app, or next to curwork.py when run from source."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


def apply_app_icon(root: tk.Tk) -> None:
    """Window, taskbar and Dock icon. On a Mac, iconphoto also sets the Dock icon when run from source;
    the built CurWork.app gets its icon (and its name in the Dock) from the bundle."""
    images = []
    for name in ("curwork-256.png", "curwork-64.png"):
        try:
            images.append(tk.PhotoImage(master=root, file=str(asset_path(name))))
        except tk.TclError:
            pass
    if images:
        root.iconphoto(True, *images)
        root._curwork_icons = images  # keep references so Tk doesn't drop the images
    if os.name == "nt":
        try:
            root.iconbitmap(default=str(asset_path("curwork.ico")))  # crisp 16/32 px icons on Windows
        except tk.TclError:
            pass


def close_window(win: tk.Toplevel) -> None:
    """Close a dialog safely: release its grab first, then destroy it, then give focus back to the main window.
    On macOS, destroying a window that still holds the grab can leave the app frozen with a spinning wheel."""
    parent = win.master
    try:
        win.grab_release()
    except tk.TclError:
        pass
    try:
        win.destroy()
    except tk.TclError:
        pass
    try:
        parent.focus_set()
    except (tk.TclError, AttributeError):
        pass


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))  # noqa: S606 - opens Explorer on a folder we own
    elif sys.platform == "darwin":
        subprocess.Popen(["/usr/bin/open", str(path)])  # full path: never pick up another "open" from PATH
    else:
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, str(path)])


def _package_version(module_name: str) -> str:
    try:
        from importlib import metadata
        return metadata.version(module_name)
    except Exception:
        mod = sys.modules.get(module_name)
        return str(getattr(mod, "__version__", "not found"))


def about_details(app: "CurWorkApp") -> list[tuple[str, list[tuple[str, str]]]]:
    """Grouped facts for the About window and for 'Copy details'. No secrets: no keys, tokens or passwords."""
    s = app.s
    tk_ver = app.root.tk.call("info", "patchlevel")
    who = app.who_lbl.cget("text")
    frozen = getattr(sys, "frozen", False)
    return [
        ("CurWork", [
            ("Version", f"{core.RELEASE_LABEL} ({core.VERSION})"),
            ("Status", core.STATUS),
            ("Build date", str(core.BUILD_DATE)),
            ("Modified by", core.MODIFIED_BY),
            ("Running as", "built app" if frozen else "Python source"),
            ("Program", str(Path(sys.executable if frozen else __file__).resolve())),
        ]),
        ("This computer", [
            ("Operating system", f"{platform.system()} {platform.release()} ({platform.machine()})"),
            ("OS details", platform.platform()),
            ("Python", f"{platform.python_version()} ({platform.python_implementation()}, {sys.executable})"),
            ("Tcl/Tk", f"{tk_ver} ({app.root.tk.call('tk', 'windowingsystem')})"),
        ]),
        ("Python packages", [(name, _package_version(name))
                             for name in ("boto3", "botocore", "s3transfer", "urllib3")]),
        ("AWS", [
            ("Sign-in", who.removeprefix("Signed in: ")),
            ("AWS profile", s.aws_profile or "(default)"),
            ("Region", s.region + ("  (FIPS endpoints)" if s.use_fips_endpoint else "")),
            ("Bucket", s.bucket),
        ]),
        ("Files", [
            ("Admin settings", str(s.source_path or "not found")
                               + (f"  (version {s.admin_version})" if s.admin_version else "")),
            ("My preferences", str(app.prefs_store.path)),
            ("Work folder", str(app.work.root)),
            ("Today's log", str(app.log_file)),
        ]),
    ]


class Tooltip:
    """A short tip that appears when you point at a control, or tab to it with the keyboard.

    It waits a moment before showing (so it doesn't flicker), never takes the keyboard focus, and goes away
    when you move off, click, or press a key."""

    DELAY_MS = 600

    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text = widget, text
        self.tip: tk.Toplevel | None = None
        self._after: str | None = None
        self._pressed_at = 0.0
        for seq, fn in (("<Enter>", self._schedule), ("<Leave>", self.hide), ("<ButtonPress>", self._pressed),
                        ("<KeyPress>", self.hide), ("<FocusIn>", self._focused), ("<FocusOut>", self.hide),
                        ("<Destroy>", self.hide)):
            widget.bind(seq, fn, add="+")

    def _pressed(self, _e=None) -> None:
        self._pressed_at = time.monotonic()
        self.hide()

    def _focused(self, _e=None) -> None:
        if time.monotonic() - self._pressed_at > 0.5:   # focus from the keyboard, not from a click
            self._schedule()

    def _schedule(self, _e=None) -> None:
        self._cancel()
        try:
            self._after = self.widget.after(self.DELAY_MS, self.show)
        except tk.TclError:
            pass

    def _cancel(self) -> None:
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def show(self) -> None:
        self._after = None
        try:
            if self.tip is not None or not self.widget.winfo_viewable():
                return
            tw = tk.Toplevel(self.widget)
        except tk.TclError:
            return
        tw.wm_overrideredirect(True)
        if tw.tk.call("tk", "windowingsystem") == "aqua":
            try:   # macOS: a real help-tag window that never steals focus
                tw.tk.call("::tk::unsupported::MacWindowStyle", "style", tw._w, "help", "noActivates")
            except tk.TclError:
                pass
        tk.Label(tw, text=self.text, justify="left", wraplength=340, background="#fffbe6", foreground="#1f1f1f",
                 relief="solid", borderwidth=1, padx=8, pady=5, font="TkTooltipFont").pack()
        tw.update_idletasks()
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        x = max(0, min(x, tw.winfo_screenwidth() - tw.winfo_reqwidth() - 8))
        if y + tw.winfo_reqheight() > tw.winfo_screenheight() - 8:
            y = self.widget.winfo_rooty() - tw.winfo_reqheight() - 6
        tw.wm_geometry(f"+{x}+{y}")
        self.tip = tw

    def hide(self, _e=None) -> None:
        self._cancel()
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


def add_tip(store: dict, widget: tk.Widget, key: str) -> tk.Widget:
    """Attach the tip helptext.TIPS[key] to widget, remember it in store, and return the widget."""
    store[key] = Tooltip(widget, helptext.TIPS[key])
    return widget


class HelpWindow(tk.Toplevel):
    """CurWork Help: topics on the left, the topic on the right, and a search box. Not modal."""

    def __init__(self, parent: tk.Tk, start: str = "quick_start"):
        super().__init__(parent)
        self.title("CurWork Help")
        self.minsize(760, 520)
        self.geometry("900x620")
        self.tips: dict[str, Tooltip] = {}
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        top = ttk.Frame(body)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(top, text="Search help:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_box = add_tip(self.tips, ttk.Entry(top, textvariable=self.search_var, width=36), "h_search")
        self.search_box.pack(side="left", padx=6)
        self.found_lbl = ttk.Label(top, text="", style="Hint.TLabel")
        self.found_lbl.pack(side="left", padx=6)
        self.search_var.trace_add("write", lambda *_: self._filter())

        self.topics = ttk.Treeview(body, show="tree", selectmode="browse", height=18)
        self.topics.column("#0", width=230, stretch=False)
        self.topics.grid(row=1, column=0, sticky="nsw", padx=(0, 10))
        self.topics.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        text_frame = ttk.Frame(body)
        text_frame.grid(row=1, column=1, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        base = tkfont.nametofont("TkTextFont")
        self._h_font = base.copy()
        self._h_font.configure(size=base.cget("size") + 3, weight="bold")
        self.text = tk.Text(text_frame, wrap="word", padx=14, pady=10, relief="flat", borderwidth=0,
                            font=base, cursor="arrow", spacing1=2, spacing3=4)
        self.text.grid(row=0, column=0, sticky="nsew")
        tsb = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        tsb.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=tsb.set)
        self.text.tag_configure("h", font=self._h_font, spacing1=10, spacing3=6)
        self.text.tag_configure("bullet", lmargin1=12, lmargin2=28)
        self.text.tag_configure("hit", background="#fff3b0", foreground="#1f1f1f")

        bottom = ttk.Frame(body)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(bottom, text=f"{APP_NAME} {core.RELEASE_LABEL}  \u00b7  {core.STATUS}  \u00b7  Updated {core.BUILD_DATE}",
                  style="Hint.TLabel").pack(side="left")
        self.close_btn = ttk.Button(bottom, text="Close", width=12, command=self.close)
        self.close_btn.pack(side="right")

        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<Command-w>" if self.tk.call("tk", "windowingsystem") == "aqua" else "<Control-w>",
                  lambda _e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.current = ""
        self._fill(helptext.search(""))
        self.show(start)
        self.lift()
        self.tips["h_search"]._pressed_at = time.monotonic()   # no tip just because the window opened
        self.search_box.focus_set()

    def close(self) -> None:
        close_window(self)

    def _fill(self, ids: list[str]) -> None:
        self.topics.delete(*self.topics.get_children())
        for tid, title, _ in helptext.TOPICS:
            if tid in ids:
                self.topics.insert("", "end", iid=tid, text=title)

    def _on_select(self) -> None:
        sel = self.topics.selection()
        if sel and sel[0] != self.current:
            self.show(sel[0])

    def show(self, topic_id: str) -> None:
        """Show one topic (and select it in the list)."""
        try:
            tid, _title, body = helptext.topic(topic_id)
        except KeyError:
            tid, _title, body = helptext.TOPICS[0]
        self.current = tid
        if self.topics.exists(tid) and self.topics.selection() != (tid,):
            self.topics.selection_set(tid)
            self.topics.see(tid)
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for line in body.splitlines():
            if line.startswith("# "):
                self.text.insert("end", line[2:] + "\n", "h")
            elif line.startswith("- "):
                self.text.insert("end", "\u2022  " + line[2:] + "\n", "bullet")
            else:
                self.text.insert("end", line + "\n")
        self._highlight()
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)

    def _filter(self) -> None:
        ids = helptext.search(self.search_var.get())
        self._fill(ids)
        words = self.search_var.get().strip()
        self.found_lbl.configure(text="" if not words else (f"{len(ids)} topic(s)" if ids else "No topics match"))
        if ids:
            self.show(self.current if self.current in ids else ids[0])

    def _highlight(self) -> None:
        self.text.tag_remove("hit", "1.0", "end")
        for word in self.search_var.get().split():
            start = "1.0"
            while True:
                start = self.text.search(word, start, stopindex="end", nocase=True)
                if not start:
                    break
                end = f"{start}+{len(word)}c"
                self.text.tag_add("hit", start, end)
                start = end


class AboutDialog(tk.Toplevel):
    """About CurWork: what the tool does, and the versions and paths support needs."""

    def __init__(self, parent: tk.Tk, app: "CurWorkApp"):
        super().__init__(parent)
        self.app = app
        self.title("About CurWork")
        self.transient(parent)
        self.resizable(True, True)
        self.minsize(720, 560)
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(2, weight=1)

        icon = getattr(parent, "_curwork_icons", [])
        if icon:
            ttk.Label(body, image=icon[-1]).grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 14))
        ttk.Label(body, text=f"{APP_NAME}  {core.RELEASE_LABEL}", style="Title.TLabel").grid(
            row=0, column=1, sticky="w")
        info = ttk.Frame(body)
        info.grid(row=1, column=1, sticky="w", pady=(2, 10))
        ttk.Label(info, text=f"{core.STATUS}  \u00b7  Updated {core.BUILD_DATE}  \u00b7  Modified by: {core.MODIFIED_BY}",
                  style="Hint.TLabel").pack(anchor="w")
        ttk.Label(info, text=APP_DESCRIPTION, wraplength=560, justify="left").pack(anchor="w", pady=(8, 0))

        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        self._bold = bold
        cols = ("value",)
        table = ttk.Treeview(body, columns=cols, show="tree headings", selectmode="browse", height=18)
        table.heading("#0", text="Item")
        table.heading("value", text="Value")
        table.column("#0", width=170, stretch=False)
        table.column("value", width=470)
        table.tag_configure("group", font=bold)
        self.groups = about_details(app)
        for group, rows in self.groups:
            g = table.insert("", "end", text=group, open=True, tags=("group",))
            for k, v in rows:
                table.insert(g, "end", text=k, values=(v,))
        sb = ttk.Scrollbar(body, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=sb.set)
        table.grid(row=2, column=0, columnspan=2, sticky="nsew")
        sb.grid(row=2, column=2, sticky="ns")

        btns = ttk.Frame(body)
        btns.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.close_btn = ttk.Button(btns, text="Close", width=16, command=self.close)
        self.close_btn.pack(side="right")
        ttk.Button(btns, text="Open log folder", width=16,
                   command=lambda: open_folder(app.work.log_dir)).pack(side="right", padx=(0, 6))
        ttk.Button(btns, text="Copy details", width=16, command=self.copy).pack(side="right", padx=(0, 6))
        self.copied = ttk.Label(btns, text="", style="Good.TLabel")
        self.copied.pack(side="left")
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<Command-w>" if self.tk.call("tk", "windowingsystem") == "aqua" else "<Control-w>", lambda _e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        # Not modal: an About window shouldn't block the app (Apple HIG). No grab, nothing waits on it.
        self.lift()
        self.focus_set()

    def close(self) -> None:
        close_window(self)

    def text(self) -> str:
        lines = [f"{APP_NAME} {core.RELEASE_LABEL} - {core.STATUS}",
                 f"Copied {_dt.datetime.now(_dt.timezone.utc):%Y-%m-%d %H:%M} UTC", ""]
        for group, rows in self.groups:
            lines.append(f"[{group}]")
            lines += [f"  {k}: {v}" for k, v in rows]
            lines.append("")
        return "\n".join(lines)

    def copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.text())
        self.copied.configure(text="Copied. Paste it into your message to your admin.")


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: "queue.Queue"):
        super().__init__(level=logging.INFO)
        self.q = q
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put(("log", self.format(record), record.levelno))
        except Exception:
            pass


class ExistsDialog(tk.Toplevel):
    """Ask what to do when a result file is already in S3."""

    def __init__(self, parent: tk.Misc, key: str):
        super().__init__(parent)
        self.title("File already in S3")
        self.resizable(False, False)
        self.transient(parent)
        self.result = "cancel"
        ttk.Label(self, text="This file is already in S3:", padding=(16, 14, 16, 2)).pack(anchor="w")
        ttk.Label(self, text=key, font=("Segoe UI", 9, "bold"), padding=(16, 0, 16, 8), wraplength=520).pack(anchor="w")
        ttk.Label(
            self,
            text="Replacing it is safe: S3 keeps the old copy as an earlier version, as long as your admin "
                 "has turned on version history for the bucket.",
            padding=(16, 0, 16, 12), wraplength=520,
        ).pack(anchor="w")
        row = ttk.Frame(self, padding=(16, 0, 16, 14))
        row.pack(fill="x")
        for text, value in (("Replace", "overwrite"), ("Replace all", "overwrite_all"),
                            ("Skip", "skip"), ("Skip all", "skip_all"), ("Stop", "cancel")):
            ttk.Button(row, text=text, command=lambda v=value: self._done(v)).pack(side="left", padx=(0, 6))
        self.protocol("WM_DELETE_WINDOW", lambda: self._done("cancel"))
        self.grab_set()
        self.wait_window(self)

    def _done(self, value: str) -> None:
        self.result = value
        close_window(self)


class SettingsDialog(tk.Toplevel):
    """Settings window: the user's own preferences (editable) and the admin settings (read-only)."""

    PAD = {"padx": (0, 12), "pady": 4}

    def __init__(self, parent: tk.Tk, app: "CurWorkApp"):
        super().__init__(parent)
        self.app = app
        self.title("CurWork Settings")
        self.transient(parent)
        self.minsize(720, 640)
        p = app.prefs
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        self._bold = bold  # keep a reference so Tk doesn't drop the font

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        # ---- My preferences: label column on the left, controls on the right ----
        mine = ttk.LabelFrame(body, text="  My preferences  ", padding=(12, 8))
        mine.grid(row=0, column=0, sticky="ew")
        mine.columnconfigure(1, weight=1)

        ttk.Label(mine, text="Result type", font=bold).grid(row=0, column=0, sticky="w", **self.PAD)
        self.tips: dict[str, Tooltip] = {}
        tip = lambda w, key: add_tip(self.tips, w, key)  # noqa: E731
        self.remember_var = tk.BooleanVar(value=p.remember_result_type)
        tip(ttk.Checkbutton(mine, text="Start with the last result type I used", variable=self.remember_var),
            "s_remember").grid(row=0, column=1, columnspan=2, sticky="w", pady=4)

        ttk.Label(mine, text="Recent folders", font=bold).grid(row=1, column=0, sticky="w", **self.PAD)
        rec = ttk.Frame(mine)
        rec.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(rec, text="Keep").pack(side="left")
        self.limit_var = tk.IntVar(value=p.recent_limit)
        tip(ttk.Spinbox(rec, from_=0, to=core.MAX_RECENT, textvariable=self.limit_var, width=4),
            "s_recent").pack(side="left", padx=6)
        ttk.Label(rec, text=f"(0 to {core.MAX_RECENT}; 0 turns it off)", style="Hint.TLabel").pack(side="left")
        self.recent = list(p.recent_folders)
        self.recent_lbl = ttk.Label(rec, text="", style="Hint.TLabel")
        self.recent_lbl.pack(side="left", padx=(12, 0))
        tip(ttk.Button(mine, text="Clear recent folders", width=20, command=self._clear_recent),
            "s_clear_recent").grid(row=1, column=2, sticky="e", padx=(8, 0), pady=4)
        self._update_recent_label()

        ttk.Label(mine, text="Pinned folders", font=bold).grid(row=2, column=0, sticky="nw", padx=(0, 12), pady=(8, 4))
        self.pins = tip(tk.Listbox(mine, height=5, selectmode="extended", exportselection=False, activestyle="none"),
                        "s_pins")
        for f in p.pinned_folders:
            self.pins.insert("end", f)
        self.pins.grid(row=2, column=1, sticky="ew", pady=(8, 4))
        tip(ttk.Button(mine, text="Remove selected", width=20, command=self._remove_pins),
            "s_remove_pins").grid(row=2, column=2, sticky="ne", padx=(8, 0), pady=(8, 4))
        if not p.pinned_folders:
            self.pins.insert("end", "None yet. Pin a folder in step 1.")
            self.pins.configure(state="disabled")

        ttk.Label(mine, text="Window layout", font=bold).grid(row=3, column=0, sticky="w", **self.PAD)
        self.reset_var = tk.BooleanVar(value=False)
        tip(ttk.Checkbutton(mine, text="Reset window size and column widths when I save", variable=self.reset_var),
            "s_reset").grid(row=3, column=1, columnspan=2, sticky="w", pady=4)

        ttk.Label(mine, text="Saved in", font=bold).grid(row=4, column=0, sticky="nw", padx=(0, 12), pady=(8, 0))
        where = str(app.prefs_store.path)
        if app.prefs_store.fallback_used:
            where += "\n(The tool folder isn't writable, so your preferences are saved in the work folder.)"
        tip(ttk.Label(mine, text=where, style="Hint.TLabel", wraplength=520, justify="left"),
            "s_saved_in").grid(row=4, column=1, columnspan=2, sticky="w", pady=(8, 0))

        # ---- Admin settings: a two-column table, grouped by topic ----
        admin = ttk.LabelFrame(body, text="  Admin settings (read-only, set by your admin)  ", padding=(12, 8))
        admin.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        admin.columnconfigure(0, weight=1)
        admin.rowconfigure(0, weight=1)
        self.table = tip(ttk.Treeview(admin, columns=("value",), show="tree headings", selectmode="browse", height=14),
                         "s_admin")
        self.table.heading("#0", text="Setting", anchor="w")
        self.table.heading("value", text="Value", anchor="w")
        self.table.column("#0", width=230, minwidth=180, stretch=False)
        self.table.column("value", width=430, minwidth=200, stretch=True)
        self.table.tag_configure("group", font=bold)
        self.table.grid(row=0, column=0, sticky="nsew")
        tsb = ttk.Scrollbar(admin, orient="vertical", command=self.table.yview)
        tsb.grid(row=0, column=1, sticky="ns")
        self.table.configure(yscrollcommand=tsb.set)
        self._full: dict[str, str] = {}
        for group, rows in self._admin_rows():
            gid = self.table.insert("", "end", text=group, open=True, tags=("group",))
            for name, value in rows:
                iid = self.table.insert(gid, "end", text=name, values=(value,))
                self._full[iid] = f"{name}: {value}"
        self.detail_lbl = ttk.Label(admin, text="Click a row to see its full value here.", style="Hint.TLabel",
                                    wraplength=640, justify="left")
        self.detail_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.table.bind("<<TreeviewSelect>>", self._show_detail)
        tip(ttk.Button(admin, text="Copy admin settings", command=self._copy_admin),
            "s_copy_admin").grid(row=2, column=0, sticky="w", pady=(8, 0))

        btns = ttk.Frame(body)
        btns.grid(row=2, column=0, sticky="e", pady=(12, 0))
        tip(ttk.Button(btns, text="Cancel", command=lambda: close_window(self)), "s_cancel").pack(side="right")
        tip(ttk.Button(btns, text="Save", command=self.save), "s_save").pack(side="right", padx=(0, 8))
        ttk.Button(btns, text="Help", command=lambda: app.open_help("settings")).pack(side="right", padx=(0, 16))
        self.bind("<Escape>", lambda _e: close_window(self))
        self.protocol("WM_DELETE_WINDOW", lambda: close_window(self))
        # Not modal (so Help can be used alongside it, and nothing can freeze waiting on it).
        self.lift()
        self.focus_set()

    def _show_detail(self, _event=None) -> None:
        sel = self.table.selection()
        if sel and sel[0] in self._full:
            self.detail_lbl.configure(text=self._full[sel[0]])

    @staticmethod
    def _short_version(text: str) -> str:
        """'Admin settings for CurWork Beta 0.014 - DRAFT - ... - updated 2026-11-22 14:32 UTC - modified by: x' -> short form."""
        if not text:
            return "not stated"
        ver = re.search(r"Beta [0-9.]+|\b\d+\.\d+(?:\.\d+)?\b", text)
        when = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", text)
        who = re.search(r"modified by:?\s*([\w.@-]+)", text, re.I)
        parts = [ver.group(0) if ver else "", f"updated {when.group(0)}" if when else "", who.group(1) if who else ""]
        if "DRAFT" in text.upper():
            parts.insert(1, "DRAFT")
        short = " \u00b7 ".join(x for x in parts if x)
        return short or text

    def _update_recent_label(self) -> None:
        n = len(self.recent)
        self.recent_lbl.configure(text=f"{n} saved now" if n else "none saved now")

    def _clear_recent(self) -> None:
        self.recent = []
        self._update_recent_label()

    def _remove_pins(self) -> None:
        if str(self.pins.cget("state")) == "disabled":
            return
        for i in reversed(self.pins.curselection()):
            self.pins.delete(i)

    def _admin_rows(self) -> list[tuple[str, list[tuple[str, str]]]]:
        s = self.app.s
        sso = s.sso or {}
        role = (f"{sso.get('role_name')} in account {sso.get('account_id')}"
                if sso.get("role_name") and sso.get("account_id") else "not set")
        return [
            ("Source", [
                ("Admin settings file", str(s.source_path or "not found")),
                ("Version", self._short_version(s.admin_version)),
            ]),
            ("Storage", [
                ("Bucket", s.bucket),
                ("Region", s.region),
                ("Encryption of saved files", "Key chosen by your admin" if s.kms_key_id else "The bucket's own key"),
                ("Government-grade (FIPS) encryption", "On" if s.use_fips_endpoint else "Off"),
            ]),
            ("Sign-in", [
                ("AWS profile", s.aws_profile or "default"),
                ("Access portal", sso.get("start_url") or "not set"),
                ("Role", role),
            ]),
            ("Folders", [
                ("You can download from", ", ".join(s.browse_roots)),
                *[(f"Result type: {name}", folder) for name, folder in s.output_stages.items()],
                ("Default result type", s.default_stage),
                ("Logs are saved in", s.log_prefix),
                ("Work folder on this computer", str(s.work_dir)),
            ]),
            ("Downloading and saving", [
                ("File types you can save in S3", "  ".join(s.upload_extensions)),
                ("Ask before downloading more than", f"{s.large_download_warning_mb:,} MB"),
                ("Files copied at the same time", str(s.max_concurrency)),
            ]),
            ("This computer", [
                ("AWS CLI", s.aws_cli_path or "Found automatically"),
                ("Use notice at start-up", "Yes" if s.login_banner else "No"),
                ("Preferences location", "Tool folder" if s.user_settings_location == "tool_folder" else "Work folder"),
            ]),
        ]

    def _admin_text(self) -> str:
        lines = [f"CurWork admin settings (version note: {self.app.s.admin_version or 'not stated'})"]
        for group, rows in self._admin_rows():
            lines.append(group)
            width = max(len(n) for n, _ in rows)
            lines += [f"  {n.ljust(width)}  {v}" for n, v in rows]
        return "\n".join(lines)

    def _copy_admin(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._admin_text())
        self.app._set_status("Admin settings copied.")

    def save(self) -> None:
        p = self.app.prefs
        try:
            limit = int(self.limit_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror(APP_TITLE, f"Recent folders to keep must be a number from 0 to {core.MAX_RECENT}.",
                                 parent=self)
            return
        p.remember_result_type = bool(self.remember_var.get())
        p.recent_limit = min(core.MAX_RECENT, max(0, limit))
        p.recent_folders = self.recent[:p.recent_limit]
        if str(self.pins.cget("state")) != "disabled":
            p.pinned_folders = list(self.pins.get(0, "end"))
        self.app.apply_prefs(reset_layout=bool(self.reset_var.get()))
        if self.app._save_prefs(quiet=False):
            log.info("Preferences saved.")
            close_window(self)


class CurWorkApp:
    POLL_MS = 100
    OUT_REFRESH_MS = 3000

    def __init__(self, root: tk.Tk, settings: core.Settings, self_test: bool = False):
        self.root = root
        self.s = settings
        self.self_test = self_test
        self.work = core.WorkArea(settings.work_dir)
        self.work.ensure()
        self.log_file = core.setup_file_logging(self.work)
        self.svc = core.S3Service(settings)
        self.prefs_store = core.UserSettingsStore(settings)
        self.prefs = self.prefs_store.load()
        self.q: "queue.Queue" = queue.Queue()
        log.addHandler(_QueueLogHandler(self.q))

        self.busy = False
        self.cancel_event = threading.Event()
        self._progress: tuple[int, int] = (0, 0)
        self.signed_in = False
        self._action_buttons: list[ttk.Button] = []
        self._placeholders: set[str] = set()
        self._closed = False
        self._close_after_task = False
        root.report_callback_exception = self._on_tk_error

        root.title(f"{APP_NAME} \u2013 {core.RELEASE_LABEL} ({core.STATUS})")
        root.minsize(980, 640)
        self._apply_geometry()
        self._build_ui()
        self._apply_column_widths()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if root.tk.call("tk", "windowingsystem") == "aqua":
            # Mac app menu: About CurWork, Settings... (Cmd+,) and Quit go to CurWork's own handlers.
            # Run them after the menu closes: opening a window (or waiting on one) inside a macOS menu
            # callback can freeze the app with a spinning wheel.
            root.createcommand("tkAboutDialog", lambda *_: root.after(50, self.open_about))
            root.createcommand("::tk::mac::ShowPreferences", lambda *_: root.after(50, self.open_settings))
            root.createcommand("::tk::mac::Quit", lambda *_: root.after(50, self.on_close))

        log.info("CurWork %s started by %s. Bucket: %s  Work folder: %s",
                 core.VERSION, core.current_user(), self.s.bucket, self.work.root)
        for override in self.s.ignored_config_overrides:
            log.warning("Ignored %s. This app only uses the admin settings file installed next to it: %s",
                        override, self.s.source_path)
        log.info("Your preferences are saved in %s%s", self.prefs_store.path,
                 " (the tool folder isn't writable, so the work folder is used)" if self.prefs_store.fallback_used else "")
        self._after_ids: dict[str, str] = {}
        if self_test:
            return          # --self-test: build the window only; no timers, dialogs or AWS calls
        self._schedule("poll", self.POLL_MS, self._poll)
        self._schedule("startup", 300, self._startup_checks)
        self._schedule("refresh", self.OUT_REFRESH_MS, self._auto_refresh_out)

    # ------------------------------------------------------------------ UI
    def _hint_color(self) -> str:
        """Color for grey hint text. On a Mac, use the system's secondary label color, which
        stays readable in both Light and Dark Mode. Elsewhere, #6b6b6b keeps at least 4.5:1
        contrast on the standard light window background (WCAG 2.2 SC 1.4.3)."""
        if self.root.tk.call("tk", "windowingsystem") == "aqua":
            try:
                self.root.winfo_rgb("systemSecondaryLabelColor")
                return "systemSecondaryLabelColor"
            except tk.TclError:
                pass
        return "#6b6b6b"

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Step.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Good.TLabel", foreground="#1b7f3b")
        style.configure("Bad.TLabel", foreground="#b42318")
        style.configure("Hint.TLabel", foreground=self._hint_color())
        style.configure("Big.TButton", padding=(10, 6))
        style.configure("Help.TButton", padding=(2, 0))
        self.tips: dict[str, Tooltip] = {}
        tip = lambda w, key: add_tip(self.tips, w, key)  # noqa: E731

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=5)
        outer.columnconfigure(1, weight=6)
        outer.rowconfigure(1, weight=1)

        # Header ---------------------------------------------------------
        head = ttk.Frame(outer)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(head, text="CurWork", style="Title.TLabel").pack(side="left")
        self.where_lbl = tip(ttk.Label(head, text=self._where_text(), style="Hint.TLabel"), "where")
        self.where_lbl.pack(side="left")
        self.sign_btn = tip(ttk.Button(head, text="Sign in", style="Big.TButton", command=self.sign_in), "sign_in")
        self.sign_btn.pack(side="right")
        tip(ttk.Button(head, text="Settings", command=self.open_settings), "settings").pack(side="right", padx=(0, 6))
        tip(ttk.Button(head, text="About", command=self.open_about), "about").pack(side="right", padx=(0, 6))
        tip(ttk.Button(head, text="Help", command=self.open_help), "help").pack(side="right", padx=(0, 6))
        self.who_lbl = tip(ttk.Label(head, text="Checking sign-in...", style="Hint.TLabel"), "who")
        self.who_lbl.pack(side="right", padx=10)

        # Step 1: S3 browser ---------------------------------------------
        s1 = self._step_frame(outer, "1. Download files from S3", "step1")
        s1.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        s1.rowconfigure(1, weight=1)
        s1.columnconfigure(0, weight=1)
        ttk.Label(s1, text="Open a customer folder, select files or a whole month, then click Download.",
                  style="Hint.TLabel", wraplength=440).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.tree = tip(ttk.Treeview(s1, columns=("size", "modified"), selectmode="extended"), "tree")
        self.tree.heading("#0", text="Name")
        self.tree.heading("size", text="Size")
        self.tree.heading("modified", text="Last changed")
        self.tree.column("#0", width=260, stretch=True)
        self.tree.column("size", width=80, anchor="e", stretch=False)
        self.tree.column("modified", width=130, stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(s1, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.tag_configure("folder", font=("Segoe UI", 9, "bold"))
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        b1 = ttk.Frame(s1)
        b1.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tip(self._btn(b1, "Refresh", self.load_roots), "refresh").pack(side="left")
        self.dl_btn = tip(self._btn(b1, "Download selected  →", self.download_selected, style="Big.TButton"), "download")
        self.dl_btn.pack(side="right")
        pin = ttk.Frame(s1)
        pin.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        pin.columnconfigure(1, weight=1)
        ttk.Label(pin, text="Pinned:").grid(row=0, column=0, sticky="w")
        self.pin_var = tk.StringVar()
        self.pin_box = tip(ttk.Combobox(pin, textvariable=self.pin_var, values=self.prefs.pinned_folders,
                                        state="readonly"), "pinned")
        self.pin_box.grid(row=0, column=1, sticky="ew", padx=4)
        tip(self._btn(pin, "Go", self.go_to_pinned), "go").grid(row=0, column=2)
        tip(ttk.Button(pin, text="Pin selected folder", command=self.pin_selected), "pin").grid(row=0, column=3, padx=(6, 0))

        right = ttk.Frame(outer)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        # Step 2: run macros ---------------------------------------------
        s2 = self._step_frame(right, "2. Run your macros as usual", "step2")
        s2.grid(row=0, column=0, sticky="ew")
        s2.columnconfigure(1, weight=1)
        ttk.Label(s2, text="In the macro menu, pick files from the In folder and save results to the Out folder.",
                  style="Hint.TLabel", wraplength=560).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        self._path_entries: dict[str, ttk.Entry] = {}
        for r, (label, key) in enumerate((("In (files from S3):", "in"), ("Out (your results):", "out")), start=1):
            ttk.Label(s2, text=label).grid(row=r, column=0, sticky="w", pady=2)
            e = ttk.Entry(s2)
            self._path_entries[key] = e
            self.tips[f"{key}_path"] = Tooltip(e, helptext.TIPS[f"{key}_path"])
            e.grid(row=r, column=1, sticky="ew", padx=6)
            # The work folder can change after sign-in, so look the folder up when the button is clicked.
            b_open = ttk.Button(s2, text="Open", command=lambda k=key: open_folder(self._work_path(k)))
            b_open.grid(row=r, column=2, padx=(0, 4))
            b_copy = ttk.Button(s2, text="Copy path", command=lambda k=key: self._copy(self._work_path(k)))
            b_copy.grid(row=r, column=3)
            self.tips[f"open_{key}"] = Tooltip(b_open, helptext.TIPS["open"])
            self.tips[f"copy_path_{key}"] = Tooltip(b_copy, helptext.TIPS["copy_path"])
        self._show_work_paths()
        self.in_count_lbl = tip(ttk.Label(s2, text="", style="Hint.TLabel"), "counts")
        self.in_count_lbl.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # Step 3: save in S3 -------------------------------------------------
        s3 = self._step_frame(right, "3. Save results in S3", "step3")
        s3.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        s3.columnconfigure(0, weight=1)
        s3.rowconfigure(0, weight=1)
        self.out_tree = tip(ttk.Treeview(s3, columns=("size", "status"), selectmode="extended", height=8), "out_list")
        self.out_tree.heading("#0", text="File in Out folder")
        self.out_tree.heading("size", text="Size")
        self.out_tree.heading("status", text="Status")
        self.out_tree.column("#0", width=300, stretch=True)
        self.out_tree.column("size", width=80, anchor="e", stretch=False)
        self.out_tree.column("status", width=150, stretch=False)
        self.out_tree.tag_configure("pending", foreground="#9a6700")
        self.out_tree.tag_configure("done", foreground="#1b7f3b")
        self.out_tree.tag_configure("open", foreground="#b42318")
        self.out_tree.grid(row=0, column=0, sticky="nsew")
        osb = ttk.Scrollbar(s3, orient="vertical", command=self.out_tree.yview)
        osb.grid(row=0, column=1, sticky="ns")
        self.out_tree.configure(yscrollcommand=osb.set)

        dest = ttk.Frame(s3)
        dest.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        dest.columnconfigure(3, weight=1)
        ttk.Label(dest, text="Result type:").grid(row=0, column=0, sticky="w")
        start_stage = self.s.default_stage
        if self.prefs.remember_result_type and self.prefs.last_result_type in self.s.output_stages:
            start_stage = self.prefs.last_result_type
        self.stage_var = tk.StringVar(value=start_stage)
        stage_box = tip(ttk.Combobox(dest, textvariable=self.stage_var, values=list(self.s.output_stages),
                                     state="readonly", width=18), "stage")
        stage_box.grid(row=0, column=1, padx=(4, 12))
        self.stage_box = stage_box
        ttk.Label(dest, text="Customer / month folder:").grid(row=0, column=2, sticky="w")
        self.folder_var = tk.StringVar(value=self.work.load_state().get("context", ""))
        self.folder_box = tip(ttk.Combobox(dest, textvariable=self.folder_var, values=self.prefs.recent_folders), "folder")
        self.folder_box.grid(row=0, column=3, sticky="ew", padx=(4, 0))
        self.dest_lbl = tip(ttk.Label(s3, text="", style="Hint.TLabel"), "dest")
        self.dest_lbl.grid(row=2, column=0, columnspan=2, sticky="w")
        self.stage_var.trace_add("write", lambda *_: (self._update_dest_preview(), self._remember_stage()))
        self.folder_var.trace_add("write", lambda *_: self._update_dest_preview())
        self._update_dest_preview()

        b3 = ttk.Frame(s3)
        b3.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tip(self._btn(b3, "Refresh list", self.refresh_out), "refresh_out").pack(side="left")
        tip(self._btn(b3, "Save selected in S3", lambda: self.upload(selected_only=True)), "upload_selected").pack(side="left", padx=6)
        tip(self._btn(b3, "Save all new or changed in S3  ↑", lambda: self.upload(selected_only=False),
                      style="Big.TButton"), "upload_all").pack(side="right")

        # Step 4: finish -------------------------------------------------
        s4 = self._step_frame(right, "4. When you're done", "step4")
        s4.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        tip(self._btn(s4, "Finish and clean up", self.finish, style="Big.TButton"), "finish").pack(side="right")
        ttk.Label(s4, text="Checks that nothing is still open in Excel or waiting to be saved in S3, saves today's log "
                           "in S3, then empties In and Out on this laptop.",
                  style="Hint.TLabel", wraplength=420).pack(side="left", fill="x", expand=True)

        # Bottom: progress + log -----------------------------------------
        bottom = ttk.Frame(outer)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(1, weight=1)
        self.status_lbl = ttk.Label(bottom, text="Ready.", width=48)
        self.status_lbl.grid(row=0, column=0, sticky="w")
        self.pbar = ttk.Progressbar(bottom, mode="determinate", maximum=1000)
        self.pbar.grid(row=0, column=1, sticky="ew", padx=8)
        self.stop_btn = tip(ttk.Button(bottom, text="Stop", command=self.cancel_event.set, state="disabled"), "stop")
        self.stop_btn.grid(row=0, column=2)
        self.logbox = ScrolledText(bottom, height=7, state="disabled", font=("Consolas", 9), wrap="word")
        self.tips["log"] = Tooltip(self.logbox, helptext.TIPS["log"])
        self.logbox.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.logbox.tag_configure("warn", foreground="#9a6700")
        self.logbox.tag_configure("err", foreground="#b42318")
        lrow = ttk.Frame(bottom)
        lrow.grid(row=2, column=0, columnspan=3, sticky="ew")
        tip(ttk.Button(lrow, text="Open log folder", command=lambda: open_folder(self.work.log_dir)), "log_folder").pack(side="right")
        ttk.Label(lrow, text="Tip: point at any button or box to see what it does. Press F1 for Help.",
                  style="Hint.TLabel").pack(side="left")
        self._build_menu()

    def _step_frame(self, parent, title: str, topic: str) -> ttk.LabelFrame:
        """A numbered step box whose title has a small ? button that opens Help at that step."""
        frame = ttk.LabelFrame(parent, style="Step.TLabelframe", padding=8)
        head = ttk.Frame(frame)
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold", size=bold.cget("size") + 1)
        self.__dict__.setdefault("_fonts", []).append(bold)
        ttk.Label(head, text=f" {title} ", font=bold).pack(side="left")
        q = ttk.Button(head, text="?", width=2, style="Help.TButton", command=lambda: self.open_help(topic))
        q.pack(side="left", padx=(2, 4))
        self.tips[f"step_help_{topic}"] = Tooltip(q, f"Help for this step ({title[3:]}).")
        frame.configure(labelwidget=head)
        return frame

    def _build_menu(self) -> None:
        """Help menu. On a Mac it's the standard Help menu (with the system search box)."""
        bar = tk.Menu(self.root)
        helpmenu = tk.Menu(bar, name="help", tearoff=False)
        helpmenu.add_command(label="CurWork Help", accelerator="F1", command=self.open_help)
        helpmenu.add_command(label="Quick start", command=lambda: self.open_help("quick_start"))
        helpmenu.add_command(label="When something goes wrong", command=lambda: self.open_help("problems"))
        helpmenu.add_command(label="Getting help", command=lambda: self.open_help("support"))
        if self.root.tk.call("tk", "windowingsystem") != "aqua":
            helpmenu.add_separator()
            helpmenu.add_command(label="About CurWork", command=self.open_about)
        bar.add_cascade(label="Help", menu=helpmenu)
        self.root.configure(menu=bar)
        self.root.bind_all("<F1>", lambda _e: self.open_help())
        if self.root.tk.call("tk", "windowingsystem") == "aqua":
            self.root.createcommand("::tk::mac::ShowHelp", lambda *_: self.root.after(50, self.open_help))

    def open_help(self, topic: str = "quick_start") -> None:
        """Open Help at a topic, or bring the open Help window forward and switch topic. Not modal."""
        win = getattr(self, "_help", None)
        if win is not None and win.winfo_exists():
            win.show(topic)
            win.deiconify()
            win.lift()
            win.focus_set()
            return
        self._help = HelpWindow(self.root, topic)

    def _btn(self, parent, text, cmd, style=None) -> ttk.Button:
        b = ttk.Button(parent, text=text, command=cmd, style=style) if style else ttk.Button(parent, text=text, command=cmd)
        self._action_buttons.append(b)
        return b

    def _copy(self, path: Path) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(str(path))
        self._set_status(f"Copied: {path}")

    def _set_status(self, text: str) -> None:
        self.status_lbl.configure(text=text if len(text) < 60 else text[:57] + "...")

    def _update_dest_preview(self) -> None:
        prefix = self.s.output_stages.get(self.stage_var.get(), "")
        folder = core._norm_prefix(self.folder_var.get())
        self.dest_lbl.configure(text=f"Results will be saved in:  s3://{self.s.bucket}/{prefix}{folder}")

    def _dest_prefix(self) -> str:
        return self.s.output_stages.get(self.stage_var.get(), "") + core._norm_prefix(self.folder_var.get())

    # ------------------------------------------------------ worker plumbing
    def _poll(self) -> None:
        if self._closed:
            return
        try:
            while True:
                item = self.q.get_nowait()
                if callable(item):
                    item()
                    if self._closed:
                        return
                elif isinstance(item, tuple) and item[0] == "log":
                    self._append_log(item[1], item[2])
        except queue.Empty:
            pass
        if self.busy:
            done, total = self._progress
            if total > 0:
                self.pbar.configure(mode="determinate", value=min(1000, int(1000 * done / total)))
        self._schedule("poll", self.POLL_MS, self._poll)

    def _schedule(self, name: str, ms: int, fn) -> None:
        """Schedule fn on the GUI thread, remembering the id so it can be cancelled on close."""
        if not self._closed:
            self._after_ids[name] = self.root.after(ms, fn)

    def _append_log(self, text: str, level: int) -> None:
        self.logbox.configure(state="normal")
        tag = "err" if level >= logging.ERROR else "warn" if level >= logging.WARNING else ""
        self.logbox.insert("end", text + "\n", tag)
        lines = int(self.logbox.index("end-1c").split(".")[0])
        if lines > 600:
            self.logbox.delete("1.0", f"{lines - 500}.0")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def ui(self, fn) -> None:
        """Run fn on the main (GUI) thread."""
        self.q.put(fn)

    def ask(self, fn):
        """From a worker thread: run fn on the GUI thread and wait for its answer."""
        done = threading.Event()
        box: dict = {}

        def run():
            try:
                box["v"] = fn()
            finally:
                done.set()

        self.q.put(run)
        done.wait()
        return box.get("v")

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in self._action_buttons:
            b.configure(state=state)
        self.sign_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if busy else "disabled")
        if busy:
            self.cancel_event.clear()
            self._progress = (0, 0)
            self.pbar.configure(mode="indeterminate", value=0)
            self.pbar.start(12)
        else:
            self.pbar.stop()
            self.pbar.configure(mode="determinate", value=0)
        if text:
            self._set_status(text)

    def run_task(self, label: str, fn, on_done=None) -> None:
        if self.busy:
            return
        self._set_busy(True, label)

        def runner():
            result, error = None, None
            try:
                result = fn()
            except BaseException as e:  # noqa: BLE001 - shown to the user
                error = e

            def finish():
                self.pbar.stop()
                self._set_busy(False)
                if error is not None:
                    kind, msg = core.classify_error(error)
                    if kind == "cancelled":
                        log.info("Stopped by user.")
                        self._set_status("Stopped.")
                    else:
                        log.error("%s failed: %s", label.rstrip("."), msg)
                        if not isinstance(error, core.CurWorkError):
                            log.debug("Error details", exc_info=error)
                        self._set_status("Something went wrong. See the message.")
                        if kind == "auth":
                            self._set_signed_out()
                        messagebox.showerror(APP_TITLE, msg, parent=self.root)
                elif on_done:
                    on_done(result)
                if self._closed:
                    return
                self.refresh_out()
                if self._close_after_task:
                    self._close_after_task = False
                    self.on_close()

            self.ui(finish)

        threading.Thread(target=runner, daemon=True).start()

    def _progress_cb(self, done: int, total: int) -> None:
        self._progress = (done, total)

    # ------------------------------------------------------------ startup
    def _startup_checks(self) -> None:
        if self.s.login_banner:
            ok = messagebox.askokcancel(APP_TITLE, self.s.login_banner, parent=self.root)
            log.info("Use notice %s by %s.", "accepted" if ok else "declined", core.current_user())
            if not ok:
                self._destroy()
                return
        warn = core.sync_folder_warning(self.work.root)
        if warn:
            log.warning(warn)
            messagebox.showwarning(APP_TITLE, warn, parent=self.root)
        self.refresh_out()
        self._leftovers_prompt()
        self.check_sign_in()

    def _leftovers_prompt(self) -> None:
        """Offer to keep or delete files left in the work folder by an earlier session."""
        n_in, n_out, n_out_all = self.work.leftovers()
        if n_in or n_out_all:
            parts = []
            if n_in:
                parts.append(f"{n_in} file(s) in In")
            if n_out:
                parts.append(f"{n_out} result file(s) in Out that are NOT saved in S3 yet")
            if n_out_all - n_out:
                parts.append(f"{n_out_all - n_out} result file(s) in Out that are already saved in S3")
            msg = ("Files from your last session are still on this laptop:\n\n  - " + "\n  - ".join(parts) +
                   "\n\nKeep them so you can finish that work?\n\n"
                   "Yes = keep them (save them in S3 or clean up when you're done)\n"
                   "No = delete them now")
            if not messagebox.askyesno(APP_TITLE, msg, parent=self.root):
                if n_out and not messagebox.askyesno(
                        APP_TITLE, f"Delete {n_out} result file(s) that were never saved in S3? This can't be undone.",
                        icon="warning", parent=self.root):
                    pass
                else:
                    self._clean_now()

    def _clean_now(self) -> None:
        skipped = self.work.clean()
        self.folder_var.set("")
        self.refresh_out()
        if skipped:
            messagebox.showwarning(APP_TITLE, "Some files couldn't be deleted because they're open (probably in Excel). "
                                   "Close Excel and click 'Finish and clean up' again.", parent=self.root)

    # ------------------------------------------------------------ sign-in
    def _set_signed_in(self, who: str) -> None:
        self.signed_in = True
        self.who_lbl.configure(text=f"Signed in: {who}", style="Good.TLabel")
        self.sign_btn.configure(text="Sign in again")

    def _set_signed_out(self, text: str = "Not signed in") -> None:
        self.signed_in = False
        self.who_lbl.configure(text=text, style="Bad.TLabel")
        self.sign_btn.configure(text="Sign in")

    def _where_text(self) -> str:
        bucket = self.s.bucket or "(read from AWS after you sign in)"
        return f"   bucket: {bucket}   |   region: {self.s.region}{'   |   FIPS' if self.s.use_fips_endpoint else ''}"

    def _read_managed_settings(self):
        """After sign-in: the managed settings from Parameter Store, or None when this install doesn't use them."""
        return self.svc.load_managed_settings() if self.s.settings_parameter else None

    def _work_path(self, key: str) -> Path:
        return self.work.in_dir if key == "in" else self.work.out_dir

    def _show_work_paths(self) -> None:
        for key, e in self._path_entries.items():
            e.configure(state="normal")
            e.delete(0, "end")
            e.insert(0, str(self._work_path(key)))
            e.configure(state="readonly")

    def _switch_work_folder(self, folder: Path) -> None:
        """Use the work folder the admin set in Parameter Store instead of the default one used before sign-in."""
        old = self.work
        new = core.WorkArea(folder)
        new.ensure()
        self.log_file = core.switch_file_logging(self.log_file, new)
        self.work = new
        self._show_work_paths()
        log.info("Work folder set by your admin: %s (CurWork used %s before you signed in).", new.root, old.root)
        if not self.folder_var.get():
            self.folder_var.set(new.load_state().get("context", ""))
        self.refresh_out()
        if self.self_test:
            return
        warn = core.sync_folder_warning(new.root)
        if warn:
            log.warning(warn)
            messagebox.showwarning(APP_TITLE, warn, parent=self.root)
        n_in, _n_out, n_out_all = old.leftovers()
        if n_in or n_out_all:
            messagebox.showwarning(
                APP_TITLE, f"Your admin moved CurWork's work folder to:\n{new.root}\n\n"
                f"{n_in + n_out_all} file(s) are still in the folder CurWork used before you signed in:\n{old.root}\n\n"
                "CurWork doesn't use that folder any more. Move any files you still need into the new folder.",
                parent=self.root)
        self._leftovers_prompt()

    def _switch_prefs(self, new) -> None:
        """Keep the biller's preferences where the admin's settings say, once those are read from AWS."""
        store = core.UserSettingsStore(new)
        if store.path == self.prefs_store.path:
            return
        if store.path.is_file():
            self.prefs = store.load()
            self.apply_prefs(reset_layout=False)
        else:
            store.save(self.prefs)
        self.prefs_store = store
        log.info("Your preferences are saved in %s", store.path)

    def _apply_settings(self, new) -> None:
        """Use the settings just read from Parameter Store everywhere in the window."""
        if new is None:
            return
        self.s = new
        self.svc.s = new
        if Path(new.work_dir) != self.work.root:
            self._switch_work_folder(new.work_dir)
        self._switch_prefs(new)
        self.where_lbl.configure(text=self._where_text())
        self.stage_box.configure(values=list(new.output_stages))
        if self.stage_var.get() not in new.output_stages:
            self.stage_var.set(new.default_stage)
        self._update_dest_preview()

    def _signed_in(self, result) -> None:
        who, new = result
        self._apply_settings(new)
        self._set_signed_in(who)
        log.info("Signed in as %s", who)
        self.load_roots()

    def check_sign_in(self) -> None:
        def work():
            core.ensure_sso_profile(self.s)
            self.svc.reset()
            return self.svc.whoami()

        if self.busy:
            return
        self._set_busy(True, "Checking sign-in...")

        def runner():
            try:
                who = work()
            except BaseException as e:  # noqa: BLE001
                kind, msg = core.classify_error(e)
                log.info("Not signed in yet (%s).", kind)
                self.ui(lambda: (self._set_busy(False, "Click 'Sign in' to start."),
                                 self._set_signed_out("Not signed in - click Sign in")))
                return
            try:
                result = (who, self._read_managed_settings())
            except BaseException as e:  # noqa: BLE001 - signed in, but the admin settings can't be read
                kind, msg = core.classify_error(e)
                log.error("Couldn't read the admin settings from Parameter Store: %s", msg)
                self.ui(lambda: (self._set_busy(False, "Something went wrong. See the message."),
                                 self._set_signed_out("Signed in, but the admin settings can't be read"),
                                 messagebox.showerror(APP_TITLE, msg, parent=self.root)))
                return
            self.ui(lambda: (self._set_busy(False, "Ready."), self._signed_in(result)))

        threading.Thread(target=runner, daemon=True).start()

    def sign_in(self) -> None:
        if not self.s.aws_profile:
            messagebox.showerror(APP_TITLE, "The admin settings file doesn't name an AWS profile (aws_profile). Ask your admin.", parent=self.root)
            return

        def work():
            added = core.ensure_sso_profile(self.s)
            if not added and not core.profile_exists(self.s.aws_profile):
                raise core.CurWorkError(
                    f"The AWS profile '{self.s.aws_profile}' isn't set up on this laptop, and the admin settings file "
                    "doesn't have the sign-in details to set it up. Ask your admin."
                )
            log.info("Opening your browser to sign in. Finish the sign-in (and MFA) there, then come back.")
            core.run_sso_login(self.s.aws_profile, on_line=lambda line: log.info("  %s", line),
                               cli_path=self.s.aws_cli_path)
            self.svc.reset()
            who = self.svc.whoami()
            return who, self._read_managed_settings()

        self.run_task("Signing in (check your browser)...", work, self._signed_in)

    # ------------------------------------------------------------ browsing
    def load_roots(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._placeholders.clear()
        for root_prefix in self.s.browse_roots:
            label = root_prefix.rstrip("/") or f"(whole bucket) {self.s.bucket}"
            self.tree.insert("", "end", iid=root_prefix or "/", text=label, open=False, tags=("folder",))
            self._add_placeholder(root_prefix or "/", "(click to load)")
        if len(self.s.browse_roots) == 1:
            first = self.s.browse_roots[0] or "/"
            self.tree.item(first, open=True)
            self._load_children(first)

    def _add_placeholder(self, parent: str, text: str) -> None:
        iid = self.tree.insert(parent, "end", text=text)  # Tk picks a unique id like I001
        self._placeholders.add(iid)

    def _needs_load(self, iid: str) -> bool:
        kids = self.tree.get_children(iid)
        return len(kids) == 1 and kids[0] in self._placeholders and \
            self.tree.item(kids[0], "text") == "(click to load)"

    def _on_tree_open(self, _event=None) -> None:
        iid = self.tree.focus()
        if iid and self._needs_load(iid):
            self._load_children(iid)
            return
        # Fallback: find any open folder that hasn't been loaded yet.
        stack = list(self.tree.get_children(""))
        while stack:
            node = stack.pop()
            if self.tree.item(node, "open"):
                if self._needs_load(node):
                    self._load_children(node)
                    return
                stack.extend(self.tree.get_children(node))

    def _load_children(self, iid: str, then=None) -> None:
        prefix = "" if iid == "/" else iid

        def work():
            return self.svc.list_level(prefix)

        def done(res):
            folders, files = res
            for kid in self.tree.get_children(iid):
                self._placeholders.discard(kid)
                self.tree.delete(kid)
            for f in folders:
                name = f[len(prefix):].rstrip("/")
                self.tree.insert(iid, "end", iid=f, text=name, tags=("folder",))
                self._add_placeholder(f, "(click to load)")
            for f in files:
                name = f.key[len(prefix):]
                mod = f.modified.astimezone().strftime("%Y-%m-%d %H:%M") if f.modified else ""
                self.tree.insert(iid, "end", iid=f.key, text=name, values=(core.human_size(f.size), mod))
            if not folders and not files:
                self._add_placeholder(iid, "(empty)")
            if then:
                then()

        self.run_task("Loading folder...", work, done)

    def download_selected(self) -> None:
        sel = [i for i in self.tree.selection() if i not in self._placeholders]
        sel = ["" if i == "/" else i for i in sel]
        if not sel:
            messagebox.showinfo(APP_TITLE, "Select one or more files or folders on the left first.", parent=self.root)
            return
        limit = self.s.large_download_warning_mb * 1024 * 1024

        def work():
            files = self.svc.expand_selection(sel)
            if not files:
                raise core.CurWorkError("There are no files in what you selected.")
            total = sum(f.size for f in files)
            if total > limit and not self.ask(lambda: messagebox.askyesno(
                    APP_TITLE, f"That's {len(files)} file(s), {core.human_size(total)} in total. Download anyway?",
                    parent=self.root)):
                raise core.Cancelled()
            log.info("Downloading %d file(s), %s...", len(files), core.human_size(total))
            def replace_local(target: Path) -> bool:
                if not self.work.input_changed(target):
                    return True  # same as what we downloaded before; safe to refresh
                return bool(self.ask(lambda: messagebox.askyesno(
                    APP_TITLE, f"'{target.name}' is already in the In folder and has been changed since it was "
                               "downloaded.\n\nReplace it with the copy from S3? Your changes would be lost.",
                    icon="warning", default="no", parent=self.root)))

            paths = self.svc.download(files, self.work.in_dir, on_progress=self._progress_cb,
                                      on_file=lambda k: self.ui(lambda: self._set_status(f"Downloading {k.rsplit('/', 1)[-1]}")),
                                      cancel=self.cancel_event, replace_local=replace_local,
                                      on_downloaded=self.work.record_download)
            context = core.context_for(sel[0], self.s.browse_roots)
            self.work.set_context(context)
            return paths, context

        def done(res):
            paths, context = res
            if context:
                self.folder_var.set(context)
                self._add_recent(context)
            log.info("Done: %d file(s) are in %s", len(paths), self.work.in_dir)
            self._set_status(f"Downloaded {len(paths)} file(s). Run your macros next.")

        self.run_task("Downloading...", work, done)

    # ------------------------------------------------------------ results
    def refresh_out(self) -> None:
        try:
            files = self.work.out_files()
        except OSError:
            return
        # Update the list in place so scrolling and selection don't jump.
        current = set(self.out_tree.get_children())
        wanted = {f.rel for f in files}
        for iid in current - wanted:
            self.out_tree.delete(iid)
        for f in files:
            tag = {"Saved in S3": "done", "Open in Excel": "open"}.get(f.status, "pending")
            values = (core.human_size(f.size), f.status)
            if f.rel in current:
                self.out_tree.item(f.rel, values=values, tags=(tag,))
            else:
                self.out_tree.insert("", "end", iid=f.rel, text=f.rel, values=values, tags=(tag,))
        n_in = len(self.work.in_files())
        extras = len(self.work.in_extras())
        warn = f"  ({extras} new or changed - results belong in Out)" if extras else ""
        self.in_count_lbl.configure(text=f"In: {n_in} file(s){warn}   |   Out: {len(files)} file(s), "
                                         f"{sum(1 for f in files if f.status != 'Saved in S3')} not saved in S3 yet",
                                    style="Bad.TLabel" if extras else "Hint.TLabel")

    def _auto_refresh_out(self) -> None:
        if self._closed:
            return
        if not self.busy:
            self.refresh_out()
        self._schedule("refresh", self.OUT_REFRESH_MS, self._auto_refresh_out)

    def upload(self, selected_only: bool) -> None:
        files = self.work.out_files()
        if selected_only:
            chosen = set(self.out_tree.selection())
            files = [f for f in files if f.rel in chosen]
            if not files:
                messagebox.showinfo(APP_TITLE, "Select one or more files in the list first.", parent=self.root)
                return
        else:
            files = [f for f in files if f.status != "Saved in S3"]
            if not files:
                messagebox.showinfo(APP_TITLE, "Everything in the Out folder is already saved in S3.", parent=self.root)
                return
        open_files = [f.rel for f in files if f.status == "Open in Excel"]
        if open_files:
            messagebox.showwarning(APP_TITLE, "Save and close these in Excel first:\n\n" + "\n".join(open_files),
                                   parent=self.root)
            return
        dest = self._dest_prefix()
        try:
            dest = self.svc.check_destination(dest)
        except core.CurWorkError as e:
            messagebox.showerror(APP_TITLE, str(e), parent=self.root)
            return
        if not core._norm_prefix(self.folder_var.get()) and not messagebox.askyesno(
                APP_TITLE, "You didn't fill in the customer / month folder, so the results will be saved straight into "
                           f"s3://{self.s.bucket}/{dest}\n\nIs that right?", parent=self.root):
            return

        sticky: dict = {}

        def on_exists(key: str) -> str:
            if "all" in sticky:
                return sticky["all"]
            choice = self.ask(lambda: ExistsDialog(self.root, key).result)
            if choice in ("overwrite_all", "skip_all"):
                sticky["all"] = choice.replace("_all", "")
                return sticky["all"]
            return choice

        def work():
            log.info("Saving %d file(s) in s3://%s/%s ...", len(files), self.s.bucket, dest)
            return self.svc.upload(
                [(f.path, f.rel) for f in files], dest, on_exists=on_exists, on_progress=self._progress_cb,
                on_file=lambda k: self.ui(lambda: self._set_status(f"Saving {k.rsplit('/', 1)[-1]} in S3")),
                on_uploaded=lambda p, rel, key: self.work.record_upload(rel, p, key),
                cancel=self.cancel_event,
            )

        def done(keys):
            log.info("Done: %d file(s) saved in S3.", len(keys))
            self._set_status(f"Saved {len(keys)} file(s) in S3.")
            if keys:
                self._add_recent(self.folder_var.get())

        self.run_task("Saving in S3...", work, done)

    # ------------------------------------------------------------ user preferences
    def _save_prefs(self, quiet: bool = True) -> bool:
        try:
            self.prefs_store.save(self.prefs)
            return True
        except core.CurWorkError as e:
            log.warning(str(e))
            if not quiet:
                messagebox.showerror(APP_TITLE, str(e), parent=self.root)
            return False

    def _apply_geometry(self) -> None:
        m = core._GEOMETRY.match(self.prefs.window_geometry or "")
        if not m:
            self.root.geometry("1180x780")
            return
        w, h, x, y = (int(g) for g in m.groups())
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(max(w, 980), sw), min(max(h, 640), sh)
        x, y = min(max(x, 0), max(0, sw - 200)), min(max(y, 0), max(0, sh - 120))  # keep it on screen
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _tree_columns(self):
        return (("tree", self.tree, ("#0", "size", "modified")), ("out_tree", self.out_tree, ("#0", "size", "status")))

    def _apply_column_widths(self) -> None:
        for name, tree, cols in self._tree_columns():
            for col in cols:
                width = self.prefs.column_widths.get(f"{name}.{col}")
                if width:
                    tree.column(col, width=width)

    def _remember_layout(self) -> None:
        try:
            if self.root.state() == "normal":
                geo = self.root.geometry()
                if core._GEOMETRY.match(geo):
                    self.prefs.window_geometry = geo
            for name, tree, cols in self._tree_columns():
                for col in cols:
                    self.prefs.column_widths[f"{name}.{col}"] = int(tree.column(col, "width"))
        except tk.TclError:
            return
        self._save_prefs()

    def _remember_stage(self) -> None:
        if self.prefs.remember_result_type and self.stage_var.get() in self.s.output_stages:
            self.prefs.last_result_type = self.stage_var.get()
            self._save_prefs()

    def _add_recent(self, folder: str) -> None:
        if self.prefs.add_recent(folder):
            self.folder_box.configure(values=self.prefs.recent_folders)
            self._save_prefs()

    def pin_selected(self) -> None:
        sel = [i for i in self.tree.selection() if i not in self._placeholders and i.endswith("/") and i != "/"]
        if len(sel) != 1:
            messagebox.showinfo(APP_TITLE, "Select one folder on the left, then click Pin selected folder.",
                                parent=self.root)
            return
        if len(self.prefs.pinned_folders) >= core.MAX_PINNED and sel[0] not in self.prefs.pinned_folders:
            messagebox.showinfo(APP_TITLE, f"You can pin up to {core.MAX_PINNED} folders. Remove one in Settings first.",
                                parent=self.root)
            return
        if self.prefs.add_pinned(sel[0]):
            self.pin_box.configure(values=self.prefs.pinned_folders)
            self._save_prefs(quiet=False)
        self.pin_var.set(sel[0])
        self._set_status(f"Pinned {sel[0]}")

    def go_to_pinned(self) -> None:
        target = core._norm_prefix(self.pin_var.get())
        if not target:
            messagebox.showinfo(APP_TITLE, "Pick a pinned folder first.", parent=self.root)
            return
        if not self.signed_in:
            messagebox.showinfo(APP_TITLE, "Sign in first.", parent=self.root)
            return
        root = next((r for r in sorted(self.s.browse_roots, key=len, reverse=True) if target.startswith(r)), None)
        if root is None:
            messagebox.showinfo(APP_TITLE, f"'{target}' isn't in a folder you're allowed to browse anymore.",
                                parent=self.root)
            return
        chain, acc = [root or "/"], root
        for part in [x for x in target[len(root):].split("/") if x]:
            acc += part + "/"
            chain.append(acc)
        self._reveal(chain, 0)

    def _reveal(self, chain: list[str], i: int) -> None:
        node = chain[i]
        if not self.tree.exists(node):
            messagebox.showinfo(APP_TITLE, f"'{chain[-1]}' wasn't found in S3. It may have been moved or removed.",
                                parent=self.root)
            return
        self.tree.item(node, open=True)
        if i == len(chain) - 1:
            self.tree.selection_set(node)
            self.tree.focus(node)
            self.tree.see(node)
            if self._needs_load(node):
                self._load_children(node)
            return
        if self._needs_load(node):
            self._load_children(node, then=lambda: self._reveal(chain, i + 1))
        else:
            self._reveal(chain, i + 1)

    def open_settings(self) -> None:
        """Show Settings, or bring it forward if it's already open. Not modal."""
        dlg = getattr(self, "_settings", None)
        if dlg is not None and dlg.winfo_exists():
            dlg.lift()
            dlg.focus_set()
            return
        self._settings = SettingsDialog(self.root, self)

    def open_about(self) -> None:
        """Show About, or bring it forward if it's already open. It doesn't block the main window."""
        dlg = getattr(self, "_about", None)
        if dlg is not None and dlg.winfo_exists():
            dlg.lift()
            dlg.focus_set()
            return
        self._about = AboutDialog(self.root, self)

    def apply_prefs(self, reset_layout: bool) -> None:
        """Called by the Settings window after the user saves."""
        self.pin_box.configure(values=self.prefs.pinned_folders)
        if self.pin_var.get() not in self.prefs.pinned_folders:
            self.pin_var.set("")
        self.folder_box.configure(values=self.prefs.recent_folders)
        if reset_layout:
            self.prefs.window_geometry = ""
            self.prefs.column_widths = {}
            self.root.geometry("1180x780")
            defaults = {"tree": (260, 80, 130), "out_tree": (300, 80, 150)}
            for name, tree, cols in self._tree_columns():
                for col, width in zip(cols, defaults[name]):
                    tree.column(col, width=width)
        if self.prefs.remember_result_type:
            self._remember_stage()

    # ------------------------------------------------------------ finish
    def finish(self, then=None) -> None:
        self.refresh_out()
        pending = self.work.pending_out()
        open_now = [f.rel for f in self.work.out_files() if f.status == "Open in Excel"]
        open_now += [rel for p, rel in self.work.in_files() if core.is_open_elsewhere(p)]
        if open_now:
            messagebox.showwarning(APP_TITLE, "Close these in Excel first:\n\n" + "\n".join(open_now), parent=self.root)
            return
        extras = self.work.in_extras()
        if extras:
            names = "\n".join(f"{rel}  ({why})" for _, rel, why in extras[:10]) + ("\n..." if len(extras) > 10 else "")
            ans = messagebox.askyesnocancel(
                APP_TITLE, f"These files in In are new or were changed after download. They may be results "
                           f"saved to the wrong folder:\n\n{names}\n\n"
                           "Yes = move them to Out so you can save them in S3\n"
                           "No = delete them with everything else\nCancel = go back", icon="warning", parent=self.root)
            if ans is None:
                return
            if ans:
                moved = self.work.move_to_out([(p, rel) for p, rel, _ in extras],
                                              strip_prefix=core._norm_prefix(self.folder_var.get()))
                self.refresh_out()
                messagebox.showinfo(APP_TITLE, f"Moved {len(moved)} file(s) to Out. Save them in S3, then click "
                                               "'Finish and clean up' again.", parent=self.root)
                return
        if pending:
            names = "\n".join(f.rel for f in pending[:10]) + ("\n..." if len(pending) > 10 else "")
            if not messagebox.askyesno(
                    APP_TITLE, f"{len(pending)} result file(s) in Out are NOT saved in S3 yet:\n\n{names}\n\n"
                               "Delete them anyway? (No = go back and save them in S3)", icon="warning", parent=self.root):
                return

        def work():
            key = None
            try:
                if self.signed_in:
                    key = self.svc.upload_log(self.log_file)
            except Exception as e:  # noqa: BLE001 - the cleanup still matters more
                log.warning("Couldn't save the log in S3 (%s). Cleaning up anyway.", core.classify_error(e)[1])
            skipped = self.work.clean()
            return key, skipped

        def done(res):
            key, skipped = res
            if key:
                log.info("Log saved to s3://%s/%s", self.s.bucket, key)
            self.folder_var.set("")
            if skipped:
                messagebox.showwarning(APP_TITLE, "Some files couldn't be deleted because they're open. "
                                       "Close Excel and click 'Finish and clean up' again.", parent=self.root)
            else:
                self._set_status("All clean. Nothing is left in In or Out.")
                if then is None:
                    messagebox.showinfo(APP_TITLE, "Done. The In and Out folders on this laptop are empty.",
                                        parent=self.root)
            if then:
                then()

        self.run_task("Cleaning up...", work, done)

    def on_close(self) -> None:
        if self._closed:
            return
        if self.busy:
            if not messagebox.askyesno(APP_TITLE, "A download or save is still running. Stop it and close?", parent=self.root):
                return
            self.cancel_event.set()
            self._close_after_task = True  # finish the stop cleanly (removes partial files), then come back here
            self._set_status("Stopping...")
            return
        n_in, n_out, n_out_all = self.work.leftovers()
        if n_in or n_out_all:
            ans = messagebox.askyesnocancel(
                APP_TITLE, "Files are still in your work folder.\n\nYes = clean up, then close\n"
                           "No = close and keep them for later\nCancel = go back", parent=self.root)
            if ans is None:
                return
            if ans:
                self.finish(then=self._destroy)
                return
            log.info("Closed with files left in the work folder (In: %d, Out not saved in S3: %d).", n_in, n_out)
        self._destroy()

    def _destroy(self) -> None:
        if not self._closed:
            self._remember_layout()
            self._closed = True
            log.info("CurWork closed.")
            for after_id in self._after_ids.values():
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
            self.root.destroy()

    def _on_tk_error(self, exc_type, exc, tb) -> None:
        """Unexpected error inside the window: log it with details and tell the user, instead of failing silently."""
        log.error("Unexpected error: %s", exc)
        log.debug("".join(traceback.format_exception(exc_type, exc, tb)))
        try:
            messagebox.showerror(APP_TITLE, f"Something unexpected went wrong:\n\n{exc}\n\n"
                                            "Details are in the log. Send it to your admin.", parent=self.root)
        except tk.TclError:
            pass


def _write_report(report: dict, report_file: str | None) -> None:
    """Print the self-test report, and save it to report_file if given. A Windows app built without a
    console has nowhere to print, so the file is how the report is read there."""
    import json
    text = json.dumps(report, indent=2)
    if sys.stdout is not None:
        try:
            print(text, flush=True)
        except (OSError, ValueError):
            pass
    if report_file:
        Path(report_file).write_text(text + "\n", encoding="utf-8")


def self_test(root: tk.Tk, settings: core.Settings, report_file: str | None = None) -> int:
    """
    --self-test: start the real window without showing dialogs, check what support usually asks about,
    print one JSON report and exit (0 = all checks passed). Makes no changes in AWS. It only reads: sts:GetCallerIdentity
    with the saved sign-in, to confirm which role CurWork would use, then the settings kept in Parameter Store.
    """
    import json
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    app = CurWorkApp(root, settings, self_test=True)
    root.update()
    check("Window title", core.RELEASE_LABEL in root.title() and core.STATUS in root.title(), root.title())
    icons = getattr(root, "_curwork_icons", [])
    check("App icon loaded", len(icons) == 2, f"{len(icons)} image(s) from {asset_path('')}")
    check("Admin settings found", settings.source_path is not None and settings.source_path.is_file(), str(settings.source_path))
    frozen = getattr(sys, "frozen", False)
    if frozen:
        check("Admin settings are next to the app, not inside it",
              settings.source_path is not None and settings.source_path.parent == core.tool_folder(), str(core.tool_folder()))
        check("Admin settings locked to the installed file (--config and CURWORK_CONFIG ignored)",
              core.candidate_config_paths() == [core.tool_folder() / core.CONFIG_FILE_NAME]
              and settings.source_path == core.tool_folder() / core.CONFIG_FILE_NAME,
              "ignored: " + (", ".join(settings.ignored_config_overrides) or "nothing"))
    details = about_details(app)
    flat = " ".join(f"{k} {v}" for _, rows in details for k, v in rows).lower()
    check("About window details", all(w in flat for w in ("python", "boto3", "tcl/tk", "admin settings")), "")
    check("About shows no secrets", not any(w in flat for w in ("secret", "aws_access_key", "token=")), "")
    dlg = AboutDialog(root, app); root.update(); dlg.destroy()
    dlg = SettingsDialog(root, app); root.update(); dlg.destroy()
    check("About and Settings windows open", True)
    expected = (settings.sso or {}).get("role_name", "")
    role_check = "Signed-in role is the one in the admin settings"
    if not expected:      # no sso section: nothing to compare, so no AWS call
        checks.append({"check": role_check, "ok": True, "skipped": True,
                       "detail": "skipped: the admin settings have no sso section"})
    else:
        try:
            app.svc.reset()
            who = app.svc.whoami()
            role = who.rsplit("(", 1)[-1].rstrip(")") if "(" in who else ""
            check(role_check, role == expected, f"signed in as {who}; admin settings expect {expected}")
            if settings.settings_parameter:
                app._apply_settings(app.svc.load_managed_settings())
                check("Settings kept in AWS read after sign-in", bool(app.s.bucket),
                      f"{settings.settings_parameter}: bucket {app.s.bucket}, work folder {app.work.root}")
        except Exception as e:  # noqa: BLE001 - report, don't crash
            kind, msg = core.classify_error(e)
            if kind in ("auth", "config"):      # no saved sign-in yet: can't check, so skip (not a failure)
                checks.append({"check": role_check, "ok": True, "skipped": True,
                               "detail": f"skipped: not signed in yet ({kind}). Sign in once, then run the self-test again."})
            else:
                check(role_check, False, f"{kind}: {msg}")
    check("Work folder usable", app.work.root.is_dir() and os.access(app.work.root, os.W_OK), str(app.work.root))
    report = {"app": f"{APP_NAME} {core.RELEASE_LABEL}", "status": core.STATUS, "built_app": frozen,
              "passed": all(c["ok"] for c in checks), "checks": checks}
    _write_report(report, report_file)
    root.destroy()
    return 0 if report["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CurWork: CUR files between S3 and your laptop.")
    parser.add_argument("--config", help="Path to curwork_admin_settings.json. Only used when running from source: "
                                         "the built app always uses the file installed next to it")
    parser.add_argument("--self-test", action="store_true",
                        help="Open the window without dialogs, check settings, icon, About and sign-in role, print a JSON report, exit")
    parser.add_argument("--report", metavar="FILE",
                        help="With --self-test: also save the JSON report to FILE (needed for CurWork.exe on Windows, "
                             "which has no console to print to)")
    parser.add_argument("--version", action="version", version=f"CurWork {core.RELEASE_LABEL} ({core.STATUS}) - updated {core.BUILD_DATE} - modified by {core.MODIFIED_BY}")
    args = parser.parse_args(argv)

    _enable_windows_dpi()
    _set_windows_app_id()
    root = tk.Tk(className=APP_NAME)   # on Linux this also names the window class for the dock
    apply_app_icon(root)
    try:
        settings = core.load_settings(args.config)
        if args.self_test:
            root.withdraw()
            return self_test(root, settings, args.report)
        CurWorkApp(root, settings)
    except core.CurWorkError as e:
        root.withdraw()
        if args.self_test:      # report instead of showing a dialog nobody will click
            import json
            _write_report({"app": f"{APP_NAME} {core.RELEASE_LABEL}", "passed": False, "checks": [
                {"check": "Admin settings found", "ok": False, "detail": str(e)}]}, args.report)
            root.destroy()
            return 2
        messagebox.showerror(APP_TITLE, str(e))
        root.destroy()
        return 2
    except Exception as e:  # noqa: BLE001 - the windowed exe has no console, so show and save the error
        crash = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "CurWork-crash.log"
        try:
            crash.write_text(f"{_dt.datetime.now().isoformat()}\n{traceback.format_exc()}", encoding="utf-8")
        except OSError:
            pass
        root.withdraw()
        messagebox.showerror(APP_TITLE, f"CurWork couldn't start:\n\n{e}\n\nDetails were saved to {crash}")
        root.destroy()
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
