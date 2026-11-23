# CurWork tests - Beta 0.015 - DRAFT - For Internal Use - updated 2026-11-23 00:55 UTC - modified by: mbitar
"""Layout check: no control is cut off or squeezed on any tab, at the normal and the smallest window size."""
import tkinter as tk
from tkinter import ttk
import curwork_settings_form
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
    for size in ("1180x780", "980x640"):
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
    a.root.geometry("980x640")
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
    a.root.geometry("1180x780")
