"""
CurWork styling in one place: fonts, colours, spacing, list sizes and the ttk styles that use them.
CurWork and the CurWork Admin Settings app both call apply() once, so every window looks the same.

Version:     Beta 0.017
Status:      DRAFT - For Internal Use (FPT)
Updated:     2026-11-23 01:38 UTC
Modified by: mbitar

Fonts are made from the system's own default font (TkDefaultFont), so the text matches the rest of
the computer on a Mac and on Windows. Nothing else in CurWork names a font family or a size.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ---- colours. Each has at least 4.5:1 contrast on the standard light window background (WCAG 2.2 SC 1.4.3).
GOOD = "#1b7f3b"          # done, signed in
BAD = "#b42318"           # problems, files open in Excel, values that can't be saved
WARN = "#9a6700"          # waiting to be saved, warnings in the log
HINT_FALLBACK = "#6b6b6b"  # grey explanations, where the system has no colour of its own for them
SEARCH_HIT = "#fff3b0"    # Help search matches
TIP_BG, TIP_FG = "#fffbe6", "#1f1f1f"

# ---- spacing (pixels)
PAD = 10                  # inside a window, a tab or a box
GAP = 8                   # between a list and the buttons under it, and between rows of controls
SMALL_GAP = 6             # between buttons in a row

# ---- file lists: the same columns and widths in every list, so the tabs line up
NAME_WIDTH = 180          # the file or folder name; it stretches with the window
SIZE_WIDTH = 90
STATE_WIDTH = 150         # the state, status or last-changed column
LIST_ROWS = 10            # how many rows a list asks for before the window stretches it

# ---- window sizes
MAIN_SIZE = (1040, 700)   # CurWork opens at this size the first time
MAIN_MIN = (900, 600)     # and can't be made smaller than this
WRAP = 600                # longest line of explanation text before it wraps

FONTS: dict[str, tkfont.Font] = {}


def hint_color(root: tk.Misc) -> str:
    """Grey explanation text. On a Mac, the system's secondary label colour, which stays readable in Light
    and Dark Mode."""
    if root.tk.call("tk", "windowingsystem") == "aqua":
        try:
            root.winfo_rgb("systemSecondaryLabelColor")
            return "systemSecondaryLabelColor"
        except tk.TclError:
            pass
    return HINT_FALLBACK


def font(name: str) -> tkfont.Font:
    """One of the shared fonts: "normal", "bold", "title", "heading" or "mono". apply() must run first."""
    return FONTS[name]


def apply(root: tk.Misc) -> ttk.Style:
    """Create the shared fonts and ttk styles for this window and every window opened from it."""
    base = tkfont.nametofont("TkDefaultFont", root=root)
    size = abs(int(base.actual("size"))) or 13

    def make(name: str, **kw) -> tkfont.Font:
        f = base.copy()
        f.configure(**kw)
        FONTS[name] = f
        return f

    FONTS["normal"] = base
    bold = make("bold", weight="bold")
    title = make("title", size=size + 4, weight="bold")
    make("heading", size=size + 2, weight="bold")
    FONTS["mono"] = tkfont.nametofont("TkFixedFont", root=root)

    style = ttk.Style(root)
    style.configure("Title.TLabel", font=title)
    style.configure("Bold.TLabel", font=bold)
    style.configure("Hint.TLabel", foreground=hint_color(root))
    style.configure("Good.TLabel", foreground=GOOD)
    style.configure("Bad.TLabel", foreground=BAD)
    style.configure("Error.TLabel", foreground=BAD)
    style.configure("TLabelframe.Label", font=bold)
    style.configure("Big.TButton", padding=(10, 6))
    style.configure("Help.TButton", padding=(2, 0))
    style.configure("Steps.TNotebook.Tab", padding=(14, 6))
    style.configure("Treeview", rowheight=int(base.metrics("linespace") * 1.45))
    return style


def tag_states(tree: ttk.Treeview) -> None:
    """The same colours for file states in every list."""
    tree.tag_configure("pending", foreground=WARN)
    tree.tag_configure("done", foreground=GOOD)
    tree.tag_configure("open", foreground=BAD)
    tree.tag_configure("changed", foreground=BAD)
    if FONTS:
        tree.tag_configure("folder", font=FONTS["bold"])


def wrap_to(label: ttk.Label, container: tk.Misc, margin: int = 24, longest: int = WRAP) -> None:
    """Wrap the label's text to the space it has, so no line is cut off when the window is narrow:
    from the width of its container, and again from the width the label is actually given."""
    def fit_container(e):
        label.configure(wraplength=min(longest, max(200, e.width - label.winfo_x() - margin)))

    def fit_label(e):
        if e.width > 1 and label.winfo_reqwidth() > e.width + 2:
            label.configure(wraplength=max(200, e.width - 4))

    container.bind("<Configure>", fit_container, add="+")
    label.bind("<Configure>", fit_label, add="+")
