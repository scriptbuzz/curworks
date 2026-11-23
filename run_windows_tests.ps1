# CurWork Beta 0.017 - DRAFT - For Internal Use (FPT) - Windows test runner - updated 2026-11-23 01:38 UTC - modified by: mbitar
#
# Runs CurWork's automated tests on a Windows 11 test machine and saves one PASS/FAIL report
# (windows_tests_results.txt, which Git ignores). Run it from the top folder of the repository:
#
#   .\run_windows_tests.ps1                      # uses the existing admin settings file
#   .\run_windows_tests.ps1 -Bucket <test bucket> # first time: makes the admin settings file for that bucket
#
# Parts:
#   1. Unit tests (mocked S3)
#   2. Window tests (mocked S3; CurWork windows flash up briefly)
#   3. Real AWS tests with CurWork's own code and the biller test sign-in. Uploads two small test files,
#      checks that billers can't write to converted/, delete, or list the whole bucket, then removes the
#      test files with your admin profile.
#   4. Self-test of CurWork from source, and of dist\CurWork.exe if it has been built
#
# Needs: build_exe.ps1 run once in CurWork-app (it creates .venv), and curwork_test.env filled in.

param([string]$Bucket = "")

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Tool = Join-Path $Root "CurWork-app"
$Py   = Join-Path $Tool ".venv\Scripts\python.exe"
$Results = Join-Path $Root "windows_tests_results.txt"
$script:Failed = 0
$script:Parts = @()

function Pass([string]$m) { Write-Host "  PASS  $m" -ForegroundColor Green }
function Fail([string]$m) { Write-Host "  FAIL  $m" -ForegroundColor Red; $script:Failed++ }
function Part([string]$name, [bool]$ok) { $script:Parts += [pscustomobject]@{ Name = $name; Ok = $ok } }

Start-Transcript -Path $Results -Force | Out-Null
try {
    Write-Host ("== CurWork Windows tests - {0:yyyy-MM-dd HH:mm} UTC" -f (Get-Date).ToUniversalTime())

    # ---- Checks before starting ----
    if (-not (Test-Path $Py)) { throw "CurWork's .venv isn't set up. In CurWork-app run .\build_exe.ps1 once first." }
    $envFile = Join-Path $Root "curwork_test.env"
    if (-not (Test-Path $envFile)) { throw "curwork_test.env is missing. Copy curwork_test.env.example to curwork_test.env and fill it in." }

    # Load the private test settings into this PowerShell session only (they're never written anywhere else).
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), "Process")
        }
    }
    foreach ($pair in @(@("CURWORK_SSO_REGION", "us-east-1"), @("CURWORK_SSO_SESSION", "curwork-test"),
                        @("CURWORK_PROFILE", "curwork-biller"), @("CURWORK_ROLE", "CurWorkBillerTest"))) {
        if (-not [Environment]::GetEnvironmentVariable($pair[0], "Process")) {
            [Environment]::SetEnvironmentVariable($pair[0], $pair[1], "Process")
        }
    }
    foreach ($name in @("CURWORK_ACCOUNT", "CURWORK_ADMIN_PROFILE", "CURWORK_SSO_START_URL")) {
        $v = [Environment]::GetEnvironmentVariable($name, "Process")
        if (-not $v -or $v -in @("000000000000", "your-admin-profile", "https://your-org.awsapps.com/start")) {
            throw "Set $name in curwork_test.env (it's missing or still the example value)."
        }
    }

    # Make or update the admin settings file for the test bucket, from the example (the real file is never in Git).
    $admin = Join-Path $Tool "curwork_admin_settings.json"
    if ($Bucket -or -not (Test-Path $admin)) {
        if (-not $Bucket) { throw "There's no admin settings file yet. Run again with -Bucket <name of the test bucket>." }
        # The laptop file only holds the sign-in settings. The bucket is kept in AWS Parameter Store.
        $cfg = Get-Content (Join-Path $Tool "curwork_admin_settings.example.json") -Raw | ConvertFrom-Json
        $cfg.aws_profile = $env:CURWORK_PROFILE
        $cfg.sso = [pscustomobject]@{
            session_name = $env:CURWORK_SSO_SESSION; start_url = $env:CURWORK_SSO_START_URL
            sso_region = $env:CURWORK_SSO_REGION; account_id = $env:CURWORK_ACCOUNT; role_name = $env:CURWORK_ROLE }
        $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $admin -Encoding UTF8
        Write-Host "Laptop settings written (sign-in: $($env:CURWORK_ROLE), profile $($env:CURWORK_PROFILE))."
        # Save the bucket in Parameter Store with the admin profile. Billers can only read it.
        & $Py -c "import sys; sys.path.insert(0, sys.argv[1]); import curwork_core as core, curwork_admin as admin; s = core.load_settings(sys.argv[2]); st = admin.AdminStore(s.settings_parameter, s.region, profile=sys.argv[3]); m, v = st.load(); m = dict(m or {}); m['bucket'] = sys.argv[4]; print('Saved the bucket in Parameter Store', s.settings_parameter, 'version', st.save(m, v))" $Tool $admin $env:CURWORK_ADMIN_PROFILE $Bucket
        if ($LASTEXITCODE -ne 0) { throw "Couldn't save the bucket in Parameter Store with the admin profile. Sign in with it (aws sso login --profile $($env:CURWORK_ADMIN_PROFILE)) and run again." }
    }
    # CurWork.exe reads the admin settings file next to it, so keep the built copy in step with the test one.
    $distDir = Join-Path $Tool "dist"
    if (Test-Path (Join-Path $distDir "CurWork.exe")) { Copy-Item $admin $distDir -Force }

    # ---- 1 and 2. Unit and window tests ----
    Write-Host "`n== 1 of 4. Unit tests"
    Push-Location $Tool
    & $Py -m pytest -q -p no:cacheprovider tests\test_core.py tests\test_admin.py | Out-Host   # Out-Host: keeps the output in the report
    $ok = ($LASTEXITCODE -eq 0); if ($ok) { Pass "Unit tests" } else { Fail "Unit tests (see above)" }
    Part "1 (unit tests)" $ok

    Write-Host "`n== 2 of 4. Window tests (windows flash up briefly; don't click them)"
    & $Py -m pytest -q -p no:cacheprovider tests\test_gui.py | Out-Host
    $ok = ($LASTEXITCODE -eq 0); if ($ok) { Pass "Window tests" } else { Fail "Window tests (see above)" }
    Part "2 (window tests)" $ok
    Pop-Location

    # ---- 3. Real AWS tests ----
    Write-Host "`n== 3 of 4. Real AWS tests"
    Push-Location $Root
    & $Py tools\real_aws_tests.py | Out-Host
    $ok = ($LASTEXITCODE -eq 0); if (-not $ok) { $script:Failed++ }
    Part "3 (real AWS)" $ok
    Pop-Location

    # ---- 4. Self-tests ----
    Write-Host "`n== 4 of 4. Self-tests"
    $before = $script:Failed
    $targets = @(,@("CurWork from source", $Py, @((Join-Path $Tool "curwork.py"))))
    $exe = Join-Path $Tool "dist\CurWork.exe"
    if (Test-Path $exe) { $targets += ,@("dist\CurWork.exe", $exe, @()) } else { Write-Host "  (dist\CurWork.exe isn't built yet, so only the source is checked)" }
    foreach ($t in $targets) {
        $report = Join-Path $env:TEMP ("curwork_self_test_{0}.json" -f [guid]::NewGuid())
        $argList = @()
        foreach ($a in $t[2]) { $argList += "`"$a`"" }          # quote paths: folder names can have spaces
        $argList += @("--self-test", "--report", "`"$report`"")
        $proc = Start-Process -FilePath $t[1] -ArgumentList $argList -Wait -PassThru -WindowStyle Hidden
        if (-not (Test-Path $report)) { Fail "$($t[0]): no self-test report"; continue }
        $r = Get-Content $report -Raw | ConvertFrom-Json
        Remove-Item $report -ErrorAction SilentlyContinue
        foreach ($c in $r.checks) {
            if ($c.skipped) { Write-Host "  SKIP  $($t[0]): $($c.check)" -ForegroundColor Yellow }
            elseif ($c.ok) { Pass "$($t[0]): $($c.check)" }
            else { Fail "$($t[0]): $($c.check)"; if ($c.detail) { Write-Host "          $($c.detail)" } }
        }
        if ($proc.ExitCode -ne 0 -and $r.passed) { Fail "$($t[0]) exited with code $($proc.ExitCode)" }
    }
    Part "4 (self-tests)" ($script:Failed -eq $before)

    # ---- Summary ----
    Write-Host "`n== Summary"
    foreach ($p in $script:Parts) {
        if ($p.Ok) { Pass "Part $($p.Name)" } else { Write-Host "  FAIL  Part $($p.Name)" -ForegroundColor Red }
    }
    if ($script:Failed -eq 0) {
        Write-Host "`n== Done. All Windows tests passed. CurWork is ready to test by hand." -ForegroundColor Green
    } else {
        Write-Host "`nSTOPPED: $($script:Failed) problem(s) found. Send windows_tests_results.txt for review before testing by hand." -ForegroundColor Red
    }
}
catch {
    Write-Host "`nSTOPPED: $($_.Exception.Message)" -ForegroundColor Red
    $script:Failed++
}
finally {
    Stop-Transcript | Out-Null
}
exit [int]($script:Failed -gt 0)
