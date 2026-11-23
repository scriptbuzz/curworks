"""
CurWork settings form: the tabbed form for the settings kept in AWS Parameter Store.

Version:     Beta 0.015
Status:      DRAFT - For Internal Use (FPT)
Updated:     2026-11-23 00:55 UTC
Modified by: mbitar

Two windows show the same form, so admins and billers see the same tabs, names and explanations:
- the CurWork Admin Settings app shows it editable (curwork_admin.py adds loading and saving);
- CurWork's own Settings tab shows it read-only.

This file only lays out and reads the form. It contains no code that saves anything to AWS, so billers'
copy of CurWork carries no way to change the settings (NIST SP 800-53 CM-7, least functionality).
"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk

import curwork_core as core

# The form: (key, name shown, kind). kind is text, list, stages or int. The text each field holds is the
# same in both windows: lists are comma-separated and result types are one "Name = folder/" per line.
FIELDS = (
    ("bucket", "S3 bucket", "text"),
    ("kms_key_id", "Encryption key for saved files", "text"),
    ("browse_roots", "Folders billers can download from", "list"),
    ("output_stages", "Result types", "stages"),
    ("default_stage", "Result type picked at start", "text"),
    ("log_prefix", "Folder where CurWork saves its logs", "text"),
    ("upload_extensions", "File types billers can save in S3", "list"),
    ("large_download_warning_mb", "Ask before downloading more than (MB)", "int"),
    ("max_concurrency", "Files copied at the same time (1 to 32)", "int"),
    ("work_dir", "Work folder on each laptop", "text"),
    ("user_settings_location", "Where each biller's preferences are saved", "text"),
    ("_version", "Version label", "text"),
)
LABELS = {key: label for key, label, _kind in FIELDS}

# Plain-language help, shown in grey under each field. In the admin app, problems replace it in red.
HINTS = {
    "bucket": "The S3 bucket that holds the CUR workbooks.",
    "kms_key_id": "Keep the bucket's own key unless your security team gave you a key for CurWork.",
    "browse_roots": "Billers can only download from these folders. They must not overlap the result folders.",
    "log_prefix": "CurWork saves each biller's log in this folder when they click Finish and clean up.",
    "output_stages": "Billers pick a result type on the 3. Save in S3 tab, and their files are saved in its folder.",
    "default_stage": "The result type CurWork picks when it starts.",
    "upload_extensions": "CurWork refuses to save any other type of file in S3.",
    "large_download_warning_mb": "CurWork asks the biller before downloading more than this many megabytes.",
    "max_concurrency": "More is faster on a good connection. Fewer is gentler on a slow one.",
    "work_dir": "In, Out and the logs are kept here. It must not be inside OneDrive, Box or another synced folder.",
    "user_settings_location": "Where each biller's own preferences, such as pinned folders, are saved.",
    "_version": "A short note shown in CurWork's About window, such as the date and what changed.",
}
TABS = (("Files in S3", ("bucket", "kms_key_id", "browse_roots", "log_prefix")),
        ("Result types", ("output_stages", "default_stage")),
        ("What billers can do", ("upload_extensions", "large_download_warning_mb", "max_concurrency")),
        ("On each laptop", ("work_dir", "user_settings_location")))
COMMON_EXTENSIONS = (".xlsx", ".xlsm", ".xlsb", ".xls", ".csv", ".txt", ".zip")
LOCATION_LABELS = {"tool_folder": "Next to CurWork (or the work folder, if billers can't write next to CurWork)",
                   "work_folder": "In each biller's work folder"}
BUCKET_KEY_LABEL = "Use the bucket's own key"
BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
HINT_COLOR, ERROR_COLOR = "#555", "#B00020"


def managed_to_form(managed: dict) -> dict[str, str]:
    """Managed settings (missing keys take CurWork's defaults) as the text shown in each form field."""
    out = {}
    for key, _label, kind in FIELDS:
        value = managed.get(key, core.DEFAULT_CONFIG.get(key, ""))
        if kind == "list":
            out[key] = ", ".join(str(v) for v in value)
        elif kind == "stages":
            out[key] = "\n".join(f"{name} = {folder}" for name, folder in dict(value).items())
        else:
            out[key] = str(value)
    return out


def settings_to_managed(s: core.Settings) -> dict:
    """The settings CurWork is using now, in the shape they're kept in Parameter Store."""
    return {"bucket": s.bucket, "kms_key_id": s.kms_key_id, "browse_roots": list(s.browse_roots),
            "output_stages": dict(s.output_stages), "default_stage": s.default_stage, "log_prefix": s.log_prefix,
            "upload_extensions": list(s.upload_extensions), "large_download_warning_mb": s.large_download_warning_mb,
            "max_concurrency": s.max_concurrency, "work_dir": str(s.work_dir),
            "user_settings_location": s.user_settings_location, "_version": s.admin_version}


def kms_label(alias: str, key_id: str) -> str:
    return f"{alias}  ({key_id})"


def kms_value(text: str) -> str:
    """The key ID behind what the encryption key drop-down shows."""
    t = (text or "").strip()
    if not t or t == BUCKET_KEY_LABEL:
        return ""
    m = re.search(r"\(([^()]+)\)\s*$", t)
    return m.group(1).strip() if m else t


# --------------------------------------------------------------------------
# Controls. get() and set() use the field's text (see managed_to_form) in both windows.
# --------------------------------------------------------------------------

class Field:
    def __init__(self, widget: tk.Widget, var: tk.StringVar | None = None):
        self.widget, self.var = widget, var
        self._watchers: list = []
        if var is not None:
            var.trace_add("write", lambda *_: self.changed())

    def get(self) -> str:
        return self.var.get()

    def set(self, text: str) -> None:
        self.var.set(text)

    def watch(self, fn) -> None:
        self._watchers.append(fn)

    def changed(self) -> None:
        for fn in self._watchers:
            fn()


class ChoiceField(Field):
    """Shows plain labels for stored values (which KMS key, where preferences are saved)."""

    def __init__(self, widget, var, to_label, to_value):
        super().__init__(widget, var)
        self.to_label, self.to_value = to_label, to_value

    def get(self) -> str:
        return self.to_value(self.var.get())

    def set(self, text: str) -> None:
        self.var.set(self.to_label(text))


class ListField(Field):
    """A list of S3 folders. Editable: a drop-down to add one and a button to remove the selected ones."""

    def __init__(self, parent, editable: bool):
        frame = ttk.Frame(parent)
        super().__init__(frame)
        frame.columnconfigure(0, weight=1)
        self.box = tk.Listbox(frame, height=4 if editable else 3, selectmode="extended", exportselection=False)
        self.box.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.pick_var = tk.StringVar()
        self.pick = None
        if editable:
            self.pick = ttk.Combobox(frame, textvariable=self.pick_var, width=24)
            self.pick.grid(row=0, column=1, sticky="ew", padx=(8, 0))
            ttk.Button(frame, text="Add folder", command=self.add).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=2)
            ttk.Button(frame, text="Remove selected", command=self.remove).grid(row=2, column=1, sticky="ew", padx=(8, 0))

    def items(self) -> list[str]:
        return list(self.box.get(0, "end"))

    def get(self) -> str:
        return ", ".join(self.items())

    def set(self, text: str) -> None:
        self.box.delete(0, "end")
        for part in text.split(","):
            if part.strip():
                self.box.insert("end", part.strip())
        self.changed()

    def add(self) -> None:
        folder = core._norm_prefix(self.pick_var.get())
        if folder and folder not in self.items():
            self.box.insert("end", folder)
            self.pick_var.set("")
            self.changed()

    def remove(self) -> None:
        for i in reversed(self.box.curselection()):
            self.box.delete(i)
        self.changed()


class StagesField(Field):
    """Result types as a small table: a name billers see and the S3 folder their files are saved in."""

    def __init__(self, parent, editable: bool):
        frame = ttk.Frame(parent)
        super().__init__(frame)
        frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("folder",), height=5 if editable else 4, selectmode="browse")
        self.tree.heading("#0", text="Name billers see")
        self.tree.heading("folder", text="S3 folder")
        self.tree.column("#0", width=160)
        self.tree.column("folder", width=140)
        self.tree.grid(row=0, column=0, rowspan=6, sticky="nsew")
        self.name_var, self.folder_var = tk.StringVar(), tk.StringVar()
        self.folder_pick = None
        if editable:
            self.tree.bind("<<TreeviewSelect>>", self._picked)
            side = dict(column=1, sticky="ew", padx=(8, 0))
            ttk.Label(frame, text="Name").grid(row=0, **side)
            ttk.Entry(frame, textvariable=self.name_var, width=20).grid(row=1, **side)
            ttk.Label(frame, text="S3 folder").grid(row=2, **side)
            self.folder_pick = ttk.Combobox(frame, textvariable=self.folder_var, width=18)
            self.folder_pick.grid(row=3, **side)
            ttk.Button(frame, text="Add or update", command=self.add).grid(row=4, pady=(6, 2), **side)
            ttk.Button(frame, text="Remove selected", command=self.remove).grid(row=5, **side)

    def rows(self) -> list[tuple[str, str]]:
        return [(self.tree.item(i, "text"), self.tree.item(i, "values")[0]) for i in self.tree.get_children()]

    def names(self) -> list[str]:
        return [name for name, _folder in self.rows()]

    def get(self) -> str:
        return "\n".join(f"{name} = {folder}" for name, folder in self.rows())

    def set(self, text: str) -> None:
        self.tree.delete(*self.tree.get_children())
        for line in text.splitlines():
            name, sep, folder = line.partition("=")
            if line.strip():
                self.tree.insert("", "end", text=name.strip(), values=(folder.strip() if sep else "",))
        self.changed()

    def _picked(self, _event=None) -> None:
        sel = self.tree.selection()
        if sel:
            self.name_var.set(self.tree.item(sel[0], "text"))
            self.folder_var.set(self.tree.item(sel[0], "values")[0])

    def add(self) -> None:
        name, folder = self.name_var.get().strip(), core._norm_prefix(self.folder_var.get())
        if not name or not folder:
            messagebox.showinfo(self.widget.winfo_toplevel().title(),
                                "Type a name and pick or type an S3 folder first.", parent=self.widget)
            return
        for i in self.tree.get_children():
            if self.tree.item(i, "text") == name:
                self.tree.item(i, values=(folder,))
                break
        else:
            self.tree.insert("", "end", text=name, values=(folder,))
        self.name_var.set("")
        self.folder_var.set("")
        self.changed()

    def remove(self) -> None:
        for i in self.tree.selection():
            self.tree.delete(i)
        self.changed()


class ExtensionsField(Field):
    """A checkbox for each common file type, and a box for any others."""

    def __init__(self, parent, editable: bool):
        frame = ttk.Frame(parent)
        super().__init__(frame)
        self.checks = {}
        for i, ext in enumerate(COMMON_EXTENSIONS):
            var = tk.BooleanVar()
            var.trace_add("write", lambda *_: self.changed())
            box = ttk.Checkbutton(frame, text=ext, variable=var)
            if not editable:
                box.state(["disabled"])
            box.grid(row=0, column=i, sticky="w", padx=(0, 10))
            self.checks[ext] = var
        ttk.Label(frame, text="Other types (separate them with commas)").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.other_var = tk.StringVar()
        self.other_var.trace_add("write", lambda *_: self.changed())
        ttk.Entry(frame, textvariable=self.other_var, state="normal" if editable else "readonly").grid(
            row=1, column=4, columnspan=3, sticky="ew", pady=(6, 0))

    def get(self) -> str:
        other = [e.strip() for e in self.other_var.get().split(",") if e.strip()]
        return ", ".join([e for e, v in self.checks.items() if v.get()] + other)

    def set(self, text: str) -> None:
        parts = [p.strip().lower() for p in text.split(",") if p.strip()]
        parts = [p if p.startswith(".") else "." + p for p in parts]
        for ext, var in self.checks.items():
            var.set(ext in parts)
        self.other_var.set(", ".join(p for p in parts if p not in self.checks))


# --------------------------------------------------------------------------
# The form
# --------------------------------------------------------------------------

class SettingsForm:
    """The tabbed settings form. editable=False shows the same form without any way to change it."""

    def __init__(self, parent, editable: bool, on_change=None, default_buttons: bool | None = None):
        self.editable = editable
        self.on_change = on_change
        self.defaults = managed_to_form({})
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.fields: dict[str, Field] = {}
        self.name_lbls: dict[str, ttk.Label] = {}
        self.hint_lbls: dict[str, ttk.Label] = {}
        self.notebook = ttk.Notebook(self.frame)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.tab_frames: list[tuple[ttk.Frame, str, tuple]] = []
        self._default_buttons = editable if default_buttons is None else default_buttons
        for title, keys in TABS:
            tab = ttk.Frame(self.notebook, padding=12)
            tab.columnconfigure(1, weight=1)
            self.notebook.add(tab, text=title)
            self.tab_frames.append((tab, title, keys))
            for n, key in enumerate(keys):
                self.add_row(tab, n * 2, key)
        version = ttk.Frame(self.frame)
        version.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        version.columnconfigure(1, weight=1)
        self.add_row(version, 0, "_version")
        if editable:
            self.fields["output_stages"].watch(self.update_stage_choices)
        self.show()

    # ---- building
    def _make_field(self, parent, key: str) -> Field:
        if key == "browse_roots":
            return ListField(parent, self.editable)
        if key == "output_stages":
            return StagesField(parent, self.editable)
        if key == "upload_extensions":
            return ExtensionsField(parent, self.editable)
        var = tk.StringVar()
        if key in ("kms_key_id", "user_settings_location"):
            if key == "kms_key_id":
                to_label, to_value = self.kms_to_label, kms_value
            else:
                to_label = lambda v: LOCATION_LABELS.get(v, v)  # noqa: E731
                to_value = lambda t: next((k for k, lbl in LOCATION_LABELS.items() if lbl == t), t)  # noqa: E731
            if not self.editable:
                return ChoiceField(ttk.Entry(parent, textvariable=var, state="readonly"), var, to_label, to_value)
            box = ttk.Combobox(parent, textvariable=var, state="normal" if key == "kms_key_id" else "readonly")
            if key == "user_settings_location":
                box.configure(values=list(LOCATION_LABELS.values()))
            return ChoiceField(box, var, to_label, to_value)
        if not self.editable:
            return Field(ttk.Entry(parent, textvariable=var, state="readonly"), var)
        if key == "max_concurrency":
            return Field(ttk.Spinbox(parent, textvariable=var, from_=1, to=32, increment=1, width=8), var)
        if key == "large_download_warning_mb":
            return Field(ttk.Spinbox(parent, textvariable=var, from_=0, to=1_000_000, increment=256, width=10), var)
        if key in ("bucket", "log_prefix"):
            return Field(ttk.Combobox(parent, textvariable=var), var)
        if key == "default_stage":
            return Field(ttk.Combobox(parent, textvariable=var, state="readonly"), var)
        return Field(ttk.Entry(parent, textvariable=var), var)

    def add_row(self, parent, row: int, key: str) -> None:
        name = ttk.Label(parent, text=LABELS[key], wraplength=190, justify="left")
        name.grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=(6, 0))
        field = self._make_field(parent, key)
        field.widget.grid(row=row, column=1, sticky="w" if isinstance(field.widget, ttk.Spinbox) else "ew", pady=(6, 0))
        if self.on_change:
            field.watch(self.on_change)
        if self._default_buttons and key != "_version":
            ttk.Button(parent, text="Use default", command=lambda k=key: self.use_default(k)).grid(
                row=row, column=2, sticky="ne", padx=(10, 0), pady=(6, 0))
        hint = ttk.Label(parent, text="", foreground=HINT_COLOR, wraplength=600, justify="left")
        hint.grid(row=row + 1, column=1, columnspan=2, sticky="w", pady=(2, 4))
        # Narrow windows: wrap the explanation to the space there is, so no line is cut off.
        parent.bind("<Configure>", lambda e, h=hint: h.configure(
            wraplength=min(600, max(240, e.width - h.winfo_x() - 24))), add="+")
        self.fields[key], self.name_lbls[key], self.hint_lbls[key] = field, name, hint

    # ---- values
    def get_form(self) -> dict[str, str]:
        return {k: f.get() for k, f in self.fields.items()}

    def set_form(self, values: dict[str, str]) -> None:
        for k, f in self.fields.items():
            if k != "default_stage":
                f.set(values.get(k, ""))
        self.update_stage_choices()
        self.fields["default_stage"].set(values.get("default_stage", ""))

    def use_default(self, key: str) -> None:
        self.fields[key].set(self.defaults.get(key, ""))
        if key == "output_stages":
            self.fields["default_stage"].set(self.defaults["default_stage"])

    def update_stage_choices(self) -> None:
        if not self.editable:
            return
        names = self.fields["output_stages"].names()
        box = self.fields["default_stage"]
        box.widget.configure(values=names)
        if names and box.get() not in names:
            box.set(names[0])

    def kms_to_label(self, value: str) -> str:
        if not value:
            return BUCKET_KEY_LABEL
        widget = self.fields["kms_key_id"].widget if "kms_key_id" in self.fields else None
        for label in (widget.cget("values") if isinstance(widget, ttk.Combobox) else ()):
            if kms_value(label) == value:
                return label
        return value

    def set_choices(self, buckets=None, keys=None, folders=None) -> None:
        """Fill the drop-downs from what exists in AWS (editable form only)."""
        if not self.editable:
            return
        if buckets is not None:
            self.fields["bucket"].widget.configure(values=buckets)
        if keys is not None:
            field = self.fields["kms_key_id"]
            current = field.get()
            field.widget.configure(values=[BUCKET_KEY_LABEL] + [kms_label(a, k) for a, k in keys])
            field.set(current)
        if folders is not None:
            self.fields["browse_roots"].pick.configure(values=folders)
            self.fields["output_stages"].folder_pick.configure(values=folders)
            self.fields["log_prefix"].widget.configure(values=folders)

    # ---- explanations, problems and changes
    def default_text(self, key: str) -> str:
        value = self.defaults.get(key, "")
        if key == "kms_key_id":
            return "the bucket's own key"
        if key == "user_settings_location":
            return LOCATION_LABELS.get(value, value).split(" (")[0].lower()
        if key == "output_stages":
            return ", ".join(line.split(" = ")[0] for line in value.splitlines())
        return value

    def show(self, errs: dict | None = None, changed: set | None = None) -> None:
        errs, changed = errs or {}, changed or set()
        for key, hint in self.hint_lbls.items():
            if key in errs:
                hint.configure(text=errs[key], foreground=ERROR_COLOR)
            else:
                default = "" if key == "_version" else f" Default: {self.default_text(key)}."
                hint.configure(text=HINTS[key] + default, foreground=HINT_COLOR)
            self.name_lbls[key].configure(text=LABELS[key] + ("  (changed)" if key in changed else ""))
        for tab, title, keys in self.tab_frames:
            mark = " - needs a fix" if any(k in errs for k in keys) else (" (changed)" if any(k in changed for k in keys) else "")
            self.notebook.tab(tab, text=title + mark)


class ScrollArea(ttk.Frame):
    """A box whose content scrolls up and down when the window is too short to show all of it.
    It moves the content inside a themed frame instead of drawing it on a canvas, so the background
    matches the rest of the window on every system. Put the content in .inner."""

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.view = ttk.Frame(self, name="scrollview")
        self.view.grid(row=0, column=0, sticky="nsew")
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self._scroll)
        self.inner = ttk.Frame(self.view)
        self.inner.place(x=0, y=0, relwidth=1)
        self._top = 0
        self.view.bind("<Configure>", lambda _e: self._update())
        self.inner.bind("<Configure>", lambda _e: self._update())
        self.bind("<Enter>", lambda _e: self.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda _e: self.unbind_all("<MouseWheel>"))

    def _update(self) -> None:
        view_h, full_h = self.view.winfo_height(), self.inner.winfo_reqheight()
        if full_h <= view_h or view_h <= 1:
            self._top = 0
            self.bar.grid_remove()
        else:
            self.bar.grid(row=0, column=1, sticky="ns")
            self._top = max(0, min(self._top, full_h - view_h))
        self.inner.place_configure(y=-self._top)
        full = max(full_h, 1)
        self.bar.set(self._top / full, min(1.0, (self._top + view_h) / full))

    def _scroll(self, *args) -> None:
        view_h, full_h = self.view.winfo_height(), self.inner.winfo_reqheight()
        if args[0] == "moveto":
            self._top = int(float(args[1]) * full_h)
        elif args[0] == "scroll":
            step = view_h * 0.9 if args[2] == "pages" else 30
            self._top += int(int(args[1]) * step)
        self._update()

    def _wheel(self, event) -> None:
        delta = event.delta if abs(event.delta) < 120 else event.delta // 120   # Mac sends small steps, Windows 120s
        self._scroll("scroll", -delta, "units")
