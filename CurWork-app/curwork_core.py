"""
CurWork core: moves CUR workbooks between Amazon S3 and a local work folder
so the billing VBA macros can run on local files with no code changes.

Version:     Beta 0.017
Status:      DRAFT - For Internal Use (FPT)
Updated:     2026-11-23 01:38 UTC
Modified by: mbitar

This module has no GUI code, so it can be tested on its own.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

import boto3
import botocore.exceptions as bexc
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig

VERSION = "0.017-beta"            # no spaces: used in the S3 user agent and metadata
RELEASE_LABEL = "Beta 0.017"
STATUS = "DRAFT - For Internal Use"
BUILD_DATE = "2026-11-23 01:38 UTC"
MODIFIED_BY = "mbitar"

log = logging.getLogger("curwork")

CONFIG_FILE_NAME = "curwork_admin_settings.json"      # protected: admin settings
USER_SETTINGS_FILE_NAME = "curwork_user_settings.json"  # unprotected: each user's own preferences
MAX_SETTINGS_BYTES = 256 * 1024  # both files are small; refuse anything bigger rather than parse it

DEFAULT_CONFIG: dict = {
    "aws_profile": "fpt-biller",
    "region": "us-east-1",
    "bucket": "",
    "use_fips_endpoint": False,
    "kms_key_id": "",
    "browse_roots": ["converted/"],
    "output_stages": {
        "Priced": "priced/",
        "Allocated": "allocated/",
        "Mapped": "mapped/",
        "Split by account": "split/",
        "Reports": "reports/",
    },
    "default_stage": "Priced",
    "log_prefix": "logs/",
    "work_dir": "%LOCALAPPDATA%\\CurWork",
    "upload_extensions": [".xlsx", ".xlsm", ".xlsb", ".xls", ".csv", ".txt", ".zip"],
    "large_download_warning_mb": 2048,
    "max_concurrency": 8,
    "aws_cli_path": "",
    "login_banner": "",
    "user_settings_location": "tool_folder",  # "tool_folder" (falls back to the work folder if not writable) or "work_folder"
    "settings_parameter": "",  # load_settings uses /curwork/admin-settings when the laptop file doesn't name one
    "sso": {
        "session_name": "",
        "start_url": "",
        "sso_region": "",
        "account_id": "",
        "role_name": "",
    },
}

# Files that Excel, Windows or this tool create and that should never be uploaded.
_IGNORE_PATTERNS = (
    re.compile(r"^~\$"),          # Excel/Office owner (lock) files
    re.compile(r"^~.*\.tmp$", re.I),
    re.compile(r".*\.part$", re.I),  # our partial downloads
    re.compile(r"^desktop\.ini$", re.I),
    re.compile(r"^thumbs\.db$", re.I),
    re.compile(r"^\.ds_store$", re.I),
)

_WINDOWS_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class CurWorkError(Exception):
    """An error with a message that is safe to show to a biller."""


class Cancelled(CurWorkError):
    pass


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@dataclass
class Settings:
    aws_profile: str
    region: str
    bucket: str
    use_fips_endpoint: bool
    kms_key_id: str
    browse_roots: list[str]
    output_stages: dict[str, str]
    default_stage: str
    log_prefix: str
    work_dir: Path
    upload_extensions: list[str]
    large_download_warning_mb: int
    max_concurrency: int
    aws_cli_path: str = ""
    login_banner: str = ""
    sso: dict = field(default_factory=dict)
    source_path: Path | None = None
    ignored_config_overrides: list[str] = field(default_factory=list)
    user_settings_location: str = "tool_folder"
    admin_version: str = ""
    settings_parameter: str = ""
    managed_loaded: bool = False          # True once the managed settings were read from Parameter Store
    local_data: dict = field(default_factory=dict, repr=False)

    @property
    def needs_managed_settings(self) -> bool:
        """True while CurWork still has to read its managed settings from Parameter Store (after sign-in)."""
        return bool(self.settings_parameter) and not self.managed_loaded

    @property
    def allowed_upload_prefixes(self) -> list[str]:
        return list(self.output_stages.values())


def _norm_prefix(p: str) -> str:
    p = (p or "").strip().lstrip("/").replace("\\", "/")
    if p and not p.endswith("/"):
        p += "/"
    return p


def _expand_work_dir(raw: str) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(raw))
    if re.search(r"%[A-Za-z_][A-Za-z0-9_]*%|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", expanded):
        # Variable was not set (for example %LOCALAPPDATA% on a non-Windows test box).
        expanded = str(Path.home() / "CurWork")
    return Path(expanded)


def candidate_config_paths(explicit: str | None = None) -> list[Path]:
    """Where to look for the admin settings file, in order.

    Config lock (NIST SP 800-53 CM-5, CM-6): the built app (CurWork.exe, or CurWork.app on a Mac) only
    reads the admin settings file installed next to it. It ignores --config, CURWORK_CONFIG and the
    user-writable %APPDATA% folder, so a biller can't point it at a settings file of their own.
    Running from source still accepts them: anyone who can run the source can also change it, so a
    lock there would add nothing, and the tests need them.
    """
    if getattr(sys, "frozen", False):
        return [tool_folder() / CONFIG_FILE_NAME]
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    if os.environ.get("CURWORK_CONFIG"):
        paths.append(Path(os.environ["CURWORK_CONFIG"]))
    paths.append(Path(__file__).resolve().parent / CONFIG_FILE_NAME)
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "CurWork" / CONFIG_FILE_NAME)
    return paths


def ignored_config_overrides(explicit: str | None = None) -> list[str]:
    """In the built app, the --config and CURWORK_CONFIG values it ignored (see candidate_config_paths)."""
    if not getattr(sys, "frozen", False):
        return []
    ignored = []
    if explicit:
        ignored.append(f"--config {explicit}")
    if os.environ.get("CURWORK_CONFIG"):
        ignored.append(f"CURWORK_CONFIG={os.environ['CURWORK_CONFIG']}")
    return ignored


def load_settings(explicit: str | None = None, strict: bool = True) -> Settings:
    """The laptop's admin settings. The file may only hold what CurWork needs to sign in (LOCAL_KEYS);
    everything else comes from Parameter Store after sign-in. strict=False (the admin settings app only)
    drops other settings instead of refusing the file, so an older file can still be copied to AWS."""
    if not getattr(sys, "frozen", False):
        # A settings file someone names on purpose must exist. Quietly falling back to a different
        # file would run CurWork against settings they didn't choose (NIST SP 800-53 CM-6).
        named = [(f"--config {explicit}", explicit)] if explicit else []
        if os.environ.get("CURWORK_CONFIG"):
            named.append((f"CURWORK_CONFIG={os.environ['CURWORK_CONFIG']}", os.environ["CURWORK_CONFIG"]))
        for how, value in named:
            if not Path(value).is_file():
                raise CurWorkError(f"The settings file you named ({how}) doesn't exist. Check the path and try again.")
    path = next((p for p in candidate_config_paths(explicit) if p.is_file()), None)
    if path is None:
        looked = "\n".join(str(p) for p in candidate_config_paths(explicit))
        raise CurWorkError(
            f"Can't find {CONFIG_FILE_NAME}. Ask your admin for it and put it in one of these places:\n{looked}"
        )
    try:
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            raise CurWorkError(f"{path} is too large to be a CurWork settings file.")
        data = json.loads(path.read_text(encoding="utf-8-sig"))  # utf-8-sig: Notepad may add a BOM
    except json.JSONDecodeError as e:
        raise CurWorkError(
            f"{path} isn't valid JSON (line {e.lineno}): {e.msg}. "
            "Tip: in Windows paths use double backslashes (C:\\\\CurWork) or forward slashes (C:/CurWork)."
        ) from e
    except OSError as e:
        raise CurWorkError(f"Can't read {path}: {e}") from e
    if not isinstance(data, dict):
        raise CurWorkError(f"{path} must contain a JSON object ({{ ... }}).")
    local_managed = sorted(k for k in data if not k.startswith("_") and k in MANAGED_KEYS)
    if local_managed and strict:
        raise CurWorkError(
            f"{path} can only hold the settings CurWork needs to sign in. These settings are kept in AWS "
            f"Parameter Store instead, so they can't be in this file: {', '.join(local_managed)}. "
            "Ask your admin to remove them. The CurWork admin settings app can copy them to AWS first.")
    if not str(data.get("settings_parameter") or "").strip():
        data = {**data, "settings_parameter": DEFAULT_PARAMETER}
    try:
        settings = settings_from_dict(data, source_path=path)
        settings.ignored_config_overrides = ignored_config_overrides(explicit)
        return settings
    except CurWorkError:
        raise
    except (TypeError, ValueError, AttributeError) as e:
        raise CurWorkError(f"A setting in {path} has the wrong type: {e}") from e


# Managed settings (NIST SP 800-53 CM-5, CM-6, AU-12). Everything except the sign-in settings comes only
# from an AWS Systems Manager Parameter Store parameter (/curwork/admin-settings unless the laptop file
# names another). Billers' AWS permissions can read it but not change it, so only the AWS admin role can
# change where data goes, where it is kept on the laptop, or how it is protected. AWS keeps every version
# and records who changed it. The laptop file holds only what CurWork needs before sign-in (LOCAL_KEYS):
# how to sign in, the Region, the FIPS switch and the use notice shown before sign-in.
DEFAULT_PARAMETER = "/curwork/admin-settings"
LOCAL_KEYS = ("aws_profile", "region", "use_fips_endpoint", "aws_cli_path", "login_banner",
              "settings_parameter", "sso")
MANAGED_KEYS = tuple(k for k in DEFAULT_CONFIG if k not in LOCAL_KEYS)
_PARAMETER_NAME = re.compile(r"^/[A-Za-z0-9_.\-/]{1,1000}$")
MAX_PARAMETER_BYTES = 4096   # the Standard tier's limit for one parameter value


def validate_managed(managed: dict) -> dict:
    """Check a managed settings object before it's saved to Parameter Store. Returns it unchanged."""
    if not isinstance(managed, dict):
        raise CurWorkError("The settings kept in AWS must be a JSON object ({ ... }).")
    unknown = sorted(k for k in managed if not k.startswith("_") and k not in MANAGED_KEYS)
    if unknown:
        raise CurWorkError(f"These settings can't be kept in AWS: {', '.join(unknown)}. "
                           f"They stay in {CONFIG_FILE_NAME} on each laptop.")
    if len(json.dumps(managed, indent=2).encode("utf-8")) > MAX_PARAMETER_BYTES:
        raise CurWorkError("The settings are too large to keep in AWS Parameter Store (the limit is 4 KB).")
    try:
        settings_from_dict({}, managed=managed)
    except (TypeError, ValueError, AttributeError) as e:
        raise CurWorkError(f"A managed setting has the wrong type: {e}") from e
    return managed


def parse_managed(value: str) -> dict:
    if len(value.encode("utf-8")) > MAX_PARAMETER_BYTES:
        raise CurWorkError("The admin settings in Parameter Store are too large to be CurWork settings.")
    try:
        managed = json.loads(value)
    except json.JSONDecodeError as e:
        raise CurWorkError(f"The admin settings in Parameter Store aren't valid JSON (line {e.lineno}): {e.msg}. "
                           "Ask your admin to fix them with the CurWork admin settings app.") from e
    if not isinstance(managed, dict):
        raise CurWorkError("The admin settings in Parameter Store must be a JSON object ({ ... }).")
    return managed


def read_managed_settings(local: Settings, ssm) -> Settings:
    """Combine the local settings with the managed settings read from Parameter Store through ssm."""
    try:
        param = ssm.get_parameter(Name=local.settings_parameter)["Parameter"]
    except bexc.ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ParameterNotFound":
            raise CurWorkError(f"CurWork's admin settings aren't in AWS Parameter Store yet "
                               f"({local.settings_parameter}). Ask your admin.") from None
        raise
    managed = parse_managed(param["Value"])
    extra = sorted(k for k in managed if not k.startswith("_") and k not in MANAGED_KEYS)
    if extra:
        log.warning("Ignored %s in Parameter Store: these settings stay in each laptop's %s.",
                    ", ".join(extra), CONFIG_FILE_NAME)
    try:
        s = settings_from_dict(local.local_data, source_path=local.source_path, managed=managed)
    except (TypeError, ValueError, AttributeError) as e:
        raise CurWorkError(f"A setting in Parameter Store has the wrong type: {e}") from e
    s.ignored_config_overrides = list(local.ignored_config_overrides)
    label = str(managed.get("_version") or "").strip()
    s.admin_version = f"{label} (Parameter Store version {param.get('Version', '?')})".strip()
    log.info("Admin settings read from Parameter Store: %s, version %s.", local.settings_parameter, param.get("Version"))
    return s


def settings_from_dict(data: dict, source_path: Path | None = None, managed: dict | None = None) -> Settings:
    """Build Settings from the local admin settings (data) and, once read, the managed settings."""
    local = data
    parameter = str(data.get("settings_parameter") or "").strip()
    if parameter and not _PARAMETER_NAME.match(parameter):
        raise CurWorkError('"settings_parameter" must be a Parameter Store name such as /curwork/admin-settings.')
    if managed is not None:
        data = {**{k: v for k, v in data.items() if k in LOCAL_KEYS},
                **{k: v for k, v in managed.items() if k in MANAGED_KEYS or k == "_version"}}
    elif parameter:
        data = {k: v for k, v in data.items() if k in LOCAL_KEYS}   # managed keys come from AWS only
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in data.items():
        if k.startswith("_"):
            continue  # comment keys
        if k == "sso" and isinstance(v, dict):
            merged["sso"].update(v)
        else:
            merged[k] = v

    bucket = str(merged["bucket"]).strip()
    waiting_for_managed = bool(parameter) and managed is None
    if (not bucket or bucket.upper().startswith("CHANGE")) and not waiting_for_managed:
        where = "the settings kept in AWS Parameter Store" if managed is not None else CONFIG_FILE_NAME
        raise CurWorkError(f"The admin settings don't name an S3 bucket yet. Set \"bucket\" in {where}.")

    stages = {str(k): _norm_prefix(v) for k, v in dict(merged["output_stages"]).items() if _norm_prefix(v)}
    if not stages:
        raise CurWorkError("The admin settings file needs at least one entry in \"output_stages\".")
    roots = [_norm_prefix(r) for r in merged["browse_roots"]] or [""]
    for r in roots:
        for s in stages.values():
            if r and (s.startswith(r) or r.startswith(s)):
                raise CurWorkError(
                    f"Browse root '{r}' and output stage '{s}' overlap. Inputs and outputs must use separate prefixes."
                )
    default_stage = merged["default_stage"] if merged["default_stage"] in stages else next(iter(stages))
    location = str(merged.get("user_settings_location") or "tool_folder").strip().lower()
    if location not in ("tool_folder", "work_folder"):
        raise CurWorkError('"user_settings_location" must be "tool_folder" or "work_folder".')
    for key in ("work_dir", "aws_cli_path"):
        if re.search(r"[\x00-\x1f]", str(merged.get(key) or "")):
            # e.g. "C:\new" in JSON silently becomes "C:" + newline + "ew"
            raise CurWorkError(
                f"The {key} setting contains a hidden control character. In Windows paths use double "
                "backslashes (C:\\\\CurWork) or forward slashes (C:/CurWork)."
            )

    return Settings(
        aws_profile=str(merged["aws_profile"]).strip(),
        region=str(merged["region"]).strip(),
        bucket=bucket,
        use_fips_endpoint=bool(merged["use_fips_endpoint"]),
        kms_key_id=str(merged["kms_key_id"] or "").strip(),
        browse_roots=roots,
        output_stages=stages,
        default_stage=default_stage,
        log_prefix=_norm_prefix(merged["log_prefix"]) or "logs/",
        work_dir=_expand_work_dir(str(merged["work_dir"])),
        upload_extensions=[e.lower() if e.startswith(".") else "." + e.lower() for e in merged["upload_extensions"]],
        large_download_warning_mb=int(merged["large_download_warning_mb"]),
        max_concurrency=min(32, max(1, int(merged["max_concurrency"]))),
        aws_cli_path=str(merged.get("aws_cli_path") or "").strip(),
        login_banner=str(merged.get("login_banner") or "").strip(),
        sso=dict(merged["sso"]),
        source_path=source_path,
        user_settings_location=location,
        admin_version=str(data.get("_version") or "").strip(),
        settings_parameter=parameter,
        managed_loaded=managed is not None,
        local_data=dict(local),
    )


# --------------------------------------------------------------------------
# User preferences (unprotected)
#
# The admin settings file is the protected part: bucket, folders, encryption,
# sign-in, logging. The user settings file holds only the harmless preferences
# below. Any other key in it is ignored, so it can never change where data goes
# or how it is protected (NIST SP 800-53 CM-5, CM-6). Who may read or write
# each file is decided by file permissions at install time.
# --------------------------------------------------------------------------

USER_PREF_KEYS = ("remember_result_type", "last_result_type", "recent_folders", "recent_limit",
                  "pinned_folders", "window_geometry", "column_widths")
MAX_RECENT = 25
MAX_PINNED = 25
_GEOMETRY = re.compile(r"^(\d{2,5})x(\d{2,5})\+(-?\d{1,5})\+(-?\d{1,5})$")
_COLUMN_KEY = re.compile(r"^[A-Za-z_]{1,20}\.[#A-Za-z0-9_]{1,20}$")


def tool_folder() -> Path:
    """The folder the tool runs from: next to CurWork.exe, next to CurWork.app on a Mac, or next to
    curwork.py when run from source. Settings files never go inside the .app bundle: changing files
    there breaks its code signature (Apple's bundle rules)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents" \
                and exe.parent.parent.parent.suffix == ".app":
            return exe.parent.parent.parent.parent
        return exe.parent
    return Path(__file__).resolve().parent


def _clean_folder(value) -> str:
    """A customer/month folder such as 'agency-a/2026-10/', or '' if it isn't a safe relative path."""
    folder = _norm_prefix(str(value or ""))
    if not folder:
        return ""
    try:
        safe_relative_path(folder.rstrip("/"))
    except CurWorkError:
        return ""
    return folder


@dataclass
class UserPrefs:
    remember_result_type: bool = True
    last_result_type: str = ""
    recent_folders: list[str] = field(default_factory=list)
    recent_limit: int = 10
    pinned_folders: list[str] = field(default_factory=list)
    window_geometry: str = ""
    column_widths: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in USER_PREF_KEYS}

    def add_recent(self, folder: str) -> bool:
        folder = _clean_folder(folder)
        if not folder or self.recent_limit <= 0:
            return False
        self.recent_folders = [folder] + [f for f in self.recent_folders if f != folder]
        del self.recent_folders[self.recent_limit:]
        return True

    def add_pinned(self, prefix: str) -> bool:
        prefix = _norm_prefix(prefix)
        if not prefix or prefix in self.pinned_folders or len(self.pinned_folders) >= MAX_PINNED:
            return False
        self.pinned_folders.append(prefix)
        return True


def prefs_from_dict(data: dict, settings: Settings | None = None) -> tuple[UserPrefs, list[str]]:
    """Build preferences from a user file. Returns the preferences and the keys that were ignored."""
    ignored = sorted(k for k in data if not str(k).startswith("_") and k not in USER_PREF_KEYS)
    p = UserPrefs()
    if isinstance(data.get("remember_result_type"), bool):
        p.remember_result_type = data["remember_result_type"]
    if isinstance(data.get("last_result_type"), str):
        p.last_result_type = data["last_result_type"][:100]
    limit = data.get("recent_limit")
    if isinstance(limit, int) and not isinstance(limit, bool):
        p.recent_limit = min(MAX_RECENT, max(0, limit))
    recent = data.get("recent_folders")
    if isinstance(recent, list):
        seen: list[str] = []
        for f in recent:
            f = _clean_folder(f) if isinstance(f, str) else ""
            if f and f not in seen:
                seen.append(f)
        p.recent_folders = seen[:p.recent_limit]
    pinned = data.get("pinned_folders")
    if isinstance(pinned, list):
        roots = settings.browse_roots if settings else None
        keep: list[str] = []
        for f in pinned:
            f = _norm_prefix(f) if isinstance(f, str) else ""
            if not f or f in keep or not _clean_folder(f):
                continue
            if roots is not None and not any(f.startswith(r) for r in roots):
                continue  # only folders billers are allowed to browse
            keep.append(f)
        p.pinned_folders = keep[:MAX_PINNED]
    geo = data.get("window_geometry")
    if isinstance(geo, str) and _GEOMETRY.match(geo):
        p.window_geometry = geo
    widths = data.get("column_widths")
    if isinstance(widths, dict):
        p.column_widths = {k: min(1200, max(30, v)) for k, v in widths.items()
                           if isinstance(k, str) and _COLUMN_KEY.match(k)
                           and isinstance(v, int) and not isinstance(v, bool)}
    return p, ignored


def user_settings_candidates(settings: Settings) -> list[Path]:
    in_work = settings.work_dir / USER_SETTINGS_FILE_NAME
    if settings.user_settings_location == "work_folder":
        return [in_work]
    return [tool_folder() / USER_SETTINGS_FILE_NAME, in_work]


def _folder_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".curwork-write-test-", delete=True):
            pass
        return True
    except OSError:
        return False


class UserSettingsStore:
    """Reads and writes the user's preferences. Never raises on a bad or missing file: it falls back to defaults."""

    def __init__(self, settings: Settings, candidates: list[Path] | None = None):
        self.settings = settings
        self.candidates = candidates or user_settings_candidates(settings)
        # Save where we're allowed to write; if the tool folder is locked down, use the next place.
        self.path = next((c for c in self.candidates if _folder_writable(c.parent)), self.candidates[-1])
        self.fallback_used = self.path != self.candidates[0]
        self.read_from: Path | None = None
        self.ignored: list[str] = []

    def load(self) -> UserPrefs:
        # Read the file we save to; if there isn't one yet, any earlier copy (for example one an admin pre-seeded).
        self.read_from = self.path if self.path.is_file() else next((c for c in self.candidates if c.is_file()), None)
        self.ignored = []
        if self.read_from is None:
            return UserPrefs()
        try:
            if self.read_from.stat().st_size > MAX_SETTINGS_BYTES:
                raise ValueError("file is too large")
            data = json.loads(self.read_from.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            log.warning("Couldn't read your settings file %s (%s). Using default preferences.", self.read_from, e)
            return UserPrefs()
        if not isinstance(data, dict):
            log.warning("Your settings file %s isn't a JSON object. Using default preferences.", self.read_from)
            return UserPrefs()
        prefs, self.ignored = prefs_from_dict(data, self.settings)
        if self.ignored:
            log.warning("Ignored in your settings file (only the admin can set these, or they aren't preferences): %s",
                        ", ".join(self.ignored))
        return prefs

    def save(self, prefs: UserPrefs) -> None:
        payload = {
            "_about": ("CurWork user preferences. Only the keys below are read. Admin settings "
                       f"(bucket, folders, encryption, sign-in) can't be changed here; they live in {CONFIG_FILE_NAME}."),
            "_saved": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "_saved_by": current_user(),
            **prefs.to_dict(),
        }
        tmp: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # A new, uniquely named temp file (never an existing file or link), then an atomic rename.
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".curwork-user-", suffix=".tmp")
            tmp = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, indent=2))
            os.replace(tmp, self.path)
        except OSError as e:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            raise CurWorkError(f"Couldn't save your preferences to {self.path}: {e.strerror or e}") from e
        self.read_from = self.path


# --------------------------------------------------------------------------
# Friendly error messages
# --------------------------------------------------------------------------

_AUTH_CODES = {
    "ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId", "InvalidToken",
    "UnrecognizedClientException", "TokenRefreshRequired", "SignatureDoesNotMatch",
}
_AUTH_EXC_NAMES = {
    "NoCredentialsError", "SSOTokenLoadError", "UnauthorizedSSOTokenError", "TokenRetrievalError",
    "SSOError", "PendingAuthorizationExpiredError", "CredentialRetrievalError", "PartialCredentialsError",
}
_NETWORK_EXC_NAMES = {
    "EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError", "ConnectionClosedError",
    "ProxyConnectionError", "SSLError", "HTTPClientError",
}


# Plain-English names for the AWS calls CurWork makes, shown when AWS refuses one.
_OPERATION_LABELS = {
    "ListObjectsV2": "listing files in S3 (needs s3:ListBucket)",
    "HeadObject": "reading a file's details in S3 (needs s3:GetObject)",
    "GetObject": "downloading a file from S3 (needs s3:GetObject)",
    "PutObject": "saving a file in S3 (needs s3:PutObject)",
    "CreateMultipartUpload": "starting to save a large file in S3 (needs s3:PutObject)",
    "UploadPart": "saving part of a large file in S3 (needs s3:PutObject)",
    "CompleteMultipartUpload": "finishing saving a large file in S3 (needs s3:PutObject)",
    "GetCallerIdentity": "checking who you're signed in as (sts:GetCallerIdentity)",
    "GetParameter": "reading CurWork's admin settings from Parameter Store (ssm:GetParameter)",
    "PutParameter": "saving CurWork's admin settings to Parameter Store (ssm:PutParameter)",
}


def classify_error(exc: BaseException) -> tuple[str, str]:
    """Return (kind, message). kind is auth, denied, notfound, network, config, cancelled or other."""
    if isinstance(exc, Cancelled):
        return "cancelled", "Stopped."
    if isinstance(exc, CurWorkError):
        return "other", str(exc)
    name = type(exc).__name__
    if isinstance(exc, bexc.ProfileNotFound):
        return "config", (
            "Your AWS sign-in profile isn't set up on this laptop yet. "
            "Click 'Sign in' to set it up, or ask your admin."
        )
    if name in _AUTH_EXC_NAMES:
        return "auth", "You're not signed in, or your sign-in has expired. Click 'Sign in' and try again."
    if isinstance(exc, bexc.ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in _AUTH_CODES:
            return "auth", "Your sign-in has expired. Click 'Sign in' and try again."
        if code in ("AccessDenied", "AccessDeniedException", "AllAccessDisabled") or status == 403:
            op = getattr(exc, "operation_name", "") or "unknown"
            reason = (exc.response.get("Error", {}).get("Message") or "").strip()
            return "denied", (
                "AWS said you don't have permission for that. "
                "If you think you should, send the log to your admin.\n\n"
                f"What AWS refused: {_OPERATION_LABELS.get(op, op)}"
                + (f"\nAWS's reason: {reason[:400]}" if reason and reason != "Forbidden" else "")
            )
        if code in ("NoSuchKey", "404", "NoSuchBucket", "NotFound") or status == 404:
            return "notfound", "That file or folder isn't in S3 (it may have been moved or deleted)."
        return "other", f"AWS error {code}: {exc.response.get('Error', {}).get('Message', '')}".strip()
    if name in _NETWORK_EXC_NAMES:
        return "network", "Can't reach AWS. Check your internet or VPN connection and try again."
    if isinstance(exc, PermissionError):
        return "other", (
            f"Windows won't let the tool use '{getattr(exc, 'filename', '')}'. "
            "If it's open in Excel, close it and try again."
        )
    return "other", f"{name}: {exc}"


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

def is_ignored_name(name: str) -> bool:
    return any(p.match(name) for p in _IGNORE_PATTERNS)


def safe_relative_path(rel: str) -> PurePosixPath:
    """Turn part of an S3 key into a safe relative path for Windows, or raise CurWorkError."""
    rel = rel.replace("\\", "/").strip("/")
    if not rel:
        raise CurWorkError("Empty file name.")
    parts = rel.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise CurWorkError(f"Unsafe path in S3 key: '{rel}'")
        if _WINDOWS_BAD_CHARS.search(part):
            raise CurWorkError(f"'{part}' has characters Windows doesn't allow in file names.")
        if part.endswith((" ", ".")):
            raise CurWorkError(f"'{part}' ends with a space or dot, which Windows doesn't allow.")
        if part.split(".")[0].lower() in _WINDOWS_RESERVED:
            raise CurWorkError(f"'{part}' is a reserved name on Windows.")
    return PurePosixPath(*parts)


def local_path_for(base: Path, rel: PurePosixPath) -> Path:
    target = (base / Path(*rel.parts)).resolve()
    base_resolved = base.resolve()
    if base_resolved not in target.parents and target != base_resolved:
        raise CurWorkError(f"Unsafe path: {rel}")
    return target


def strip_root(key: str, roots: Iterable[str]) -> str:
    for r in sorted(roots, key=len, reverse=True):
        if r and key.startswith(r):
            return key[len(r):]
    return key


def context_for(key_or_prefix: str, roots: Iterable[str]) -> str:
    """'converted/agency-a/2026-10/file.xlsx' -> 'agency-a/2026-10/'."""
    rel = strip_root(key_or_prefix, roots)
    if not rel.endswith("/"):
        rel = rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""
    return rel


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def sync_folder_warning(path: Path) -> str | None:
    """Warn if the work folder sits inside a cloud-sync folder (copies would leave the laptop)."""
    parts = [x.lower() for x in Path(path).parts]
    for marker in ("onedrive", "box", "dropbox", "google drive", "icloud drive"):
        if any(part == marker or part.startswith(marker + " ") or part.startswith(marker + "-") for part in parts):
            return (f"The work folder {path} looks like it's inside a {marker.title()} sync folder. "
                    "Files would be copied off the laptop. Ask your admin to change work_dir.")
    return None


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


# --------------------------------------------------------------------------
# Work folder (In / Out / Logs)
# --------------------------------------------------------------------------

@dataclass
class OutFile:
    path: Path
    rel: str
    size: int
    status: str  # "Not saved in S3", "Saved in S3", "Changed since saved", "Open in Excel"
    s3_key: str = ""


class WorkArea:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.in_dir = self.root / "In"
        self.out_dir = self.root / "Out"
        self.log_dir = self.root / "Logs"
        self.state_file = self.root / "state.json"
        self._lock = threading.Lock()

    def ensure(self) -> None:
        for d in (self.in_dir, self.out_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- state -----------------------------------------------------------
    def load_state(self) -> dict:
        with self._lock:
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError
            except (FileNotFoundError, ValueError):
                data = {}
        data.setdefault("uploaded", {})
        data.setdefault("downloaded", {})
        data.setdefault("context", "")
        return data

    def save_state(self, state: dict) -> None:
        with self._lock:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
            os.replace(tmp, self.state_file)

    def set_context(self, context: str) -> None:
        st = self.load_state()
        st["context"] = context
        self.save_state(st)

    def record_download(self, path: Path) -> None:
        rel = path.relative_to(self.in_dir).as_posix()
        st = self.load_state()
        s = path.stat()
        st["downloaded"][rel] = {"size": s.st_size, "mtime": s.st_mtime}
        self.save_state(st)

    def input_changed(self, path: Path) -> bool:
        """True if a file in In was changed after it was downloaded (or wasn't downloaded at all)."""
        try:
            rel = path.relative_to(self.in_dir).as_posix()
        except ValueError:
            return False
        rec = self.load_state()["downloaded"].get(rel)
        if not path.exists():
            return False
        s = path.stat()
        return not rec or rec["size"] != s.st_size or abs(rec["mtime"] - s.st_mtime) >= 0.001

    def in_extras(self) -> list[tuple[Path, str, str]]:
        """
        Files in In that weren't downloaded by CurWork, or were changed after download.
        These are often results saved to the wrong folder, so they'd be lost at clean-up.
        Returns (path, rel, "new" | "changed").
        """
        downloaded = self.load_state()["downloaded"]
        extras = []
        for p, rel in self.in_files():
            rec = downloaded.get(rel)
            s = p.stat()
            if not rec:
                extras.append((p, rel, "new"))
            elif rec["size"] != s.st_size or abs(rec["mtime"] - s.st_mtime) >= 0.001:
                extras.append((p, rel, "changed"))
        return extras

    def move_to_out(self, items: list[tuple[Path, str]], strip_prefix: str = "") -> list[str]:
        """
        Move files from In to Out. Never overwrites: adds ' (2)' etc. Returns new rel paths.
        strip_prefix (the customer/month folder, e.g. 'agency-a/2026-10/') is removed so the file
        doesn't end up under that folder twice once the upload adds it back.
        """
        moved = []
        for p, rel in items:
            out_rel = rel[len(strip_prefix):] if strip_prefix and rel.startswith(strip_prefix) else rel
            target = self.out_dir / Path(*PurePosixPath(out_rel).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            n = 2
            while target.exists():
                target = target.with_name(f"{Path(out_rel).stem} ({n}){Path(out_rel).suffix}")
                n += 1
            shutil.move(str(p), str(target))
            moved.append(target.relative_to(self.out_dir).as_posix())
            log.info("Moved %s from In to Out as %s", rel, moved[-1])
        return moved

    def record_upload(self, rel: str, path: Path, key: str) -> None:
        st = self.load_state()
        s = path.stat()
        st["uploaded"][rel] = {
            "size": s.st_size,
            "mtime": s.st_mtime,
            "key": key,
            "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        }
        self.save_state(st)

    # ---- listing ---------------------------------------------------------
    @staticmethod
    def _walk(base: Path) -> list[tuple[Path, str]]:
        out: list[tuple[Path, str]] = []
        if not base.exists():
            return out
        for p in sorted(base.rglob("*")):
            if p.is_file() and not is_ignored_name(p.name):
                out.append((p, p.relative_to(base).as_posix()))
        return out

    def in_files(self) -> list[tuple[Path, str]]:
        return self._walk(self.in_dir)

    def out_files(self) -> list[OutFile]:
        state = self.load_state()["uploaded"]
        result = []
        for p, rel in self._walk(self.out_dir):
            s = p.stat()
            rec = state.get(rel)
            if is_open_elsewhere(p):
                status = "Open in Excel"
            elif rec and rec["size"] == s.st_size and abs(rec["mtime"] - s.st_mtime) < 0.001:
                status = "Saved in S3"
            elif rec:
                status = "Changed since saved"
            else:
                status = "Not saved in S3"
            result.append(OutFile(p, rel, s.st_size, status, rec["key"] if rec else ""))
        return result

    def pending_out(self) -> list[OutFile]:
        return [f for f in self.out_files() if f.status != "Saved in S3"]

    def leftovers(self) -> tuple[int, int, int]:
        """(files in In, Out files not yet uploaded, all files in Out)."""
        out = self.out_files()
        return len(self.in_files()), sum(1 for f in out if f.status != "Saved in S3"), len(out)

    # ---- cleanup ---------------------------------------------------------
    def clean(self) -> list[str]:
        """Delete everything in In and Out. Returns files that couldn't be deleted (usually open in Excel)."""
        skipped: list[str] = []

        def _on_error(func, path, exc_info=None):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                skipped.append(str(path))

        for d in (self.in_dir, self.out_dir):
            if not d.exists():
                continue
            for child in d.iterdir():
                try:
                    if child.is_dir() and not child.is_symlink():
                        if sys.version_info >= (3, 12):
                            shutil.rmtree(child, onexc=_on_error)
                        else:  # pragma: no cover
                            shutil.rmtree(child, onerror=_on_error)
                    else:
                        try:
                            child.unlink()
                        except PermissionError:
                            _on_error(os.unlink, str(child))
                except Exception:
                    skipped.append(str(child))
        st = self.load_state()
        st["uploaded"] = {}
        st["downloaded"] = {}
        st["context"] = ""
        self.save_state(st)
        if skipped:
            log.warning("Couldn't delete %d file(s), probably open in Excel: %s", len(skipped), skipped)
        else:
            log.info("Work folder cleaned: In and Out are empty.")
        return skipped


def _write_blocked(path: Path) -> bool:
    """Windows only: True if another program holds the file so we can't open it for writing."""
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def is_open_elsewhere(path: Path) -> bool:
    """
    True if the file looks open in Excel.
    On Windows the real test is whether Excel holds the file. An Excel owner file (~$name)
    only counts if Excel is still holding it too; owner files left behind after a crash are ignored.
    On other systems (tests only) an owner file counts as open.
    """
    if not path.exists():
        return False
    owner = path.parent / f"~${path.name}"
    if os.name == "nt":
        if _write_blocked(path):
            return True
        return owner.exists() and _write_blocked(owner)
    return owner.exists()


# --------------------------------------------------------------------------
# AWS sign-in
# --------------------------------------------------------------------------

def find_aws_cli(configured: str = "") -> str | None:
    """
    Find the AWS CLI without ever picking up an aws.exe from the current folder
    (Windows searches there by default, which allows binary planting).
    Order: admin-set path, standard install folders, then PATH with the current folder excluded.
    """
    if configured:
        return configured if Path(configured).is_file() else None
    candidates = []
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Amazon" / "AWSCLIV2" / "aws.exe")
    for c in candidates:
        if c.is_file():
            return str(c)
    if os.name == "nt":
        os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"
    found = shutil.which("aws")
    if found and Path(found).resolve().parent == Path.cwd().resolve():
        return None
    return str(Path(found).resolve()) if found else None


def aws_config_path() -> Path:
    return Path(os.environ.get("AWS_CONFIG_FILE") or Path.home() / ".aws" / "config")


def profile_exists(profile: str) -> bool:
    cfg = aws_config_path()
    if cfg.exists():
        text = cfg.read_text(encoding="utf-8", errors="replace")
        if re.search(rf"^\[\s*profile\s+{re.escape(profile)}\s*\]\s*$", text, re.M):
            return True
        if profile == "default" and re.search(r"^\[\s*default\s*\]\s*$", text, re.M):
            return True
    try:
        return profile in boto3.Session().available_profiles
    except Exception:
        return False


def ensure_sso_profile(settings: Settings) -> bool:
    """
    If the AWS profile is missing and the admin settings file has SSO details, append the
    profile to ~/.aws/config. Never rewrites existing content. Returns True if added.
    """
    profile = settings.aws_profile
    sso = settings.sso or {}
    needed = ("session_name", "start_url", "sso_region", "account_id", "role_name")
    if not profile or profile_exists(profile) or not all(str(sso.get(k, "")).strip() for k in needed):
        return False
    cfg_path = aws_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    existing = cfg_path.read_text(encoding="utf-8", errors="replace") if cfg_path.exists() else ""
    block = []
    if not re.search(rf"^\[\s*sso-session\s+{re.escape(sso['session_name'])}\s*\]", existing, re.M):
        block += [
            f"[sso-session {sso['session_name']}]",
            f"sso_start_url = {sso['start_url']}",
            f"sso_region = {sso['sso_region']}",
            "sso_registration_scopes = sso:account:access",
            "",
        ]
    block += [
        f"[profile {profile}]",
        f"sso_session = {sso['session_name']}",
        f"sso_account_id = {sso['account_id']}",
        f"sso_role_name = {sso['role_name']}",
        f"region = {settings.region}",
    ]
    if settings.use_fips_endpoint:
        block.append("use_fips_endpoint = true")
    block.append("")
    prefix = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    with open(cfg_path, "a", encoding="utf-8") as fh:
        fh.write(prefix + "\n".join(block))
    log.info("Added AWS profile '%s' to %s", profile, cfg_path)
    return True


def run_sso_login(profile: str, on_line: Callable[[str], None] | None = None, timeout: int = 900,
                  cli_path: str = "") -> None:
    """Run 'aws sso login'. The CLI opens the browser; we stream its output to on_line."""
    aws = find_aws_cli(cli_path)
    if not aws:
        raise CurWorkError(
            "The AWS CLI isn't installed on this laptop. Ask IT to install AWS CLI version 2."
        )
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    proc = subprocess.Popen(
        [aws, "sso", "login", "--profile", profile],
        stdin=subprocess.DEVNULL,  # a windowed exe has no console; all three handles must be set
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
        cwd=str(Path.home()),
    )
    timer = threading.Timer(timeout, proc.kill)  # reading output blocks, so enforce the timeout here
    timer.start()
    try:
        if proc.stdout is None:
            raise CurWorkError("Couldn't read the output of the AWS CLI sign-in.")
        for line in proc.stdout:
            line = line.rstrip()
            if line and on_line:
                on_line(line)
        rc = proc.wait()
    finally:
        timed_out = not timer.is_alive()
        timer.cancel()
    if timed_out and rc != 0:
        raise CurWorkError("Sign-in timed out. Try again.")
    if rc != 0:
        raise CurWorkError("Sign-in didn't finish. Try again, or send the log to your admin.")


# --------------------------------------------------------------------------
# S3
# --------------------------------------------------------------------------

@dataclass
class S3File:
    key: str
    size: int
    modified: _dt.datetime | None


class _Progress:
    """Thread-safe byte counter for boto3 callbacks. Raises Cancelled when asked to stop."""

    def __init__(self, total: int, on_progress: Callable[[int, int], None] | None, cancel: threading.Event | None):
        self.total = total
        self.done = 0
        self._lock = threading.Lock()
        self._cb = on_progress
        self._cancel = cancel

    def __call__(self, n: int) -> None:
        if self._cancel is not None and self._cancel.is_set():
            raise Cancelled()
        with self._lock:
            self.done += n
            done = self.done
        if self._cb:
            self._cb(done, self.total)


def friendly_identity(arn: str) -> str:
    """arn:aws:sts::123:assumed-role/AWSReservedSSO_CUR_Biller_0123456789abcdef/jane@x.com -> jane@x.com (CUR_Biller)"""
    m = re.match(r".*:assumed-role/AWSReservedSSO_(.+)_[0-9a-f]{16}/(.+)$", arn) or \
        re.match(r".*:assumed-role/([^/]+)/(.+)$", arn)
    return f"{m.group(2)} ({m.group(1)})" if m else arn


class S3Service:
    def __init__(self, settings: Settings, session: boto3.Session | None = None):
        self.s = settings
        self._injected_session = session
        self._session: boto3.Session | None = None
        self._client = None
        self._sts = None

    # ---- clients ---------------------------------------------------------
    def reset(self) -> None:
        """Forget cached credentials (call after signing in again)."""
        self._session = None
        self._client = None
        self._sts = None

    def _boto_config(self) -> BotoConfig:
        return BotoConfig(
            region_name=self.s.region,
            use_fips_endpoint=self.s.use_fips_endpoint,
            retries={"max_attempts": 8, "mode": "adaptive"},
            connect_timeout=15,
            read_timeout=120,
            user_agent_extra=f"CurWork/{VERSION}",
        )

    def session(self) -> boto3.Session:
        if self._injected_session is not None:
            return self._injected_session
        if self._session is None:
            self._session = boto3.Session(profile_name=self.s.aws_profile or None, region_name=self.s.region)
        return self._session

    @property
    def client(self):
        if self.s.needs_managed_settings:   # never use S3 with settings that didn't come from Parameter Store
            raise CurWorkError("CurWork hasn't read its admin settings from AWS yet. Click 'Sign in' and try again.")
        if self._client is None:
            self._client = self.session().client("s3", config=self._boto_config())
        return self._client

    def whoami(self) -> str:
        if self._sts is None:
            self._sts = self.session().client("sts", config=self._boto_config())
        return friendly_identity(self._sts.get_caller_identity()["Arn"])

    def load_managed_settings(self) -> Settings:
        """Read the managed admin settings from Parameter Store (after sign-in) and return the full Settings.
        Fails closed: if the parameter can't be read, CurWork doesn't fall back to anything else."""
        return read_managed_settings(self.s, self.session().client("ssm", config=self._boto_config()))

    def _transfer_config(self) -> TransferConfig:
        return TransferConfig(
            multipart_threshold=64 * 1024 * 1024,
            multipart_chunksize=64 * 1024 * 1024,
            max_concurrency=self.s.max_concurrency,
            use_threads=True,
        )

    # ---- listing ---------------------------------------------------------
    def list_level(self, prefix: str) -> tuple[list[str], list[S3File]]:
        folders: list[str] = []
        files: list[S3File] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.s.bucket, Prefix=prefix, Delimiter="/"):
            folders += [cp["Prefix"] for cp in page.get("CommonPrefixes", [])]
            for obj in page.get("Contents", []):
                if obj["Key"] == prefix or obj["Key"].endswith("/"):
                    continue
                files.append(S3File(obj["Key"], obj["Size"], obj.get("LastModified")))
        return folders, files

    def list_recursive(self, prefix: str) -> list[S3File]:
        files: list[S3File] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.s.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith("/"):
                    files.append(S3File(obj["Key"], obj["Size"], obj.get("LastModified")))
        return files

    def expand_selection(self, selection: Iterable[str]) -> list[S3File]:
        """Selection items are file keys or folder prefixes (ending in '/')."""
        seen: dict[str, S3File] = {}
        for item in selection:
            if item == "" or item.endswith("/"):
                for f in self.list_recursive(item):
                    seen.setdefault(f.key, f)
            else:
                head = self.client.head_object(Bucket=self.s.bucket, Key=item)
                seen.setdefault(item, S3File(item, head["ContentLength"], head.get("LastModified")))
        return sorted(seen.values(), key=lambda f: f.key)

    def exists(self, key: str) -> bool:
        """
        True if the exact key is already in S3. Uses a listing, not HeadObject: the biller permission set
        grants s3:ListBucket only for the CurWork folders (an s3:prefix condition), and with that kind of
        grant S3 may answer a HeadObject on a missing key with 403 instead of 404.
        """
        resp = self.client.list_objects_v2(Bucket=self.s.bucket, Prefix=key, MaxKeys=1)
        return any(obj.get("Key") == key for obj in resp.get("Contents", []))

    # ---- download --------------------------------------------------------
    def download(
        self,
        files: list[S3File],
        dest_root: Path,
        on_progress: Callable[[int, int], None] | None = None,
        on_file: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
        replace_local: Callable[[Path], bool] | None = None,
        on_downloaded: Callable[[Path], None] | None = None,
    ) -> list[Path]:
        """
        replace_local(target) is asked when a local copy exists; return False to keep it.
        on_downloaded(path) is called after each file lands.
        """
        # Check every path before downloading anything. With one browse root the root is dropped
        # (In/agency-a/2026-10/...); with several, it's kept so files from different roots can't collide.
        plan: list[tuple[S3File, Path]] = []
        for f in files:
            src = strip_root(f.key, self.s.browse_roots) if len(self.s.browse_roots) == 1 else f.key
            rel = safe_relative_path(src)
            plan.append((f, local_path_for(dest_root, rel)))

        total = sum(f.size for f, _ in plan)
        progress = _Progress(total, on_progress, cancel)
        done: list[Path] = []
        for f, target in plan:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if target.exists():
                if is_open_elsewhere(target):
                    raise CurWorkError(f"'{target.name}' is open in Excel. Close it before downloading it again.")
                if replace_local is not None and not replace_local(target):
                    log.info("Kept your local copy of %s", target.name)
                    progress(f.size)
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            if on_file:
                on_file(f.key)
            try:
                self.client.download_file(
                    self.s.bucket, f.key, str(part), Callback=progress, Config=self._transfer_config()
                )
                got = part.stat().st_size
                if got != f.size:
                    raise CurWorkError(f"Download of {f.key} was incomplete ({got} of {f.size} bytes).")
                os.replace(part, target)
            finally:
                if part.exists():
                    try:
                        part.unlink()
                    except OSError:
                        pass
            log.info("Downloaded s3://%s/%s -> %s (%s)", self.s.bucket, f.key, target, human_size(f.size))
            if on_downloaded:
                on_downloaded(target)
            done.append(target)
        return done

    # ---- upload ----------------------------------------------------------
    def check_destination(self, dest_prefix: str) -> str:
        dest = _norm_prefix(dest_prefix)
        if not dest:
            raise CurWorkError("Pick where in S3 the results should go.")
        if not any(dest.startswith(p) for p in self.s.allowed_upload_prefixes):
            allowed = ", ".join(self.s.allowed_upload_prefixes)
            raise CurWorkError(f"Results can only go under these S3 folders: {allowed}")
        try:
            safe_relative_path(dest)  # same safety rules as file names
        except CurWorkError:
            raise CurWorkError(
                "The customer / month folder can't contain '..', a colon, or characters like < > \" | ? *. "
                "Use something like: agency-a/2026-10"
            ) from None
        return dest

    def _extra_args(self, source_name: str) -> dict:
        extra = {
            "ChecksumAlgorithm": "SHA256",
            "Metadata": {
                "uploaded-by": _ascii(current_user()),
                "source-file": _ascii(source_name)[:200],
                "curwork-version": VERSION,
            },
        }
        if self.s.kms_key_id:
            extra["ServerSideEncryption"] = "aws:kms"
            extra["SSEKMSKeyId"] = self.s.kms_key_id
        return extra

    def upload(
        self,
        items: list[tuple[Path, str]],
        dest_prefix: str,
        on_exists: Callable[[str], str] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        on_file: Callable[[str], None] | None = None,
        on_uploaded: Callable[[Path, str, str], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> list[str]:
        """
        Upload (local_path, relative_path) pairs to dest_prefix + relative_path.
        on_exists(key) returns 'overwrite', 'skip' or 'cancel' when the key is already in S3.
        Returns the keys that were uploaded.
        """
        dest = self.check_destination(dest_prefix)
        plan: list[tuple[Path, str, str]] = []
        for path, rel in items:
            if path.suffix.lower() not in self.s.upload_extensions:
                log.info("Skipped %s (your admin hasn't allowed this file type to be saved in S3)", rel)
                continue
            if is_open_elsewhere(path):
                raise CurWorkError(f"'{path.name}' is still open in Excel. Save and close it, then save it in S3.")
            key = dest + safe_relative_path(rel).as_posix()
            plan.append((path, rel, key))
        if not plan:
            raise CurWorkError("There's nothing in the Out folder to save in S3.")

        total = sum(p.stat().st_size for p, _, _ in plan)
        progress = _Progress(total, on_progress, cancel)
        uploaded: list[str] = []
        for path, rel, key in plan:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if self.exists(key):
                choice = on_exists(key) if on_exists else "skip"
                if choice == "cancel":
                    raise Cancelled()
                if choice != "overwrite":
                    log.info("Skipped %s (already in S3, kept the S3 copy)", key)
                    progress(path.stat().st_size)
                    continue
                log.info("Replacing %s (S3 keeps the old copy if version history is turned on)", key)
            if on_file:
                on_file(key)
            size = path.stat().st_size
            self.client.upload_file(
                str(path), self.s.bucket, key,
                ExtraArgs=self._extra_args(path.name), Callback=progress, Config=self._transfer_config(),
            )
            head = self.client.head_object(Bucket=self.s.bucket, Key=key)
            if head["ContentLength"] != size:
                raise CurWorkError(f"S3 has a different size for {key} than the local file. Save it in S3 again.")
            log.info("Saved %s in s3://%s/%s (%s)", path, self.s.bucket, key, human_size(size))
            if on_uploaded:
                on_uploaded(path, rel, key)
            uploaded.append(key)
        return uploaded

    def upload_log(self, log_file: Path) -> str | None:
        if not log_file.is_file() or log_file.stat().st_size == 0:
            return None
        day = _dt.date.today().isoformat()
        key = f"{self.s.log_prefix}{_ascii(current_user())}/{day}/{log_file.name}"
        extra = self._extra_args(log_file.name)
        self.client.upload_file(str(log_file), self.s.bucket, key, ExtraArgs=extra)
        return key


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

def switch_file_logging(old_file: Path, work: WorkArea) -> Path:
    """Move logging to a new work folder (after the admin's work folder is read from Parameter Store).
    Today's earlier lines move with it, so one log file holds the whole session (NIST SP 800-53 AU-9)."""
    for h in list(log.handlers):
        if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == Path(old_file):
            log.removeHandler(h)
            h.close()
    work.log_dir.mkdir(parents=True, exist_ok=True)
    new_file = work.log_dir / f"curwork-{_dt.date.today().isoformat()}.log"
    if Path(old_file) != new_file and Path(old_file).is_file():
        try:
            with open(new_file, "a", encoding="utf-8") as out:
                out.write(Path(old_file).read_text(encoding="utf-8"))
            Path(old_file).unlink()
        except OSError as e:
            log.warning("Couldn't move today's earlier log lines from %s: %s", old_file, e)
    return setup_file_logging(work)


def setup_file_logging(work: WorkArea, keep_days: int = 14) -> Path:
    work.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = work.log_dir / f"curwork-{_dt.date.today().isoformat()}.log"
    if not any(isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_file for h in log.handlers):
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)  # error details go to the file only
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
    log.setLevel(logging.DEBUG)
    cutoff = _dt.datetime.now().timestamp() - keep_days * 86400
    for old in work.log_dir.glob("curwork-*.log"):
        try:
            if old != log_file and old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass
    return log_file
