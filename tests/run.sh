#!/bin/sh
# Tests Save for Web: the unit tests of the model (tests/unit.py, no
# GIMP), then the plug-in in a headless GIMP (tests/gimp-test.py), then
# the exported files outside GIMP (tests/check.py), then, if a headless
# Chrome and node are there, the dialog on a Broadway display
# (tests/gui/gui-test.sh).
#
# GIMP runs with a throwaway profile in tests/output (GIMP3_DIRECTORY),
# where the plug-in is installed: your own GIMP profile and plug-ins are
# not used or changed. GIMP runs isolated from your folders
# (tests/isolate.sh, with gimp-devtools/gimp-run.sh): HOME and the XDG
# folders inside the Flatpak point into tests/output/gimp-home. Before and
# after, it lists your folders of GIMP and the other apps
# (gimp-devtools/snapshot.sh) and fails if anything there changed.
#
#   tests/run.sh                  all tests
#   SFW_GUI=0 tests/run.sh        without the Broadway test
#   SFW_ONLY=target tests/run.sh  only the GIMP cases whose names contain it
#   GIMP_FLATPAK=0 tests/run.sh   with a native GIMP 3 (gimp-console-3.2)
#
# Prints PASS, FAIL or SKIP per check and exits non-zero if one fails.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
here=$(cd "$(dirname "$0")" && pwd)
src=$(dirname "$here")
out=$here/output
GIMP_RUN_HOME=$out/gimp-home
export GIMP_RUN_HOME
# shellcheck source=SCRIPTDIR/isolate.sh
. "$here/isolate.sh"
mkdir -p "$out"
snapshot_take "$out/snapshot-before.txt"
status=0

echo "== unit"
python3 "$here/unit.py" >"$out/unit.log" 2>&1 || status=1
grep -v "PASS" "$out/unit.log"
echo "SFW UNIT $(grep -c PASS "$out/unit.log") passed"

# the plug-in, in the throwaway profile
profile=$out/profile
plugdir=$profile/plug-ins/save-for-web
rm -rf "$plugdir" "$out/cases" "$out/results.json"
mkdir -p "$plugdir"
cp "$src"/save-for-web/*.py "$plugdir/"
chmod 755 "$plugdir/save-for-web.py"

echo "== GIMP"
log=$out/gimp.log
gimp_run --timeout=1800 --filesystem="$src" --env=GIMP3_DIRECTORY="$profile" \
  --env=SFW_SRC="$src" --env=SFW_OUT="$out" --env=SFW_ONLY="$SFW_ONLY" -- \
  gimp-console-3.2 --no-interface --no-fonts --batch-interpreter python-fu-eval \
  -b "exec(open('$here/gimp-test.py').read())" --quit >"$log" 2>&1
rc=$?
[ $rc = 124 ] && { echo "SFW FAIL GIMP did not finish in 30 minutes"; status=1; }
grep -E "^SFW GIMP (FAIL|failures)|Traceback|^  File|Error" "$log"
echo "SFW GIMP $(grep -c '^SFW GIMP PASS' "$log") passed, $(grep -c '^SFW case' "$log") exports"
grep -q "^SFW GIMP failures: 0$" "$log" || status=1
# messages of the plug-in (its process is named after it)
if grep -E "save-for-web.py.*(WARNING|CRITICAL)|inconsistent state" "$log"; then
    echo "SFW FAIL: warnings from the plug-in, see $log"
    status=1
fi

echo "== files"
python3 "$here/check.py" "$out" >"$out/check.log" 2>&1 || status=1
grep -vE "PASS" "$out/check.log"
echo "SFW FILES $(grep -c PASS "$out/check.log") passed"

if [ "${SFW_GUI:-1}" != 0 ] && [ -z "$SFW_ONLY" ]; then
    echo "== GUI (Broadway)"
    "$here/gui/gui-test.sh" || status=1
fi

snapshot_check "$out/snapshot-before.txt" "SFW " || status=1
[ $status = 0 ] && echo "SFW all passed" || echo "SFW FAILED (logs in $out)"
exit $status
