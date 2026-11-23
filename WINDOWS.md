# Setting up, testing and running CurWork on Windows 11

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.016** · Updated 2026-11-23 01:23 UTC · Modified by: mbitar

> **Status: Windows testing hasn't been done yet. It's waiting for approval.** Nothing in this guide has been run on a Windows 11 PC so far. Don't give `CurWork.exe` to billers until the Windows tests have been approved, run and passed.

This guide walks you through getting CurWork working on a Windows 11 PC, from a fresh machine to a tested app. It's written for whoever builds and tests CurWork. Billers don't need any of this: they only get the finished `CurWork.exe` and its settings file.

There are seven parts, and you do them in order:

1. Install the tools
2. Get the code
3. Add your private test settings
4. Build CurWork
5. Point CurWork at the test bucket
6. Run the automated tests
7. Test it by hand

Plan on about an hour the first time. After that, a rebuild and a full test run take about ten minutes.

> **Before you start:** the test bucket and the biller test sign-in are created from the Mac test kit (menu options 3 and 4). The Windows steps use them but don't create them. If they don't exist yet, set them up on the Mac first, or ask your admin.

## 1. Install the tools

You need admin rights on the PC to install these. Install each one with its default options unless the step says otherwise.

| Tool | Where to get it | Notes |
|---|---|---|
| **Python 3.12 (64-bit)** | [python.org/downloads/windows](https://www.python.org/downloads/windows/) | Use the "Windows installer (64-bit)". Keep **"Use admin privileges when installing py.exe"** ticked: the build uses the `py` launcher it installs. |
| **AWS CLI version 2** | [AWS CLI installer for Windows](https://awscli.amazonaws.com/AWSCLIV2.msi) ([install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)) | CurWork uses it to sign in. It installs to `C:\Program Files\Amazon\AWSCLIV2`, which is where CurWork looks for it. |
| **Git for Windows** | [git-scm.com/download/win](https://git-scm.com/download/win) | Also installs the Bash and Perl that the repository's upload checks need. |
| **Microsoft Excel** | Your company's Microsoft 365 | Only needed for the hand tests in part 7. |

When they're installed, open a **new** PowerShell window and check that all three answer with a version number:

```powershell
py -3.12 --version
aws --version
git --version
```

## 2. Get the code

If Git asks you to sign in, use a GitHub account that has access to the repository.

```powershell
cd $HOME
git clone https://github.com/scriptbuzz/curworks.git
cd curworks
git config core.hooksPath .githooks
```

The last line turns on the checks that stop AWS account numbers, sign-in addresses, keys and private values from being uploaded to GitHub. Git for Windows runs them with its own Bash, so they work the same as on a Mac.

## 3. Add your private test settings

Your AWS details live in one private file that never leaves your PC.

1. In the `curworks` folder, make a copy of `curwork_test.env.example` and name it `curwork_test.env`.
2. Open `curwork_test.env` in Notepad and fill in:
   - `CURWORK_ACCOUNT`: the 12-digit test account number.
   - `CURWORK_ADMIN_PROFILE`: your AWS CLI profile with admin rights in that account. The real AWS tests use it only to remove the test files they make.
   - `CURWORK_SSO_START_URL` and `CURWORK_SSO_REGION`: your company's AWS sign-in address and its Region.
3. Leave the other lines as they are, unless your admin tells you otherwise.
4. If you don't have the admin profile on this PC yet, create it once with `aws configure sso` and use the same name you put in the file.

Git ignores `curwork_test.env`, and the upload checks block its values from appearing in any other file.

## 4. Build CurWork

PowerShell blocks scripts by default. The first command below allows them in this PowerShell window only, which is safer than changing the setting for the whole PC.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
cd $HOME\curworks\CurWork-app
.\build_exe.ps1
```

The build script does all of this, and stops at the first step that fails:

1. Creates a clean Python environment (`.venv`) inside the app folder.
2. Installs CurWork's packages, checking each one against its locked SHA-256 fingerprint.
3. Runs all the automated tests (the CurWork windows flash up briefly; don't click them).
4. Checks every package for known security holes with `pip-audit`.
5. Writes a list of everything inside the build (`sbom-runtime.cdx.json`).
6. Builds `dist\CurWork.exe` with its icon, without the admin code. It also builds `dist\CurWorkAdmin.exe`, the admin settings app.
7. Runs both new apps in self-test mode and stops if any check fails.

It finishes with `dist\CurWork.exe`, `dist\curwork_admin_settings.json` and the SBOM. If you see a yellow warning that the admin settings file is only the example, that's expected on a test PC: part 5 replaces it.

## 5. Point CurWork at the test bucket

You need the name of the test bucket. It starts with `curwork-test-`. You can find it in the AWS console under S3, or on the Mac in the `test_bucket.txt` file in the repository folder.

```powershell
cd $HOME\curworks
.\run_windows_tests.ps1 -Bucket curwork-test-REPLACE-WITH-YOUR-BUCKET
```

The first time, this creates `CurWork-app\curwork_admin_settings.json` from the example file. That file only holds the sign-in settings: it fills in your sign-in address and the biller test sign-in from `curwork_test.env`, and copies the file next to `CurWork.exe`. It saves the bucket in AWS Parameter Store with your admin profile, because CurWork reads every other setting from there after sign-in. Sign in with the admin profile first. Then it carries straight on with the tests in part 6. You only need `-Bucket` again if the test bucket changes.

## 6. Run the automated tests

Always run these before testing by hand, and again after every change.

```powershell
cd $HOME\curworks
.\run_windows_tests.ps1
```

If you're not signed in to AWS yet, your browser opens. Sign in, approve, and go back to PowerShell.

The script runs four parts and saves everything to `windows_tests_results.txt` (Git ignores it):

| Part | What it checks |
|---|---|
| 1. Unit tests | CurWork's settings, S3, sign-in and file logic, against a mocked S3 |
| 2. Window tests | Drives the real CurWork window through sign-in, download, upload, Help, About, Settings and Finish, against a mocked S3. It also checks that CurWork's calls fit inside the biller permission policy |
| 3. Real AWS tests | Signs in as the biller test role and downloads the small and the 116 MB workbook. It uploads a result and the log, and proves that a biller **can't** write to `converted/`, delete files or list the whole bucket. Then it removes its test files with your admin profile |
| 4. Self-tests | Opens CurWork from the source code and `dist\CurWork.exe` without any pop-ups. It checks the settings file, icon, About, Settings, and that you're signed in with the right role |

It ends with either **"All Windows tests passed"** or **"STOPPED"** and a list of what failed. If anything fails, send `windows_tests_results.txt` for review before you test by hand.

## 7. Test it by hand

Start `CurWork-app\dist\CurWork.exe`. To run it from the source code instead, use:

```powershell
cd $HOME\curworks\CurWork-app
.\.venv\Scripts\python.exe curwork.py
```

The first time you open the `.exe`, Windows may say **"Windows protected your PC"**. That's because test builds aren't code-signed yet. Click **More info**, then **Run anyway**. Real builds for billers must be signed (see part 8). If Smart App Control is on, Windows may block an unsigned app completely; run CurWork from the source code instead.

Go through these and note anything that looks wrong:

| # | Try this | What should happen |
|---|---|---|
| 1 | Look at the taskbar and the window title | CurWork's own icon. The title reads "CurWork – Beta 0.016 (DRAFT - For Internal Use)" |
| 2 | Click **Sign in** | Your browser opens. After you approve, CurWork shows your name and the biller test role in green |
| 3 | Open `agency-b` > `2026-10` and click **Download selected** | A progress bar, then the 116 MB file appears in **In** |
| 4 | Click **Open** next to **In**, open the file in Excel and run your macros | Four sheets of made-up data. Save the results to **Out** (use **Copy path** next to **Out** in the macro's Save dialog) |
| 5 | Close the file in Excel. Pick a result type, then click **Save all new or changed in S3** | The status changes to **Saved in S3** |
| 6 | Select the same file and click **Save selected in S3** | CurWork asks whether to replace it |
| 7 | Point at a few buttons, press **F1**, and click a step's **?** | A tip under each button. Help opens at the right topic |
| 8 | Open **About**, click **Copy details**, then close it | The details paste cleanly. The window closes straight away |
| 9 | Change something in **Settings**, close CurWork and open it again | Your change is kept |
| 10 | Click **Finish and clean up** | In and Out are emptied and the log is saved in S3 |

## 8. Getting CurWork onto biller laptops

This is the admin's job, and the [Admin and Security Guide](CurWork-app/ADMIN_AND_SECURITY_GUIDE.md) has the full details. In short:

- Build on a clean build PC, not a biller laptop.
- Sign `CurWork.exe` and `CurWorkAdmin.exe` with the company code-signing certificate.
- Give billers `CurWork.exe` only. `CurWorkAdmin.exe` is for admins.
- Put `CurWork.exe` and the real `curwork_admin_settings.json` together in a folder billers can read but not change, for example `C:\Program Files\CurWork`.
- Make sure the AWS CLI is installed on each laptop. CurWork adds the billers' AWS sign-in profile itself the first time they click **Sign in**.
- Billers' files go to `%LOCALAPPDATA%\CurWork`. That folder isn't synced to OneDrive, which is why it's the default.

## 9. Cleaning up after testing

1. In CurWork, click **Finish and clean up**.
2. Remove the AWS test items with the Mac test kit (menu option 10). It finds the test bucket and the biller test sign-in in AWS.
3. On this PC, you can delete:
   - the `%LOCALAPPDATA%\CurWork` folder;
   - the `curwork-biller` profile and the `curwork-test` sign-in session from `%USERPROFILE%\.aws\config` (open it in Notepad and delete those sections);
   - `curwork_test.env`, if you've finished testing on this PC.

## If something goes wrong

| What you see | What to do |
|---|---|
| "running scripts is disabled on this system" | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in the same PowerShell window, then try again |
| "py is not recognized" or "No suitable Python runtime found" | Install Python 3.12 from python.org (part 1), then open a new PowerShell window |
| "aws is not recognized" | Install the AWS CLI (part 1), then open a new PowerShell window |
| The build stops at "Check every installed package for known vulnerabilities" | A package has a known security hole. Don't skip the check; send the build output for review |
| CurWork says "AWS said you don't have permission for that" | The message names the refused AWS call. Check that **About** shows the biller test role. If it shows a different role, run part 5 again |
| CurWork warns that the work folder is inside OneDrive | Set the work folder back to `%LOCALAPPDATA%\CurWork` in the CurWork Admin Settings app |
| A test fails in part 6 | Send `windows_tests_results.txt` for review before you test by hand |

These Windows steps were checked against the code, but Windows testing hasn't been done yet. It's waiting for approval. If a step doesn't match what you see, note what you saw and report it.

---
*DRAFT - For Internal Use (FPT) · Beta 0.016 · Updated 2026-11-23 01:23 UTC · Modified by: mbitar*
