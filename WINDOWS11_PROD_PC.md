# curworks on a Windows 11 Production PC

_Last modified: 2026-11-25 12:35 EST_

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.017** · Updated 2026-11-25 17:35 UTC · Modified by: mbitar

**curworks** ([scriptbuzz/curworks](https://github.com/scriptbuzz/curworks)) is a PoC of CurWork, a Python desktop app for FPT's billing team. It runs from its Python code or as CurWork.exe, a single file built from that code. A biller signs in to AWS with their company account, and CurWork copies cost report workbooks from Amazon S3 to the PC. It saves the biller's results back to S3, checks them and empties its work folders. It stores no passwords or AWS keys. It has been tested on a Mac.

This page answers two questions: can curworks run on a production Windows 11 PC, and what needs a Windows administrator password?

[Back to the README](README.md)

## Answer so far

**Probably yes, without a Windows administrator.** This comes from the code and vendor documentation. Nothing has been run on Windows. The PC's policies and network decide, so run Check 1.

- "Administrator" means a Windows administrator of the PC, not the AWS administrator.
- Reported by the user, not checked: the user has no administrator password, and Python is installed.
- Microsoft Office is out of scope.

There are three ways to run CurWork:

| Way | Administrator needed? | Requires |
|---|---|---|
| **1. Python command** | No | Python 3.10 or newer with tkinter, seven Python packages, CurWork's code, AWS CLI |
| **2. CurWork.exe in a user folder** | No | CurWork.exe (not built yet), AWS CLI |
| **3. CurWork.exe in C:\Program Files** | **Yes** | The same as 2, copied by a Windows administrator |

With ways 1 and 2, users can edit the settings file, so use only the test bucket. Way 3 prevents that.

## What needs a Windows administrator

| Part | Administrator needed? | What company policy can block |
|---|---|---|
| AWS CLI version 2 | No with AWSCLIV2-User.msi (one user). **Yes** with AWSCLIV2.msi (all users). | One-user installs, or aws.exe |
| Python 3.10 or newer | No, if it is already installed | python.exe |
| Seven Python packages (way 1) | No | Downloads from pypi.org |
| CurWork's code (way 1) | No | Running code that IT hasn't approved |
| CurWork.exe in a user folder (way 2) | No | Unsigned apps |
| CurWork.exe in C:\Program Files (way 3) | **Yes** | Unsigned apps |
| Connection to AWS | No | The connection, through a firewall, proxy or HTTPS inspection |
| Wrong clock | **Yes**, by default | |

## Tell IT first

These steps are part of a planned test, but security tools may report or block them, because attackers do similar things. Before you run anything, send this section to IT and the security team with the PC name, the user, the planned time and the link to the reviewed version of this page. Wait for their yes.

**No step needs a security tool to be paused, or an exception to be added.** If a tool blocks a step or shows a warning, stop, do not try again, and tell IT.

| Step | What it does | Why a security tool may react | Alert likely? |
|---|---|---|---|
| All blocks | A long block is pasted into PowerShell | Pasted scripts are a common way to attack a PC. PowerShell logs may keep the whole block. | **Yes** |
| Check 1, step 1 | Runs `whoami /groups` | It shows the rights of the user | **Yes** |
| Check 1, step 1 | Reads the AppLocker, App Control, Smart App Control and SmartScreen rules | It shows which security rules protect the PC | **Yes** |
| Check 1, steps 2 and 3 | Looks for Python and the AWS CLI in the registry and on the PATH, and runs them | PowerShell starts other programs, and Python runs short code from the command line | Possibly |
| Check 1, steps 4 and 5 | Uses `curl.exe` to contact seven AWS and Microsoft addresses | Many connections in a row can look like a network scan | Possibly |
| Check 1, step 4 | Python connects to AWS without the proxy | It can look like an attempt to go around the proxy | Possibly |
| Check 1, steps 3 and 4 | Reads the Windows Installer and proxy settings | It shows how the PC is set up | Less likely |
| Check 2, steps 1 and 2 | Creates a Python program in the user folder, and downloads seven packages from pypi.org | New programs in a user folder and downloaded code are watched closely | **Yes** |
| Check 2, step 3 | Runs CurWork's code, which is not signed, and calls AWS | Unsigned code connects to the internet | Possibly |
| After Check 2, sign-in | The AWS CLI opens the browser and waits for an answer on 127.0.0.1 | A program waits for a network connection | Possibly |
| After Check 2, save to S3 | Uploads a sample workbook to Amazon S3 | Data loss prevention watches uploads | **Yes** |
| Clean-up, step 1 | Lists the running programs | It shows what runs on the PC | Less likely |
| Clean-up, step 3 | Signs out of AWS | The AWS CLI deletes its saved sign-ins | Less likely |
| Clean-up, step 4 | Opens the AWS config file | Attackers look for cloud settings there | Possibly |
| Clean-up, steps 5 to 8 | Deletes work files, logs and settings | Deleting logs can look like hiding activity. Ask IT whether to keep them. | **Yes** |

The last column is our estimate. It depends on the company's security tools, and nothing has been tested with them.

## Check 1: Run now

This check installs, changes and saves nothing, and needs no password. It has not been run on Windows, so read it first and follow company rules on pasting commands.

1. Get IT's yes. See [Tell IT first](#tell-it-first).
2. Sign in to Windows as the user who will run CurWork.
3. Open **Windows PowerShell** as the normal user, not with **Run as administrator**.
4. If your Region isn't us-east-1, change `$region` near the top of the block.
5. Paste the whole block and press Enter. It takes up to about two minutes.
6. Read the last three lines, check the table for anything private, and send it back. If PowerShell shows an error, send that too.

```powershell
& {
# ============================================================
# CHECK 1: which ways of running CurWork are likely to work, and which need a Windows administrator
# ============================================================
# This block reads Windows policies, installed programs, proxy settings, the clock and disk space.
# It runs Python and the AWS CLI only to get their versions and test a connection.
# It sends empty test requests to AWS and to Microsoft sign-in. It doesn't sign in.
# It installs, changes and saves nothing.
# The ampersand and the braces around the block make PowerShell run it as one piece, and keep
# its settings out of the rest of your session.
#
# WORKS         = no problem was found
# WINDOWS ADMIN = a Windows administrator must install or change it
# ASK IT        = a company rule may block it, or the check couldn't tell
# TEST LATER    = no problem was found, but only Check 2 can prove it
# INFO          = background only
  # The AWS Region. Change it if your settings file uses another one.
  $region = 'us-east-1'
  # Hide progress bars, so that the output is easy to copy. This applies only inside this block.
  $ProgressPreference = 'SilentlyContinue'
  # Step shows which check is running, so that the window doesn't look stuck. It isn't part of the table.
  function Step($Number, $Text) { Write-Host "[$Number/6] $Text" }
  # Adds one line to the results table and hides your user folder name.
  # It uses Select-Object, so that it also works when PowerShell is restricted.
  function Add-Row($Result, $Check, $Detail) {
    $text = "$Detail" -replace [regex]::Escape($env:USERPROFILE), '%USERPROFILE%'
    1 | Select-Object @{n='Result';e={$Result}}, @{n='Check';e={$Check}}, @{n='Detail';e={$text}}
  }
  # Reads one registry value. Never writes.
  function Get-Reg($path, $name) { (Get-ItemProperty -Path $path -ErrorAction SilentlyContinue).$name }

  # ------------------------------------------------------------
  # PART 1. Windows account, and the rules that decide which programs may run
  # ------------------------------------------------------------
  Step 1 'Windows account and application control'
  # S-1-5-32-544 is the local Administrators group.
  $isAdmin = [bool](whoami.exe /groups | Select-String 'S-1-5-32-544')
  if ($isAdmin) { Add-Row 'INFO' 'Windows account' 'This account is a local administrator.' } else { Add-Row 'INFO' 'Windows account' 'This account is not a local administrator.' }
  # PowerShell is limited (not FullLanguage) when AppLocker or App Control restricts scripts.
  $mode = "$($ExecutionContext.SessionState.LanguageMode)"
  # $control lists the rules that are on. Any entry means ASK IT.
  $control = @()
  if ($mode -ne 'FullLanguage') { $control += "PowerShell is in $mode mode" }
  # $unknown lists the checks that couldn't be read. They count as ASK IT, never as a pass.
  $unknown = @()
  # $msiRules becomes true if AppLocker controls installer (MSI) files.
  $msiRules = $false
  try {
    # AppLocker: read the rules that apply to this PC. Exe and Dll rules can block CurWork,
    # Python and the AWS CLI. Msi rules can block the AWS CLI installer.
    [xml]$al = Get-AppLockerPolicy -Effective -Xml -ErrorAction Stop
    foreach ($c in @($al.AppLockerPolicy.RuleCollection)) {
      # A rule group is enforced if it is Enabled, or if it has rules and no mode is set.
      $on = ($c.EnforcementMode -eq 'Enabled') -or (($c.EnforcementMode -eq 'NotConfigured') -and ($c.ChildNodes.Count -gt 0))
      if ($on -and ($c.Type -eq 'Exe' -or $c.Type -eq 'Dll')) { $control += "AppLocker $($c.Type) rules are enforced" }
      if ($on -and $c.Type -eq 'Msi') { $msiRules = $true }
    }
  } catch { $unknown += 'AppLocker' }
  try {
    # App Control (WDAC): 2 means that rules for programs are enforced.
    $dg = Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard -ErrorAction Stop
    if ($dg.UsermodeCodeIntegrityPolicyEnforcementStatus -eq 2) { $control += 'App Control (WDAC) is enforced' }
  } catch { $unknown += 'App Control (WDAC)' }
  # Smart App Control: 0 is off, 1 is on and 2 is evaluation. When on, it can block unsigned apps.
  $sac = Get-Reg 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' 'VerifiedAndReputablePolicyState'
  if ($sac -eq 1) { $control += 'Smart App Control is on' }
  if ($control.Count) { Add-Row 'ASK IT' 'Application control' ($control -join '; ') }
  elseif ($unknown.Count) { Add-Row 'ASK IT' 'Application control' ('This could not be read: ' + ($unknown -join ', ')) }
  else { Add-Row 'WORKS' 'Application control' 'No enforced AppLocker program rules, App Control or Smart App Control were found.' }
  # SmartScreen: Block means that users can't choose Run anyway for an unrecognized app.
  $smart = (Get-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System' 'ShellSmartScreenLevel') -eq 'Block'
  if ($smart) { Add-Row 'ASK IT' 'SmartScreen' 'Policy stops users from running an app after the warning.' } else { Add-Row 'INFO' 'SmartScreen' 'No Group Policy that blocks was found. Other management tools can still set one.' }

  # ------------------------------------------------------------
  # PART 2. Python (needed only for way 1, the Python command)
  # It must be 3.10 or newer, because four of CurWork's packages need that, and it must include
  # tkinter, which draws CurWork's window.
  # ------------------------------------------------------------
  Step 2 'Python'
  $py = $null; $pyNote = 'Python was not found.'
  # Find installed copies in the registry. The py command isn't used, because it can install
  # Python on some PCs.
  $found = @(Get-Reg 'HKLM:\SOFTWARE\Python\*\*\InstallPath' 'ExecutablePath') + @(Get-Reg 'HKCU:\SOFTWARE\Python\*\*\InstallPath' 'ExecutablePath')
  # Also look on the PATH, but skip the Microsoft Store shortcuts in WindowsApps.
  $cmds = @(Get-Command python.exe -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
  if ($cmds -like '*\WindowsApps\*') { $pyNote = 'Only a Microsoft Store shortcut was found. Type python --version to see whether Python is really installed.' }
  $found += @($cmds | Where-Object { $_ -notlike '*\WindowsApps\*' })
  # Try each copy once, and stop at the first one that passes.
  # -I ignores the current folder and user settings. -B stops Python from writing cache files.
  foreach ($f in @($found | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique)) {
    $v = & $f -I -B -c "import sys;print('%d|%d|%s'%(sys.version_info[0],sys.version_info[1],sys.executable))" 2>$null | Select-Object -Last 1
    if ("$v" -match '^(\d+)\|(\d+)\|(.+)$') {
      $maj = [int]$Matches[1]; $min = [int]$Matches[2]; $exe = $Matches[3]
      if ($maj -ne 3 -or $min -lt 10) { $pyNote = "Python $maj.$min at $exe is too old. It must be 3.10 or newer."; continue }
      # Try to load tkinter.
      $tk = & $exe -I -B -c "import tkinter;print('tk-ok')" 2>$null | Select-Object -Last 1
      if ("$tk" -ne 'tk-ok') { $pyNote = "Python $maj.$min at $exe has no tkinter, which draws the window."; continue }
      $py = $exe; $pyNote = "Python $maj.$min at $exe, with tkinter. CurWork is tested only on 3.12."; break
    }
  }
  if ($py) { Add-Row 'WORKS' 'Python' $pyNote } else { Add-Row 'ASK IT' 'Python' $pyNote }
  if ($py) {
    # pip would install the seven packages later. Here it only reports its version.
    $pip = & $py -B -m pip --version 2>$null | Select-Object -Last 1
    if ("$pip" -like 'pip *') { Add-Row 'WORKS' 'pip' 'pip runs.' } else { Add-Row 'INFO' 'pip' 'pip did not run. The seven packages can be copied over instead.' }
  }

  # ------------------------------------------------------------
  # PART 3. AWS CLI version 2 (needed for every way, because it does the sign-in)
  # ------------------------------------------------------------
  Step 3 'AWS CLI'
  $aws = $null; $awsNote = 'The AWS CLI version 2 was not found.'
  # Look where the all-users installer puts it, then the one-user installer, then the PATH.
  $paths = @("$env:ProgramFiles\Amazon\AWSCLIV2\aws.exe", "$env:LOCALAPPDATA\Programs\Amazon\AWSCLIV2\aws.exe")
  $paths += @(Get-Command aws.exe -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
  # Ask each copy for its version. It must be version 2.
  foreach ($p in $paths) {
    if ($p -and (Test-Path $p)) {
      $v = & $p --version 2>$null | Select-Object -First 1
      if ("$v" -like 'aws-cli/2*') { $aws = $p; $awsNote = "$(("$v" -split ' ')[0]) at $p"; break } else { $awsNote = "$p did not run, or it is not version 2." }
    }
  }
  # Windows Installer policies that block one-user installs.
  $noMsi = Get-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Installer' 'DisableMSI'
  $noUser = Get-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Installer' 'DisableUserInstalls'
  $awsResult = 'WORKS'
  # If the AWS CLI is missing, decide who can install it:
  #   - policy blocks one-user installs: a Windows administrator
  #   - application control may block it: ask IT
  #   - otherwise: you can, with AWSCLIV2-User.msi
  if (-not $aws) {
    if ($noMsi -eq 1 -or $noMsi -eq 2 -or $noUser -eq 1) { $awsResult = 'WINDOWS ADMIN'; $awsNote += ' Policy blocks one-user installs.' }
    elseif ($msiRules -or $control.Count -or $unknown.Count) { $awsResult = 'ASK IT'; $awsNote += ' Application control may block AWSCLIV2-User.msi or aws.exe.' }
    else { $awsResult = 'TEST LATER'; $awsNote += ' AWSCLIV2-User.msi should install without a Windows administrator.' }
  }
  Add-Row $awsResult 'AWS CLI' $awsNote

  # ------------------------------------------------------------
  # PART 4. Network
  # ------------------------------------------------------------
  Step 4 'Network (this can take two minutes if it is blocked)'
  # Any HTTP number, even 403 or 404, means that the address was reached.
  # sts = who am I, ssm = settings, s3 = files, oidc and portal.sso = AWS sign-in.
  $bad = @()
  foreach ($h in @("sts.$region.amazonaws.com", "ssm.$region.amazonaws.com", "s3.$region.amazonaws.com", 's3.amazonaws.com', "oidc.$region.amazonaws.com", "portal.sso.$region.amazonaws.com", 'login.microsoftonline.com')) {
    $code = "$(curl.exe -sS -o NUL -w '%{http_code}' --max-time 15 "https://$h" 2>$null)"
    if ($code -notmatch '^[1-5]\d\d$') { $bad += $h }
  }
  if ($bad.Count) { Add-Row 'ASK IT' 'Network addresses' ('Not reached without a proxy: ' + ($bad -join ', ')) } else { Add-Row 'WORKS' 'Network addresses' 'All seven addresses were reached.' }
  # Connect from Python to AWS, without a proxy. A certificate from Amazon means that the
  # traffic isn't inspected. Any other issuer means that it is.
  $pyNet = $false
  if ($py) {
    $n = & $py -I -B -c "import http.client as c;k=c.HTTPSConnection('sts.$region.amazonaws.com',443,timeout=15);k.connect();i=dict(x[0] for x in k.sock.getpeercert()['issuer']);k.request('GET','/');print('NET|%d|%s'%(k.getresponse().status,i.get('organizationName')))" 2>$null | Select-Object -Last 1
    if ("$n" -match '^NET\|(\d+)\|(.+)$') {
      $issuer = $Matches[2]
      if ($issuer -eq 'Amazon') { $pyNet = $true; Add-Row 'WORKS' 'Python to AWS' 'Python connected, and AWS traffic is not inspected.' }
      else { Add-Row 'ASK IT' 'Python to AWS' "AWS traffic is inspected (certificate from $issuer). Ask for an exemption or the company certificate file." }
    } else { Add-Row 'ASK IT' 'Python to AWS' 'Python could not connect directly. A proxy, inspection or a block on python.exe is likely.' }
  }
  # Proxy settings for this user. They matter if an address above wasn't reached.
  $inet = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
  $proxy = @()
  if ((Get-Reg $inet 'ProxyEnable') -eq 1) { $proxy += 'a fixed proxy' }
  if (Get-Reg $inet 'AutoConfigURL') { $proxy += 'an automatic proxy script' }
  if ($env:HTTPS_PROXY) { $proxy += 'HTTPS_PROXY' }
  if ($proxy.Count) { Add-Row 'INFO' 'Proxy' ('Set on this PC: ' + ($proxy -join ', ') + '. If the network lines say ASK IT, ask for its address and whether it needs NTLM.') } else { Add-Row 'WORKS' 'Proxy' 'No proxy setting was found for this user.' }

  # ------------------------------------------------------------
  # PART 5. Clock. AWS rejects requests when it's wrong, and by default only a Windows administrator
  # can set it. More than 4 minutes off fails.
  # ------------------------------------------------------------
  Step 5 'Clock'
  $clockBad = $false
  $line = curl.exe -sI --max-time 15 "https://sts.$region.amazonaws.com" 2>$null | Select-String '^date:' | Select-Object -First 1
  if ($line) {
    $off = ((Get-Date) - (Get-Date (("$line" -replace '^date:\s*', '').Trim()))).TotalMinutes
    if ($off -lt 0) { $off = -$off }
    if ($off -gt 4) { $clockBad = $true; Add-Row 'WINDOWS ADMIN' 'Clock' ('The clock is off by about {0:N0} minutes.' -f $off) } else { Add-Row 'WORKS' 'Clock' 'The clock matches AWS.' }
  } else { Add-Row 'INFO' 'Clock' 'Not checked, because AWS was not reached.' }

  # ------------------------------------------------------------
  # PART 6. Disk space
  # ------------------------------------------------------------
  Step 6 'Disk space'
  # Free space on the Windows drive. 2 GB leaves room for the 116 MB test workbook and results.
  $free = (Get-PSDrive -Name $env:SystemDrive.Substring(0, 1)).Free / 1GB
  if ($free -gt 2) { Add-Row 'WORKS' 'Disk space' ('{0:N0} GB free' -f $free) } else { Add-Row 'INFO' 'Disk space' ('Only {0:N1} GB free. Free up space.' -f $free) }

  # ------------------------------------------------------------
  # PART 7. The answer for each way of running CurWork (the lines that start with ==>)
  # ------------------------------------------------------------
  # The network passes if every address was reached and, when Python was found, Python
  # connected to AWS too.
  $netOk = ($bad.Count -eq 0) -and ($pyNet -or -not $py)
  # The first rule that matches decides the answer.
  # $needsApp is true for CurWork.exe and false for the Python command.
  function Get-Verdict($needsApp) {
    if ($clockBad) { return @('WINDOWS ADMIN', 'The clock must be corrected.') }
    if ($awsResult -eq 'WINDOWS ADMIN') { return @('WINDOWS ADMIN', 'The AWS CLI must be installed by a Windows administrator.') }
    if (-not $netOk) { return @('ASK IT', 'The network lines say ASK IT.') }
    if ($control.Count -or $unknown.Count -or $awsResult -eq 'ASK IT') { return @('ASK IT', 'Application control or the AWS CLI line says ASK IT.') }
    if ($needsApp -and $smart) { return @('ASK IT', 'SmartScreen can block the unsigned app.') }
    if (-not $needsApp -and -not $py) { return @('ASK IT', 'The Python line says ASK IT.') }
    if ($awsResult -eq 'TEST LATER') { return @('TEST LATER', 'Install AWSCLIV2-User.msi for this user first.') }
    return @('TEST LATER', 'Nothing else has to be installed.')
  }
  # Ways 1 and 2 need no Windows administrator if the parts above pass. Way 3 always does.
  $v1 = Get-Verdict $false
  Add-Row $v1[0] '==> 1. Python command' $v1[1]
  $v2 = Get-Verdict $true
  Add-Row $v2[0] '==> 2. CurWork.exe, user folder' ($v2[1] + ' CurWork.exe has to be built first.')
  Add-Row 'WINDOWS ADMIN' '==> 3. CurWork.exe, Program Files' 'A Windows administrator must copy the files there.'
# Show the table. Lines that need an administrator come first, and the answers (==>) come last.
} | Sort-Object { if ($_.Check -like '==>*') { 9 } else { @{ 'WINDOWS ADMIN' = 0; 'ASK IT' = 1; 'TEST LATER' = 2; 'WORKS' = 3; 'INFO' = 4 }[$_.Result] } }, { $_.Check } | Format-Table Result, Check, Detail -AutoSize -Wrap | Out-String -Width 120
```

| Result | Meaning |
|---|---|
| `WORKS` | No problem was found. |
| `WINDOWS ADMIN` | A Windows administrator must install or change it. |
| `ASK IT` | A company rule may block it, or the check couldn't tell. IT or the network team must answer. |
| `TEST LATER` | No problem was found. Check 2 proves it. |
| `INFO` | Background only. |

The output shows no password and hides the user folder, but it can name security programs and company rules, so treat it as internal. The check can't see every policy, so `WORKS` can still fail.

## Check 2: Run after approval

First, get approval for Windows testing and for the Python command, and [tell IT](#tell-it-first). Then copy CurWork's code and the test settings file to a user folder ([how to fill in the settings](WINDOWS_BUILD_AND_TEST.md)), and install the AWS CLI if it is missing.

This check installs the Python packages in CurWork's own folder and runs CurWork's self-test. In a normal **Windows PowerShell** window, set the first two values and paste the block.

```powershell
# ============================================================
# CHECK 2: does CurWork start on this PC from the Python command
# ============================================================
# Run it only after Windows testing and the Python command are approved.
# It creates the folder .venv inside CurWork's folder, installs the seven packages there,
# and runs CurWork's own self-test. The self-test changes nothing in AWS.
# It adds the .venv folder and CurWork's work folder. Signing in later adds an AWS profile and
# temporary sign-in tokens. The clean-up block below removes or lists all of them.
#
# CHANGE THESE TWO LINES: the folder that holds CurWork's code and its settings file,
# and the Python path that Check 1 showed.
$App = "$HOME\curworks\CurWork-app"
$Python = 'python'
& {
    $venv = "$App\.venv\Scripts\python.exe"
    # STEP 1: are the code and the settings file there? Then create the private Python folder.
    Write-Host '[1/3] Creating the private Python folder.'
    if (-not ((Test-Path "$App\curwork.py") -and (Test-Path "$App\curwork_admin_settings.json"))) { 'STOP: the code or the settings file is missing.'; return }
    & $Python -I -m venv "$App\.venv"
    if (-not (Test-Path $venv)) { 'STOP: Python could not create its folder.'; return }
    'WORKS: the private Python folder is ready.'
    # STEP 2: install the packages. pip checks each one against its known fingerprint (hash).
    Write-Host '[2/3] Installing the seven packages. This can take a minute.'
    & $venv -m pip install --quiet --no-cache-dir --require-hashes -r "$App\requirements-lock.txt"
    # LASTEXITCODE is 0 when the last program worked.
    if ($LASTEXITCODE -ne 0) { 'STOP: the packages were not installed.'; return }
    'WORKS: the packages are installed.'
    # STEP 3: run the self-test. It shows only the name and result of each check, so no AWS details.
    Write-Host '[3/3] Running the self-test.'
    try { $report = & $venv "$App\curwork.py" --config "$App\curwork_admin_settings.json" --self-test | Out-String | ConvertFrom-Json -ErrorAction Stop }
    catch { 'STOP: the self-test gave no report.'; return }
    if (-not $report) { 'STOP: the self-test gave no report.'; return }
    foreach ($c in $report.checks) {
        if ($c.skipped) { "SKIPPED: $($c.check)" } elseif ($c.ok) { "WORKS: $($c.check)" } else { "STOP: $($c.check)" }
    }
    if ($report.passed) { 'WORKS: CurWork starts on this PC.' } else { 'STOP: the self-test failed.' }
}
```

Then start CurWork, choose **Sign in**, download a sample file, save a result to S3, and finish with **4. Finish and clean up**:

```powershell
& "$App\.venv\Scripts\python.exe" "$App\curwork.py"
```

| What you see | Likely cause | Who acts |
|---|---|---|
| The code or the settings file is missing | Wrong folder in `$App` | User |
| Python could not create its folder | Wrong path in `$Python`, or a rule blocks python.exe | User, then IT |
| The packages were not installed | A proxy, HTTPS inspection or a block on pypi.org | IT or the network team |
| The self-test gave no report | A rule blocks python.exe, or tkinter is missing | IT |
| SKIPPED: the signed-in role | Nobody has signed in yet | User signs in, then runs Check 2 again |
| Sign-in doesn't finish in the browser | A rule blocks 127.0.0.1, or sign-in needs a managed PC | IT or the identity team |
| Access denied | The user lacks the biller permission set | AWS administrator |
| Any other error | Unknown | Record the message |

Use **sample files only**. To undo this check, use [the clean-up block](#clean-up-after-the-checks).

## Clean up after the checks

Check 1 leaves nothing to clean up. After Check 2, choose **4. Finish and clean up** in CurWork, close it, and ask IT whether to keep the logs. Then run this block in the same kind of window. It shows its progress, asks before each deletion, and reports the status of every step. It has not been run on Windows, so read it first.

```powershell
# ============================================================
# CLEAN UP: remove what Check 2 and CurWork left on this PC
# ============================================================
# It asks before each deletion. Pressing Enter always keeps the item.
# It shows its progress, checks each deletion, and ends with a table of what was removed and kept.
# Deleted files do not go to the Recycle Bin. It needs no Windows administrator.
#
# CHANGE THESE TWO LINES if needed: the folder that holds CurWork's code, and the work folder
# that CurWork's Settings tab shows.
$App = "$HOME\curworks\CurWork-app"
$Work = "$env:LOCALAPPDATA\CurWork"
& {
    $total = 9
    $rows = @()
    # Step shows the progress bar and the step number.
    function Step($Number, $Text) {
        Write-Progress -Activity 'CurWork clean-up' -Status "Step $Number of $total. $Text" -PercentComplete (100 * ($Number - 1) / $total)
        Write-Host ''
        Write-Host "[$Number/$total] $Text"
    }
    # Status shows the result of a step in color, and returns one line for the final table.
    function Status($Item, $Result, $Detail) {
        $color = @{ 'DONE' = 'Green'; 'NOT FOUND' = 'Green'; 'KEPT' = 'Yellow'; 'BY HAND' = 'Yellow'; 'FAILED' = 'Red' }[$Result]
        Write-Host "      $Result - $Detail" -ForegroundColor $color
        1 | Select-Object @{n='Result';e={$Result}}, @{n='Item';e={$Item}}, @{n='Detail';e={$Detail}}
    }
    # RemoveOne shows one file or folder, asks, deletes it, and checks that it is gone.
    # It refuses a folder that contains a link, because a link can lead to files somewhere else.
    # $Word is what the user must type.
    function RemoveOne($Item, $Path, $Word) {
        if (-not (Test-Path -LiteralPath $Path)) { return Status $Item 'NOT FOUND' 'Nothing to remove.' }
        try {
            $root = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
            $all = @(Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction Stop)
            $links = @(@($root) + $all | Where-Object { "$($_.Attributes)" -match 'ReparsePoint' })
            if ($links.Count) { return Status $Item 'BY HAND' 'It contains a link, so it was not touched.' }
            $files = @($all | Where-Object { -not $_.PSIsContainer })
            $mb = ($files | Measure-Object -Property Length -Sum).Sum / 1MB
            Write-Host "      $Path"
            Write-Host ('      {0} files, {1:N1} MB' -f $files.Count, $mb)
            $answer = Read-Host "      Type $Word to delete it, or press Enter to keep it"
            if ($answer -cne $Word) { return Status $Item 'KEPT' 'You kept it.' }
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            if (Test-Path -LiteralPath $Path) { return Status $Item 'FAILED' 'It is still there.' }
            return Status $Item 'DONE' 'Deleted.'
        } catch { return Status $Item 'FAILED' "$($_.Exception.Message)" }
    }

    Write-Host 'CurWork clean-up. Nothing is deleted without your answer.'
    # The settings file holds the names of the AWS profile and the sign-in session.
    # They are read first, because the file can be deleted in step 8.
    $settings = $null
    try { $settings = Get-Content -LiteralPath "$App\curwork_admin_settings.json" -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop } catch { }

    # STEP 1: CurWork must be closed, so that no file is in use.
    Step 1 'Checking that CurWork is closed'
    $running = @()
    $checked = $true
    try { $running = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -eq 'CurWork.exe' -or ($_.Name -like 'python*' -and $_.CommandLine -like '*curwork.py*') }) }
    catch { $checked = $false }
    if ($running.Count) { Write-Progress -Activity 'CurWork clean-up' -Completed; 'STOP: close CurWork, then run this block again. Nothing was deleted.'; return }
    if ($checked) { $rows += Status 'CurWork closed' 'DONE' 'CurWork is not running.' }
    else { $rows += Status 'CurWork closed' 'BY HAND' 'Windows did not show the running programs. Make sure that CurWork is closed.' }

    # STEP 2: the user confirms that the results are safe in S3.
    Step 2 'Checking that your results are saved'
    $left = @(Get-ChildItem -LiteralPath "$Work\Out" -Recurse -File -ErrorAction SilentlyContinue).Count
    Write-Host "      The Out folder holds $left files."
    $answer = Read-Host '      Are all results that you need saved in S3? Type y to go on, or press Enter to stop'
    if ($answer -ne 'y') { Write-Progress -Activity 'CurWork clean-up' -Completed; 'STOP: save your results in CurWork first. Nothing was deleted.'; return }
    $rows += Status 'Results saved' 'DONE' 'You confirmed it.'

    # STEP 3: sign out of AWS. The AWS CLI deletes its own temporary sign-in tokens.
    # This block never opens the token files. It only checks whether the folder holds any file,
    # and then relies on the result that the AWS CLI reports.
    Step 3 'Signing out of AWS'
    $aws = @("$env:ProgramFiles\Amazon\AWSCLIV2\aws.exe", "$env:LOCALAPPDATA\Programs\Amazon\AWSCLIV2\aws.exe") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not (Test-Path "$HOME\.aws\sso\cache\*.json")) { $rows += Status 'AWS sign-in' 'NOT FOUND' 'There is no saved sign-in.' }
    elseif (-not $aws) { $rows += Status 'AWS sign-in' 'BY HAND' 'The AWS CLI was not found in its usual folders. Run: aws sso logout' }
    else {
        Write-Host '      This ends ALL your AWS sign-ins through IAM Identity Center on this PC, not only the one for CurWork.'
        $answer = Read-Host '      Type y to sign out, or press Enter to stay signed in'
        if ($answer -ne 'y') { $rows += Status 'AWS sign-in' 'KEPT' 'You did not sign out.' }
        else {
            & $aws sso logout
            if ($LASTEXITCODE -eq 0) { $rows += Status 'AWS sign-in' 'DONE' 'The AWS CLI reported that you are signed out.' }
            else { $rows += Status 'AWS sign-in' 'FAILED' 'The AWS CLI reported an error. Run: aws sso logout' }
        }
    }

    # STEP 4: the AWS profile. The user edits the file, because it can hold other profiles too.
    # This block changes nothing in it. It only checks whether the sections are gone.
    Step 4 'Checking the AWS profile'
    $config = "$HOME\.aws\config"
    if ($env:AWS_CONFIG_FILE) { $config = $env:AWS_CONFIG_FILE }
    if (-not (Test-Path -LiteralPath $config)) { $rows += Status 'AWS profile' 'NOT FOUND' 'There is no AWS config file.' }
    elseif (-not $settings -or -not $settings.aws_profile) { $rows += Status 'AWS profile' 'BY HAND' "The settings file could not be read. Look for CurWork's sections in $config." }
    else {
        $names = @("[profile $($settings.aws_profile)]", "[sso-session $($settings.sso.session_name)]")
        $found = @(Get-Content -LiteralPath $config | ForEach-Object { $_.Trim() } | Where-Object { $names -contains $_ })
        if (-not $found.Count) { $rows += Status 'AWS profile' 'NOT FOUND' 'Its sections are not in the file.' }
        else {
            Write-Host "      Found: $($found -join ' and ')"
            Write-Host '      Keep a section if it was there before CurWork, or if another profile uses it.'
            $answer = Read-Host '      Type y to open the file in Notepad, or press Enter to keep the sections'
            if ($answer -eq 'y') {
                & "$env:SystemRoot\System32\notepad.exe" $config
                $null = Read-Host '      Delete each section with the lines under it, save the file, then press Enter here'
                $found = @(Get-Content -LiteralPath $config | ForEach-Object { $_.Trim() } | Where-Object { $names -contains $_ })
                if ($found.Count) { $rows += Status 'AWS profile' 'KEPT' "Still in the file: $($found -join ' and ')" }
                else { $rows += Status 'AWS profile' 'DONE' 'The sections are gone.' }
            } else { $rows += Status 'AWS profile' 'KEPT' 'You kept the sections.' }
        }
    }

    # STEP 5: the work folder, with its In, Out and Logs folders.
    # The folder must look like a CurWork work folder, so that a wrong path in $Work deletes nothing.
    Step 5 'Work folder'
    if ((Test-Path -LiteralPath $Work) -and -not ((Test-Path -LiteralPath "$Work\In") -and (Test-Path -LiteralPath "$Work\Out") -and (Test-Path -LiteralPath "$Work\Logs"))) { $rows += Status 'Work folder' 'BY HAND' 'It does not look like a CurWork work folder, so it was not touched.' }
    else { $rows += RemoveOne 'Work folder' $Work 'DELETE' }

    # STEP 6: the file that CurWork writes if it cannot start.
    Step 6 'Crash log'
    $rows += RemoveOne 'Crash log' "$env:LOCALAPPDATA\CurWork-crash.log" 'y'

    # STEP 7: the private Python folder, and the files that Python made from the code.
    Step 7 'Python files'
    $rows += RemoveOne 'Private Python folder' "$App\.venv" 'y'
    $rows += RemoveOne 'Python cache' "$App\__pycache__" 'y'

    # STEP 8: the settings files. The first one holds the account number and the sign-in address.
    Step 8 'Settings files'
    $rows += RemoveOne 'Settings file' "$App\curwork_admin_settings.json" 'y'
    $rows += RemoveOne 'Your preferences' "$App\curwork_user_settings.json" 'y'

    # STEP 9: proxy and certificate settings of this user. The company may have set them, so this
    # block only reports them.
    Step 9 'Proxy and certificate settings'
    $user = Get-ItemProperty -Path 'HKCU:\Environment' -ErrorAction SilentlyContinue
    $set = @('HTTPS_PROXY', 'AWS_CA_BUNDLE' | Where-Object { $user.$_ })
    if ($set.Count) { $rows += Status 'User settings' 'BY HAND' "Set: $($set -join ', '). Remove only what you added for CurWork." }
    else { $rows += Status 'User settings' 'NOT FOUND' 'None is set.' }

    # Show the table and one final line.
    Write-Progress -Activity 'CurWork clean-up' -Completed
    $rows | Format-Table Result, Item, Detail -AutoSize -Wrap | Out-String -Width 120
    $open = @($rows | Where-Object { $_.Result -eq 'KEPT' -or $_.Result -eq 'BY HAND' -or $_.Result -eq 'FAILED' })
    if ($open.Count) { "NOT FINISHED: $($open.Count) items are left. See the table." } else { 'FINISHED: every item in the table is removed.' }
}
```

| Result | Meaning |
|---|---|
| `DONE` | The step worked. |
| `NOT FOUND` | There was nothing to remove. |
| `KEPT` | You chose to keep it. |
| `BY HAND` | You have to look at it and decide. |
| `FAILED` | It could not be removed. Close other programs and run the block again. |

You can run the block again at any time. It does not remove these:

- **CurWork's code:** delete its folder in File Explorer.
- **AWS CLI:** if you installed it for this test, remove it in **Settings**, **Apps**, **Installed apps**.
- **Results in S3:** billers cannot delete them, so ask the AWS administrator.

## Ask IT

1. May the user run CurWork's code with Python? This needs IT's approval. It must not be used to get around a rule that blocks unsigned apps.
2. May the user install AWSCLIV2-User.msi, or will you install AWSCLIV2.msi?
3. May Python and the AWS CLI connect to the [network addresses](#network-addresses) on port 443, without HTTPS inspection? If not, which proxy and certificate file should they use?
4. May the browser open 127.0.0.1, which sign-in uses?
5. Does data loss prevention block uploads to S3?

## Who fixes what

| Problem | Who fixes it |
|---|---|
| Firewall or security software blocks python.exe, aws.exe or port 443 | Windows administrator or security team |
| Wrong clock | Windows administrator |
| Missing VPN client, if one is needed | Windows administrator |
| One-user installs are blocked | Windows administrator |
| AppLocker, App Control, Smart App Control or SmartScreen blocks a program | IT or security team |
| Proxy or web filter blocks an address, or accepts only NTLM sign-in | Network team |
| Browser or security software blocks 127.0.0.1 | IT |
| Sign-in is allowed only from a managed PC | Identity team |
| Data loss prevention blocks uploads to S3 | Security team |
| The user lacks the biller permission set | AWS administrator |

## What the user can change

- **Proxy:** set HTTPS_PROXY for your user.
- **HTTPS inspection:** set AWS_CA_BUNDLE for your user to the certificate file from IT. Never turn off certificate checks.
- **AWS CLI not found:** put its full path in `aws_cli_path` in the settings file.

## Network addresses

CurWork makes only outgoing HTTPS connections (port 443). It needs no inbound firewall rule.

- **S3:** s3.us-east-1.amazonaws.com and s3.amazonaws.com, also with the bucket name in front
- **AWS services:** sts, ssm, oidc and portal.sso, each followed by .us-east-1.amazonaws.com
- **Sign-in:** the company's awsapps.com address, other AWS sign-in pages, login.microsoftonline.com
- **Setup only:** awscli.amazonaws.com, pypi.org, files.pythonhosted.org

With the FIPS setting on, AWS uses other addresses.

## Biggest unknown: application control

Company rules such as AppLocker, App Control or Smart App Control can block unsigned apps and programs in a user folder. That would stop ways 1 and 2, and perhaps the one-user AWS CLI. Check 1 reads the rules it can see.

If a rule blocks CurWork, do not turn the rule off or work around it. Ask IT to approve or sign the app, or use way 3.

## If IT says no

| Alternative | Needs | Limit |
|---|---|---|
| Way 3, installed by IT | A signed CurWork.exe and a Windows administrator | Has to be built and signed first |
| Download and upload with the AWS CLI | An approved AWS CLI, and a sign-in with access to the bucket | No CurWork screens, checks or clean-up. Users can overwrite each other. |

## Real rollout by IT

The [Admin and Security Guide](CurWork-app/ADMIN_AND_SECURITY_GUIDE.md) has the details.

- Build on a non-production Windows PC with [WINDOWS_BUILD_AND_TEST.md](WINDOWS_BUILD_AND_TEST.md), and sign CurWork.exe with the company certificate.
- Put CurWork.exe and the real curwork_admin_settings.json in a folder that users can read but not change, such as C:\Program Files\CurWork. This needs a Windows administrator.
- Install AWSCLIV2.msi for all users. This needs a Windows administrator. CurWork adds the AWS sign-in profile itself the first time the user clicks **Sign in**.
- Don't put CurWorkAdmin.exe or the AWS admin profile on the PC.
- CurWork keeps its work files in %LOCALAPPDATA%\CurWork, which OneDrive doesn't sync.

## Not confirmed

- Nothing has been run on Windows, including these checks.
- The checks can't see firewall rules for programs, browser rules, Entra rules or data loss prevention.
- AWS's full list of sign-in addresses.
- Windows testing is waiting for approval.

## Sources

- AWS CLI install, proxies and certificates: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html, https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-proxy.html and https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-troubleshooting.html
- Python on Windows: https://docs.python.org/3.12/using/windows.html
- AppLocker: https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/applocker/executable-rules-in-applocker
- SmartScreen: https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/available-settings
- Smart App Control: https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview
- Windows Firewall defaults: https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/
- Who can set the clock: https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/security-policy-settings/change-the-system-time

---

*DRAFT - For Internal Use (FPT) · Beta 0.017 · Updated 2026-11-25 17:35 UTC · Modified by: mbitar*
