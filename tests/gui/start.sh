#!/bin/sh
# Opens the Export for Web dialog in the Flatpak GIMP on a Broadway
# display (http://127.0.0.1:8085/), to use or test it with
# gimp-devtools/gui/cdp.mjs (see gui-test.sh), on a generated scene
# (tests/gui/open-dialog.py). The plug-in is taken from save-for-web/ into
# a throwaway profile, tests/output/gui/profile, which the GUI tests
# keep between runs of the dialog (for "remember the last settings");
# SFW_FRESH=1 starts with an empty one. When the dialog closes, GIMP
# writes tests/output/gui/result.txt and quits.
#
#   tests/gui/start.sh
#   SFW_SCENE=1600x1000 tests/gui/start.sh    a bigger scene
#   SFW_PROFILE=adobe tests/gui/start.sh      the scene in Adobe RGB
#
# broadwayd stops when GIMP quits, also when GIMP fails. GIMP loads no
# fonts (--no-fonts): on Broadway it can hang at start while loading them.
# GIMP runs isolated from your own folders (tests/isolate.sh), with the
# throwaway home of tests/run.sh, and --new-instance, so that a GIMP you
# have open is not asked to do it.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
here=$(cd "$(dirname "$0")" && pwd)
tests=$(dirname "$here")
src=$(dirname "$tests")
out=$tests/output/gui
profile=$out/profile
mkdir -p "$out"
[ "${SFW_FRESH:-0}" = 1 ] && rm -rf "$profile"
mkdir -p "$profile/plug-ins/save-for-web"
cp "$src"/save-for-web/*.py "$profile/plug-ins/save-for-web/"
chmod 755 "$profile/plug-ins/save-for-web/save-for-web.py"
GIMP_RUN_HOME=${GIMP_RUN_HOME:-$tests/output/gimp-home}
# shellcheck source=SCRIPTDIR/../isolate.sh
. "$tests/isolate.sh"
gimp_run --flatpak --filesystem="$src" \
  --env=GDK_BACKEND=broadway --env=BROADWAY_DISPLAY=:5 \
  --env=GIMP3_DIRECTORY="$profile" --env=SFW_OUT="$out" \
  --env=SFW_SCENE="${SFW_SCENE:-640x400}" --env=SFW_PROFILE="${SFW_PROFILE:-}" \
  -- sh -c \
  "broadwayd --port 8085 :5 & bw=\$!; trap 'kill \$bw' EXIT; sleep 2; \
   gimp-3.2 --new-instance --no-splash --no-fonts \
   --batch-interpreter python-fu-eval -b \"exec(open('$here/open-dialog.py').read())\""
