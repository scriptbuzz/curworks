# Third-party notices

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.015** · Updated 2026-11-23 00:55 UTC · Modified by: mbitar

CurWork belongs to FPT (see the [LICENSE](LICENSE)), but it's built on the open source parts listed below. Their authors own them, and each one keeps its own license. The versions are the ones locked in `CurWork-app/requirements-lock.txt` today. If the lock file changes, check this list again.

| Component | Version | License | Used for |
|---|---|---|---|
| Python | 3.12 | PSF License 2.0 | Language runtime (bundled in the built app) |
| Tcl/Tk (tkinter) | 8.6 / 9.0 | Tcl/Tk license (BSD-style) | The window (bundled in the built app) |
| boto3 | 1.44.9 | Apache-2.0 | AWS SDK for Python |
| botocore | 1.44.9 | Apache-2.0 | AWS SDK core |
| s3transfer | 0.19.3 | Apache-2.0 | S3 uploads and downloads |
| jmespath | 1.1.0 | MIT | Used by botocore |
| python-dateutil | 2.9.0.post0 | Apache-2.0 or BSD-3-Clause (dual) | Used by botocore |
| six | 1.17.0 | MIT | Used by python-dateutil |
| urllib3 | 2.8.0 | MIT | HTTPS connections |

These tools are used to build and test CurWork. They aren't shipped inside it, except for a small part of PyInstaller that starts the built app:

| Tool | License |
|---|---|
| PyInstaller | GPL-2.0 with a bootloader exception that allows bundling proprietary apps |
| pytest | MIT |
| moto | Apache-2.0 |
| pip-audit | Apache-2.0 |
| XlsxWriter (large sample maker) | BSD-2-Clause |

Each package includes its full license text, and you can also read it on the package's page at https://pypi.org. Before CurWork goes to anyone outside the test group, check every package's current license and include the notices it asks for.

---
*DRAFT - For Internal Use (FPT) · Beta 0.015 · Updated 2026-11-23 00:55 UTC · Modified by: mbitar*
