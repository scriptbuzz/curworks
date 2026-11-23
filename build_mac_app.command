#!/bin/bash
# CurWork Beta 0.016 - DRAFT - For Internal Use (FPT) - Mac app build - updated 2026-11-23 01:23 UTC - modified by: mbitar
# Builds CurWork.app (for testing on this Mac) so CurWork shows up with its own name and icon in the Dock,
# the app switcher (Cmd+Tab), Finder and Spotlight. Uses PyInstaller from CurWork's own .venv.
# It also builds CurWork Admin.app, the separate app admins use to change the settings in Parameter Store.
# CurWork.app is built without the admin code, so billers' copy can't change any settings.
# Both apps go into CurWork-app/, next to curwork_admin_settings.json, which they read from there.
# It is ad-hoc signed for this Mac only; it is not notarized and isn't meant to be shared.
# Before opening CurWork it runs both apps' self-tests and only opens CurWork if every check passes.
# Results are saved to build_mac_app_results.txt next to this file.
HERE="$(cd "$(dirname "$0")" && pwd)"
exec > >(tee "$HERE/build_mac_app_results.txt") 2>&1
cd "$HERE/CurWork-app" || exit 1
TOOL="$PWD"; PY="$TOOL/.venv/bin/python"; APP="$TOOL/CurWork.app"
WORK="$(mktemp -d -t curwork-build)"
fail() { echo "  FAIL  $1"; echo "STOPPED. Nothing was changed in CurWork-app."; rm -rf "$WORK"; read -n1 -r -p "Press any key to close."; exit 1; }
echo "== CurWork Mac app build - $(date -u '+%Y-%m-%d %H:%M UTC')"

echo; echo "== Build"
"$PY" -m PyInstaller --noconfirm --clean --log-level WARN --windowed --name CurWork \
  --icon "$TOOL/assets/curwork.icns" --add-data "$TOOL/assets:assets" \
  --osx-bundle-identifier internal.curwork.beta --exclude-module curwork_admin \
  --distpath "$WORK/dist" --workpath "$WORK/build" --specpath "$WORK" "$TOOL/curwork.py" || fail "PyInstaller build"
NEW="$WORK/dist/CurWork.app"; PLIST="$NEW/Contents/Info.plist"

echo; echo "== App details (Info.plist)"
plutil -replace CFBundleDisplayName        -string "CurWork" "$PLIST" &&
plutil -replace CFBundleShortVersionString -string "0.016" "$PLIST" &&
plutil -replace CFBundleVersion            -string "0.016" "$PLIST" &&
plutil -replace LSApplicationCategoryType  -string "public.app-category.business" "$PLIST" &&
plutil -replace NSHighResolutionCapable    -bool true "$PLIST" &&
plutil -replace NSHumanReadableCopyright   -string "Beta 0.016 - DRAFT - For Internal Use" "$PLIST" || fail "Info.plist update"
echo "  Info.plist updated"

echo; echo "== Sign for this Mac (ad-hoc) and check the signature"
codesign --force --sign - "$NEW" || fail "codesign"
codesign --verify --deep --strict "$NEW" && echo "  PASS  signature is valid" || fail "signature check"

echo; echo "== Close CurWork if it's running (an old copy would keep running after the app is replaced)"
if pgrep -f "CurWork.app/Contents/MacOS/CurWork" >/dev/null; then
  osascript -e 'tell application id "internal.curwork.beta" to quit' >/dev/null 2>&1 &
  for i in 1 2 3 4 5 6 7 8 9 10; do pgrep -f "CurWork.app/Contents/MacOS/CurWork" >/dev/null || break; sleep 1; done
  pkill -f "CurWork.app/Contents/MacOS/CurWork" 2>/dev/null; sleep 1
  pgrep -f "CurWork.app/Contents/MacOS/CurWork" >/dev/null && fail "CurWork is still running. Quit it, then run this again." || echo "  PASS  the running CurWork was closed"
else
  echo "  CurWork wasn't running."
fi

echo; echo "== Put CurWork.app next to the admin settings file"
[ -d "$APP" ] && { echo "  Replacing the previous build: $APP"; rm -rf "$APP"; }
mv "$NEW" "$APP" || fail "move CurWork.app"
rm -rf "$WORK"
[ -x "$APP/Contents/MacOS/CurWork" ] && echo "  PASS  $APP" || fail "CurWork.app is missing"
[ -f "$TOOL/curwork_admin_settings.json" ] && echo "  PASS  admin settings found next to it" || echo "  FAIL  no curwork_admin_settings.json next to CurWork.app"
echo "  Name: $(plutil -extract CFBundleDisplayName raw "$APP/Contents/Info.plist")   Version: $(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist")"

echo; echo "== Self-test of the new app (window, settings next to the app, icon, About, Settings, signed-in role)"
REPORT=$(perl -e 'alarm 90; exec @ARGV' "$APP/Contents/MacOS/CurWork" --self-test 2>/dev/null)
echo "$REPORT" | "$PY" -c 'import json,sys
t=sys.stdin.read(); i=t.find("{")
if i<0: print("  FAIL  the app gave no self-test report"); sys.exit(1)
r=json.loads(t[i:])
for c in r["checks"]: print(("  SKIP  " if c.get("skipped") else "  PASS  " if c["ok"] else "  FAIL  ")+c["check"]+(("\n          "+c["detail"]) if c["detail"] else ""))
sys.exit(0 if r["passed"] else 1)'
CURWORK_OK=$?

echo; echo "== Build CurWork Admin.app (the separate app admins use to change the settings in Parameter Store)"
ADMIN_APP="$TOOL/CurWork Admin.app"; AWORK="$(mktemp -d -t curwork-admin-build)"
"$PY" -m PyInstaller --noconfirm --clean --log-level WARN --windowed --name "CurWork Admin" \
  --icon "$TOOL/assets/curwork.icns" --osx-bundle-identifier internal.curwork.admin --exclude-module curwork \
  --distpath "$AWORK/dist" --workpath "$AWORK/build" --specpath "$AWORK" "$TOOL/curwork_admin.py" || fail "PyInstaller build of CurWork Admin"
APLIST="$AWORK/dist/CurWork Admin.app/Contents/Info.plist"
plutil -replace CFBundleDisplayName        -string "CurWork Admin" "$APLIST" &&
plutil -replace CFBundleShortVersionString -string "0.016" "$APLIST" &&
plutil -replace CFBundleVersion            -string "0.016" "$APLIST" &&
plutil -replace NSHighResolutionCapable    -bool true "$APLIST" &&
plutil -replace NSHumanReadableCopyright   -string "Beta 0.016 - DRAFT - For Internal Use" "$APLIST" || fail "CurWork Admin Info.plist update"
codesign --force --sign - "$AWORK/dist/CurWork Admin.app" || fail "codesign of CurWork Admin"
codesign --verify --deep --strict "$AWORK/dist/CurWork Admin.app" && echo "  PASS  signature is valid" || fail "CurWork Admin signature check"
pkill -f "CurWork Admin.app/Contents/MacOS/CurWork Admin" 2>/dev/null
[ -d "$ADMIN_APP" ] && rm -rf "$ADMIN_APP"
mv "$AWORK/dist/CurWork Admin.app" "$ADMIN_APP" || fail "move CurWork Admin.app"
rm -rf "$AWORK"
echo "  PASS  $ADMIN_APP"
echo; echo "== Self-test of CurWork Admin.app (window and form only; it doesn't sign in or call AWS)"
AREPORT=$(perl -e 'alarm 60; exec @ARGV' "$ADMIN_APP/Contents/MacOS/CurWork Admin" --self-test 2>/dev/null)
echo "$AREPORT" | "$PY" -c 'import json,sys
t=sys.stdin.read(); i=t.find("{")
if i<0: print("  FAIL  the admin app gave no self-test report"); sys.exit(1)
r=json.loads(t[i:])
for c in r["checks"]: print(("  PASS  " if c["ok"] else "  FAIL  ")+c["check"]+(("\n          "+c["detail"]) if c["detail"] else ""))
sys.exit(0 if r["passed"] else 1)'
ADMIN_OK=$?
find "$APP" -name "curwork_admin*" | grep -q . && { echo "  FAIL  CurWork.app contains the admin code"; ADMIN_OK=1; } \
  || echo "  PASS  CurWork.app doesn't contain the admin code"

if [ $CURWORK_OK -eq 0 ] && [ $ADMIN_OK -eq 0 ]; then
  echo; echo "== Done. Opening CurWork.app. To keep it in the Dock: right-click its Dock icon > Options > Keep in Dock."
  open "$APP"
else
  echo; echo "STOPPED: an app failed its self-test (FAIL lines above), so CurWork wasn't opened. Send build_mac_app_results.txt for review."
fi
read -n1 -r -p "Press any key to close."
