"""
CurWork Beta 0.013 - DRAFT - For Internal Use (FPT) - help text - updated 2026-11-22 23:56 UTC - modified by: mbitar

All of CurWork's help in one place: the short tips that appear when you point at a control, and the topics
in the Help window. Keeping the words here (not scattered through the window code) means the help and the
guides can be checked and updated together.

Writing rules: plain English, short sentences, say what happens and what to do. No jargon a biller wouldn't use.
"""
from __future__ import annotations

# --------------------------------------------------------------------------------------------------------------
# Tips: shown when you point at a control (or tab to it with the keyboard). One or two short sentences.
# --------------------------------------------------------------------------------------------------------------
TIPS: dict[str, str] = {
    # Header
    "where": "The S3 bucket and AWS Region CurWork works with. Your admin sets these.",
    "who": "Who you're signed in as, and the role you're using. Green means you're signed in.",
    "sign_in": "Opens your browser to sign in with your company account. Use it when you start, or when your "
               "sign-in has expired.",
    "help": "Open CurWork Help (F1).",
    "settings": "Your own preferences (recent and pinned folders, result type, window layout), and the admin "
                "settings you can look at but not change.",
    "about": "Version numbers and file locations. Use Copy details when you contact support.",
    # Step 1
    "tree": "Folders and files in S3. Open a folder to see what's inside. Select files, or a whole month "
            "folder, then click Download selected. Hold Cmd (Mac) or Ctrl (Windows) to select more than one.",
    "refresh": "Reload the folder list from S3, for example after someone adds new files.",
    "download": "Copy the selected files (or every file in the selected folders) from S3 into your In folder.",
    "pinned": "Folders you pinned for quick access. Pick one, then click Go.",
    "go": "Jump to the pinned folder you picked.",
    "pin": "Add the folder selected above to your pinned folders, so you can jump back to it later.",
    # Step 2
    "in_path": "Your In folder: files downloaded from S3 land here. Open them from here in Excel.",
    "out_path": "Your Out folder: save your macro results here. Only files in Out can be saved in S3.",
    "open": "Open this folder in Finder (Mac) or File Explorer (Windows).",
    "copy_path": "Copy this folder's path, to paste into the macro's file dialog.",
    "counts": "How many files are in In and Out, and how many results still need to be saved in S3.",
    # Step 3
    "out_list": "Result files in your Out folder and their status: Not saved in S3, Saved in S3, Changed "
                "since saved, or Open in Excel (close it before you save it in S3).",
    "stage": "What kind of results these are. It decides which S3 folder they go to (for example Priced).",
    "folder": "The customer and month, for example agency-a/2026-10. It's filled in for you when you "
              "download a month folder. Type or pick a recent one to change it.",
    "dest": "Exactly where in S3 your results will be saved. Check it before you save.",
    "refresh_out": "Check the Out folder again now. It's also checked every few seconds.",
    "upload_selected": "Save only the files you selected in the list above in S3.",
    "upload_all": "Save every file in Out in S3 that isn't saved there yet, or that changed since it was saved.",
    # Step 4 and bottom
    "finish": "Use at the end of your work. It checks that nothing is still open or waiting to be saved, saves "
              "today's log in S3 for support, then empties In and Out on this computer.",
    "stop": "Stop the download or save that's running. Partly copied files are removed.",
    "log": "What CurWork has done this session. If something goes wrong, the details are here.",
    "log_folder": "Open the folder with CurWork's log files, to send one to support.",
    # Settings window
    "s_remember": "When on, CurWork starts with the result type you used last time.",
    "s_recent": "How many recent customer/month folders to remember for the folder box. 0 turns it off.",
    "s_clear_recent": "Forget the recent folders list.",
    "s_pins": "Your pinned folders. Select some and click Remove selected to unpin them.",
    "s_remove_pins": "Unpin the folders selected in the list.",
    "s_reset": "Put the window size and column widths back to normal when you click Save.",
    "s_saved_in": "The file on this computer where your preferences are kept. Only you use it.",
    "s_admin": "Settings your admin controls, such as the bucket and folders. You can read them here, but "
               "not change them. Click a row to see its full value.",
    "s_copy_admin": "Copy these admin settings as text, for example to send to support.",
    "s_save": "Save your preferences and close this window.",
    "s_cancel": "Close without saving changes.",
    # Help window
    "h_search": "Type a word to find topics, for example save, Excel or permission.",
}

# --------------------------------------------------------------------------------------------------------------
# Help topics: (id, title, text). In the text, a line starting with "# " is a heading and "- " is a bullet.
# --------------------------------------------------------------------------------------------------------------
TOPICS: list[tuple[str, str, str]] = [
    ("quick_start", "Quick start", """\
# Quick start
CurWork downloads CUR workbooks from S3 to this computer, lets you run your usual Excel macros on them, saves the results in S3, and then cleans up.
- 1. Sign in. Click Sign in at the top right and finish signing in in your browser.
- 2. Download files. In step 1, open a customer, select a month folder (or single files), and click Download selected. They go to your In folder.
- 3. Run your macros as usual. Open the files from the In folder. Save the results to the Out folder.
- 4. Save results in S3. In step 3, check the result type and the customer/month folder, then click Save all new or changed in S3.
- 5. Finish. In step 4, click Finish and clean up when you're done for the day.
Tip: point at any button or box to see what it does. Press F1 to open this Help at any time.
"""),
    ("sign_in", "Signing in", """\
# Signing in
CurWork uses your company sign-in. You don't type a password into CurWork.
- Click Sign in. Your browser opens. Sign in there (including any multi-factor step), then come back to CurWork.
- When you're signed in, the top of the window shows your name and role in green.
- Sign-ins expire after a few hours. If CurWork says your sign-in has expired, click Sign in again. Nothing you've downloaded is lost.
- If the browser doesn't open, or it says you have no access, contact your admin.
"""),
    ("step1", "Step 1: Download files from S3", """\
# Step 1: Download files from S3
The list on the left shows the folders in S3 that you can use, usually one folder per customer and one per month inside it.
- Open a folder by clicking the arrow next to it.
- Select a whole month folder to download every file in it, or select single files. Hold Cmd (Mac) or Ctrl (Windows) to select more than one.
- Click Download selected. The files are copied into your In folder, in the same customer/month folders.
- When you download a month folder, CurWork fills in the customer/month folder for step 3, so your results go back to the right place.
- If a file is already in In and you've changed it, CurWork asks before replacing it.
- For very large downloads, CurWork asks you to confirm first. A progress bar shows how far it's got. Click Stop to cancel.
# Pinned folders
Pin folders you use often. Select a folder and click Pin selected folder. Later, pick it from Pinned and click Go.
"""),
    ("step2", "Step 2: Run your macros", """\
# Step 2: Run your macros as usual
Your macros don't change. Only where the files are is different.
- In the macro, pick the input files from the In folder. Click Copy path next to In to paste the folder path into the macro's file dialog.
- Save the results to the Out folder (click Copy path next to Out).
- Don't save results into In. CurWork warns you if new or changed files appear there.
- Close the result files in Excel when you're done with them. Files that are open can't be saved in S3.
"""),
    ("step3", "Step 3: Save results in S3", """\
# Step 3: Save results in S3
Saving a file in S3 copies it from your Out folder to S3. Some people call this uploading.
The list shows the files in your Out folder and their status:
- Not saved in S3: new, and not saved in S3 yet.
- Saved in S3: saved, and not changed since.
- Changed since saved: you changed it after saving it in S3. Save it again.
- Open in Excel: close it in Excel first.
Before you save, check the two boxes under the list:
- Result type: the kind of results (for example Priced). It decides which S3 folder they're saved in.
- Customer / month folder: for example agency-a/2026-10. It's filled in when you download a month folder.
The line under the boxes shows exactly where in S3 the results will be saved. Then click Save all new or changed in S3, or select files and click Save selected in S3.
# If a file is already in S3
CurWork asks whether to Replace it, Skip it, or Stop. Replacing is safe: S3 keeps the old copy as an earlier version.
"""),
    ("step4", "Step 4: Finish and clean up", """\
# Step 4: Finish and clean up
Click Finish and clean up at the end of your work. CurWork:
- checks that no file is still open in Excel and nothing is waiting to be saved in S3, and asks you first if something is;
- if files in In look like results saved in the wrong place, offers to move them to Out so you can save them in S3;
- saves today's log in S3, so support can help if needed;
- empties the In and Out folders on this computer.
Your files stay safe in S3. If you close CurWork without finishing, it reminds you about leftover files the next time it starts.
"""),
    ("settings", "Settings", """\
# Settings
Click Settings at the top right (on a Mac also CurWork > Settings…, or Cmd+,).
# My preferences (you can change these)
- Result type: start with the result type you used last time.
- Recent folders: how many customer/month folders to remember, or clear them.
- Pinned folders: remove pins you don't need.
- Window layout: put the window size and columns back to normal.
- Saved in: where your preferences are kept on this computer.
# Admin settings (read-only)
The bucket, folders, sign-in and other rules are set by your admin and can't be changed here. Click a row to see its full value. Click Copy admin settings to send them to support.
"""),
    ("problems", "When something goes wrong", """\
# When something goes wrong
CurWork says what happened in plain words, and the details go into the log at the bottom of the window.
- "You're not signed in" or "Your sign-in has expired": click Sign in.
- "AWS said you don't have permission for that": the message says what AWS refused (for example downloading a file). If you think you should be allowed, send the log to your admin.
- "Can't reach AWS": check your internet or VPN connection, then try again.
- "That file or folder isn't in S3": someone may have moved or deleted it. Click Refresh.
- A file shows "Open in Excel": save and close it in Excel, then save it in S3 again.
- A download or save was stopped part-way: partly copied files are removed. Just start it again.
- CurWork found files from last time when it started: choose Yes to keep them and carry on, or No to delete them.
If you're stuck, see Getting help.
"""),
    ("keys", "Keyboard shortcuts", """\
# Keyboard shortcuts
- F1: open CurWork Help.
- Esc: close the window in front (Help, About, Settings).
- Cmd+W (Mac) or Ctrl+W (Windows): close the Help or About window.
- Cmd+, (Mac): open Settings.
- Cmd or Ctrl + click: select more than one file in a list.
- Tab: move between controls. Tips also appear when a control gets the keyboard focus.
"""),
    ("support", "Getting help", """\
# Getting help
When you contact support:
- Open About and click Copy details. Paste it into your message. It has the version numbers and file locations, and no passwords or keys.
- Click Open log folder (at the bottom right, or in About) and attach today's log file.
- Say what you were doing and what message you saw. A screenshot helps.
Don't attach customer workbooks unless support asks for them.
"""),
    ("data", "Your data and security", """\
# Your data and security
- Workbooks stay encrypted in S3. They're only on this computer between Download and Finish and clean up.
- CurWork uses your own company sign-in and only the S3 folders your admin allows.
- Keep the work folder out of OneDrive, Box, Dropbox, Google Drive or iCloud Drive. CurWork warns you if it's inside one, because files would be copied off this computer.
- Finish and clean up at the end of each day so no customer files are left behind.
"""),
]


def topic(topic_id: str) -> tuple[str, str, str]:
    for t in TOPICS:
        if t[0] == topic_id:
            return t
    raise KeyError(topic_id)


def search(words: str) -> list[str]:
    """Topic ids whose title or text contains every word typed (case doesn't matter)."""
    terms = [w for w in words.lower().split() if w]
    if not terms:
        return [t[0] for t in TOPICS]
    return [tid for tid, title, text in TOPICS if all(w in (title + " " + text).lower() for w in terms)]
