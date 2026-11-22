# Security policy

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.012** · Updated 2026-11-22 23:32 UTC · Modified by: mbitar

CurWork is FPT's private software, and we built it with security first. The [README](README.md) explains how, and the [Admin and Security Guide](CurWork-app/ADMIN_AND_SECURITY_GUIDE.md) has the details.

## If you find a security problem

- Don't post it anywhere public. That means no GitHub issue, pull request or discussion, and nothing outside FPT.
- Tell the CurWork owner privately, through your manager or FPT's security contact.
- Say what you saw and how to make it happen again. Add the version details (in CurWork, open **About** and click **Copy details**) and the log file (**About**, then **Open log folder**). Take out any customer data first.
- If you think an AWS key, an account number or customer data got out, say that first, so access can be shut off quickly.

## Which versions get fixes

Only the latest build of Beta 0.012. Fixes go into the next build, so replace older builds rather than patching them.

## What this covers

The CurWork app, its settings files, the AWS permission policies in `CurWork-app/iam/`, the Windows build script and the Mac test kit. Please also report problems you find in AWS, Python or other parts CurWork uses, and we'll pass them on to whoever makes them.

## What we promise

- Limited access, encryption and no stored passwords or keys are requirements. They're never optional.
- Every build checks the Python packages for known security holes, and lists everything that's inside it.
- AWS account numbers, sign-in addresses and keys stay out of the code, and checks block them from being uploaded.

These are our design promises for an early internal version. They aren't an official certification under NIST, FedRAMP or any other program.

---
*DRAFT - For Internal Use (FPT) · Beta 0.012 · Updated 2026-11-22 23:32 UTC · Modified by: mbitar*
