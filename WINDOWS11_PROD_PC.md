# curworks PoC on a production Windows 11 PC

_Last modified: 2026-11-25 11:51 EST_

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.017** · Updated 2026-11-25 16:51 UTC · Modified by: mbitar

**curworks** ([scriptbuzz/curworks](https://github.com/scriptbuzz/curworks)) is a PoC of CurWork, a desktop app for FPT's billing team. A biller signs in to AWS with their company account, and CurWork copies cost report workbooks from Amazon S3 to the PC. It saves the biller's results back to S3, checks them and empties its work folders. It stores no passwords or AWS keys. It has been tested on a Mac. This document shows whether it can run on a production Windows 11 PC, and what a PC administrator must install.

**"PC administrator" means a local Windows administrator**, not the AWS administrator.

## Answer

Probably yes, without a PC administrator. The PC's policies and network decide, so run the check below.

| Way to run CurWork | PC administrator needed? | Requires |
|---|---|---|
| **1. Python command** | No | Python 3.10 or newer with tkinter, seven Python packages, CurWork's code, AWS CLI |
| **2. CurWork.exe in a user folder** | No | CurWork.exe (not built yet), AWS CLI |
| **3. CurWork.exe in C:\Program Files** | **Yes** | The same as 2, copied by a PC administrator |

- **AWS CLI version 2:** AWSCLIV2-User.msi (one user) needs no PC administrator. AWSCLIV2.msi (all users) does.
- **Security:** with ways 1 and 2, users can edit the settings file, so use only the test bucket. Way 3 prevents that.
- **Way 1 needs IT's approval.** Running the code through Python must not be used to get around a rule that blocks unsigned apps.

## Run the check

1. Sign in to Windows as the user who will run CurWork.
2. Open PowerShell. Don't run it as administrator.
3. If your Region isn't us-east-1, change `$region` near the top of the block.
4. Paste the whole block and press Enter. It takes up to two minutes.
5. Read the last three lines, check the table for anything private, and send it back.

It installs, changes and saves nothing.

```powershell
# =====================================================================================
# curworks PoC: production PC check (DRAFT - For Internal Use (FPT), Beta 0.017)
#
# Shows which ways of running CurWork are likely to work on this PC, and which need a
# PC administrator (a local Windows administrator).
# Reads Windows policies, installed programs, proxy settings, the clock and disk space.
# Runs Python and the AWS CLI only to get their versions and test a connection.
# Sends empty test requests to AWS and Microsoft sign-in. It doesn't sign in.
# Installs, changes and saves nothing.
#
# WORKS          = the check passed
# LIKELY WORKS   = nothing found that blocks it; only a real run can prove it
# NEEDS PC ADMIN = a PC administrator must install or change something
# ASK IT         = a company rule may block it, or the check couldn't tell
# INFO           = for information only
# =====================================================================================
# The braces keep everything below out of the rest of your session.
& {
  # The AWS Region. Change it if your settings file uses another one.
  $region = 'us-east-1'
  # Adds one line to the results table and hides your user folder name.
  function Add-Row($Result, $Check, $Detail) { [pscustomobject]@{ Result = $Result; Check = $Check; Detail = "$Detail" -replace [regex]::Escape($env:USERPROFILE), '%USERPROFILE%' } }
  # Reads one registry value. Never writes.
  function Get-Reg($path, $name) { (Get-ItemProperty -Path $path -ErrorAction SilentlyContinue).$name }

  # -------------------------------------------------------------------------------------
  # PART 1. Windows account, and the rules that decide which programs may run
  # -------------------------------------------------------------------------------------
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

  # -------------------------------------------------------------------------------------
  # PART 2. Python (needed only for way 1, the Python command)
  # It must be 3.10 or newer, because four of CurWork's packages need that, and it must include
  # tkinter, which draws CurWork's window.
  # -------------------------------------------------------------------------------------
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

  # -------------------------------------------------------------------------------------
  # PART 3. AWS CLI version 2 (needed for every way, because it does the sign-in)
  # -------------------------------------------------------------------------------------
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
  #   - policy blocks one-user installs: a PC administrator
  #   - application control may block it: ask IT
  #   - otherwise: you can, with AWSCLIV2-User.msi
  if (-not $aws) {
    if ($noMsi -eq 1 -or $noMsi -eq 2 -or $noUser -eq 1) { $awsResult = 'NEEDS PC ADMIN'; $awsNote += ' Policy blocks one-user installs.' }
    elseif ($msiRules -or $control.Count -or $unknown.Count) { $awsResult = 'ASK IT'; $awsNote += ' Application control may block AWSCLIV2-User.msi or aws.exe.' }
    else { $awsResult = 'LIKELY WORKS'; $awsNote += ' AWSCLIV2-User.msi should install without a PC administrator.' }
  }
  Add-Row $awsResult 'AWS CLI' $awsNote

  # -------------------------------------------------------------------------------------
  # PART 4. Network
  # -------------------------------------------------------------------------------------
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

  # -------------------------------------------------------------------------------------
  # PART 5. Clock. AWS rejects requests when it's wrong, and by default only a PC administrator
  # can set it. More than 4 minutes off fails.
  # -------------------------------------------------------------------------------------
  $clockBad = $false
  $line = curl.exe -sI --max-time 15 "https://sts.$region.amazonaws.com" 2>$null | Select-String '^date:' | Select-Object -First 1
  if ($line) {
    $off = ((Get-Date) - (Get-Date (("$line" -replace '^date:\s*', '').Trim()))).TotalMinutes
    if ($off -lt 0) { $off = -$off }
    if ($off -gt 4) { $clockBad = $true; Add-Row 'NEEDS PC ADMIN' 'Clock' ('The clock is off by about {0:N0} minutes.' -f $off) } else { Add-Row 'WORKS' 'Clock' 'The clock matches AWS.' }
  } else { Add-Row 'INFO' 'Clock' 'Not checked, because AWS was not reached.' }

  # -------------------------------------------------------------------------------------
  # PART 6. Disk space
  # -------------------------------------------------------------------------------------
  # Free space on the Windows drive. 2 GB leaves room for the 116 MB test workbook and results.
  $free = (Get-PSDrive -Name $env:SystemDrive.Substring(0, 1)).Free / 1GB
  if ($free -gt 2) { Add-Row 'WORKS' 'Disk space' ('{0:N0} GB free' -f $free) } else { Add-Row 'INFO' 'Disk space' ('Only {0:N1} GB free. Free up space.' -f $free) }

  # -------------------------------------------------------------------------------------
  # PART 7. The answer for each way of running CurWork (the lines that start with ==>)
  # -------------------------------------------------------------------------------------
  # The network passes if every address was reached and, when Python was found, Python
  # connected to AWS too.
  $netOk = ($bad.Count -eq 0) -and ($pyNet -or -not $py)
  # The first rule that matches decides the answer.
  # $needsApp is true for CurWork.exe and false for the Python command.
  function Get-Verdict($needsApp) {
    if ($clockBad) { return @('NEEDS PC ADMIN', 'The clock must be corrected.') }
    if ($awsResult -eq 'NEEDS PC ADMIN') { return @('NEEDS PC ADMIN', 'The AWS CLI must be installed by a PC administrator.') }
    if (-not $netOk) { return @('ASK IT', 'The network lines say ASK IT.') }
    if ($control.Count -or $unknown.Count -or $awsResult -eq 'ASK IT') { return @('ASK IT', 'Application control or the AWS CLI line says ASK IT.') }
    if ($needsApp -and $smart) { return @('ASK IT', 'SmartScreen can block the unsigned app.') }
    if (-not $needsApp -and -not $py) { return @('ASK IT', 'The Python line says ASK IT.') }
    if ($awsResult -eq 'LIKELY WORKS') { return @('LIKELY WORKS', 'Install AWSCLIV2-User.msi for this user first.') }
    return @('LIKELY WORKS', 'Nothing else has to be installed.')
  }
  # Ways 1 and 2 need no PC administrator if the parts above pass. Way 3 always does.
  $v1 = Get-Verdict $false
  Add-Row $v1[0] '==> 1. Python command' $v1[1]
  $v2 = Get-Verdict $true
  Add-Row $v2[0] '==> 2. CurWork.exe, user folder' ($v2[1] + ' CurWork.exe has to be built first.')
  Add-Row 'NEEDS PC ADMIN' '==> 3. CurWork.exe, Program Files' 'A PC administrator must copy the files there.'
} | Format-Table Result, Check, Detail -AutoSize -Wrap
```

If PowerShell shows an error, send the text.

## What only others can change

| Problem | Who fixes it |
|---|---|
| Firewall or security software blocks python.exe, aws.exe or port 443 | PC administrator or security team |
| Wrong clock | PC administrator |
| Missing VPN client, if one is needed | PC administrator |
| One-user installs are blocked | PC administrator |
| AppLocker, App Control, Smart App Control or SmartScreen blocks a program | IT or security team |
| Proxy or web filter blocks an address, or accepts only NTLM sign-in | Network team |
| Browser or security software blocks 127.0.0.1, which sign-in uses | IT |
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

## Not confirmed

- Nothing has been run on Windows, including this check.
- The check can't see firewall rules for programs, browser rules, Entra rules or data loss prevention.
- AWS's full list of sign-in addresses.
- Windows testing is waiting for approval.

For the full Windows setup, see [WINDOWS.md](WINDOWS.md).

## Sources

- AWS CLI install, proxies and certificates: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html, https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-proxy.html and https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-troubleshooting.html
- Python on Windows: https://docs.python.org/3.12/using/windows.html
- AppLocker: https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/applocker/executable-rules-in-applocker
- SmartScreen: https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/available-settings
- Smart App Control: https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview
- Windows Firewall defaults: https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/
- Who can set the clock: https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/security-policy-settings/change-the-system-time
