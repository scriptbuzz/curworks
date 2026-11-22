# Testing CurWork by hand on a Mac

> **DRAFT - For Internal Use (FPT)** · Version **Beta 0.011** · Updated 2026-11-22 21:51 UTC · Modified by: mbitar

This checklist tests CurWork's own steps on a Mac: signing in, downloading, uploading and cleaning up. It doesn't test the VBA macros, because Excel for Mac may run them differently. Test the macros on a Windows laptop (see [WINDOWS.md](WINDOWS.md), part 7).

## Before you start

Do these in order from the test menu (`CurWork_Test_Menu.command`). Don't test by hand until both pass.

1. **Option 7, Build and open CurWork.app.** This rebuilds the app from the current code. Rebuild after every code change, or option 8 reports that the app is out of date.
2. **Option 8, Run all automated tests.** Type **confirm** when asked. Every line must say PASS. If anything fails, stop and send `automated_tests_results.txt` for review.

## The checklist

Open `CurWork-Beta-0.011/CurWork.app` and note anything that looks wrong.

| # | Try this | What should happen |
|---|---|---|
| 1 | Look at the Dock and the window title | The Dock shows CurWork's own icon, not the Python rocket. The title reads "CurWork – Beta 0.011 (DRAFT - For Internal Use)". |
| 2 | Click **Sign in** | Your browser opens. After you approve, CurWork shows your name and the biller test role in green. |
| 3 | Open `agency-b` > `2026-10` and click **Download selected** | A progress bar moves, then the 116 MB file appears in **In**. |
| 4 | Click **Open** next to **In** and open the file in Excel | The file has four sheets of made-up data. |
| 5 | In Excel, use **File > Save As** to save the workbook into **Out**. Click **Copy path** next to **Out** and paste the path into the Save dialog | The saved workbook appears in **Out** and stays open in Excel. |
| 6 | Leave that workbook open in Excel, pick a result type, and click **Upload all new or changed** | CurWork refuses and says the file is still open in Excel. |
| 7 | Close the file in Excel and click **Upload all new or changed** again | The status changes to **Uploaded**. |
| 8 | Upload the same file again | CurWork asks whether to replace the file that's already in S3. |
| 9 | Point at a few buttons, press **F1**, and click a step's **?** | A tip appears under each button. Help opens at the right topic. |
| 10 | Open **About**, click **Copy details**, then close the window | The details paste cleanly into a note. The About window closes straight away, with no spinning wheel. |
| 11 | Change something in **Settings**, quit CurWork and open it again | Your change is still there. |
| 12 | Click **Finish and clean up** | In and Out are emptied, and CurWork says the log was uploaded. |

## Known Mac differences

- **The open-file check is weaker than on Windows.** On a Mac, CurWork only looks for the small `~$` file that Excel creates next to an open workbook. If Excel crashes and leaves that file behind, CurWork treats the workbook as open until you delete the `~$` file.
- **The app is signed for this Mac only.** Option 7 signs it without an Apple developer certificate, so it won't open on another Mac without a warning.

## When you're done

Use option 10, **Clean up when finished**, so no test items are left in AWS or on this Mac.
