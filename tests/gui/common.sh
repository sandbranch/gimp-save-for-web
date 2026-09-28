# Sourced by gui-test.sh and look.sh: starts GIMP with the dialog
# (start.sh) and a headless Chrome, and
# finds the dialog on the Broadway page. Sets $here, $out, $cdp, $view,
# x0 and y0 (the dialog's top left corner on the page) and p (positions
# from that corner); stops the Chrome, and the GIMP it started, on exit.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
tests=$(dirname "$here")
src=$(dirname "$tests")
out=$tests/output/gui
devtools=${GIMP_PLUGIN_DEVTOOLS:-$src/../gimp-devtools}
cdp="node $devtools/gui/cdp.mjs"
# the page size is set in each call: Chrome forgets it when cdp.mjs ends
view=size:${SFW_VIEW:-1500,1000}

chrome=$(command -v google-chrome || command -v chromium || command -v chromium-browser)
[ -n "$chrome" ] || { echo "SFW GUI SKIP: no Chrome or Chromium"; exit 0; }

mkdir -p "$out"
CDP_PORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
export CDP_PORT

# the Flatpak instance of the dialog's GIMP: the one whose sandbox runs
# open-dialog.py. Only it is stopped at the end, not other runs of the
# Flatpak, such as a GEGL command started meanwhile.
ours () {
    flatpak ps --columns=instance,child-pid,application 2>/dev/null |
      while read -r instance pid app; do
          [ "$app" = org.gimp.GIMP ] || continue
          cat "/proc/$pid/cmdline" 2>/dev/null | tr '\0' ' ' |
            grep -qF "$here/open-dialog.py" && echo "$instance"
      done
}
[ -z "$(ours)" ] || { echo "SFW GUI FAIL: the dialog's GIMP is already running"; exit 1; }
chrome_pid=
gimp_instance=
cleanup () {
    [ -n "$chrome_pid" ] && kill "$chrome_pid" 2>/dev/null
    # GIMP quits by itself when the dialog closes; otherwise it is stopped
    [ -n "$gimp_instance" ] || gimp_instance=$(ours)
    for instance in $gimp_instance; do
        flatpak kill "$instance" 2>/dev/null
    done
}
trap cleanup EXIT

rm -f "$out/result.txt"
"$here/start.sh" >"$out/gimp.log" 2>&1 &
"$chrome" --headless=new --remote-debugging-port="$CDP_PORT" \
  --user-data-dir="$out/chrome" --password-store=basic about:blank \
  >/dev/null 2>&1 &
chrome_pid=$!
i=0
while [ -z "$gimp_instance" ] && [ $i -lt 30 ]; do
    sleep 1
    gimp_instance=$(ours)
    i=$((i + 1))
done

# the dialog: the topmost large window on the page (Broadway draws each
# window as a canvas, stacked by z-index; GIMP's own window is under it)
find_dialog () {
    $cdp $view nav:http://127.0.0.1:8085/ wait:4000 \
      "eval:(() => { const c = [...document.querySelectorAll('canvas')]
        .map(e => [e.getBoundingClientRect(), Number(e.style.zIndex) || 0])
        .filter(([r]) => r.left >= 0 && r.top >= 0 && r.width > 500 && r.height > 500)
        .sort((a, b) => b[1] - a[1])[0];
        return c ? Math.round(c[0].left) + ',' + Math.round(c[0].top) : '' })()" 2>/dev/null
}
at=
i=0
while [ $i -lt 30 ]; do
    at=$(find_dialog)
    [ -n "$at" ] && break
    i=$((i + 1))
    sleep 3
done
x0=${at%,*}
y0=${at#*,}
p () { echo "$(( x0 + $1 )),$(( y0 + $2 ))"; }
