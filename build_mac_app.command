#!/bin/bash
# CurWork Beta 0.011 - DRAFT - For Internal Use (FPT) - Mac app build - updated 2026-11-22 17:22 UTC - modified by: mbitar
# Builds CurWork.app (for testing on this Mac) so CurWork shows up with its own name and icon in the Dock,
# the app switcher (Cmd+Tab), Finder and Spotlight. Uses PyInstaller from CurWork's own .venv.
# The app goes into CurWork-Beta-0.011/, next to curwork_admin_settings.json, which it reads from there.
# It is ad-hoc signed for this Mac only; it is not notarized and isn't meant to be shared.
# Before opening the app it runs the app's self-test and only opens it if every check passes.
# Results are saved to build_mac_app_results.txt next to this file.
HERE="$(cd "$(dirname "$0")" && pwd)"
exec > >(tee "$HERE/build_mac_app_results.txt") 2>&1
cd "$HERE/CurWork-Beta-0.011" || exit 1
TOOL="$PWD"; PY="$TOOL/.venv/bin/python"; APP="$TOOL/CurWork.app"
WORK="$(mktemp -d -t curwork-build)"
fail() { echo "  FAIL  $1"; echo "STOPPED. Nothing was changed in CurWork-Beta-0.011."; rm -rf "$WORK"; read -n1 -r -p "Press any key to close."; exit 1; }
echo "== CurWork Mac app build - $(date -u '+%Y-%m-%d %H:%M UTC')"

echo; echo "== Build"
"$PY" -m PyInstaller --noconfirm --clean --log-level WARN --windowed --name CurWork \
  --icon "$TOOL/assets/curwork.icns" --add-data "$TOOL/assets:assets" \
  --osx-bundle-identifier internal.curwork.beta \
  --distpath "$WORK/dist" --workpath "$WORK/build" --specpath "$WORK" "$TOOL/curwork.py" || fail "PyInstaller build"
NEW="$WORK/dist/CurWork.app"; PLIST="$NEW/Contents/Info.plist"

echo; echo "== App details (Info.plist)"
plutil -replace CFBundleDisplayName        -string "CurWork" "$PLIST" &&
plutil -replace CFBundleShortVersionString -string "0.011" "$PLIST" &&
plutil -replace CFBundleVersion            -string "0.011" "$PLIST" &&
plutil -replace LSApplicationCategoryType  -string "public.app-category.business" "$PLIST" &&
plutil -replace NSHighResolutionCapable    -bool true "$PLIST" &&
plutil -replace NSHumanReadableCopyright   -string "Beta 0.011 - DRAFT - For Internal Use" "$PLIST" || fail "Info.plist update"
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
if [ $? -eq 0 ]; then
  echo; echo "== Done. Opening CurWork.app. To keep it in the Dock: right-click its Dock icon > Options > Keep in Dock."
  open "$APP"
else
  echo; echo "STOPPED: the new app failed its self-test (FAIL lines above), so it wasn't opened. Send build_mac_app_results.txt for review."
fi
read -n1 -r -p "Press any key to close."
