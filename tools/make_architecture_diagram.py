#!/usr/bin/env python3
"""
Draws docs/diagrams/exhibit4-aws-architecture.svg: how the billers' and the admin's laptops work with the
AWS services CurWork uses, and which security control protects each part.

Version:     Beta 0.017
Status:      DRAFT - For Internal Use (FPT)
Updated:     2026-11-23 02:24 UTC
Modified by: mbitar

The icons in tools/aws-icons are unchanged copies from the official AWS Architecture Icons package
(July 2026 release). This script copies each icon's drawing into the diagram, so the SVG needs no other files.

Run it from the repository folder:  python3 tools/make_architecture_diagram.py
Add  --check FILE  to also write a copy that marks each text's container, for the layout check.
"""
from __future__ import annotations

import datetime as dt
import html
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ICONS = ROOT / "tools" / "aws-icons"
OUT = ROOT / "docs" / "diagrams" / "exhibit4-aws-architecture.svg"

W, H = 1620, 1195
INK = "#232F3E"        # AWS squid ink: text, arrows and the AWS Cloud border
SUB = "#545B64"        # secondary text
GREY = "#7D8998"       # AWS group border for company and laptop groups
REGION = "#00A4A6"     # AWS Region group border (dashed)
SEC = "#DD344C"        # AWS security, identity and compliance colour
SEC_BG = "#FDF0F2"
FONT = "Arial, Helvetica, sans-serif"

CHECK = "--check" in sys.argv
parts: list[str] = []


def version() -> str:
    core = (ROOT / "CurWork-app" / "curwork_core.py").read_text()
    v = re.search(r'^VERSION = "([0-9.]+)-beta"', core, re.M).group(1)
    return f"Beta {v}"


def box_attr(box):
    return f' data-box="{box[0]},{box[1]},{box[2]},{box[3]}"' if CHECK and box else ""


def icon(name: str, x: float, y: float, size: float) -> None:
    src = (ICONS / name).read_text()
    m = re.search(r"<svg[^>]*viewBox=\"([^\"]+)\"[^>]*>(.*)</svg>", src, re.S)
    body = re.sub(r"<title>.*?</title>", "", m.group(2), flags=re.S)
    body = re.sub(r'\s(id|xmlns:xlink)="[^"]*"', "", body)
    body = re.sub(r">\s+<", "><", body).strip()
    cls = ' class="icon"' if CHECK else ""
    parts.append(f'<svg{cls} x="{x}" y="{y}" width="{size}" height="{size}" viewBox="{m.group(1)}">{body}</svg>')


def text(x, y, s, size=12.5, weight="normal", fill=INK, anchor="start", box=None) -> None:
    body = html.escape(s)
    body = re.sub(r"\*\*(.+?)\*\*", r'<tspan font-weight="bold">\1</tspan>', body)
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
                 f'text-anchor="{anchor}"{box_attr(box)}>{body}</text>')


def chips(x, y, ids, box=None) -> float:
    """Red NIST control chips in a row. Returns the x after the last chip."""
    for cid in ids:
        w = 7.4 * len(cid) + 14
        parts.append(f'<rect x="{x}" y="{y}" width="{w:.0f}" height="18" rx="9" fill="{SEC}"/>')
        text(x + w / 2, y + 13, cid, 11, "bold", "#FFFFFF", "middle", box)
        x += w + 6
    return x


def group(x, y, w, h, label, icon_name=None, color=GREY, dashed=False, icon_size=32) -> None:
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{color}" stroke-width="1.5"{dash}/>')
    if icon_name:
        icon(icon_name, x if icon_size == 32 else x + 4, y if icon_size == 32 else y + 3, icon_size)
    text(x + 40, y + 21, label, 14, "bold", INK, box=(x, y, w, h))


def node(x, y, icon_name, titles, subs, col_w, nist=(), badge=None) -> float:
    """An icon with its name and a few lines of explanation to its right. Returns the bottom y."""
    icon(icon_name, x, y, 48)
    box = (x, y, col_w, 200)
    ty = y + 15
    for t in titles:
        text(x + 58, ty, t, 14, "bold", INK, box=box)
        ty += 17
    for s in subs:
        text(x + 58, ty, s, 12.5, fill=SUB, box=box)
        ty += 16
    if nist:
        chips(x + 58, ty - 8, nist, box)
        ty += 16
    if badge:
        step(x + 2, y + 2, badge)
    return ty


def callout(x, y, w, lines, nist=()) -> float:
    """A security control: a pink box with a padlock, plain sentences and the NIST control chips."""
    h = 12 + 17 * len(lines) + (28 if nist else 2)
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{SEC_BG}" stroke="{SEC}" stroke-width="1.2"/>')
    icon("Res_SSL-padlock_48_Light.svg", x + 7, y + 8, 20)
    box = (x, y, w, h)
    for i, line in enumerate(lines):
        text(x + 33, y + 22 + 17 * i, line, 12.5, fill=INK, box=box)
    if nist:
        chips(x + 33, y + 14 + 17 * len(lines), nist, box)
    return y + h


def step(cx, cy, n) -> None:
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="11" fill="{INK}" stroke="#FFFFFF" stroke-width="1.5"/>')
    text(cx, cy + 4.5, str(n), 12.5, "bold", "#FFFFFF", "middle")


def arrow(points, dashed=False, both=False) -> None:
    d = "M" + " L".join(f"{px},{py}" for px, py in points)
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    start = ' marker-start="url(#arrow)"' if both else ""
    parts.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.5"{dash}{start} marker-end="url(#arrow)"/>')


def build() -> str:
    parts.clear()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    text(30, 40, "Exhibit 4: How CurWork's laptops and AWS services work together", 22, "bold")
    text(30, 66, "The numbered arrows show the steps in order. Each pink box with a padlock describes a security "
                 "control, and the red chips name the matching NIST SP 800-53 control.", 13.5, fill=SUB)

    # ---------- company side
    group(30, 90, 500, 740, "Company network", "Corporate-data-center_32.svg")
    node(50, 133, "Res_SAML-token_48_Light.svg", ["Company sign-in (Microsoft Entra ID)"],
         ["Checks the password and the multi-factor code,", "then tells IAM Identity Center who signed in."], 470)

    group(46, 210, 468, 430, "Biller's Windows laptop", "Res_Client_48_Light.svg", icon_size=28)
    c1, c2, cw = 62, 290, 220
    node(c1, 255, "Res_User_48_Light.svg", ["Biller"], ["Signs in and does", "the four steps."], cw)
    node(c2, 255, "Res_Internet_48_Light.svg", ["Web browser"], ["Shows the company", "sign-in page."], cw)
    node(c1, 345, "Res_Generic-Application_48_Light.svg", ["CurWork"],
         ["Runs the four steps", "and calls AWS through", "the AWS CLI."], cw)
    node(c2, 345, "Arch_AWS-Command-Line-Interface_48.svg", ["AWS CLI"],
         ["The AWS command line", "tool holds the access,", "which ends on its own."], cw)
    node(c1, 435, "Res_Folders_48_Light.svg", ["In and Out folders"], ["Hold the files only", "during a session."], cw,
         badge=6)
    node(c2, 435, "Res_Data-Table_48_Light.svg", ["Excel macros"], ["Price, allocate, map", "and split the files."], cw,
         badge=4)
    callout(58, 520, 444, ["BitLocker encrypts the disk, and the screen locks when idle.",
                           "Finish and clean up empties the work folders after each session.",
                           "Only the signed CurWork app is allowed to run.",
                           "Billers' copy of CurWork contains no admin code."],
            ["SC-28", "MP-6", "AC-11", "CM-14", "CM-7"])

    group(46, 660, 468, 150, "Admin's laptop", "Res_Client_48_Light.svg", icon_size=28)
    node(c1, 703, "Res_User_48_Light.svg", ["AWS admin"], ["Changes CurWork's", "shared settings."], cw)
    node(c2, 703, "Res_Gear_48_Light.svg", ["CurWork Admin", "Settings app"], ["Checks each value", "before it saves."], cw)

    # ---------- AWS side
    group(620, 90, 970, 740, "AWS Cloud", "AWS-Cloud-logo_32.svg", color=INK)
    group(640, 135, 930, 680, "AWS Region chosen by the admin", "Region_32.svg", color=REGION, dashed=True)
    a1, a2, a3, aw = 660, 965, 1270, 285

    node(a1, 190, "Arch_AWS-IAM-Identity-Center_48.svg", ["IAM Identity Center"],
         ["Trusts the company sign-in", "and gives access that ends", "after 1 to 12 hours."], aw)
    callout(a1, 275, 285, ["No password or access key is", "ever stored on the laptop."], ["IA-2", "IA-5", "AC-12"])
    node(a2, 190, "Arch_AWS-Identity-and-Access-Management_48.svg", ["Biller permission set"],
         ["Allows listing CurWork's", "folders, reading converted/", "and saving results and logs."], aw)
    callout(a2, 275, 285, ["Billers can't delete anything or", "look at the rest of the bucket."], ["AC-3", "AC-6"])
    node(a3, 190, "Arch_AWS-Client-VPN_48.svg", ["Optional network limit"],
         ["The admin can allow access", "only from the company VPN", "or a private VPC endpoint."], aw)

    node(a1, 370, "Arch_Amazon-Simple-Storage-Service_48.svg", ["Amazon S3 bucket"],
         ["Stores the workbooks in", "CurWork's folders."], aw)
    fx, fy, fw, fh = a2, 362, 270, 112
    parts.append(f'<rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" rx="4" fill="#F2F8EC" stroke="#7AA116" stroke-width="1.2"/>')
    fbox = (fx, fy, fw, fh)
    text(fx + 12, fy + 21, "**converted/** holds the input workbooks.", box=fbox)
    text(fx + 12, fy + 38, "Billers can only read this folder.", fill=SUB, box=fbox)
    text(fx + 12, fy + 60, "**priced/, allocated/, mapped/, split/**", box=fbox)
    text(fx + 12, fy + 77, "and **reports/** hold the results.", box=fbox)
    text(fx + 12, fy + 99, "**logs/** holds one log per session.", box=fbox)
    callout(a1, 490, 575, ["Public access is blocked, and S3 accepts only TLS 1.2 or newer.",
                           "Versioning keeps every replaced copy for the retention period.",
                           "S3 checks each saved file's SHA-256 fingerprint."],
            ["SC-8", "AC-3", "CP-9", "SI-7"])

    node(a3, 370, "Arch_AWS-Key-Management-Service_48.svg", ["AWS KMS key"],
         ["A customer-managed key", "encrypts every stored file."], aw)
    callout(a3, 490, 285, ["Each stored file is encrypted.", "FIPS endpoints can be turned on",
                           "for the connections to AWS."], ["SC-28", "SC-13"])

    node(a1, 690, "Res_AWS-Systems-Manager_Parameter-Store_48.svg", ["Systems Manager", "Parameter Store"],
         ["Holds the bucket, folders", "and rules CurWork uses."], aw)
    callout(a2, 690, 285, ["Billers can only read the settings.", "Only the AWS admin role can save",
                           "them, and every version is kept."], ["CM-5", "CM-6"])
    node(a3, 690, "Arch_AWS-CloudTrail_48.svg", ["AWS CloudTrail"],
         ["Records every sign-in,", "download, save and", "settings change. It is the", "official record."], aw,
         nist=["AU-2", "AU-3", "AU-12"])

    # services that work together inside AWS
    arrow([(905, 214), (961, 214)], dashed=True)
    arrow([(fx + fw + 2, 394), (a3 - 4, 394)], dashed=True, both=True)

    # ---------- company security monitoring, outside AWS
    parts.append(f'<rect x="1200" y="860" width="370" height="70" fill="none" stroke="{GREY}" stroke-width="1.5"/>')
    sbox = (1200, 860, 370, 70)
    icon("Res_Shield_48_Light.svg", 1210, 871, 48)
    text(1268, 881, "Company security monitoring (SIEM)", 14, "bold", box=sbox)
    text(1268, 899, "Keeps the CloudTrail records and alerts", fill=SUB, box=sbox)
    text(1268, 915, "when a bucket, key or access policy changes.", fill=SUB, box=sbox)

    # ---------- steps between the laptops and AWS
    arrow([(514, 279), (572, 279), (572, 214), (656, 214)])                    # 1 browser to Identity Center
    arrow([(440, 152), (596, 152), (596, 200), (656, 200)], dashed=True, both=True)  # 1 Identity Center and Entra
    step(615, 214, 1)
    arrow([(514, 418), (556, 418), (556, 702), (656, 702)])                    # 2 settings
    step(556, 560, 2)
    arrow([(656, 381), (518, 381)])                                            # 3 download
    step(552, 381, 3)
    arrow([(514, 403), (656, 403)])                                            # 5 and 6 save results and log
    step(582, 403, 5)
    step(608, 403, 6)
    arrow([(514, 726), (656, 726)])                                            # 7 admin saves settings
    step(590, 726, 7)
    arrow([(1294, 742), (1294, 857)])                                          # 8 CloudTrail to monitoring
    step(1294, 845, 8)

    # ---------- how each step works
    text(30, 882, "How each step works", 15, "bold")
    steps = [
        "The biller signs in. IAM Identity Center sends the biller to the company sign-in, then gives the AWS CLI "
        "access that ends on its own.",
        "CurWork reads the bucket, folders and rules from Parameter Store. It doesn't use S3 until it has them.",
        "CurWork downloads the workbooks from converted/ into the In folder. The connection uses TLS 1.2 or newer.",
        "The biller runs the Excel macros. They work on the laptop and save their results in the Out folder.",
        "CurWork saves the results in the result folders. S3 checks each file's SHA-256 fingerprint, and CurWork "
        "checks its size.",
        "Finish and clean up saves the session log in logs/ and then empties the In and Out folders.",
        "The AWS admin changes the settings with the CurWork Admin Settings app. AWS refuses a save from anyone else.",
        "CloudTrail sends its record of every call to the company's security monitoring.",
    ]
    lbox = (30, 860, 1150, 300)
    for i, s in enumerate(steps, 1):
        y = 885 + 27 * i
        step(42, y - 4.5, i)
        text(62, y, s, 13, box=lbox)

    # ---------- key
    kx, ky, kw, kh = 1200, 950, 370, 212
    parts.append(f'<rect x="{kx}" y="{ky}" width="{kw}" height="{kh}" fill="#FFFFFF" stroke="{GREY}" stroke-width="1"/>')
    kbox = (kx, ky, kw, kh)
    text(kx + 14, ky + 22, "Key", 14, "bold", box=kbox)
    parts.append(f'<rect x="{kx + 14}" y="{ky + 33}" width="34" height="20" rx="4" fill="{SEC_BG}" stroke="{SEC}"/>')
    icon("Res_SSL-padlock_48_Light.svg", kx + 21, ky + 34, 18)
    text(kx + 68, ky + 48, "A security control that protects that part.", box=kbox)
    chips(kx + 14, ky + 60, ["AC-6"])
    text(kx + 68, ky + 74, "The matching NIST SP 800-53 Rev. 5 control.", box=kbox)
    step(kx + 25, ky + 95, 1)
    text(kx + 68, ky + 100, "A step, explained under the diagram.", box=kbox)
    arrow([(kx + 14, ky + 120), (kx + 48, ky + 120)])
    text(kx + 68, ky + 124, "Sign-in, files or settings move this way.", box=kbox)
    arrow([(kx + 14, ky + 142), (kx + 48, ky + 142)], dashed=True)
    text(kx + 68, ky + 146, "One service works with another.", box=kbox)
    text(kx + 14, ky + 170, "CurWork follows NIST SP 800-53 Rev. 5, the AWS", fill=SUB, box=kbox)
    text(kx + 14, ky + 186, "Well-Architected Security Pillar and the CIS AWS", fill=SUB, box=kbox)
    text(kx + 14, ky + 202, "Foundations Benchmark.", fill=SUB, box=kbox)

    text(W - 30, H - 14, f"CurWork {version()} · DRAFT - For Internal Use (FPT) · Updated {stamp} · Modified by: mbitar",
         11.5, fill=SUB, anchor="end")

    title = ("Exhibit 4: How CurWork's laptops and AWS services work together. Billers sign in through IAM Identity "
             "Center and the company sign-in, CurWork reads its settings from Parameter Store, downloads from and "
             "saves to an S3 bucket encrypted with a KMS key, and CloudTrail records every call.")
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="{html.escape(title)}" font-family="{FONT}">'
            f'<title>{html.escape(title)}</title>'
            f'<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker></defs>'
            f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')
    return head + "".join(parts) + "</svg>\n"


if __name__ == "__main__":
    if CHECK:
        out = pathlib.Path(sys.argv[sys.argv.index("--check") + 1])
        out.write_text(build())
        CHECK = False
    OUT.write_text(build())
    print(f"Wrote {OUT.relative_to(ROOT)}")
