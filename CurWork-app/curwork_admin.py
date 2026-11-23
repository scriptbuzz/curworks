"""
CurWork Admin Settings: a window for AWS admins to view and change the CurWork settings kept in AWS
Systems Manager Parameter Store (bucket, folders, encryption, file rules, work folder). Drop-downs list
the buckets, encryption keys and folders that exist in AWS, and each setting shows its default and any
problem in plain words before anything is saved.

Version:     Beta 0.014
Status:      DRAFT - For Internal Use (FPT)
Updated:     2026-11-23 00:16 UTC
Modified by: mbitar

Who can change the settings is decided by AWS, not by this window: billers' permissions can only read
the parameter (ssm:GetParameter), so a save works only for a sign-in whose role may call
ssm:PutParameter on it, such as the AWS admin role (NIST SP 800-53 AC-3, AC-6, CM-5). Parameter Store
keeps every version, and CloudTrail records who saved each one (AU-2, AU-12).

Run:  python curwork_admin.py --profile <admin profile>
      python curwork_admin.py --profile <admin profile> --parameter /curwork/admin-settings --region us-east-1
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import boto3
import botocore.exceptions as bexc

import curwork_core as core

APP_TITLE = "CurWork Admin Settings"
DEFAULT_PARAMETER = core.DEFAULT_PARAMETER

# The form: (key, label, kind). kind is text, list (comma-separated), stages (one "Name = folder/" per line) or int.
FIELDS = (
    ("bucket", "S3 bucket", "text"),
    ("kms_key_id", "Encryption key for saved files (leave blank to use the bucket's own key)", "text"),
    ("browse_roots", "Folders billers can download from (separate them with commas)", "list"),
    ("output_stages", "Result types (one per line: Name = folder/)", "stages"),
    ("default_stage", "Result type picked at start", "text"),
    ("log_prefix", "Folder where CurWork saves its logs", "text"),
    ("upload_extensions", "File types billers can save in S3 (separate them with commas)", "list"),
    ("large_download_warning_mb", "Ask before downloading more than (MB)", "int"),
    ("max_concurrency", "Files copied at the same time (1 to 32)", "int"),
    ("work_dir", "Work folder on each laptop (In, Out and logs are kept here)", "text"),
    ("user_settings_location", "Where each biller's preferences are saved (tool_folder or work_folder)", "text"),
    ("_version", "Version label", "text"),
)


# --------------------------------------------------------------------------
# Form values <-> managed settings
# --------------------------------------------------------------------------

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


def form_to_managed(form: dict[str, str]) -> dict:
    """The form's text as a managed settings object. Raises CurWorkError with a plain message."""
    managed: dict = {}
    for key, label, kind in FIELDS:
        raw = (form.get(key) or "").strip()
        if kind == "list":
            managed[key] = [part.strip() for part in raw.split(",") if part.strip()]
        elif kind == "stages":
            stages = {}
            for n, line in enumerate(raw.splitlines(), 1):
                if not line.strip():
                    continue
                name, sep, folder = line.partition("=")
                if not sep or not name.strip() or not folder.strip():
                    raise core.CurWorkError(f"Result types, line {n}: write it as  Name = folder/")
                stages[name.strip()] = folder.strip()
            managed[key] = stages
        elif kind == "int":
            try:
                managed[key] = int(raw)
            except ValueError:
                raise core.CurWorkError(f"'{label}' must be a whole number.") from None
        elif raw or key != "_version":
            managed[key] = raw
    return core.validate_managed(managed)


def describe_changes(before: dict | None, after: dict) -> list[str]:
    """One plain line per setting that changes, for the confirmation before saving. A setting missing from
    the saved version counts as CurWork's default, which is also what the form shows for it."""
    lines = []
    for key, label, _kind in FIELDS:
        old = (before.get(key, core.DEFAULT_CONFIG.get(key)) if before is not None else None)
        new = after.get(key, core.DEFAULT_CONFIG.get(key))
        if old != new:
            lines.append(f"{label}: {json.dumps(old) if old is not None else '(not set)'} -> "
                         f"{json.dumps(new) if new is not None else '(not set)'}")
    return lines


# --------------------------------------------------------------------------
# Parameter Store
# --------------------------------------------------------------------------

class AdminStore:
    """Reads and saves the managed settings parameter. AWS decides whether a save is allowed."""

    def __init__(self, parameter: str, region: str, profile: str = "", use_fips: bool = False,
                 session: boto3.Session | None = None):
        self.parameter = parameter
        self.region = region
        self.profile = profile
        self.use_fips = use_fips
        self._session = session

    def session(self) -> boto3.Session:
        if self._session is None:
            self._session = boto3.Session(profile_name=self.profile or None, region_name=self.region)
        return self._session

    def reset(self) -> None:
        self._session = None

    def _client(self, name: str):
        return self.session().client(name, region_name=self.region,
                                     config=core.BotoConfig(use_fips_endpoint=self.use_fips, retries={"mode": "standard"}))

    def whoami(self) -> str:
        return core.friendly_identity(self._client("sts").get_caller_identity()["Arn"])

    def load(self) -> tuple[dict | None, int | None]:
        """(managed settings, version), or (None, None) if the parameter doesn't exist yet."""
        try:
            p = self._client("ssm").get_parameter(Name=self.parameter)["Parameter"]
        except bexc.ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ParameterNotFound":
                return None, None
            raise
        return core.parse_managed(p["Value"]), int(p["Version"])

    def history(self) -> list[dict]:
        """Every saved version, newest first: version, when, who, label."""
        ssm = self._client("ssm")
        rows, token = [], None
        while True:
            kw = {"Name": self.parameter, "MaxResults": 50, **({"NextToken": token} if token else {})}
            page = ssm.get_parameter_history(**kw)
            for p in page.get("Parameters", []):
                try:
                    label = str(json.loads(p.get("Value") or "{}").get("_version") or "")
                except (json.JSONDecodeError, AttributeError):
                    label = "(not valid JSON)"
                rows.append({"version": int(p["Version"]), "when": p.get("LastModifiedDate"),
                             "who": core.friendly_identity(p.get("LastModifiedUser", "")), "label": label})
            token = page.get("NextToken")
            if not token:
                break
        return sorted(rows, key=lambda r: r["version"], reverse=True)

    def save(self, managed: dict, expected_version: int | None) -> int:
        """Save a new version. expected_version is the version the admin loaded (None for the first save);
        if someone else saved since, nothing is written."""
        core.validate_managed(managed)
        _current, version = self.load()
        if version != expected_version:
            raise core.CurWorkError(
                f"Someone else saved the settings since you loaded them (now version {version}). "
                "Click Load from AWS to see their change, then make yours again.")
        ssm = self._client("ssm")
        kw = {"Name": self.parameter, "Value": json.dumps(managed, indent=2), "Type": "String", "Tier": "Standard",
              "Description": "CurWork admin settings. Change them with the CurWork Admin Settings app."}
        try:
            if expected_version is None:
                resp = ssm.put_parameter(**kw, Overwrite=False, Tags=[{"Key": "Purpose", "Value": "CurWork"}])
            else:
                resp = ssm.put_parameter(**kw, Overwrite=True)
        except bexc.ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("AccessDenied", "AccessDeniedException"):
                raise core.CurWorkError(
                    "Your AWS sign-in isn't allowed to change CurWork's admin settings. "
                    "Only the AWS admin role can. Sign in with the admin profile and try again.") from None
            if code == "ParameterAlreadyExists":
                raise core.CurWorkError("Someone else created the settings a moment ago. Click Load from AWS, then try again.") from None
            raise
        return int(resp["Version"])

    # ---- lists that fill the form's drop-downs (read-only; the admin role may list these)
    def list_buckets(self) -> list[str]:
        return sorted(b["Name"] for b in self._client("s3").list_buckets().get("Buckets", []))

    def list_kms_keys(self) -> list[tuple[str, str]]:
        """(alias, key ID) for each customer-managed key that has an alias. AWS-managed keys (alias/aws/...)
        are left out: "Use the bucket's own key" already covers the bucket's default encryption."""
        out = []
        for page in self._client("kms").get_paginator("list_aliases").paginate():
            for a in page.get("Aliases", []):
                if a.get("TargetKeyId") and not a.get("AliasName", "").startswith("alias/aws/"):
                    out.append((a["AliasName"], a["TargetKeyId"]))
        return sorted(out)

    def list_folders(self, bucket: str, limit: int = 500) -> list[str]:
        """The top-level folders in a bucket, such as converted/ and priced/."""
        folders: list[str] = []
        for page in self._client("s3").get_paginator("list_objects_v2").paginate(Bucket=bucket, Delimiter="/"):
            folders += [p["Prefix"] for p in page.get("CommonPrefixes", [])]
            if len(folders) >= limit:
                break
        return sorted(folders)[:limit]


# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------

# The form's plain-language help, shown in grey under each field. Errors replace it in red.
HINTS = {
    "bucket": "The S3 bucket that holds the CUR workbooks.",
    "kms_key_id": "Keep the bucket's own key unless your security team gave you a key for CurWork.",
    "browse_roots": "Billers can only download from these folders. They must not overlap the result folders.",
    "log_prefix": "CurWork saves each biller's log in this folder when they click Finish and clean up.",
    "output_stages": "Billers pick a result type in step 3, and their files are saved in its folder.",
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
_BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
LABELS = {key: label for key, label, _kind in FIELDS}


def kms_label(alias: str, key_id: str) -> str:
    return f"{alias}  ({key_id})"


def kms_value(text: str) -> str:
    """The key ID behind what the encryption key drop-down shows."""
    t = (text or "").strip()
    if not t or t == BUCKET_KEY_LABEL:
        return ""
    m = re.search(r"\(([^()]+)\)\s*$", t)
    return m.group(1).strip() if m else t


def field_errors(form: dict[str, str]) -> dict[str, str]:
    """One plain message per field that can't be saved as it is. "_form" holds a problem between fields."""
    errs: dict[str, str] = {}
    bucket = (form.get("bucket") or "").strip()
    if not bucket:
        errs["bucket"] = "Pick or type the S3 bucket."
    elif not _BUCKET_NAME.match(bucket):
        errs["bucket"] = "A bucket name has 3 to 63 lowercase letters, numbers, dots or hyphens."
    if not [r for r in (form.get("browse_roots") or "").split(",") if r.strip()]:
        errs["browse_roots"] = "Add at least one folder billers can download from."
    names = []
    for n, line in enumerate((form.get("output_stages") or "").splitlines(), 1):
        if not line.strip():
            continue
        name, sep, folder = line.partition("=")
        if not sep or not name.strip() or not folder.strip():
            errs["output_stages"] = f"Line {n}: every result type needs a name and a folder (Name = folder/)."
            break
        names.append(name.strip())
    if not names and "output_stages" not in errs:
        errs["output_stages"] = "Add at least one result type."
    if names and (form.get("default_stage") or "").strip() not in names:
        errs["default_stage"] = "Pick one of the result types."
    if not [e for e in (form.get("upload_extensions") or "").split(",") if e.strip()]:
        errs["upload_extensions"] = "Allow at least one type of file."
    for key, low, high in (("large_download_warning_mb", 0, None), ("max_concurrency", 1, 32)):
        try:
            value = int((form.get(key) or "").strip())
        except ValueError:
            errs[key] = "Type a whole number."
            continue
        if value < low or (high is not None and value > high):
            errs[key] = f"Use a number from {low} to {high}." if high else f"Use {low} or more."
    if (form.get("user_settings_location") or "").strip() not in LOCATION_LABELS:
        errs["user_settings_location"] = "Pick one of the two places."
    if re.search(r"[\x00-\x1f]", form.get("work_dir") or ""):
        errs["work_dir"] = "The folder has a hidden control character in it. Use / or \\\\ between folder names."
    if not errs:
        try:
            form_to_managed(form)
        except core.CurWorkError as e:
            errs["_form"] = str(e)
    return errs


class _Field:
    """One form control. get() and set() use the same text the form always used (see managed_to_form)."""

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


class _ChoiceField(_Field):
    """A drop-down that shows plain labels for stored values (where preferences go, which KMS key)."""

    def __init__(self, parent, to_label, to_value, editable: bool):
        var = tk.StringVar()
        super().__init__(ttk.Combobox(parent, textvariable=var, state="normal" if editable else "readonly"), var)
        self.to_label, self.to_value = to_label, to_value

    def get(self) -> str:
        return self.to_value(self.var.get())

    def set(self, text: str) -> None:
        self.var.set(self.to_label(text))


class _ListField(_Field):
    """A list of S3 folders with a drop-down to add one and a button to remove the selected ones."""

    def __init__(self, parent):
        frame = ttk.Frame(parent)
        super().__init__(frame)
        frame.columnconfigure(0, weight=1)
        self.box = tk.Listbox(frame, height=4, selectmode="extended", exportselection=False)
        self.box.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.pick_var = tk.StringVar()
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


class _StagesField(_Field):
    """Result types as a small table: a name billers see and the S3 folder their files are saved in."""

    def __init__(self, parent):
        frame = ttk.Frame(parent)
        super().__init__(frame)
        frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("folder",), height=5, selectmode="browse")
        self.tree.heading("#0", text="Name billers see")
        self.tree.heading("folder", text="S3 folder")
        self.tree.column("#0", width=160)
        self.tree.column("folder", width=140)
        self.tree.grid(row=0, column=0, rowspan=6, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._picked)
        self.name_var, self.folder_var = tk.StringVar(), tk.StringVar()
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
            messagebox.showinfo(APP_TITLE, "Type a name and pick or type an S3 folder first.", parent=self.widget)
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


class _ExtensionsField(_Field):
    """A checkbox for each common file type, and a box for any others."""

    def __init__(self, parent):
        frame = ttk.Frame(parent)
        super().__init__(frame)
        self.checks = {}
        for i, ext in enumerate(COMMON_EXTENSIONS):
            var = tk.BooleanVar()
            var.trace_add("write", lambda *_: self.changed())
            ttk.Checkbutton(frame, text=ext, variable=var).grid(row=0, column=i, sticky="w", padx=(0, 10))
            self.checks[ext] = var
        ttk.Label(frame, text="Other types (separate them with commas)").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.other_var = tk.StringVar()
        self.other_var.trace_add("write", lambda *_: self.changed())
        ttk.Entry(frame, textvariable=self.other_var).grid(row=1, column=4, columnspan=3, sticky="ew", pady=(6, 0))

    def get(self) -> str:
        other = [e.strip() for e in self.other_var.get().split(",") if e.strip()]
        return ", ".join([e for e, v in self.checks.items() if v.get()] + other)

    def set(self, text: str) -> None:
        parts = [p.strip().lower() for p in text.split(",") if p.strip()]
        parts = [p if p.startswith(".") else "." + p for p in parts]
        for ext, var in self.checks.items():
            var.set(ext in parts)
        self.other_var.set(", ".join(p for p in parts if p not in self.checks))


class AdminApp:
    def __init__(self, root: tk.Tk, store: AdminStore, local_settings: core.Settings | None = None):
        self.root = root
        self.store = store
        self.local = local_settings
        self.loaded: dict | None = None
        self.version: int | None = None
        self.can_save = False
        self.busy = False
        self.pending_lookups = 0
        self._refresh_job = None
        self._q: queue.Queue = queue.Queue()
        self.defaults = managed_to_form({})
        root.title(f"{APP_TITLE} - {core.RELEASE_LABEL} ({core.STATUS})")
        self._build()
        root.after(50, self._poll)

    # ---- layout
    def _build(self) -> None:
        f = ttk.Frame(self.root, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text=APP_TITLE, font=("TkDefaultFont", 15, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Only a sign-in with the AWS admin role can save. Billers can only read these settings.",
                  foreground="#555").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.profile_var = tk.StringVar(value=self.store.profile)
        self.param_var = tk.StringVar(value=self.store.parameter)
        self.region_var = tk.StringVar(value=self.store.region)
        ttk.Label(f, text="AWS admin profile").grid(row=2, column=0, sticky="w", pady=2, padx=(0, 10))
        who = ttk.Frame(f)
        who.grid(row=2, column=1, sticky="ew", pady=2)
        who.columnconfigure(0, weight=1)
        ttk.Entry(who, textvariable=self.profile_var).grid(row=0, column=0, sticky="ew")
        ttk.Label(who, text="AWS Region").grid(row=0, column=1, padx=(12, 6))
        ttk.Entry(who, textvariable=self.region_var, width=14).grid(row=0, column=2)
        ttk.Label(f, text="Where the settings are kept (Parameter Store name)").grid(
            row=3, column=0, sticky="w", pady=2, padx=(0, 10))
        ttk.Entry(f, textvariable=self.param_var).grid(row=3, column=1, sticky="ew", pady=2)
        btns = ttk.Frame(f)
        btns.grid(row=2, column=2, rowspan=2, sticky="ne", padx=(10, 0))
        self.sign_btn = ttk.Button(btns, text="Sign in", command=self.sign_in, width=14)
        self.sign_btn.pack(fill="x")
        self.load_btn = ttk.Button(btns, text="Load from AWS", command=self.load, width=14)
        self.load_btn.pack(fill="x", pady=4)
        self.status_lbl = ttk.Label(f, text="Sign in with the admin profile, then click Load from AWS.", wraplength=720)
        self.status_lbl.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 6))
        self.lookup_lbl = ttk.Label(f, text="", foreground="#555", wraplength=720)
        self.lookup_lbl.grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.lookup_lbl.grid_remove()      # shown only while it has something to say

        self.fields: dict[str, _Field] = {}
        self.name_lbls: dict[str, ttk.Label] = {}
        self.hint_lbls: dict[str, ttk.Label] = {}
        self.notebook = ttk.Notebook(f)
        self.notebook.grid(row=7, column=0, columnspan=3, sticky="nsew")
        f.rowconfigure(7, weight=1)
        self.tab_frames: list[tuple[ttk.Frame, str, tuple]] = []
        for title, keys in TABS:
            tab = ttk.Frame(self.notebook, padding=12)
            tab.columnconfigure(1, weight=1)
            self.notebook.add(tab, text=title)
            self.tab_frames.append((tab, title, keys))
            for n, key in enumerate(keys):
                self._add_row(tab, n * 2, key)

        bottom = ttk.Frame(f)
        bottom.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(1, weight=1)
        self._add_row(bottom, 0, "_version")
        self.form_err_lbl = ttk.Label(f, text="", foreground="#B00020", wraplength=720)
        self.form_err_lbl.grid(row=9, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.form_err_lbl.grid_remove()
        actions = ttk.Frame(f)
        actions.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.copy_btn = ttk.Button(actions, text="Copy from this laptop's settings file", command=self.fill_from_local)
        self.copy_btn.pack(side="left")
        self.history_btn = ttk.Button(actions, text="History", command=self.show_history)
        self.history_btn.pack(side="left", padx=6)
        self.save_btn = ttk.Button(actions, text="Save in AWS", command=self.save, state="disabled")
        self.save_btn.pack(side="right")

        self.fields["bucket"].widget.bind("<<ComboboxSelected>>", lambda _e: self._lookup_folders())
        self.fields["bucket"].widget.bind("<FocusOut>", lambda _e: self._lookup_folders())
        self.fields["output_stages"].watch(self._update_stage_choices)
        self._refresh()
        self.root.update_idletasks()      # never open smaller than the form needs, so nothing is cut off
        self.root.minsize(self.root.winfo_reqwidth(), self.root.winfo_reqheight())

    def _make_field(self, parent, key: str) -> _Field:
        if key == "kms_key_id":
            return _ChoiceField(parent, self._kms_to_label, kms_value, editable=True)
        if key == "user_settings_location":
            field = _ChoiceField(parent, lambda v: LOCATION_LABELS.get(v, v),
                                 lambda t: next((k for k, lbl in LOCATION_LABELS.items() if lbl == t), t), editable=False)
            field.widget.configure(values=list(LOCATION_LABELS.values()))
            return field
        if key == "browse_roots":
            return _ListField(parent)
        if key == "output_stages":
            return _StagesField(parent)
        if key == "upload_extensions":
            return _ExtensionsField(parent)
        var = tk.StringVar()
        if key == "max_concurrency":
            return _Field(ttk.Spinbox(parent, textvariable=var, from_=1, to=32, increment=1, width=8), var)
        if key == "large_download_warning_mb":
            return _Field(ttk.Spinbox(parent, textvariable=var, from_=0, to=1_000_000, increment=256, width=10), var)
        if key in ("bucket", "log_prefix"):
            return _Field(ttk.Combobox(parent, textvariable=var), var)
        if key == "default_stage":
            return _Field(ttk.Combobox(parent, textvariable=var, state="readonly"), var)
        return _Field(ttk.Entry(parent, textvariable=var), var)

    def _add_row(self, parent, row: int, key: str) -> None:
        name = ttk.Label(parent, text=LABELS[key], wraplength=190, justify="left")
        name.grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=(6, 0))
        field = self._make_field(parent, key)
        sticky = "w" if isinstance(field.widget, ttk.Spinbox) else "ew"
        field.widget.grid(row=row, column=1, sticky=sticky, pady=(6, 0))
        field.watch(self._schedule_refresh)
        if key != "_version":
            ttk.Button(parent, text="Use default", command=lambda k=key: self.use_default(k)).grid(
                row=row, column=2, sticky="ne", padx=(10, 0), pady=(6, 0))
        hint = ttk.Label(parent, text="", foreground="#555", wraplength=600, justify="left")
        hint.grid(row=row + 1, column=1, columnspan=2, sticky="w", pady=(2, 4))
        self.fields[key], self.name_lbls[key], self.hint_lbls[key] = field, name, hint

    @staticmethod
    def _note(lbl: ttk.Label, text: str) -> None:
        """A note line that takes no room while it's empty."""
        lbl.configure(text=text)
        if text:
            lbl.grid()
        else:
            lbl.grid_remove()

    def _kms_to_label(self, value: str) -> str:
        if not value:
            return BUCKET_KEY_LABEL
        for label in self.fields["kms_key_id"].widget.cget("values") if "kms_key_id" in self.fields else ():
            if kms_value(label) == value:
                return label
        return value

    def _default_text(self, key: str) -> str:
        value = self.defaults.get(key, "")
        if key == "kms_key_id":
            return "the bucket's own key"
        if key == "user_settings_location":
            return LOCATION_LABELS.get(value, value).split(" (")[0].lower()
        if key == "output_stages":
            return ", ".join(line.split(" = ")[0] for line in value.splitlines())
        return value

    # ---- form
    def get_form(self) -> dict[str, str]:
        return {k: f.get() for k, f in self.fields.items()}

    def set_form(self, values: dict[str, str]) -> None:
        for k, f in self.fields.items():
            if k == "default_stage":
                continue
            f.set(values.get(k, ""))
        self._update_stage_choices()
        self.fields["default_stage"].set(values.get("default_stage", ""))
        self._refresh()

    def set_field(self, key: str, text: str) -> None:
        self.fields[key].set(text)
        self._refresh()

    def use_default(self, key: str) -> None:
        self.set_field(key, self.defaults.get(key, ""))
        if key == "output_stages":
            self.fields["default_stage"].set(self.defaults["default_stage"])
            self._refresh()

    def _update_stage_choices(self) -> None:
        names = self.fields["output_stages"].names()
        box = self.fields["default_stage"]
        box.widget.configure(values=names)
        if names and box.get() not in names:
            box.set(names[0])

    def _schedule_refresh(self) -> None:
        if self._refresh_job is None:
            self._refresh_job = self.root.after(120, self._refresh)

    def _refresh(self) -> None:
        """Show each field's help or its problem in plain words, and mark what changed since Load."""
        self._refresh_job = None
        form = self.get_form()
        ready = self.can_save
        errs = field_errors(form) if ready else {}
        before = managed_to_form(self.loaded or {}) if ready else form
        changed = {k for k in self.fields if form.get(k, "").strip() != before.get(k, "").strip()}
        for key, hint in self.hint_lbls.items():
            if key in errs:
                hint.configure(text=errs[key], foreground="#B00020")
            else:
                default = "" if key == "_version" else f" Default: {self._default_text(key)}."
                hint.configure(text=HINTS[key] + default, foreground="#555")
            self.name_lbls[key].configure(text=LABELS[key] + ("  (changed)" if key in changed else ""))
        for tab, title, keys in self.tab_frames:
            mark = " - needs a fix" if any(k in errs for k in keys) else (" (changed)" if any(k in changed for k in keys) else "")
            self.notebook.tab(tab, text=title + mark)
        self._note(self.form_err_lbl, errs.get("_form", ""))
        self.errors, self.changed_keys = errs, changed

    # ---- background work (AWS calls and the browser sign-in can take a while)
    def run(self, label: str, work, done) -> None:
        if self.busy:
            return
        self.busy = True
        self.status_lbl.configure(text=label)
        self._sync_store()

        def runner():
            try:
                result = work()
                self._q.put((lambda: done(result), True))
            except BaseException as e:  # noqa: BLE001
                self._q.put((lambda err=e: self._failed(err), True))   # bind it now: Python clears e after this block

        threading.Thread(target=runner, daemon=True).start()

    def _lookup(self, work, done) -> None:
        """Fill a drop-down from AWS without blocking the window. A failure only means typing the name."""
        self.pending_lookups += 1

        def runner():
            try:
                result = work()
                self._q.put((lambda: done(result), False))
            except BaseException as e:  # noqa: BLE001
                self._q.put((lambda err=e: self._lookup_failed(err), False))

        threading.Thread(target=runner, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                fn, task = self._q.get_nowait()
                if task:
                    self.busy = False
                else:
                    self.pending_lookups -= 1
                fn()
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _failed(self, e: BaseException) -> None:
        kind, msg = core.classify_error(e)
        self.status_lbl.configure(text="Something went wrong. See the message.")
        messagebox.showerror(APP_TITLE, msg, parent=self.root)

    def _lookup_failed(self, e: BaseException) -> None:
        _kind, msg = core.classify_error(e)
        self._note(self.lookup_lbl, f"CurWork couldn't list everything in AWS, so some drop-downs may be empty. "
                                       f"You can still type the names. AWS said: {msg}")

    def _lookup_all(self) -> None:
        self._note(self.lookup_lbl, "Reading the buckets, encryption keys and folders you can pick from...")

        def got_buckets(names):
            self.fields["bucket"].widget.configure(values=names)

        def got_keys(keys):
            field = self.fields["kms_key_id"]
            current = field.get()
            field.widget.configure(values=[BUCKET_KEY_LABEL] + [kms_label(a, k) for a, k in keys])
            field.set(current)
            if self.lookup_lbl.cget("text").startswith("Reading"):
                self._note(self.lookup_lbl, "")
        self._lookup(self.store.list_buckets, got_buckets)
        self._lookup(self.store.list_kms_keys, got_keys)
        self._lookup_folders()

    def _lookup_folders(self) -> None:
        bucket = self.fields["bucket"].get().strip()
        if not self.can_save or not _BUCKET_NAME.match(bucket) or bucket == getattr(self, "_folders_for", None):
            return
        self._folders_for = bucket

        def got(folders):
            if self.fields["bucket"].get().strip() != bucket:
                return
            for key in ("browse_roots", "output_stages"):
                pick = self.fields[key].pick if key == "browse_roots" else self.fields[key].folder_pick
                pick.configure(values=folders)
            self.fields["log_prefix"].widget.configure(values=folders)
        self._lookup(lambda: self.store.list_folders(bucket), got)

    def _sync_store(self) -> None:
        new = (self.profile_var.get().strip(), self.param_var.get().strip(), self.region_var.get().strip())
        if new != (self.store.profile, self.store.parameter, self.store.region):
            self.store.profile, self.store.parameter, self.store.region = new
            self.store.reset()
            self.loaded, self.version, self.can_save = None, None, False
            self.save_btn.configure(state="disabled")

    # ---- actions
    def sign_in(self) -> None:
        def work():
            core.run_sso_login(self.store.profile, cli_path=self.local.aws_cli_path if self.local else "")
            self.store.reset()
            return self.store.whoami()
        self.run("Signing in (check your browser)...", work,
                 lambda who: self.status_lbl.configure(text=f"Signed in as {who}. Click Load from AWS."))

    def load(self) -> None:
        def work():
            return self.store.whoami(), *self.store.load()

        def done(result):
            who, managed, version = result
            self.loaded, self.version, self.can_save = managed, version, True
            self._folders_for = None
            self.save_btn.configure(state="normal")
            if managed is None:
                self.set_form(managed_to_form({}))
                self.status_lbl.configure(text=f"Signed in as {who}. {self.store.parameter} doesn't exist yet. Fill in the form, or "
                                               "copy from this laptop's settings file, then click Save in AWS to create it.")
            else:
                self.set_form(managed_to_form(managed))
                self.status_lbl.configure(text=f"Signed in as {who}. Loaded version {version} of {self.store.parameter}.")
            self._lookup_all()
        self.run("Loading...", work, done)

    def fill_from_local(self) -> None:
        if not self.local:
            messagebox.showinfo(APP_TITLE, f"There's no local {core.CONFIG_FILE_NAME} to copy from.", parent=self.root)
            return
        local = {k: v for k, v in self.local.local_data.items() if k in core.MANAGED_KEYS or k == "_version"}
        self.set_form(managed_to_form(local))
        self.status_lbl.configure(text=f"Copied from {self.local.source_path}. Check it, then click Save in AWS.")

    def save(self) -> None:
        if not self.can_save:
            return
        form = self.get_form()
        errs = field_errors(form)
        if errs:
            self._refresh()
            key = next(iter(errs))
            where = "" if key == "_form" else f"{LABELS[key]}: "
            messagebox.showerror(APP_TITLE, f"Fix this before saving.\n\n{where}{errs[key]}", parent=self.root)
            return
        managed = form_to_managed(form)
        changes = describe_changes(self.loaded, managed)
        if not changes:
            messagebox.showinfo(APP_TITLE, "Nothing has changed, so there's nothing to save.", parent=self.root)
            return
        if not messagebox.askyesno(APP_TITLE, "Save these changes in AWS? Every CurWork user gets them "
                                   "the next time they sign in.\n\n" + "\n".join(changes), parent=self.root):
            return
        expected = self.version

        def done(version):
            self.loaded, self.version = managed, version
            self.status_lbl.configure(text=f"Saved version {version} of {self.store.parameter}.")
            self._refresh()
        self.run("Saving...", lambda: self.store.save(managed, expected), done)

    def show_history(self) -> None:
        def done(rows):
            win = tk.Toplevel(self.root)
            win.title(f"{APP_TITLE} - history")
            tree = ttk.Treeview(win, columns=("when", "who", "label"), height=14)
            for col, text, width in (("#0", "Version", 70), ("when", "Saved (UTC)", 170),
                                     ("who", "Saved by", 300), ("label", "Version label", 180)):
                tree.heading(col, text=text)
                tree.column(col, width=width)
            for r in rows:
                when = r["when"].strftime("%Y-%m-%d %H:%M") if hasattr(r["when"], "strftime") else str(r["when"] or "")
                tree.insert("", "end", text=str(r["version"]), values=(when, r["who"], r["label"]))
            tree.pack(fill="both", expand=True, padx=10, pady=10)
            ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))
            self.status_lbl.configure(text=f"{len(rows)} saved version(s) of {self.store.parameter}.")
        self.run("Reading the history...", self.store.history, done)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--profile", default=os.environ.get("CURWORK_ADMIN_PROFILE", ""),
                        help="AWS profile that signs in with the admin role")
    parser.add_argument("--parameter", default="", help=f"Parameter Store name (default {DEFAULT_PARAMETER})")
    parser.add_argument("--region", default="", help="AWS Region of the parameter")
    parser.add_argument("--config", default=None, help=f"Local {core.CONFIG_FILE_NAME} to take defaults from")
    args = parser.parse_args(argv)
    try:
        local = core.load_settings(args.config, strict=False)   # an older file can still be copied to AWS
    except core.CurWorkError:
        local = None
    parameter = args.parameter or (local.settings_parameter if local else "") or DEFAULT_PARAMETER
    region = args.region or (local.region if local else "") or "us-east-1"
    store = AdminStore(parameter, region, profile=args.profile, use_fips=bool(local and local.use_fips_endpoint))
    root = tk.Tk(className="CurWorkAdmin")
    AdminApp(root, store, local)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
