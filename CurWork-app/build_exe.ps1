# CurWork Beta 0.016 - DRAFT - For Internal Use (FPT) - updated 2026-11-23 01:23 UTC - modified by: mbitar
# Builds dist\CurWork.exe (for billers) and dist\CurWorkAdmin.exe (for admins) on a Windows build machine.
# CurWork.exe is built without the admin code, so billers' copy can't change any settings.
# Run from this folder in PowerShell:  .\build_exe.ps1
#
# Every step must succeed. In Windows PowerShell, "$ErrorActionPreference = Stop" does NOT stop
# on a failing program (pip, pytest, pip-audit), so each step checks the exit code itself.

$ErrorActionPreference = "Stop"

function Invoke-Step([string]$What, [scriptblock]$Command) {
    Write-Host "== $What"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed (exit code $LASTEXITCODE). The build stopped."
    }
}

$py = ".\.venv\Scripts\python.exe"

Invoke-Step "Create a clean build environment" { py -3.12 -m venv --clear .venv }
Invoke-Step "Update pip" { & $py -m pip install --upgrade pip }
Invoke-Step "Install runtime packages (exact versions, hash-checked)" { & $py -m pip install --require-hashes -r requirements-lock.txt }
Invoke-Step "Install build and test tools" { & $py -m pip install -r requirements-dev.txt }
Invoke-Step "Run the tests" { & $py -m pytest -q }
Invoke-Step "Check every installed package for known vulnerabilities" { & $py -m pip_audit --strict }
Invoke-Step "Write the software bill of materials (runtime packages)" { & $py -m pip_audit --require-hashes -r requirements-lock.txt -f cyclonedx-json -o sbom-runtime.cdx.json }
Invoke-Step "Build CurWork.exe" { & $py -m PyInstaller --noconfirm --onefile --windowed --name CurWork --icon assets\curwork.ico --add-data "assets;assets" --exclude-module curwork_admin curwork.py }
Invoke-Step "Build CurWorkAdmin.exe" { & $py -m PyInstaller --noconfirm --onefile --windowed --name CurWorkAdmin --icon assets\curwork.ico --exclude-module curwork curwork_admin.py }

# The admin settings file is never stored in Git. Use the real one if it's here; otherwise copy the
# example so the self-test can run, and say clearly that it must be replaced before handing CurWork out.
if (Test-Path curwork_admin_settings.json) {
    Copy-Item curwork_admin_settings.json dist\ -Force
    $usingExample = $false
} else {
    Copy-Item curwork_admin_settings.example.json dist\curwork_admin_settings.json -Force
    $usingExample = $true
}
Copy-Item sbom-runtime.cdx.json dist\ -Force

# Self-test the built exe. It's a window app with no console, so it writes its report to a file,
# and PowerShell must wait for it to finish.
Write-Host "== Self-test of dist\CurWork.exe"
$report = Join-Path (Resolve-Path dist) "self_test_report.json"
Remove-Item $report -ErrorAction SilentlyContinue
$proc = Start-Process -FilePath "dist\CurWork.exe" -ArgumentList "--self-test", "--report", "`"$report`"" -Wait -PassThru
if (-not (Test-Path $report)) { throw "The self-test didn't write a report. The build stopped." }
$result = Get-Content $report -Raw | ConvertFrom-Json
foreach ($c in $result.checks) {
    if ($c.skipped) { $tag = "SKIP" } elseif ($c.ok) { $tag = "PASS" } else { $tag = "FAIL" }
    Write-Host ("  {0}  {1}" -f $tag, $c.check)
    if ($c.detail) { Write-Host ("          {0}" -f $c.detail) }
}
if ($proc.ExitCode -ne 0 -or -not $result.passed) { throw "The built CurWork.exe failed its self-test. The build stopped." }

Write-Host "== Self-test of dist\CurWorkAdmin.exe (window and form only; it doesn't sign in or call AWS)"
$areport = Join-Path (Resolve-Path dist) "admin_self_test_report.json"
Remove-Item $areport -ErrorAction SilentlyContinue
$aproc = Start-Process -FilePath "dist\CurWorkAdmin.exe" -ArgumentList "--self-test", "--report", "`"$areport`"" -Wait -PassThru
if (-not (Test-Path $areport)) { throw "The admin self-test didn't write a report. The build stopped." }
$aresult = Get-Content $areport -Raw | ConvertFrom-Json
foreach ($c in $aresult.checks) {
    if ($c.ok) { $tag = "PASS" } else { $tag = "FAIL" }
    Write-Host ("  {0}  {1}" -f $tag, $c.check)
}
if ($aproc.ExitCode -ne 0 -or -not $aresult.passed) { throw "The built CurWorkAdmin.exe failed its self-test. The build stopped." }

Write-Host "Built dist\CurWork.exe and dist\CurWorkAdmin.exe with curwork_admin_settings.json and sbom-runtime.cdx.json. Both self-tests passed."
Write-Host "Give billers CurWork.exe only. CurWorkAdmin.exe is for admins."
if ($usingExample) {
    Write-Warning "dist\curwork_admin_settings.json is only the EXAMPLE (no sign-in details). Replace it with the real admin settings file before anyone uses this build."
}
Write-Host "Sign both .exe files with the company code-signing certificate before handing them out."
