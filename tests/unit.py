#!/usr/bin/env python3
# Unit tests of save-for-web/sfw_model.py (no GIMP): the settings, the
# output size, the JPEG XL distance, the target-size search, the download
# time and the size text. Prints PASS or FAIL per check; exits 1 on a
# failure.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                'save-for-web'))
import sfw_model as m   # noqa: E402

failures = 0


def check(ok, what):
    global failures
    print('SFW UNIT %s %s' % ('PASS' if ok else 'FAIL', what))
    if not ok:
        failures += 1


# settings
d = m.defaults()
check(d['format'] == 'jpeg' and d['jpeg-quality'] == 85, 'defaults: JPEG at quality 85')
check(set(d) == set(m.SETTINGS), 'defaults cover every setting')
c = m.check({'jpeg-quality': 250, 'colors': 1, 'target-kb': -3, 'keep-exif': 1})
check(c['jpeg-quality'] == 100 and c['colors'] == 2 and c['target-kb'] == 0.1
      and c['keep-exif'] is True, 'check clamps ints, doubles and makes bools')
try:
    m.check({'format': 'bmp'})
    check(False, 'an unknown format is refused')
except ValueError:
    check(True, 'an unknown format is refused')
for f, _ in m.FORMATS:
    check(f in m.EXTENSIONS and f in m.EXPORTERS and f in m.FORMAT_KEYS,
          'format %s has an extension, an exporter and its keys' % f)
    check(all(k in m.SETTINGS for k in m.FORMAT_KEYS[f]), 'the keys of %s are settings' % f)
check(all(k in m.SETTINGS for k in m.BASE_KEYS), 'the base keys are settings')
check(set(m.JPEG_SUBSAMPLING) == {n for n, _ in m.SUBSAMPLING},
      'every subsampling has a file-jpeg-export value')

# output size
s = dict(d)
check(m.output_size(640, 480, s) == (640, 480), 'no resize')
s.update({'scale-mode': 'percent', 'percent': 50.0})
check(m.output_size(640, 480, s) == (320, 240), '50 percent')
s['percent'] = 33.3
check(m.output_size(100, 7, s) == (33, 2), '33.3 percent rounds')
s['percent'] = 1.0
check(m.output_size(40, 30, s) == (1, 1), 'never below 1 pixel')
s.update({'scale-mode': 'size', 'width': 320, 'height': 0, 'keep-aspect': True})
check(m.output_size(640, 480, s) == (320, 240), 'width, keep aspect')
s.update({'width': 0, 'height': 100})
check(m.output_size(640, 480, s) == (133, 100), 'height, keep aspect (133.33 rounds)')
s.update({'width': 300, 'height': 100})
check(m.output_size(640, 480, s) == (300, 225), 'width wins with keep aspect')
s.update({'keep-aspect': False})
check(m.output_size(640, 480, s) == (300, 100), 'width and height without the aspect')
s.update({'width': 0})
check(m.output_size(640, 480, s) == (640, 100), 'width 0 is the source width')

# JPEG XL distance (libjxl JxlEncoderDistanceFromQuality)
check(m.jxl_distance(100) == 0.1, 'quality 100: distance 0 clamped to 0.1')
check(abs(m.jxl_distance(90) - 1.0) < 1e-9, 'quality 90: distance 1.0')
check(abs(m.jxl_distance(30) - 6.4) < 1e-9, 'quality 30: distance 6.4')
check(abs(m.jxl_distance(20) - (53 / 3000 * 400 - 23 / 20 * 20 + 25)) < 1e-9,
      'quality 20: the quadratic part')
check(m.jxl_distance(1) == 15.0, 'quality 1: clamped to 15')
ds = [m.jxl_distance(q) for q in range(1, 101)]
check(all(a >= b for a, b in zip(ds, ds[1:])), 'distance falls as the quality rises')

# target-size search
sizes = {v: 1000 + 37 * v for v in range(0, 101)}
calls = []


def size_of(v):
    calls.append(v)
    return sizes[v]


v, size, fits, tried = m.search_target(1, 100, size_of, 3000)
check(fits and v == 54 and size == sizes[54] and sizes[55] > 3000,
      'bisection finds the highest fitting value (54)')
check(len(calls) == len(set(calls)) and len(calls) <= 9,
      'no value encoded twice, %d encodes for 100 values' % len(calls))
calls.clear()
v, size, fits, tried = m.search_target(1, 100, size_of, 10 ** 6)
check(fits and v == 100 and calls == [100], 'a target above the highest: one encode')
v, size, fits, tried = m.search_target(1, 100, size_of, 500)
check(not fits and v == 1, 'a target below the lowest: does not fit, the lowest value')
# not monotonic: the result must still fit
bumpy = {v: 1000 + 37 * v + (300 if v % 7 == 0 else 0) for v in range(0, 101)}
v, size, fits, tried = m.search_target(1, 100, lambda x: bumpy[x], 3000)
check(fits and bumpy[v] <= 3000, 'a bumpy size curve: the result still fits (%d)' % v)
for fmt, lossless in (('jpeg', None), ('webp', 'webp-lossless'), ('avif', 'avif-lossless'),
                      ('jxl', 'jxl-lossless')):
    t = dict(d, format=fmt)
    check(m.search_parameter(t) is not None, '%s: target size searches %s' %
          (fmt, m.search_parameter(t)[0]))
    if lossless:
        t[lossless] = True
        check(m.search_parameter(t) is None, '%s lossless: no target search' % fmt)
check(m.search_parameter(dict(d, format='png')) is None, 'PNG-24: no target search')
check(m.search_parameter(dict(d, format='png8'))[0] == 'colors', 'PNG-8 searches colours')
check(m.search_parameter(dict(d, format='gif', palette='web')) is None,
      'GIF with the web palette: no target search')

# download time and texts
check(abs(m.download_seconds(125000, 1e6) - 1.0) < 1e-9, '125 kB at 1 Mbit/s: 1 s')
check(abs(m.download_seconds(125000, 1e6, 0.1) - 1.1) < 1e-9, 'plus the latency')
check(m.format_seconds(0.05) == '50 ms' and m.format_seconds(1.25) == '1.2 s'
      and m.format_seconds(42.4) == '42 s' and m.format_seconds(185) == '3 min 05 s',
      'seconds as text')
check(m.format_size(999) == '999 bytes' and m.format_size(12601) == '12.6 kB (12,601 bytes)'
      and m.format_size(1301512) == '1.30 MB (1,301,512 bytes)', 'sizes as text')
check(m.ratio_text(50, 1000) == '5.0 % of uncompressed' and
      m.ratio_text(500, 1000) == '50 % of uncompressed', 'ratio as text')
check(m.psnr(0) == math.inf and abs(m.psnr(1.0) - 48.1308) < 1e-3, 'PSNR from the MSE')

print('SFW UNIT failures: %d' % failures)
sys.exit(1 if failures else 0)
