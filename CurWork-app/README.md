# CurWork

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.014** · Updated 2026-11-23 00:16 UTC · Modified by: mbitar

CurWork is a small Windows app for the billing team. It copies converted CUR workbooks from Amazon S3 to a local work folder, so the existing VBA macros (pricer, allocator, mapper and the rest) run on local files instead of Box. It then sends the results back to S3 and cleans up the laptop. **The VBA code doesn't change.**

**Admins, IT and security reviewers:** start with `ADMIN_AND_SECURITY_GUIDE.md`. It covers AWS setup, building, deployment, settings, security controls, the NIST SP 800-53 mapping, risks and open decisions.

## Quickstart for billers

1. Start CurWork and click **Sign in**. Finish the company sign-in and MFA in the browser. The sign-in line at the top turns green and shows your user name and role.
2. **Step 1:** open a customer folder, select a month or single files, and click **Download selected**.
3. **Step 2:** run your macros as usual. Pick files from `In` (use **Copy path**) and save results to `Out`.
4. **Step 3:** check the result type and the customer/month folder, then click **Save all new or changed in S3**.
5. **Step 4:** close the files in Excel, then click **Finish and clean up**. When it says the In and Out folders are empty, you're done.

Need help? Point at any button or box to see what it does, click the **?** next to a step, or press **F1** (or click **Help**) for the full help with search.

## What billers see

One window with four steps:

1. **Download files from S3:** open a customer folder, select files or a whole month, click **Download selected**. Files land in `In`. **Pin selected folder** and **Go** jump straight to folders you use often.
2. **Run your macros as usual:** in the macro menu, pick files from `In` and save results to `Out`. **Open** and **Copy path** buttons make this quick.
3. **Save results in S3:** the list shows every file in `Out` with a status (*Not saved in S3*, *Saved in S3*, *Changed since saved*, *Open in Excel*). Pick the result type and click **Save all new or changed in S3**. The customer/month folder is filled in from the download, and recent folders are in the drop-down.
4. **Finish and clean up:** stops if anything is still open in Excel, left in `In` or not saved in S3. Otherwise it saves the day's log in S3 and empties `In` and `Out`.

**Settings** (top right) holds each user's own preferences: recent and pinned folders, whether to remember the last result type, and the window layout. It also shows the admin settings, read-only.

Built-in safety:
- **Sign-in:** billers sign in once per session (1 to 12 hours, set by the admin) with IAM Identity Center and MFA. No access keys are stored anywhere.
- **Inputs stay safe:** inputs and outputs use separate S3 folders, and the app refuses to upload into input folders.
- **Asks before replacing:** if a result is already in S3, the app asks before replacing it.
- **Checked transfers:** uploads send a SHA-256 checksum that S3 checks, then the app confirms the file size in S3. Downloads go to a `.part` file first and are renamed only when complete.
- **Open-file check:** files still open in Excel are never uploaded or deleted. Lock files left behind after a crash are ignored.
- **Results saved to the wrong folder:** if a macro saved a result into `In`, or changed an input, the app flags it and offers to move it to `Out` before clean-up.
- **Re-downloading over your edits:** if an `In` file was changed after download, the app asks before replacing it.
- **Leftovers:** at start-up the app reports files left from the last session, and at close it offers to clean up.
- **Safe file names:** S3 file names are checked before they become local file names, which blocks `..` tricks and names Windows doesn't allow.
- **Logs:** a local log of every action, uploaded to S3 at **Finish and clean up** (if still signed in).
- **No silent failures:** unexpected errors are logged and shown. If the app can't start, it saves `CurWork-crash.log` in `%LOCALAPPDATA%`.

## Files

| File | What it's for |
|---|---|
| `curwork.py` | The app window (tkinter) |
| `curwork_test.env.example` | Template for the private test settings (`curwork_test.env`, never committed) |
| `tools/check_no_aws_details.sh`, `.githooks/` | Blocks commits and pushes that contain AWS account numbers, sign-in URLs, emails, keys or private values |
| `.gitignore` | Keeps secrets, personal settings, test output, build output and local working files out of Git. Also skips the 116 MB test workbook (over GitHub's 100 MB limit). |
| `curwork_admin.py` | The CurWork Admin Settings app: AWS admins use it to view and change the managed settings in AWS Parameter Store. Only the AWS admin role can save. |
| `curwork_help.py` | All help text in one place: the tips shown when you point at a control, and the Help window topics |
| `curwork_core.py` | S3, sign-in, settings and work-folder logic (no window code, fully tested) |
| `curwork_admin_settings.json` | **Protected** laptop settings: only what CurWork needs to sign in (the sign-in details, Region, FIPS switch and use notice). Everything else, such as the bucket, folders, encryption key and work folder, is kept in AWS Parameter Store. Not stored in Git (it's in `.gitignore`); the admin hands it out. |
| `curwork_user_settings.json` | **Unprotected** user preferences. Not shipped: the app creates it the first time a user saves a preference. |
| `ADMIN_AND_SECURITY_GUIDE.md` | Setup, deployment, settings reference, security controls, NIST mapping, risks, open decisions |
| `iam/biller_permission_set_policy.json` | Least-privilege policy for the billers' permission set |
| `iam/bucket_policy_additions.json` | Bucket policy statements that require TLS 1.2 or higher |
| `iam/README.md` | What the two policy files are for |
| `requirements.txt` | Runtime package (boto3) as a version range, for running from source |
| `requirements-lock.txt` | Runtime packages at exact versions with SHA-256 hashes, used by the build |
| `requirements-dev.txt` | Build and test tools (not shipped) |
| `build_exe.ps1` | Builds `CurWork.exe` with its icon (tests, vulnerability check, SBOM, build) |
| `tests/test_core.py` | Unit tests for the settings, S3, sign-in and work-folder logic (mocked S3) |
| `tests/test_gui.py` | Window tests: drives the real CurWork window through sign-in, browse, small and multipart downloads, upload, refusals, About, Settings, Finish and `--self-test`, and checks CurWork's calls fit the biller policy. Needs a display (xvfb-run on Linux). |
| `assets/` | App icon: `curwork.ico` (Windows), `curwork.icns` (Mac app), PNGs for the window and Dock |
| `mac-test-kit/` | Double-click scripts and made-up sample workbooks for testing on a Mac against a real AWS test bucket (see its README). Not for billers. |

## Building the exe

On a Windows build machine with Python 3.12 (64-bit) from [python.org](https://www.python.org/downloads/windows/), run `build_exe.ps1` (command below). It installs the hash-locked runtime packages, runs the tests, checks every package with [pip-audit](https://pypi.org/project/pip-audit/), writes a software bill of materials (`sbom-runtime.cdx.json`), and builds `dist\CurWork.exe` with [PyInstaller](https://pyinstaller.org/). If any step fails, the build stops. Sign the exe with the company code-signing certificate before handing it out. Details are in the Admin and Security Guide, section 4.

The app uses [boto3](https://aws.amazon.com/sdk-for-python/) (the AWS SDK for Python) for all S3 calls.

## Things to know

- **Big CURs:** Excel sheets stop at 1,048,576 rows. CurWork moves files as they are and doesn't split them.
- **Two billers, one file:** there's no check-out lock. If two billers upload the same result name, the second one is asked before replacing it, and S3 Versioning keeps the earlier copy.
- **Rules and lookup files** stay where they are today (the rules files sit in Box). Moving them to S3 later would mean adding their folder to `browse_roots` and pointing the macro menu at the local copies. Check with the VBA owner whether that's a settings change or a code change.
- **Local logs** are kept for 14 days in `%LOCALAPPDATA%\CurWork\Logs`. They contain file names and actions, not file contents.

## Testing

Run the tests from the CurWork folder (commands at the end of this section). They use a mocked S3, so no AWS account is needed. One test needs a POSIX (Mac or Linux) account that isn't root; it's skipped on Windows and when run as root.

```powershell
py -3.12 -m pip install -r requirements.txt -r requirements-dev.txt
py -3.12 -m pytest -q
```

## Testing on a Mac (real AWS)

The app is built for Windows, but the code runs on a Mac for testing. The `mac-test-kit/` folder has double-click scripts that do the setup; its README explains the folder layout.

**Test plan (biller test sign-in):** run `CurWork_Test_Menu.command` and follow the numbers. Run option 8 (**Run all automated tests**) before any hand testing; test by hand only when it ends with "All automated tests passed".
1. Check this Mac: Python, Tk and the AWS CLI; sets up `.venv`; runs the automated tests.
2. Create the test bucket: the admin profile is used only to create and check a locked-down test bucket with the sample workbooks (one is 116 MB, 3.2 million rows). It then sets up the **CurWorkBillerTest** permission set from `iam/biller_permission_set_policy.json`, limited to test buckets, and points CurWork at it (profile `curwork-biller`). This tests the real least-privilege biller access (NIST SP 800-53 AC-6).
3. Build or start CurWork: sign in, browse, download (including the large file), open a file in Excel, upload to an allowed folder, try a folder that isn't allowed (it should be refused), pin and **Go**, change **Settings** and restart, check **About**, then **Finish and clean up**.
4. Clean up when finished: finds and removes everything the test created, including the permission set, with a PASS/FAIL check for each item.

**Results so far (2026-11-22, macOS 27.2.1, Apple silicon):**
- Mac check passed: Python 3.12.13, Tk 9.0.3, AWS CLI 2.35.14, hash-checked packages installed, tests passed.
- Test bucket with all samples (including the 116 MB file) set up; 11 of 11 checks passed. CurWork.app builds, is signed for the test Mac, and opens.
- Downloads were refused with the first test role. Cause found: AWS's ViewOnlyAccess policy (on the AWSReadOnlyAccess permission set) can list files but not read them (no s3:GetObject). The test now uses the CurWorkBillerTest permission set instead.
- The built Mac app was looking for its admin settings inside CurWork.app. Fixed.

**Your AWS details stay private:** the test scripts read the account number, admin profile and sign-in URL from `curwork_test.env` (copy `curwork_test.env.example` and fill it in). That file is in `.gitignore`, and Git commit and push checks (`.githooks/`, turned on with `git config core.hooksPath .githooks`) block any commit or push that contains an AWS account number, an `awsapps.com` sign-in URL, an email address, an access key, a private key, or any value from `curwork_test.env`. The automated tests run the same check on every file Git would add.

**What's different on a Mac:**
- The work folder is `~/CurWork`, because `%LOCALAPPDATA%` doesn't exist on a Mac.
- **The open-file check is weaker.** On Windows the app asks Windows whether Excel holds the file. On a Mac it only looks for Excel's `~$` owner file, so a leftover `~$` file from a crash makes a file show as *Open in Excel* until you delete it.
- **The VBA macros** may not behave the same in Excel for Mac. Test CurWork's steps on the Mac and the macros on a Windows laptop.

## Change log

| Version | Date (UTC) | Changes | Modified by |
|---|---|---|---|
| Beta 0.014 | 2026-11-23 00:16 | The CurWork Admin Settings app is easier to use. Settings are grouped on four tabs. After Load, the bucket, encryption key and S3 folders are drop-downs filled from what exists in AWS, and you can still type a name. File types are checkboxes, numbers have arrows and limits, result types are a small table, and where preferences are saved is a plain choice of two places. Each setting shows a one-line explanation, its default and a **Use default** button. Changes are marked, and a value that can't be saved is explained in red under the setting before anything is saved. | mbitar |
| Beta 0.013 | 2026-11-22 23:57 | The laptop settings file now only holds what CurWork needs to sign in: the sign-in details, the Region, the FIPS switch and the use notice. Every other setting, now including the work folder and where preferences are saved, is kept in AWS Parameter Store, which CurWork always reads after sign-in (`/curwork/admin-settings` unless the file names another). CurWork refuses a laptop file that holds any other setting. After sign-in it switches to the work folder the admin set, and today's log moves with it. The admin settings app has fields for the work folder and the preferences location, and the self-test now also reads the settings kept in AWS. The setup scripts save the bucket in Parameter Store instead of the laptop file. | mbitar |
| Beta 0.012 | 2026-11-22 23:33 | Plain wording: the window, Help, the admin settings app and the guides now say "save in S3" instead of "send" or "upload". For example, the main button is **Save all new or changed in S3** and a finished file shows **Saved in S3**. The program folder is now `CurWork-app`, with no version in its name. Since the last entry: there is a checklist for testing by hand on a Mac (`MAC_HAND_TEST.md`); a settings file named with `--config` that doesn't exist now stops CurWork with an error; new tests cover the use notice, an expired sign-in and the checksum S3 checks when a file is saved; option 3 also saves a new test bucket to the settings kept in AWS; and new tests check that the Parameter Store settings work, are easy to use, and can only be changed by an admin. | mbitar |
| Beta 0.011 | 2026-11-22 22:44 | Managed settings: the settings that decide where data goes can live in AWS Parameter Store. CurWork reads them after each sign-in, billers can only read them, and only the AWS admin role can change them with the new CurWork Admin Settings app (`curwork_admin.py`). 91 tests pass. | mbitar |
| Beta 0.011 | 2026-11-22 21:50 | Running from source: if the settings file named by `--config` or `CURWORK_CONFIG` doesn't exist, CurWork stops with an error instead of quietly using the settings file next to `curwork.py`. | mbitar |
| Beta 0.011 | 2026-11-22 20:56 | Config lock: the built app only reads the admin settings file installed next to it. It ignores `--config` and `CURWORK_CONFIG` and logs a warning if either is used. Running from source still accepts them. | mbitar |
| Beta 0.011 | 2026-11-22 18:13 | AWS details out of Git: the test scripts read the account number, admin profile and sign-in URL from a private `curwork_test.env` (ignored by Git; template `curwork_test.env.example`). New commit and push checks block AWS account numbers, sign-in URLs, emails, keys and private values, and the automated tests run the same check. The admin settings file is ignored too. Docs no longer name the test account or profile. | mbitar |
| Beta 0.011 | 2026-11-22 18:08 | Added `.gitignore`. Test scripts' messages now say "send ... for review". Image files carry no extra metadata. | mbitar |
| Beta 0.011 | 2026-11-22 18:05 | Help: tips on every button, box and list (point at it, or tab to it); a **Help** window (Help button, F1, Help menu; on a Mac the standard Help menu with search) with 11 searchable topics, from Quick start to When something goes wrong; a **?** button on each step that opens Help at that step; Help in Settings. All help text lives in `curwork_help.py`. Settings is no longer modal (one window, brought forward if already open). 67 tests pass. | mbitar |
| Beta 0.011 | 2026-11-22 17:53 | Fix: the Mac app froze (spinning wheel) after closing About. About is no longer modal (nothing waits on it; a second click brings it forward). All dialogs release their grab before closing. Mac menu items (About CurWork, Settings…, Quit) now run after the menu closes. New window tests for About, Settings and the real replace prompt; 63 tests pass. | mbitar |
| Beta 0.011 | 2026-11-22 17:31 | First full automated run on the Mac: biller test access set up (CurWorkBillerTest, via the management account), all 15 real AWS checks passed (including the three refusals), and the app and source self-tests passed. The window tests crashed Python on macOS. Fixed: the tests reuse one window root (macOS Tk can crash when a second root is made in one process), the self-test test runs in its own process, and the test runner runs each window test in its own process and saves the full output to `code_tests_output.txt`. The self-test makes no AWS call when the settings have no sso section. | mbitar |
| Beta 0.011 | 2026-11-22 17:23 | Biller test access: when the admin profile can't manage IAM Identity Center (it's a member account), the setup finds the organization's management account, adds an AWS CLI profile `curwork-ic-admin` for your admin role there (with a backup of ~/.aws/config), and uses it; no traceback on refusal. Cleanup also removes that profile. The Mac build closes a running CurWork before replacing the app, so an old copy can't stay open. | mbitar |
| Beta 0.011 | 2026-11-22 17:09 | Automated testing before any hand testing: new window tests (`tests/test_gui.py`, 60 tests in all pass), a `--self-test` mode in the app (JSON report: settings, icon, About, Settings, signed-in role), and a Mac test runner (`run_automated_tests.command`, menu option 8) that runs script checks, all tests, real AWS tests with CurWork's own code (`tools/real_aws_tests.py`), and the built app's and source's self-test. The Mac app build now opens the app only if its self-test passes. | mbitar |
| Beta 0.011 | 2026-11-22 16:53 | Mac test now signs in with a **CurWorkBillerTest** permission set built from CurWork's own biller policy (test buckets only) instead of AWSReadOnlyAccess. New `setup_biller_access.command` (menu option 4), run automatically by setup and reset. Cleanup also finds and removes the permission set and its assignments. Menu renumbered 1 to 10. | mbitar |
| Beta 0.011 | 2026-11-22 16:48 | Fix: the built Mac app now finds `curwork_admin_settings.json` next to CurWork.app (it was looking inside the app). Download check skips the role test with a clear note when the curwork-readonly profile isn't set up yet. Found the download refusal's cause: the test role AWSReadOnlyAccess has only the ViewOnlyAccess policy, which has no s3:GetObject. 51 tests pass. | mbitar |
| Beta 0.011 | 2026-11-22 16:44 | When AWS refuses something, the message and the log now say which call was refused in plain English (for example "downloading a file from S3 (needs s3:GetObject)") and AWS's own reason when it gives one. 50 tests pass. | mbitar |
| Beta 0.011 | 2026-11-22 16:33 | Test menu option 9, **Reset everything**: deletes every test item, then creates a fresh test bucket with all samples (a typed **confirm** for each part; stops if the first part doesn't fully succeed). Cleanup now accepts ranges like 2-5 and says what didn't match. | mbitar |
| Beta 0.011 | 2026-11-22 16:24 | Test menu now shows, under each option, when to use it, what it does step by step and what it changes. New large made-up sample (3.2 million rows over 4 sheets, 116 MB) for load testing, with `tools/make_large_sample.py` and an upload step (`upload_large_sample.command`). | mbitar |
| Beta 0.011 | 2026-11-22 16:17 | Mac test kit: `CurWork_Test_Menu.command`, one numbered menu for every test script in run order, with explanations and last-run PASS/FAIL. | mbitar |
| Beta 0.011 | 2026-11-22 16:14 | Window title is now "CurWork – Beta 0.011 (DRAFT - For Internal Use)". App icon on the window, taskbar and Dock; on Windows CurWork gets its own taskbar identity (AppUserModelID) instead of Python's. New **About** window (button, and About CurWork in the Mac app menu): what the tool does, version, build date, Python, Tcl/Tk, OS, package versions, sign-in, bucket, settings and log paths, with Copy details and Open log folder. Mac app menu Settings… (Cmd+,) and Quit go to CurWork. A built Mac app reads its settings from the folder next to CurWork.app, never inside it. Mac test kit: build_mac_app.command and diagnose_download.command. | mbitar |
| Beta 0.011 | 2026-11-22 16:02 | Grey hint text is easier to read: on a Mac it uses the system secondary label color (works in Light and Dark Mode); elsewhere #6b6b6b (at least 4.5:1 contrast, WCAG 2.2 SC 1.4.3). Delete script now saves `delete_results.txt`. | mbitar |
| Beta 0.011 | 2026-11-22 14:58 | Added `mac-test-kit/` (Mac check, test bucket setup with 11 PASS/FAIL checks, launcher, and a cleanup script that finds every test item even after a crash, with pick-and-**confirm** deletes and re-checks). Mac test plan uses the AWSReadOnlyAccess role for CurWork and the admin profile only for setup. Mac check results recorded. | mbitar |
| Beta 0.011 | 2026-11-22 14:36 | Settings window redesigned: preferences in aligned rows with a label column, admin settings in a two-column table grouped by topic (Source, Storage, Sign-in, Folders, Transfers, This computer), a short version line, full value of any row shown on click, and a Copy admin settings button. | mbitar |
| Beta 0.011 | 2026-11-22 13:42 | Accuracy, consistency and security review. New `ADMIN_AND_SECURITY_GUIDE.md`; admin setup, settings reference and NIST mapping moved there from this README. Existing-result check now uses a listing, so it works with the prefix-limited permission set. Build script stops when tests or pip-audit fail. Runtime packages hash-locked (`requirements-lock.txt`), build tools split out (`requirements-dev.txt`), SBOM written by the build. Settings files size-limited, with a safer save. Plainer wording in messages. 47 tests pass. | mbitar |
| Beta 0.011 | 2026-11-22 13:08 | Settings split into a protected admin file (`curwork_config.json` renamed to `curwork_admin_settings.json`) and an unprotected user file (`curwork_user_settings.json`). New **Settings** window, pinned folders with **Go**, recent customer/month folders, remembered result type, saved window size and column widths. New admin setting `user_settings_location`. | mbitar |
| Beta 0.011 | 2026-11-22 12:45 | Names from the meeting removed: customer names in code comments, an error message and tests replaced with agency-a / agency-b; team and company names removed. No logic changes. | mbitar |
| Beta 0.011 | 2026-11-22 12:42 | Internal account name removed from every file; sample and test bucket names made generic. No logic changes. | mbitar |
| Beta 0.011 | 2026-11-22 12:40 | Added "Testing on a Mac (real AWS)". No logic changes. | mbitar |
| Beta 0.011 | 2026-11-22 12:30 | Renumbered from 1.1.0 to Beta 0.011. DRAFT - For Internal Use label and stamps on every file and in the window title. Quickstart added. Accuracy fixes in this README. No logic changes. | mbitar |
| 1.1.0 (code) | 2026-11-22 11:45 | Logic review fixes: results saved to In by mistake, edited inputs, stale Excel lock files, clean stop on close, crash log, no `aws.exe` from the current folder, config checks, no duplicate AWS profile, sync-folder warning, optional AC-8 notice, pip-audit in the build. | mbitar |
| 1.0.0 (code) | 2026-11-22 11:33 | First release | mbitar |

---
*DRAFT - For Internal Use (FPT) · Beta 0.014 · Updated 2026-11-23 00:16 UTC · Modified by: mbitar*
