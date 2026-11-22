"""
CurWork Admin Settings: a small window for AWS admins to view and change CurWork's managed admin
settings (bucket, folders, encryption, upload rules) in AWS Systems Manager Parameter Store.

Version:     Beta 0.012
Status:      DRAFT - For Internal Use (FPT)
Updated:     2026-11-22 23:32 UTC
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
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import boto3
import botocore.exceptions as bexc

import curwork_core as core

APP_TITLE = "CurWork Admin Settings"
DEFAULT_PARAMETER = "/curwork/admin-settings"

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
    ("_version", "Version label (shown in CurWork's About window)", "text"),
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


# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------

class AdminApp:
    def __init__(self, root: tk.Tk, store: AdminStore, local_settings: core.Settings | None = None):
        self.root = root
        self.store = store
        self.local = local_settings
        self.loaded: dict | None = None
        self.version: int | None = None
        self.can_save = False
        self.busy = False
        self._q: queue.Queue = queue.Queue()
        root.title(f"{APP_TITLE} - {core.RELEASE_LABEL} ({core.STATUS})")
        root.minsize(760, 560)
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
        for row, (label, var) in enumerate((("AWS admin profile", self.profile_var),
                                            ("Where the settings are kept (Parameter Store name)", self.param_var),
                                            ("AWS Region", self.region_var)), start=2):
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(f, textvariable=var).grid(row=row, column=1, sticky="ew", pady=2)
        btns = ttk.Frame(f)
        btns.grid(row=2, column=2, rowspan=3, sticky="ne", padx=(10, 0))
        self.sign_btn = ttk.Button(btns, text="Sign in", command=self.sign_in, width=14)
        self.sign_btn.pack(fill="x")
        self.load_btn = ttk.Button(btns, text="Load from AWS", command=self.load, width=14)
        self.load_btn.pack(fill="x", pady=4)
        self.status_lbl = ttk.Label(f, text="Sign in with the admin profile, then click Load from AWS.")
        self.status_lbl.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 8))

        form = ttk.LabelFrame(f, text="Settings kept in AWS", padding=10)
        form.grid(row=6, column=0, columnspan=3, sticky="nsew")
        f.rowconfigure(6, weight=1)
        form.columnconfigure(1, weight=1)
        self.inputs: dict[str, tk.Widget] = {}
        for row, (key, label, kind) in enumerate(FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="nw", pady=3, padx=(0, 10))
            if kind == "stages":
                w = tk.Text(form, height=5, width=50, wrap="none")
            else:
                w = ttk.Entry(form)
            w.grid(row=row, column=1, sticky="ew", pady=3)
            self.inputs[key] = w

        bottom = ttk.Frame(f)
        bottom.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.copy_btn = ttk.Button(bottom, text="Copy from this laptop's settings file", command=self.fill_from_local)
        self.copy_btn.pack(side="left")
        self.history_btn = ttk.Button(bottom, text="History", command=self.show_history)
        self.history_btn.pack(side="left", padx=6)
        self.save_btn = ttk.Button(bottom, text="Save in AWS", command=self.save, state="disabled")
        self.save_btn.pack(side="right")

    # ---- form
    def get_form(self) -> dict[str, str]:
        return {k: (w.get("1.0", "end") if isinstance(w, tk.Text) else w.get()) for k, w in self.inputs.items()}

    def set_form(self, values: dict[str, str]) -> None:
        for k, w in self.inputs.items():
            if isinstance(w, tk.Text):
                w.delete("1.0", "end")
                w.insert("1.0", values.get(k, ""))
            else:
                w.delete(0, "end")
                w.insert(0, values.get(k, ""))

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
                self._q.put(lambda: done(result))
            except BaseException as e:  # noqa: BLE001
                self._q.put(lambda err=e: self._failed(err))   # bind it now: Python clears e after this block

        threading.Thread(target=runner, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                fn = self._q.get_nowait()
                self.busy = False
                fn()
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _failed(self, e: BaseException) -> None:
        kind, msg = core.classify_error(e)
        self.status_lbl.configure(text="Something went wrong. See the message.")
        messagebox.showerror(APP_TITLE, msg, parent=self.root)

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
            self.save_btn.configure(state="normal")
            if managed is None:
                self.set_form(managed_to_form({}))
                self.status_lbl.configure(text=f"Signed in as {who}. {self.store.parameter} doesn't exist yet. Fill in the form, or "
                                               "copy from this laptop's settings file, then click Save in AWS to create it.")
            else:
                self.set_form(managed_to_form(managed))
                self.status_lbl.configure(text=f"Signed in as {who}. Loaded version {version} of {self.store.parameter}.")
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
        try:
            managed = form_to_managed(self.get_form())
        except core.CurWorkError as e:
            messagebox.showerror(APP_TITLE, str(e), parent=self.root)
            return
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
        local = core.load_settings(args.config)
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
