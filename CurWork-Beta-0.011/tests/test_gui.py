"""
CurWork Beta 0.011 - DRAFT - For Internal Use (FPT) - window tests - modified by: mbitar

Drives the real CurWork window (tkinter) against a mocked S3 (moto), the way a biller would:
sign-in check, browse, download (small and multipart), upload, refused uploads, the AWS refusal message,
About, Settings, Finish and clean up, and --self-test. One test also enforces CurWork's biller IAM policy
in the mock to check CurWork's calls fit inside it (moto checks actions and resources, not conditions).

Needs a display: on Linux run under xvfb-run; on a Mac the windows flash up briefly.
Skipped when tkinter or a display isn't available.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing",
                  AWS_SESSION_TOKEN="testing", AWS_DEFAULT_REGION="us-east-1")
for var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
    os.environ.pop(var, None)

tk = pytest.importorskip("tkinter")
boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")
from botocore.exceptions import ClientError  # noqa: E402

import curwork  # noqa: E402
import curwork_core as core  # noqa: E402

_REAL_EXISTS = curwork.ExistsDialog

BUCKET = "curwork-test-123456789012-gui"
SMALL = {"converted/agency-a/2026-10/agency-a-cur-2026-10.xlsx": 250_000,
         "converted/agency-a/2026-09/agency-a-cur-2026-09.xlsx": 240_000}
BIG_KEY = "converted/agency-b/2026-10/agency-b-cur-2026-10.xlsx"
BIG_SIZE = 12 * 1024 * 1024   # bigger than the test's multipart threshold, so download uses parts


_ROOT = None


def _session_root():
    """One Tk root for every window test. On macOS, creating a new Tk() after destroying another in the same
    process can crash Python (segmentation fault), so the tests reuse one root, as the real app does."""
    global _ROOT
    if _ROOT is None:
        try:
            _ROOT = tk.Tk(className=curwork.APP_NAME)
        except tk.TclError:
            _ROOT = False
        else:
            curwork.apply_app_icon(_ROOT)
    return _ROOT


pytestmark = pytest.mark.skipif(not _session_root(), reason="no display for tkinter (use xvfb-run on Linux)")


def _reset_root(root, app=None):
    """Close one test's app without destroying the shared root: cancel its timers, remove its widgets."""
    if app is not None:
        app._closed = True
        for after_id in list(app._after_ids.values()):
            try:
                root.after_cancel(after_id)
            except tk.TclError:
                pass
    for w in root.winfo_children():
        w.destroy()
    root.update()


class Dialogs:
    """Records message boxes instead of showing them; answers yes to questions."""

    def __init__(self, monkeypatch):
        self.seen: list[tuple[str, str]] = []
        for name in ("showinfo", "showwarning", "showerror"):
            monkeypatch.setattr(curwork.messagebox, name, self._rec(name))
        monkeypatch.setattr(curwork.messagebox, "askyesno", lambda *a, **k: (self.seen.append(("ask", a[1])), True)[1])
        monkeypatch.setattr(curwork.messagebox, "askyesnocancel", lambda *a, **k: (self.seen.append(("ask", a[1])), True)[1])
        monkeypatch.setattr(curwork.messagebox, "askokcancel", lambda *a, **k: True)
        monkeypatch.setattr(curwork, "ExistsDialog", lambda parent, key: type("D", (), {"result": "overwrite"})())

    def _rec(self, kind):
        return lambda *a, **k: self.seen.append((kind, a[1] if len(a) > 1 else ""))

    def errors(self):
        return [m for k, m in self.seen if k == "showerror"]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    m = moto.mock_aws()
    m.start()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    for key, size in SMALL.items():
        s3.put_object(Bucket=BUCKET, Key=key, Body=os.urandom(size))
    s3.put_object(Bucket=BUCKET, Key=BIG_KEY, Body=os.urandom(BIG_SIZE))
    monkeypatch.setattr(core.S3Service, "_transfer_config", lambda self: core.TransferConfig(
        multipart_threshold=5 * 1024 * 1024, multipart_chunksize=5 * 1024 * 1024, max_concurrency=4))
    monkeypatch.chdir(tmp_path)
    dialogs = Dialogs(monkeypatch)
    settings = core.settings_from_dict({"bucket": BUCKET, "aws_profile": "", "work_dir": str(tmp_path / "CurWork")})
    store = core.UserSettingsStore(settings, candidates=[tmp_path / "prefs.json"])
    monkeypatch.setattr(core, "UserSettingsStore", lambda s, candidates=None: store)
    root = _session_root()
    root.deiconify()
    app = curwork.CurWorkApp(root, settings)

    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    def idle(timeout=60):
        end = time.time() + timeout
        pump(0.3)
        while app.busy and time.time() < end:
            pump(0.1)
        pump(0.3)
        assert not app.busy, "task didn't finish in time"

    def open_folder(iid):
        app.tree.item(iid, open=True)
        app.tree.focus(iid)
        app._on_tree_open()
        idle()

    pump(1.0)
    idle()
    w = type("World", (), dict(s3=s3, app=app, root=root, dialogs=dialogs, pump=pump, idle=idle,
                               open_folder=open_folder, tmp=tmp_path))
    yield w
    _reset_root(root, app)
    m.stop()


def test_startup_title_icon_and_sign_in(world):
    a = world.app
    assert world.root.title() == f"CurWork – {core.RELEASE_LABEL} ({core.STATUS})"
    assert len(getattr(world.root, "_curwork_icons", [])) == 2
    assert "Signed in" in a.who_lbl.cget("text")
    assert "converted/" in a.tree.get_children("")
    assert world.dialogs.errors() == []


def test_browse_and_download_month_folder(world):
    a = world.app
    world.open_folder("converted/agency-a/")
    world.open_folder("converted/agency-a/2026-10/")
    a.tree.selection_set("converted/agency-a/2026-10/")
    a.download_selected()
    world.idle()
    got = {r: p.stat().st_size for p, r in a.work.in_files()}
    assert got == {"agency-a/2026-10/agency-a-cur-2026-10.xlsx": 250_000}
    assert not list(a.work.in_dir.rglob("*.part")), "partial download file left behind"
    assert a.folder_var.get().rstrip("/") == "agency-a/2026-10"
    assert world.dialogs.errors() == []


def test_large_multipart_download(world):
    a = world.app
    world.open_folder("converted/agency-b/")
    world.open_folder("converted/agency-b/2026-10/")
    a.tree.selection_set(BIG_KEY)
    a.download_selected()
    world.idle(timeout=120)
    files = {r: p.stat().st_size for p, r in a.work.in_files()}
    assert files.get("agency-b/2026-10/agency-b-cur-2026-10.xlsx") == BIG_SIZE
    assert world.dialogs.errors() == []


def test_upload_results_then_finish_cleans_up(world):
    a = world.app
    world.open_folder("converted/agency-a/")
    world.open_folder("converted/agency-a/2026-10/")
    a.tree.selection_set("converted/agency-a/2026-10/")
    a.download_selected()
    world.idle()
    (a.work.out_dir / "agency-a-cur-2026-10_priced.xlsx").write_bytes(os.urandom(300_000))
    a.refresh_out()
    a.upload(selected_only=False)
    world.idle()
    keys = [o["Key"] for o in world.s3.list_objects_v2(Bucket=BUCKET, Prefix="priced/").get("Contents", [])]
    assert keys == ["priced/agency-a/2026-10/agency-a-cur-2026-10_priced.xlsx"]
    a.upload(selected_only=False)      # same file again: asks, overwrites, no error
    world.idle()
    a.finish()
    world.idle()
    assert a.work.leftovers() == (0, 0, 0)
    logs = world.s3.list_objects_v2(Bucket=BUCKET, Prefix="logs/").get("Contents", [])
    assert logs, "Finish should upload today's log"
    assert world.dialogs.errors() == []


def test_upload_outside_allowed_folders_is_refused(world):
    with pytest.raises(core.CurWorkError):
        world.app.svc.check_destination("converted/agency-a/2026-10/")
    with pytest.raises(core.CurWorkError):
        world.app.svc.check_destination("priced/../converted/")


def test_refusal_message_names_the_call(world, monkeypatch):
    a = world.app

    def denied(*_a, **_k):
        raise ClientError({"Error": {"Code": "403", "Message": "Forbidden"},
                           "ResponseMetadata": {"HTTPStatusCode": 403}}, "HeadObject")

    monkeypatch.setattr(a.svc.client, "download_file", denied)
    world.open_folder("converted/agency-a/")
    world.open_folder("converted/agency-a/2026-10/")
    a.tree.selection_set("converted/agency-a/2026-10/agency-a-cur-2026-10.xlsx")
    a.download_selected()
    world.idle()
    errs = world.dialogs.errors()
    assert errs and "needs s3:GetObject" in errs[-1]
    log_text = a.log_file.read_text(encoding="utf-8")
    assert "needs s3:GetObject" in log_text, "the log should say which call was refused"


def test_about_and_settings_windows(world):
    a = world.app
    dlg = curwork.AboutDialog(world.root, a)
    world.pump(0.3)
    text = dlg.text()
    for word in ("Beta 0.011", "boto3", "Python", "Tcl/Tk", BUCKET, "Admin settings"):
        assert word in text
    assert "secret" not in text.lower()
    dlg.copy()
    assert world.root.clipboard_get() == text
    dlg.destroy()
    s = curwork.SettingsDialog(world.root, a)
    world.pump(0.3)
    s.destroy()


def test_biller_policy_allows_curwork_and_blocks_the_rest(tmp_path, monkeypatch):
    """Enforces iam/biller_permission_set_policy.json in the mock and runs CurWork's own calls through it."""
    from moto.core import set_initial_no_auth_action_count
    policy = (Path(__file__).resolve().parent.parent / "iam" / "biller_permission_set_policy.json").read_text()
    policy = json.loads(policy.replace("arn:aws:s3:::BUCKET_NAME", "arn:aws:s3:::curwork-test-123456789012-*"))
    policy["Statement"] = [st for st in policy["Statement"] if not st["Sid"].startswith("UseThe")]  # no KMS in the mock

    @set_initial_no_auth_action_count(6)
    @moto.mock_aws
    def run():
        admin = boto3.client("s3", region_name="us-east-1")
        iam = boto3.client("iam", region_name="us-east-1")
        admin.create_bucket(Bucket=BUCKET)                                                   # 1
        admin.put_object(Bucket=BUCKET, Key="converted/agency-a/2026-10/a.xlsx", Body=b"a")  # 2
        iam.create_user(UserName="biller")                                                   # 3
        iam.put_user_policy(UserName="biller", PolicyName="biller", PolicyDocument=json.dumps(policy))  # 4
        key = iam.create_access_key(UserName="biller")["AccessKey"]                          # 5
        admin.list_buckets()                                                                 # 6
        session = boto3.Session(aws_access_key_id=key["AccessKeyId"], aws_secret_access_key=key["SecretAccessKey"],
                                region_name="us-east-1")
        settings = core.settings_from_dict({"bucket": BUCKET, "aws_profile": "", "work_dir": str(tmp_path / "w")})
        svc = core.S3Service(settings, session=session)
        files = svc.expand_selection(["converted/agency-a/2026-10/"])
        got = svc.download(files, tmp_path / "in")
        assert [p.read_bytes() for p in got] == [b"a"]
        out = tmp_path / "r.xlsx"
        out.write_bytes(b"r")
        assert svc.exists("priced/agency-a/2026-10/r.xlsx") is False
        svc.upload([(out, "r.xlsx")], "priced/agency-a/2026-10/")
        assert svc.exists("priced/agency-a/2026-10/r.xlsx") is True
        log = tmp_path / "curwork-test.log"
        log.write_text("log line\n")
        assert svc.upload_log(log)
        raw = session.client("s3")
        for label, call in (("write to converted/", lambda: raw.put_object(Bucket=BUCKET, Key="converted/x.xlsx", Body=b"x")),
                            ("delete a result", lambda: raw.delete_object(Bucket=BUCKET, Key="priced/agency-a/2026-10/r.xlsx")),
                            ("another bucket", lambda: raw.list_objects_v2(Bucket="someone-elses-bucket"))):
            with pytest.raises(ClientError) as e:
                call()
            assert e.value.response["Error"]["Code"] in ("AccessDenied", "403"), label
    run()


def test_self_test_mode_reports_and_exits(tmp_path):
    """Runs 'curwork.py --self-test' in its own process, the way the build and the test runner do."""
    import subprocess
    cfg = tmp_path / core.CONFIG_FILE_NAME
    cfg.write_text(json.dumps({"bucket": BUCKET, "aws_profile": "", "work_dir": str(tmp_path / "CurWork")}))
    env = {**os.environ, "HOME": str(tmp_path)}
    run = subprocess.run([sys.executable, str(Path(curwork.__file__)), "--config", str(cfg), "--self-test"],
                         capture_output=True, text=True, timeout=120, env=env)
    report = json.loads(run.stdout[run.stdout.index("{"):])
    assert run.returncode == 0, report
    assert report["passed"] is True
    names = {c["check"] for c in report["checks"]}
    assert {"Window title", "App icon loaded", "About window details", "Signed-in role is the one in the admin settings"} <= names


_REAL_STORE = core.UserSettingsStore


def test_about_opens_without_blocking_and_closes(world):
    """About must not block the main window, and Close must close it (a hang here froze the Mac app)."""
    a = world.app
    started = time.time()
    a.open_about()                     # returns right away: the About window isn't modal
    assert time.time() - started < 2
    world.pump(0.3)
    first = a._about
    assert first.winfo_exists()
    a.open_about()                     # a second click brings the same window forward
    assert a._about is first
    first.close_btn.invoke()
    world.pump(0.3)
    assert not first.winfo_exists()
    a.refresh_out()                    # the main window still responds
    world.pump(0.2)
    assert world.dialogs.errors() == []


def test_settings_opens_without_blocking_and_closes(world):
    a = world.app
    started = time.time()
    a.open_settings()                  # returns right away: Settings isn't modal
    assert time.time() - started < 2
    world.pump(0.3)
    first = a._settings
    a.open_settings()                  # a second click brings the same window forward
    assert a._settings is first
    curwork.close_window(first)
    world.pump(0.2)
    assert not first.winfo_exists()


def test_replace_prompt_closes_and_returns(world, monkeypatch):
    """The real 'file already in S3' window: clicking Replace must close it and hand back the answer."""
    def click_replace():
        for w in world.root.winfo_children():
            if isinstance(w, tk.Toplevel) and hasattr(w, "_done"):
                w._done("overwrite")
    world.root.after(500, click_replace)
    started = time.time()
    dlg = _REAL_EXISTS(world.root, "priced/agency-a/2026-10/r.xlsx")   # the real dialog, not the test stand-in
    assert dlg.result == "overwrite"
    assert time.time() - started < 10
    assert not dlg.winfo_exists()


def test_tips_cover_every_control(world):
    """Every tip in curwork_help.TIPS is attached to a control in the main window, Settings or Help."""
    import curwork_help
    a = world.app
    a.open_settings()
    a.open_help()
    world.pump(0.3)
    attached = {t.text for t in list(a.tips.values()) + list(a._settings.tips.values()) + list(a._help.tips.values())}
    missing = [key for key, text in curwork_help.TIPS.items() if text not in attached]
    assert not missing, f"tips not attached to anything: {missing}"
    for key in ("sign_in", "download", "upload_all", "finish", "folder", "stage", "help"):
        assert key in a.tips
    curwork.close_window(a._settings)
    a._help.close()


def test_tip_appears_and_goes_away(world):
    a = world.app
    t = a.tips["download"]
    t.show()
    world.pump(0.2)
    assert t.tip is not None and t.tip.winfo_exists()
    assert "In folder" in t.text
    t.hide()
    world.pump(0.1)
    assert t.tip is None


def test_help_window_topics_search_and_step_buttons(world):
    import curwork_help
    a = world.app
    started = time.time()
    a.open_help()                                   # not modal
    assert time.time() - started < 2
    world.pump(0.3)
    h = a._help
    assert h.current == "quick_start"
    assert len(h.topics.get_children()) == len(curwork_help.TOPICS)
    assert "Quick start" in h.text.get("1.0", "end")
    h.search_var.set("excel")
    world.pump(0.2)
    shown = h.topics.get_children()
    assert shown and all("excel" in (t + x).lower() for i, t, x in curwork_help.TOPICS if i in shown)
    assert h.text.tag_ranges("hit"), "search words should be highlighted"
    h.search_var.set("zzzz-no-such-word")
    world.pump(0.2)
    assert h.found_lbl.cget("text") == "No topics match"
    h.search_var.set("")
    a.open_help("step3")                            # the ? on step 3 reuses the same window
    world.pump(0.2)
    assert a._help is h and h.current == "step3"
    assert "Result type" in h.text.get("1.0", "end")
    world.root.event_generate("<F1>")               # F1 also opens Help
    world.pump(0.2)
    assert a._help is h
    h.close_btn.invoke()
    world.pump(0.2)
    assert not h.winfo_exists()


def test_help_text_is_complete():
    import curwork_help
    ids = [t[0] for t in curwork_help.TOPICS]
    assert len(ids) == len(set(ids))
    for tid, title, text in curwork_help.TOPICS:
        assert text.lstrip().startswith("# "), tid
        assert "TODO" not in text and "  " not in title
    for needed in ("quick_start", "sign_in", "step1", "step2", "step3", "step4", "settings", "problems", "keys", "support"):
        assert needed in ids
    assert curwork_help.search("upload") and curwork_help.search("") == ids


def test_self_test_saves_report_file(tmp_path):
    """--report saves the self-test result to a file (how CurWork.exe on Windows reports it)."""
    import subprocess
    cfg = tmp_path / core.CONFIG_FILE_NAME
    cfg.write_text(json.dumps({"bucket": BUCKET, "aws_profile": "", "work_dir": str(tmp_path / "CurWork")}))
    out = tmp_path / "report.json"
    env = {**os.environ, "HOME": str(tmp_path)}
    run = subprocess.run([sys.executable, str(Path(curwork.__file__)), "--config", str(cfg), "--self-test",
                          "--report", str(out)], capture_output=True, text=True, timeout=120, env=env)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["passed"] is True
    missing = tmp_path / "nope.json"
    run = subprocess.run([sys.executable, str(Path(curwork.__file__)), "--config", str(missing), "--self-test",
                          "--report", str(out)], capture_output=True, text=True, timeout=120, env=env)
    assert run.returncode != 0
    assert json.loads(out.read_text(encoding="utf-8"))["passed"] is False
