#!/bin/sh
# Tests the Export for Web dialog as a user would, on a Broadway display,
# with a fresh throwaway profile (tests/gui/start.sh, SFW_FRESH=1):
#
#  1. opens it on the generated scene (JPEG, the defaults), switches the
#     view to side by side, the format to WebP, sets a target size of
#     4 kB, the view to split at 200 % and drags the divider, and presses
#     Export: the file proposed (tests/output/gui/scene.webp) is written,
#     its size is the size returned, it fits in 4 kB, it is a lossy WebP
#     of 640 x 400 that decodes, and the image is unchanged;
#     While the target is on, the quality slider is insensitive and shows
#     the quality found (a click on it changes nothing); the manual
#     quality (80) is what GIMP remembers, not the found one;
#  2. opens it again: the settings are remembered (WebP, the target, the
#     folder), so Export writes scene.webp again, the same bytes;
#  3. again, turns the target size off: the found quality becomes the
#     manual one, so Export writes the same bytes, and that quality is
#     remembered now;
#  4. once more: PNG-8, crop to the selection, Export: a 320 x 200
#     indexed PNG.
#
# Screenshots of each step are left in tests/output/gui/. Needs a headless
# Chrome (google-chrome or chromium), node 22 and ../gimp-devtools (or
# GIMP_PLUGIN_DEVTOOLS) for gui/cdp.mjs. Prints PASS or FAIL for each
# check and exits non-zero if one fails.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
here=$(cd "$(dirname "$0")" && pwd)
rm -rf "$here/../output/gui"
status=0
pass () { echo "SFW GUI PASS $1"; }
fail () { echo "SFW GUI FAIL $1"; status=1; }

# waits for result.txt (the dialog closed and GIMP wrote it)
wait_result () {
    i=0
    while [ ! -f "$out/result.txt" ] && [ $i -lt 60 ]; do
        i=$((i + 1))
        sleep 2
    done
    [ -f "$out/result.txt" ]
}

# a remembered setting: the value GIMP stored for the procedure's last run
last () {
    sed -n "s/^($1 \(.*\))\$/\1/p" \
      "$out/profile/plug-in-settings/GimpProcedureConfigRun-plug-in-save-for-web.last"
}
last_is () {
    got=$(last "$1")
    [ "$got" = "$2" ] && pass "remembered: $1 $2 ($3)" || fail "remembered: $1 is '$got', not $2 ($3)"
}
result_is () {
    got=$(sed -n "s/^$1 //p" "$out/result.txt")
    [ "$got" = "$2" ] && pass "returned: $1 $2 ($3)" || fail "returned: $1 is '$got', not $2 ($3)"
}

# the checks of one exported file: name, format, width, height, the
# largest size, extra (python condition on the fileinfo dict i)
check_file () {
    python3 - "$out" "$@" <<'PY'
import os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(sys.argv[1]), '..'))
import fileinfo
out, name, fmt, w, h, most, extra = sys.argv[1:8]
res = dict(l.split(' ', 1) for l in open(os.path.join(out, 'result.txt')).read().splitlines())
path = os.path.join(out, name)
bad = 0
def report(ok, what):
    global bad
    print('SFW GUI %s %s' % ('PASS' if ok else 'FAIL', what))
    bad |= not ok
report(res.get('status') == 'success', '%s: the dialog exported (%s)' % (name, res.get('status')))
if not os.path.exists(path):
    report(False, '%s: written' % name)
    sys.exit(1)
i = fileinfo.info(path)
size = os.path.getsize(path)
report(size == int(res['file-size']), '%s: %d bytes, the size returned' % (name, size))
report(size <= int(most), '%s: at most %s bytes' % (name, most))
dims = subprocess.run(['magick', 'identify', '-format', '%w %h', path], capture_output=True,
                      text=True).stdout.split()
report(i['format'] == fmt and dims == [w, h] and (res['width'], res['height']) == (w, h),
       '%s: a %s of %s x %s that decodes' % (name, fmt, w, h))
if extra != '-':
    expr, _, label = extra.partition('#')
    report(eval(expr), '%s: %s' % (name, label or expr))
report(res.get('unchanged') == 'True', 'the image is unchanged (pixels, selection, clean)')
report(res.get('images') == '1', 'no image left open by the dialog (%s open)' % res.get('images'))
sys.exit(bad)
PY
}

# ---------------------------------------------------------------- 1
SFW_FRESH=1
export SFW_FRESH
. "$here/common.sh"
if [ -z "$at" ]; then
    fail "the dialog did not open (log: $out/gimp.log)"
    exit 1
fi
pass "the dialog opened"
# (positions from the dialog's top left corner; the settings below the
# format part move with the format chosen. The target is typed after
# Backspace and Delete: End in a spin button sets it to its maximum)
$cdp $view wait:1500 move:"$(p 500 950)" wait:300 shot:"$out/01-open.png" \
     click:"$(p 133 84)" wait:600 click:"$(p 122 116)" wait:1500 \
     move:"$(p 500 950)" shot:"$out/02-side-by-side.png" \
     click:"$(p 1037 111)" wait:600 click:"$(p 927 201)" wait:2500 \
     move:"$(p 500 950)" wait:300 shot:"$out/03-webp.png" \
     click:"$(p 855 326)" wait:2500 click:"$(p 1050 326)" wait:400 \
     key:Backspace key:Backspace key:Backspace key:Backspace key:Backspace key:Backspace \
     key:Delete key:Delete key:Delete key:Delete key:Delete key:Delete wait:200 \
     text:4 wait:300 key:Tab wait:6000 move:"$(p 500 950)" wait:300 shot:"$out/04-target.png" \
     click:"$(p 870 170)" wait:2500 move:"$(p 500 950)" wait:300 \
     shot:"$out/04b-slider-clicked.png" \
     click:"$(p 133 84)" wait:600 click:"$(p 97 113)" wait:800 \
     click:"$(p 288 84)" wait:600 click:"$(p 288 113)" wait:800 \
     down:"$(p 415 400)" move:"$(p 380 400)" move:"$(p 300 400)" up:"$(p 300 400)" \
     wait:500 move:"$(p 500 950)" wait:300 shot:"$out/05-split-200.png" \
     down:"$(p 600 500)" move:"$(p 560 480)" move:"$(p 500 450)" up:"$(p 500 450)" \
     wait:500 move:"$(p 500 950)" wait:300 shot:"$out/05b-panned.png" >/dev/null ||
  fail "the steps in the dialog"
$cdp $view click:"$(p 1150 810)" >/dev/null
if wait_result; then
    check_file scene.webp webp 640 400 4000 "i['lossless'] is False#lossy" || status=1
    cp "$out/scene.webp" "$out/first.webp"
    grep -q '^fits True$' "$out/result.txt" && pass "the target size was met" ||
      fail "the target size: $(grep fits "$out/result.txt")"
    result_is quality 54 "the quality the search found, not the slider's 80 nor a click on it"
    last_is webp-quality 80 "the manual quality, not the found one"
    last_is target-size yes "target size on"
else
    fail "no result after Export (log: $out/gimp.log)"
fi
cleanup
chrome_pid=
gimp_instance=
cp "$out/result.txt" "$out/result-1.txt" 2>/dev/null

# ---------------------------------------------------------------- 2
SFW_FRESH=0
rm -f "$out/scene.webp" "$out/result.txt"
. "$here/common.sh"
if [ -z "$at" ]; then
    fail "the dialog did not open again (log: $out/gimp.log)"
else
    $cdp $view wait:6000 move:"$(p 500 950)" wait:300 shot:"$out/06-remembered.png" \
         click:"$(p 1150 810)" >/dev/null
    if wait_result; then
        check_file scene.webp webp 640 400 4000 "open('$out/scene.webp','rb').read() == open('$out/first.webp','rb').read()#the same bytes as in the first run (settings remembered)" ||
          status=1
    else
        fail "no result after Export in the second run (log: $out/gimp.log)"
    fi
fi
cleanup
chrome_pid=
gimp_instance=
cp "$out/result.txt" "$out/result-2.txt" 2>/dev/null

# ---------------------------------------------------------------- 3
rm -f "$out/scene.webp" "$out/result.txt"
. "$here/common.sh"
if [ -z "$at" ]; then
    fail "the dialog did not open a third time (log: $out/gimp.log)"
else
    $cdp $view wait:6000 click:"$(p 855 326)" wait:4000 move:"$(p 500 950)" wait:300 \
         shot:"$out/06b-target-off.png" click:"$(p 1150 810)" >/dev/null
    if wait_result; then
        check_file scene.webp webp 640 400 4000 "open('$out/scene.webp','rb').read() == open('$out/first.webp','rb').read()#target off: the found quality taken over, the same bytes" ||
          status=1
        result_is quality -1 "no target search"
        last_is webp-quality 54 "the found quality, taken over"
        last_is target-size no "target size off"
    else
        fail "no result after Export in the third run (log: $out/gimp.log)"
    fi
fi
cleanup
chrome_pid=
gimp_instance=
cp "$out/result.txt" "$out/result-3.txt" 2>/dev/null

# ---------------------------------------------------------------- 4
rm -f "$out/result.txt"
. "$here/common.sh"
if [ -z "$at" ]; then
    fail "the dialog did not open a fourth time (log: $out/gimp.log)"
else
    # PNG-8 (the format list opens with WebP, the current one, over the
    # combo: PNG-8 is one item above), then crop to the selection
    $cdp $view wait:6000 click:"$(p 1037 111)" wait:600 click:"$(p 927 82)" wait:10000 \
         move:"$(p 500 950)" wait:300 shot:"$out/07-png8.png" \
         click:"$(p 855 479)" wait:10000 move:"$(p 500 950)" wait:300 \
         shot:"$out/08-png8-crop.png" click:"$(p 1150 810)" >/dev/null
    if wait_result; then
        check_file scene.png png 320 200 1000000 "i['color_type'] == 3 and i['palette'] <= 256#indexed, the selection only" ||
          status=1
    else
        fail "no result after Export in the fourth run (log: $out/gimp.log)"
    fi
fi

[ $status = 0 ] && echo "SFW GUI all passed" || echo "SFW GUI FAILED (screenshots in $out)"
exit $status
