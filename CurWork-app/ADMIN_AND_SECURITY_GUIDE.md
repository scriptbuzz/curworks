# CurWork Admin and Security Guide

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.013** · Updated 2026-11-22 23:56 UTC · Modified by: mbitar

This guide is for the people who set up, run and review CurWork: the AWS admin, IT (laptop management), the build owner and security reviewers. Billers don't need it; the CurWork Guide and the README cover daily use. The shared online copy of this guide also has an exhibit of the three control layers.

## 1. Who does what

| Role | Sets up | Keeps running |
|---|---|---|
| AWS admin | Identity Center permission set, the CUR bucket, KMS key, CloudTrail data events | Permission set assignments, bucket settings, reviewing CloudTrail in the SIEM |
| IT | Laptop baseline (BitLocker, screen lock, AWS CLI v2), app deployment, AppLocker or WDAC rules, HTTPS inspection exceptions | Deploying new versions and new admin settings files |
| Build owner | The admin settings file, the build, code signing | Rebuilding when packages change; keeping the SBOM |
| Security reviewer | Signs off the controls in section 8 and the decisions in section 9 | Reviews changes to the permission set, bucket policy and admin settings |

Three layers decide what a biller can do. The strongest is in AWS, so nothing on the laptop can get past it:

1. **The AWS permission set.** The hard limit. Whatever happens on the laptop, a biller can only read and write what the permission set allows.
2. **The admin settings file** (`curwork_admin_settings.json`, protected). Which bucket, folders, encryption and sign-in the app uses.
3. **The user preferences file** (`curwork_user_settings.json`, unprotected). Recent and pinned folders, result type, window layout. It can't change layers 1 or 2.

## 2. Before you start

- Microsoft Entra ID is connected to AWS IAM Identity Center with SAML and SCIM. If Entra connects straight to IAM roles instead, the app's **Sign in** button won't work as built.
- An AWS account with the CUR bucket and a customer-managed KMS key.
- Laptops: Windows 11, BitLocker on, screen lock on idle, AWS CLI v2. Python 3.12 with tkinter is only needed if you run from source instead of the exe.
- A Windows build machine with Python 3.12 (64-bit) and the company code-signing certificate.
- The open decisions in section 9 reviewed.

## 3. AWS setup (AWS admin)

**Permission set for billers**
1. Create a permission set in IAM Identity Center from `iam/biller_permission_set_policy.json`.
2. Replace `BUCKET_NAME`, `REGION`, `ACCOUNT_ID` and `KMS_KEY_ID`.
3. Set the session length. The default is 1 hour and the maximum is 12 hours. With 8 hours or more, one sign-in covers a workday.
4. Assign it to the billers' Entra group for the billing account.

What the permission set allows:
- List only the CurWork folders (`converted/`, the output folders, `logs/`).
- Read `converted/`.
- Write and read the output folders and `logs/`. Read access lets the app confirm each upload.
- Use the one KMS key.
- Nothing else. There's no delete permission, so a biller can't remove files, and S3 Versioning keeps every replaced copy.

Keep `s3:ListBucket` on the output folders. The app lists the destination to check whether a result is already there before it asks **Replace** or **Skip**.

**The CUR bucket**
- Block Public Access on.
- ACLs off (Object Ownership: bucket owner enforced, the default for new buckets).
- S3 Versioning on, with a lifecycle rule that removes old versions after your retention period.
- Default encryption: SSE-KMS with the customer-managed key.
- Add the statements in `iam/bucket_policy_additions.json`. They refuse any request without TLS, or with TLS older than 1.2.
- Optional: only allow access from the company VPN (`aws:SourceIp`) or a VPC endpoint (`aws:SourceVpce`).

**Audit**
- Turn on CloudTrail data events (read and write) for the bucket and send them to the SIEM. This is the official record of who downloaded and uploaded each file.
- Alert on changes to the bucket policy, the KMS key policy and the biller permission set.

## 4. Build and sign (build owner)

1. Fill in `curwork_admin_settings.json` (section 6). The app won't start until `bucket` is set.
2. On the Windows build machine, run `build_exe.ps1` from the CurWork folder (command below). If any step fails, the build stops. It:
   - creates a clean build environment,
   - installs the runtime packages from `requirements-lock.txt` (exact versions, checked against SHA-256 hashes),
   - installs the build and test tools from `requirements-dev.txt`,
   - runs the tests,
   - checks every installed package for known vulnerabilities with pip-audit,
   - writes a software bill of materials (`sbom-runtime.cdx.json`, CycloneDX format),
   - builds `dist\CurWork.exe` and copies the admin settings file and the SBOM next to it.
3. Sign `CurWork.exe` with the company code-signing certificate.
4. Keep the SBOM with the release.

To update a package: change `requirements.txt`, regenerate `requirements-lock.txt` with `pip-compile --generate-hashes`, then rebuild.

**Packaging note:** the build makes a single-file exe. Single-file PyInstaller apps unpack to a temp folder when they start, which some antivirus tools flag. A folder build with an installer, or running from source with the company's Python, avoids that (open decision in section 9).

Build command (PowerShell, from the CurWork folder):

```powershell
.\build_exe.ps1
```

## 5. Deploy to laptops (IT)

1. Install to `C:\Program Files\CurWork` with the company's deployment tool (for example Intune): `CurWork.exe` and `curwork_admin_settings.json`. Don't include a user preferences file; each user's is created on first use.
2. If AppLocker or WDAC is enforced, allow the signed exe (or `pythonw.exe` running `curwork.py`, if you run from source).
3. If the network inspects HTTPS traffic, exclude `*.amazonaws.com` and `*.awsapps.com`, or give the AWS CLI and CurWork the company CA bundle through `AWS_CA_BUNDLE`. Never turn off certificate checks.
4. Confirm BitLocker and screen lock.
5. If the `sso` section of the admin settings file is filled in, the app adds the AWS profile to each laptop the first time a biller clicks **Sign in**. It only adds; it never rewrites `~/.aws/config`.
6. Pilot: one biller runs the full daily workflow on a test customer before everyone switches over.

## 6. Settings

**Two files, side by side in the tool folder** (next to `CurWork.exe`, or next to `curwork.py` when run from source):

| File | What's in it | Who controls it |
|---|---|---|
| `curwork_admin_settings.json` (protected) | Bucket, Region, AWS profile and sign-in, input and output folders, FIPS, KMS key, work folder, log folder, file types, use notice | The admin |
| `curwork_user_settings.json` (unprotected) | Remember last result type, last result type, recent folders, how many to keep, pinned folders, window size and position, column widths | Each user, in the app's **Settings** window |

How the app protects the split:
- It reads only the preference keys from the user file. Any other key, such as `bucket`, is ignored and noted in the log.
- Bad values in the user file are dropped or kept in range; they never stop the app. Pinned folders outside the admin's browse folders are ignored.
- Settings files larger than 256 KB aren't read.
- The user file is saved through a new temporary file and then renamed, so a crash can't leave it half-written.
- If users can't write to the tool folder (normal in Program Files), the user file is saved in their work folder instead.
- **Finish and clean up** never deletes either file.

**Admin settings reference**

The admin settings live in two places (NIST SP 800-53 AC-3, AC-6, CM-5, CM-6):
- **On each laptop,** in `curwork_admin_settings.json` next to the app: only what CurWork needs before sign-in. That is how to sign in, the Region, the FIPS switch and the use notice.
- **In AWS Systems Manager Parameter Store,** in the parameter `/curwork/admin-settings`: everything else. That includes where data goes, how it's protected and where it's kept on the laptop. AWS decides who can change these settings, not the laptop.

*Settings on each laptop* (`curwork_admin_settings.json`)

| Setting | Default | What it controls |
|---|---|---|
| `sso` | empty | Identity Center session name, start URL (the AWS access portal URL, not an Entra URL), SSO Region, account ID and role name. When filled in, the app sets up the AWS profile at first sign-in. |
| `aws_profile` | `fpt-biller` | AWS profile name on each laptop |
| `region` | `us-east-1` | The AWS Region of the bucket and the parameter |
| `use_fips_endpoint` | `false` | `true` sends CurWork's own AWS calls to FIPS 140-3 validated endpoints. The AWS CLI sign-in follows its own profile settings. |
| `aws_cli_path` | empty | Full path to `aws.exe`. Empty means Program Files, then PATH, never the current folder. |
| `login_banner` | empty | System-use notice shown before sign-in (NIST AC-8). The biller must click OK to continue. |
| `settings_parameter` | `/curwork/admin-settings` | The Parameter Store name that holds the other settings. Leave it out to use the default. |

CurWork refuses to start if this file holds any other setting, and the message names each one. That way a setting kept in AWS can never be overridden on a laptop. Keys that start with `_` are notes and are ignored. Keep `_version` up to date with the version and date/time of each change.

*Settings kept in Parameter Store* (changed with the CurWork Admin Settings app)

| Setting | Default | What it controls |
|---|---|---|
| `bucket` | none (required) | The S3 bucket that holds the CUR workbooks |
| `kms_key_id` | empty | Empty uses the bucket's default encryption. A key ID forces that key on every file saved in S3. |
| `browse_roots` | `["converted/"]` | Folders billers can download from. Must not overlap the output folders. |
| `output_stages` | Priced, Allocated, Mapped, Split by account, Reports | Result types in the drop-down and the S3 folder each one is saved in. Every folder here must also be in the permission set. |
| `default_stage` | `Priced` | Result type shown first, unless the user's "remember last result type" is on |
| `log_prefix` | `logs/` | S3 folder for the logs saved at Finish |
| `work_dir` | `%LOCALAPPDATA%\CurWork` | Work folder on each laptop. Must not be inside OneDrive, Box or another sync folder. Use `\\` or `/` in paths. |
| `user_settings_location` | `tool_folder` | `tool_folder` (next to the app; work folder if users can't write there) or `work_folder` (each user's own work folder) |
| `upload_extensions` | `.xlsx .xlsm .xlsb .xls .csv .txt .zip` | File types billers can save in S3 |
| `large_download_warning_mb` | `2048` | Asks before downloading more than this |
| `max_concurrency` | `8` | Files copied at the same time (1 to 32) |

**How the app finds the laptop settings file:** the built app (`CurWork.exe`, or `CurWork.app` on a Mac) only reads the file installed next to it. It ignores `--config`, the `CURWORK_CONFIG` environment variable and `%APPDATA%\CurWork\`, so a biller can't point it at a settings file of their own. If someone tries, the app writes a warning to the log naming what it ignored. If the installed file is missing, the app won't start and names the one place the file must go. When CurWork runs from source (`python curwork.py`), it still accepts `--config` and `CURWORK_CONFIG`, then looks next to `curwork.py`, then in `%APPDATA%\CurWork\`. If the file named by `--config` or `CURWORK_CONFIG` doesn't exist, CurWork stops with an error instead of quietly using a different file. Anyone who can run the source can also change it, so a lock there would add nothing, and the tests need these options.

**How CurWork reads the settings kept in Parameter Store**

- CurWork reads the parameter right after each sign-in. Until then it won't use S3. If it can't read the parameter, it stops and says so. It never falls back to other settings.
- Before sign-in, CurWork uses the default work folder. If the parameter names a different work folder, CurWork switches to it right after sign-in. Today's log moves with it, so one log file holds the whole session. If files were left in the default folder, CurWork tells the biller where they are.
- Settings found in the parameter that belong on the laptop are ignored, and CurWork writes a warning to the log.
- The biller permission set may only read parameters under `/curwork/` (`ssm:GetParameter`). It can't change or delete them. Give `ssm:PutParameter` on the parameter only to the AWS admin role.
- Parameter Store keeps every saved version, and CloudTrail records who saved each one (AU-2, AU-12). The parameter is a Standard-tier `String` with no secrets in it, so it costs nothing and needs no KMS key.

**The CurWork Admin Settings app** (`curwork_admin.py`) is how admins view and change the managed settings. Run it with the AWS admin profile:

```
python curwork_admin.py --profile <admin profile>
```

- **Sign in** opens the browser for the admin sign-in. **Load from AWS** reads the current version.
- The form checks every value with the same rules CurWork uses before anything is saved. **Save in AWS** lists each change and asks you to confirm it.
- If another admin saved a newer version after you clicked Load from AWS, nothing is saved. Load their version first, then make your change again.
- **Copy from this laptop's settings file** copies the settings kept in AWS out of an older `curwork_admin_settings.json` that still holds them. Use it once to move an older install to Parameter Store, then remove those settings from the laptop file. To create the parameter from scratch, fill in the form and click **Save in AWS**.
- **History** lists every saved version, when it was saved and who saved it.
- A sign-in without permission to change the parameter, such as a biller's, gets a message saying that only the AWS admin role can change the settings. The app doesn't decide this itself; AWS refuses the save.

**User preferences reference**

| Preference | Default | What it does |
|---|---|---|
| `remember_result_type` | `true` | Starts step 3 on the last result type used |
| `last_result_type` | empty | Saved automatically when the result type changes |
| `recent_folders` | empty | Recent customer/month folders, newest first |
| `recent_limit` | `10` | How many recent folders to keep (0 to 25; 0 turns it off) |
| `pinned_folders` | empty | Pinned S3 folders (up to 25, only inside the browse folders) |
| `window_geometry` | empty | Window size and position, moved back on screen if a monitor was removed |
| `column_widths` | empty | Column widths in the two lists |

## 7. Day-to-day admin tasks

- **Change an admin setting:** change it in the CurWork Admin Settings app. Billers get it the next time they sign in. Only the sign-in settings need a new laptop file: edit it, update `_version`, redeploy it, and ask billers to restart CurWork.
- **Add a result type:** add it to `output_stages` and add the same folder to the permission set (the `ListBucket` prefixes and the write resources). Keep it separate from the browse folders.
- **Add a customer:** nothing to do in CurWork. New customer folders appear in the S3 browser once the converted files are in S3.
- **Release a new version:** build, sign, deploy. The admin and user settings files stay as they are.
- **Monitor:** CloudTrail data events in the SIEM are the official record. Each biller's log is also uploaded to `logs/<user>/<date>/` at Finish, for troubleshooting. Local logs stay on the laptop for 14 days.
- **Remove a biller:** remove them from the Entra group or the permission set assignment. Credentials already issued keep working until they expire (up to the session length). To cut them off sooner, follow AWS's guidance on revoking active sessions for a permission set.
- **Lost or stolen laptop:** BitLocker protects the disk. Remove the user's access, then check CloudTrail for that user. Files on the laptop are limited to work that wasn't cleaned up.

## 8. Security design

**Where the data is and what protects it**

| Stage | Where the data is | Protection |
|---|---|---|
| Stored | S3 bucket | SSE-KMS, Block Public Access, Versioning, no delete for billers, CloudTrail |
| Moving | Between S3 and the laptop | TLS 1.2 or higher (enforced by the bucket policy); FIPS endpoints optional on the AWS side |
| Downloading | In folder | Lands as `.part` and is renamed only when the size matches S3 |
| Working | In and Out folders | BitLocker; Excel works on local copies only |
| Uploading | Out folder to S3 | SHA-256 checksum checked by S3, then the size is confirmed; files open in Excel are never uploaded |
| After the session | Laptop | **Finish and clean up** empties In and Out; leftovers are flagged at the next start and at close |

**Built into the app**
- Temporary credentials only. No access keys are stored anywhere.
- Uploads only into the admin's output folders; inputs are read-only by design.
- S3 file names are checked before they become local file names, which blocks `..` tricks and names Windows doesn't allow.
- Never runs an `aws.exe` from the current folder, which blocks binary planting. The path can be pinned.
- Starts the AWS CLI with a fixed list of arguments and no shell.
- Files open in Excel are never uploaded, replaced or deleted.
- Warns if the work folder is inside a cloud-sync folder.
- Optional use notice at start-up.
- The user preferences file can't change admin settings (section 6).

**Must be set on AWS:** the permission set and session length, the bucket settings, CloudTrail data events and alerts (section 3).

**Must be set on the laptop:** BitLocker, screen lock, the signed app in Program Files, AppLocker or WDAC rules, and HTTPS inspection handled without turning off certificate checks.

**Checks run in this review (2026-11-22)**
- pip-audit: no known vulnerabilities in the runtime or build packages.
- bandit (Python security scanner): no medium or high findings. The low findings are expected: the app starts the AWS CLI and the folder viewer with fixed arguments and no shell.
- 60 automated tests pass, plus 1 that needs a non-root Mac or Linux account. Window tests drive the real window through sign-in, browse, small and multipart downloads, upload, refusals, About, Settings, Finish and the self-test, and check CurWork's calls fit inside the biller policy (the mock checks actions and resources, not conditions; the real AWS tests check the conditions).
- Fixed in this review:
  - The check for an existing result now uses a listing. With the prefix-limited permission set, the old check (HeadObject) could get "access denied" instead of "not found" for a new file.
  - The build script now stops when tests or pip-audit fail.
  - Runtime packages are locked to exact versions with hashes, and the build writes an SBOM.
  - Settings files have a size limit and a safer save.
- Mac test (2026-11-22): the Mac check passed (Python 3.12.13, Tk 9.0.3, AWS CLI 2.35.14). A test bucket with all samples (including a 116 MB, 3.2-million-row workbook) passed 11 of 11 checks. CurWork signs in with a test permission set, **CurWorkBillerTest**, built from `iam/biller_permission_set_policy.json` and limited to test buckets, so the test checks the real least-privilege access (NIST SP 800-53 AC-6). The first test role, AWSReadOnlyAccess, turned out to carry only AWS's ViewOnlyAccess policy, which can list but not read S3 files. The admin profile is used only to create the test bucket and permission set. Scripts are in `mac-test-kit/`.
- Not yet done: the app run against AWS on the Mac; a run on a Windows biller laptop with real Excel; a test with the real biller permission set. The updated build script hasn't been run on Windows yet.

**NIST SP 800-53 Rev. 5 mapping**

| Control | What covers it | Where | Status |
|---|---|---|---|
| AC-3, AC-6 Least privilege | Permission set lists only the CurWork folders, reads `converted/`, writes the output folders and `logs/`, no delete. The app also refuses uploads outside the output folders. | AWS + app | Met |
| AC-8 Use notice | Optional `login_banner`; the biller must click OK to continue | App | Met if set |
| AC-11 Idle lock | Windows screen lock and session expiry; the app has no lock of its own | Laptop | By design |
| AC-12 Session end | Permission set session length (1 to 12 hours) | AWS | Met |
| AU-2, AU-3, AU-12 Audit events | CloudTrail data events for every S3 read and write, sent to the SIEM; local log with actions and file names | AWS + app | Met |
| AU-9 Protect audit data | Billers can edit local logs, so CloudTrail is the official record | AWS | By design |
| AU-10 Non-repudiation | Identity comes from Identity Center and CloudTrail; the Windows user name in logs and S3 metadata is for convenience only | AWS | By design |
| CM-5, CM-6 Config control | Admin settings in Program Files; user preferences can't change them. The built app only reads the admin settings installed next to it and ignores `--config` and `CURWORK_CONFIG` (config lock). IT still has to make the install folder read-only for billers. | IT + app | Met (app); IT to confirm folder permissions |
| CM-7, SI-7 Least function, integrity | No `aws.exe` from the current folder; fixed arguments, no shell | App | Met |
| CM-14, SI-7(15) Signed software | Sign the exe before deployment; allow only the signed app | IT | Process |
| IA-2 MFA | Entra sign-in with MFA through Identity Center | Entra + AWS | Met |
| IA-5 Authenticators | No access keys; temporary credentials and an SSO token cache that expire | AWS CLI | Met |
| MP-6 Media sanitization | Deleting from an SSD isn't sanitization; BitLocker protects the copies | Laptop | Needs BitLocker |
| RA-5, SI-2 Vulnerabilities, patching | pip-audit in every build; keep Python and the AWS CLI patched | Build + IT | Process |
| SC-8 Encryption in transit | TLS everywhere; the bucket policy refuses non-TLS and TLS older than 1.2 | AWS | Met |
| SC-13 Validated crypto | FIPS endpoints are available on the AWS side. The laptop end uses the OpenSSL that ships with Python, which isn't a FIPS-validated module. | App | Open |
| SC-28 Encryption at rest | SSE-KMS on the bucket, BitLocker on the laptop | AWS + laptop | Met |
| SI-10 Input checks | S3 file names and destination folders are checked; settings files are size-limited and validated | App | Met |
| SR-3, SR-4 Supply chain | Runtime packages locked with hashes, SBOM per build, pip-audit per build | Build | Met |

The design also follows the AWS Well-Architected Framework: the Security pillar (temporary credentials, least privilege, traceability, encryption) and the Reliability pillar (retries, checksums, versioning).

## 9. Risks and open decisions

**Risks still open**
- Laptop-side TLS isn't FIPS-validated (SC-13).
- Billers can edit their local logs. CloudTrail is the official record.
- No check-out lock between billers. S3 Versioning keeps every replaced copy.
- While a session is open, customer data sits on the laptop. BitLocker and Finish limit that.
- In the tool folder, the user preferences file is shared by everyone who uses that laptop, and it can name customers (recent and pinned folders).

**Decisions to make**
- [ ] **Laptop-side FIPS (SC-13):** if your data or contract needs it, choose one: (1) send S3 traffic through the agency's FIPS-validated VPN, (2) build Python against an OpenSSL 3 FIPS provider with a valid CMVP certificate, or (3) rewrite the transfer part in .NET so Windows' own crypto handles TLS with Windows FIPS mode on.
- [ ] **Entra connection:** confirm Entra connects through IAM Identity Center.
- [ ] **Packaging:** single-file exe, folder build with an installer, or run from source.
- [ ] **HTTPS inspection:** confirm whether the proxy inspects AWS traffic and which fix IT prefers.
- [x] **Config lock:** done 2026-11-22 20:56 UTC. The built app only reads the admin settings installed next to it.
- [ ] **Settings file permissions:** who can read and write each file, and whether user preferences stay in the tool folder or move to each user's work folder (`user_settings_location`).

## 10. Change log

| Date and time (UTC) | Version | Change | Modified by |
|---|---|---|---|
| 2026-11-22 23:57 | Beta 0.013 | Smallest possible laptop file (NIST SP 800-53 CM-5, CM-6): `curwork_admin_settings.json` may only hold the sign-in settings, the Region, the FIPS switch and the use notice, and CurWork refuses it otherwise. Parameter Store is now required, and also holds the work folder (`work_dir`) and the preferences location (`user_settings_location`). CurWork switches to the admin's work folder right after sign-in and moves today's log with it, so one log holds the whole session (AU-9). | mbitar |
| 2026-11-22 23:33 | Beta 0.012 | Plain wording: CurWork and the admin settings app now say "save in S3" instead of "send" or "upload". The admin app's buttons are now **Load from AWS**, **Save in AWS** and **Copy from this laptop's settings file**. The program folder is now `CurWork-app`. New tests prove that billers can only read the settings kept in AWS and that only an admin can save them (NIST SP 800-53 AC-3, AC-6, CM-5). | mbitar |
| 2026-11-22 22:44 | Beta 0.011 | Managed settings (NIST SP 800-53 AC-3, CM-5, AU-12): the settings that decide where data goes can live in AWS Parameter Store. Billers can only read them, only the AWS admin role can change them, and the new CurWork Admin Settings app is how admins change them. | mbitar |
| 2026-11-22 21:50 | Beta 0.011 | Running from source: if the settings file named by `--config` or `CURWORK_CONFIG` doesn't exist, CurWork stops with an error. Before, it quietly used the settings file next to `curwork.py` instead (NIST SP 800-53 CM-6). | mbitar |
| 2026-11-22 20:56 | Beta 0.011 | Config lock (NIST SP 800-53 CM-5, CM-6): the built app only reads the admin settings installed next to it. `--config`, `CURWORK_CONFIG` and `%APPDATA%` are ignored there and logged; the self-test checks the lock. Running from source is unchanged. 3 new tests; 71 pass. | mbitar |
| 2026-11-22 18:13 | Beta 0.011 | Source control: AWS account numbers, sign-in URLs and profile names are kept in a private, Git-ignored `curwork_test.env`; commit and push checks block them (NIST SP 800-53 AC-22 Publicly Accessible Content, SA-11 developer testing). AWS doesn't class account IDs as secret, but keeping them, sign-in URLs and profile names out of a shared repository limits what an outsider can learn about the environment. The admin settings file is not stored in Git. | mbitar |
| 2026-11-22 17:09 | Beta 0.011 | Testing: window tests, app self-test (`--self-test`), and a Mac runner that also tests the biller permission set against real AWS (allowed calls work; writes to `converted/`, deletes and whole-bucket listing are refused). | mbitar |
| 2026-11-22 16:53 | Beta 0.011 | Mac test moved to a CurWorkBillerTest permission set built from the biller policy (test buckets only); the AWSReadOnlyAccess set has only ViewOnlyAccess (no s3:GetObject). Built Mac app now reads admin settings next to CurWork.app. Refusal messages name the AWS call refused. | mbitar |
| 2026-11-22 16:14 | Beta 0.011 | Mac: a built CurWork.app reads its admin and user settings from the folder next to the .app, never inside it (changing files in a signed bundle breaks its signature). Windows: the exe has the CurWork icon and its own taskbar identity. New About window shows versions and paths for support; it shows no keys or tokens. 49 tests pass. | mbitar |
| 2026-11-22 14:58 | Beta 0.011 | Testing status updated: Mac check results, read-only real-AWS test plan, `mac-test-kit/`. | mbitar |
| 2026-11-22 13:42 | Beta 0.011 | First version of this guide. Admin and security content moved here from the CurWork Guide and the README. Adds roles, the control-layers exhibit (online copy), deployment, day-to-day tasks, data protection by stage, and the checks and fixes from this review. | mbitar |

---
*DRAFT - For Internal Use (FPT) · Beta 0.013 · Updated 2026-11-22 23:56 UTC · Modified by: mbitar*
