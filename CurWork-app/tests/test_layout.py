# CurWork tests - Beta 0.016 - DRAFT - For Internal Use - updated 2026-11-23 01:23 UTC - modified by: mbitar
"""Layout check: no control is cut off or squeezed on any tab, at the normal and the smallest window size."""
import tkinter as tk
from tkinter import ttk
import curwork_settings_form
import curwork_style
from test_gui import world  # noqa: F401  (the window test fixture)


def _clipped(root):
    """Widgets that are mapped but cut off by their parent, or labels narrower than their text."""
    bad = []
    def walk(w):
        for c in w.winfo_children():
            if not c.winfo_ismapped():
                continue
            if isinstance(c, (tk.Toplevel,)):
                continue
            p = c.winfo_parent() and c.nametowidget(c.winfo_parent())
            if p is not None and not isinstance(p, ttk.Notebook) and not str(p).endswith('scrollview'):
                if c.winfo_x() + c.winfo_width() > p.winfo_width() + 1 or c.winfo_y() + c.winfo_height() > p.winfo_height() + 1:
                    bad.append(f"overflow {c.winfo_class()} {str(c)[-40:]} {c.winfo_x()},{c.winfo_y()} {c.winfo_width()}x{c.winfo_height()} in {p.winfo_width()}x{p.winfo_height()}")
            if c.winfo_class() in ("TLabel", "TButton", "TCheckbutton") and c.winfo_reqwidth() > c.winfo_width() + 2:
                bad.append(f"squeezed {c.winfo_class()} '{str(c.cget('text'))[:40]}' req {c.winfo_reqwidth()} got {c.winfo_width()}")
            walk(c)
    walk(root)
    return bad


def test_no_control_is_cut_off_on_any_tab(world):
    a = world.app
    problems = []
    for size in ("1040x700", "900x600"):
        a.root.geometry(size)
        for tab in a.tabs.tabs():
            a.tabs.select(tab)
            world.pump(0.3)
            name = a.tabs.tab(tab, "text").strip()
            panel = a.settings_panel
            if name != "Settings":
                problems += [f"{size} {name}: {b}" for b in _clipped(a.root)]
                continue
            for inner in panel.inner.tabs():
                panel.inner.select(inner)
                world.pump(0.2)
                pages = panel.admin_form.notebook.tabs() if "Admin" in panel.inner.tab(inner, "text") else [None]
                for page in pages:
                    if page:
                        panel.admin_form.notebook.select(page)
                        world.pump(0.2)
                    problems += [f"{size} Settings {page}: {b}" for b in _clipped(a.root)]
    assert not problems, "\n".join(problems)


def test_settings_scrolls_when_the_window_is_short(world):
    a = world.app
    a.root.geometry("900x600")
    a.open_settings()
    panel = a.settings_panel
    panel.inner.select(1)
    world.pump(0.4)
    box = panel.inner.nametowidget(panel.inner.tabs()[1])
    assert isinstance(box, curwork_settings_form.ScrollArea)
    assert box.bar.winfo_ismapped(), "the admin settings don't fit, so the scroll bar must show"
    box._scroll("moveto", "1.0")
    world.pump(0.2)
    assert box._top == box.inner.winfo_reqheight() - box.view.winfo_height()   # the last row is reachable
    a.root.geometry("1040x700")


def test_file_lists_match_on_every_tab(world):
    """Every file list sits in a titled box with the same column widths, and side-by-side boxes are the same width."""
    a = world.app
    a.root.geometry("1040x700")
    lists = (a.tree, a.in_tree_dl, a.in_tree, a.out_view, a.out_tree)
    widths = set()
    for tree in lists:
        assert tree.master.winfo_class() == "TLabelframe"
        widths.add(tuple(int(tree.column(c, "width")) for c in ("#0", *tree["columns"])[1:]))
    assert len(widths) == 1, widths          # size and state columns are the same everywhere
    for tab, pair in ((a.tab_download, (a.tree, a.in_tree_dl)), (a.tab_work, (a.in_tree, a.out_view))):
        a.tabs.select(tab)
        world.pump(0.4)
        left, right = (t.master.winfo_width() for t in pair)
        assert abs(left - right) <= 12, (left, right)
        assert pair[0].master.winfo_rooty() == pair[1].master.winfo_rooty()


def test_window_opens_at_the_tabbed_size_and_ignores_older_saved_sizes(world):
    a = world.app
    a.prefs.window_geometry = "1399x780+29+34"
    a.prefs.column_widths = {"tree.#0": 518}      # saved by the older one-window layout
    a._apply_geometry()
    world.pump(0.3)
    assert a.root.winfo_width() <= curwork_style.MAIN_SIZE[0]
    assert a.root.winfo_reqwidth() <= curwork_style.MAIN_SIZE[0], "the window asks to be wider than it opens"


def test_fonts_and_colours_come_only_from_the_style_module():
    import re
    from pathlib import Path
    here = Path(__file__).resolve().parent.parent
    for name in ("curwork.py", "curwork_admin.py", "curwork_settings_form.py"):
        text = (here / name).read_text()
        assert not re.search(r'font=\(|"Segoe|"Consolas|nametofont|foreground="#|background="#', text), name
