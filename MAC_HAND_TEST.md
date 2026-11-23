# Testing CurWork by hand on a Mac

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.017** · Updated 2026-11-23 01:38 UTC · Modified by: mbitar

This checklist tests CurWork's own steps on a Mac: signing in, downloading, saving results in S3 and cleaning up. It doesn't test the VBA macros, because Excel for Mac may run them differently. Test the macros on a Windows laptop (see [WINDOWS.md](WINDOWS.md), part 7).

## Before you start

Do these in order from the test menu (`CurWork_Test_Menu.command`). Don't test by hand until both pass.

1. **Option 7, Build and open CurWork.app.** This rebuilds CurWork and CurWork Admin from the current code. Rebuild after every code change, or option 8 reports that the app is out of date.
2. **Option 8, Run all automated tests.** Type **confirm** when asked. Every line must say PASS. If anything fails, stop and send `automated_tests_results.txt` for review.

## The checklist

Open `CurWork-app/CurWork.app` and note anything that looks wrong.

| # | Try this | What should happen |
|---|---|---|
| 1 | Look at the Dock and the window title | The Dock shows CurWork's own icon, not the Python rocket. The title reads "CurWork – Beta 0.017 (DRAFT - For Internal Use)". |
| 2 | Click **Sign in** | Your browser opens. After you approve, CurWork shows your name and the biller test role in green. |
| 3 | On the **1. Download from S3** tab, open `agency-b` > `2026-10` and click **Download selected** | A progress bar moves at the bottom of the window, then the 116 MB file appears in the list on the right, **Already in your In folder**. |
| 4 | Click **Next: 2. Work in Excel**. Click **Open** next to **In** and open the file in Excel | The file has four sheets of made-up data. |
| 5 | In Excel, use **File > Save As** to save the workbook into **Out**. Click **Copy path** next to **Out** and paste the path into the Save dialog | The saved workbook appears in **Out** and stays open in Excel. |
| 6 | Leave that workbook open in Excel. On the **3. Save in S3** tab, pick a result type, and click **Save all new or changed in S3** | CurWork refuses and says the file is still open in Excel. |
| 7 | Close the file in Excel and click **Save all new or changed in S3** again | The status changes to **Saved in S3**. |
| 8 | Select the same file in the list and click **Save selected in S3** | CurWork asks whether to replace the file that's already in S3. |
| 9 | Point at a few buttons, press **F1**, and click **? Help for this step** on a tab. Press Cmd+1 to Cmd+5 | A tip appears under each button. Help opens at the right topic. Each Cmd+number opens one tab. |
| 10 | Open **About**, click **Copy details**, then close the window | The details paste cleanly into a note. The About window closes straight away, with no spinning wheel. |
| 11 | On the **Settings** tab, change something in **My preferences** and click **Save**. Quit CurWork and open it again | Your change is still there. |
| 12 | On the **Settings** tab, open **Admin settings (read-only)** | It shows the same tabs as CurWork Admin, filled in with the bucket and folders. Nothing can be changed, and there's no Save button. |
| 13 | Make the window as small as it goes and look at each tab | Nothing is cut off. The admin settings get a scroll bar. |
| 14 | Open `CurWork-app/CurWork Admin.app` | The admin app opens with its own name in the Dock. Close it without signing in. |
| 15 | Click **4. Finish and clean up** | In and Out are emptied, and CurWork says the log was saved in S3. |

## Known Mac differences

- **The open-file check is weaker than on Windows.** On a Mac, CurWork only looks for the small `~$` file that Excel creates next to an open workbook. If Excel crashes and leaves that file behind, CurWork treats the workbook as open until you delete the `~$` file.
- **The app is signed for this Mac only.** Option 7 signs it without an Apple developer certificate, so it won't open on another Mac without a warning.

## When you're done

Use option 10, **Clean up when finished**, so no test items are left in AWS or on this Mac.

---
*DRAFT - For Internal Use (FPT) · Beta 0.017 · Updated 2026-11-23 01:38 UTC · Modified by: mbitar*
