#!/usr/bin/env python3
# Checks the files tests/gimp-test.py exported, outside GIMP: that each
# decodes (ImageMagick; JPEG XL, which this ImageMagick cannot read, in
# GIMP), that its size is the size the procedure returned, that its
# header says what was asked, that the target-size results fit, that the
# metadata is there or not as chosen (read from the file's structure by
# tests/fileinfo.py, and compared with ImageMagick's and GIMP's reading),
# and that the preview's decoded pixels are those of the written file.
#
#   tests/check.py tests/output
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fileinfo   # noqa: E402

out = sys.argv[1]
with open(os.path.join(out, 'results.json')) as f:
    results = json.load(f)
cases = results['cases']
formats = results['formats']
failures = 0
checked = 0


def report(ok, what):
    global failures, checked
    checked += 1
    print('SFW FILES %s %s' % ('PASS' if ok else 'FAIL', what))
    if not ok:
        failures += 1


def magick_decode(path):
    """(width, height, uint8 array h x w x 4) as ImageMagick decodes it."""
    wh = subprocess.run(['magick', 'identify', '-format', '%w %h\n', path + '[0]'],
                        capture_output=True, text=True, check=True).stdout.split()
    w, h = int(wh[0]), int(wh[1])
    raw = subprocess.run(['magick', path + '[0]', '-alpha', 'on', '-depth', '8', 'rgba:-'],
                         capture_output=True, check=True).stdout
    return w, h, np.frombuffer(raw, np.uint8).reshape(h, w, 4)


def magick_profiles(path):
    v = subprocess.run(['magick', 'identify', '-verbose', path + '[0]'], capture_output=True,
                       text=True).stdout
    return sorted({line.strip().split(':')[0].replace('Profile-', '')
                   for line in v.splitlines() if line.strip().startswith('Profile-')})


def icc_description(icc):
    if not icc or len(icc) < 132:
        return None
    n = struct.unpack('>I', icc[128:132])[0]
    for i in range(n):
        sig, off, size = struct.unpack('>4sII', icc[132 + 12 * i:144 + 12 * i])
        if sig != b'desc':
            continue
        t = icc[off:off + 4]
        if t == b'desc':
            count = struct.unpack('>I', icc[off + 8:off + 12])[0]
            return icc[off + 12:off + 12 + count].rstrip(b'\0').decode('latin-1')
        if t == b'mluc':
            ln, o = struct.unpack('>II', icc[off + 20:off + 28])
            return icc[off + o:off + o + ln].decode('utf-16-be')
    return None


decoded = {}


def pixels(name):
    """The case's pixels as ImageMagick decodes them (not for JPEG XL)."""
    if name not in decoded:
        decoded[name] = magick_decode(cases[name]['path'])[2]
    return decoded[name]


def ok_case(name):
    c = cases.get(name)
    return c is not None and c.get('status') == 'success'


# ------------------------------------------------------------ every file

EXPECT_FORMAT = {'jpg': 'jpeg', 'png': 'png', 'webp': 'webp', 'avif': 'avif', 'jxl': 'jxl',
                 'gif': 'gif'}
infos = {}
for name, c in sorted(cases.items()):
    if c.get('status') != 'success':
        report(False, '%s: exported (%s)' % (name, c.get('error')))
        continue
    path = c['path']
    if not os.path.exists(path):
        report(False, '%s: the file is there' % name)
        continue
    info = fileinfo.info(path)
    infos[name] = info
    ext = path.rsplit('.', 1)[1]
    ok = info['format'] == EXPECT_FORMAT[ext]
    size_ok = os.path.getsize(path) == c['file-size']
    dims = None
    if ext == 'jxl':
        if 'readback' in c:
            dims = tuple(c['readback']['size'])
        elif c.get('preview'):
            # the preview cases were decoded by GIMP already
            dims = (c['width'], c['height'])
        decodes = dims is not None
        how = 'GIMP'
    else:
        try:
            w, h, px = magick_decode(path)
            decoded[name] = px
            dims = (w, h)
            decodes = True
        except subprocess.CalledProcessError as e:
            decodes = False
        how = 'ImageMagick'
    report(ok and size_ok and decodes and dims == (c['width'], c['height']),
           '%s: a %s that decodes (%s), %d x %d, %d bytes as returned' % (
               name, info['format'], how, c['width'], c['height'], c['file-size']))
    if 'readback' in c and ext != 'jxl':
        report(tuple(c['readback']['size']) == dims, '%s: GIMP reads it back at %s' % (
            name, c['readback']['size']))

# ------------------------------------------------------------ headers


def info_is(name, what, **want):
    if name not in infos:
        # (with SFW_ONLY the case may not have run)
        if not results.get('only'):
            report(False, '%s: %s (no file)' % (name, what))
        return
    got = {k: infos[name].get(k) for k in want}
    report(got == want, '%s: %s %s' % (name, what, '' if got == want else '(got %s)' % got))


info_is('photo-jpeg', 'progressive, 4:2:0 by default', progressive=True, sampling='420')
info_is('jpeg-baseline', 'baseline when not progressive', progressive=False)
for sub in ('444', '422', '440', '420'):
    info_is('jpeg-sub' + sub, 'sampling %s' % sub, sampling=sub)
info_is('gray-jpeg', 'a grey JPEG has one component', components=1)
info_is('photo-png', 'RGB, 8 bit, not interlaced', color_type=2, bit_depth=8, interlace=0)
info_is('alpha-png', 'RGBA', color_type=6, bit_depth=8)
info_is('gray-png', 'grey', color_type=0, bit_depth=8)
info_is('profile-png', '8 bit from a 16-bit image', color_type=2, bit_depth=8)
info_is('png-interlace', 'interlaced', interlace=1)
info_is('layers-png', 'no alpha channel: all opaque after merging (dropped)', color_type=2)
for name, most in (('photo-png8', 256), ('png8-c2', 2), ('png8-c16', 16), ('png8-c64', 64),
                   ('png8-mono', 2), ('png8-web', 216), ('png8-keep', 6),
                   ('png8-keep-scaled', 6), ('png8-alpha', 8)):
    if name in infos:
        i = infos[name]
        report(i.get('color_type') == 3 and 0 < i.get('palette', 0) <= most,
               '%s: indexed PNG with %s colours (at most %d)' % (name, i.get('palette'), most))
info_is('png8-keep', 'the image\'s own palette of 6 colours', palette=6)
if 'png8-alpha' in infos:
    report(infos['png8-alpha'].get('trns', 0) > 0, 'png8-alpha: a tRNS chunk (transparency)')
info_is('gif-c32', '32 colours', palette=32)
info_is('gif-interlace', 'interlaced', interlace=True)
info_is('photo-gif', 'not interlaced, one frame', interlace=False, frames=1)
info_is('photo-webp', 'lossy', lossless=False)
info_is('webp-lossless', 'lossless (VP8L)', lossless=True)
info_is('webp-alpha', 'with alpha', alpha=True)
for f in ('avif', 'jxl'):
    if f in formats:
        info_is('photo-' + f, 'the %s signature' % f, format=f)
info_is('jxl-q95', 'a bare JPEG XL codestream without metadata', container=False)

# ------------------------------------------------------------ settings take effect


def size(name):
    return cases[name]['file-size'] if ok_case(name) else None


def smaller(a, b, what):
    if ok_case(a) and ok_case(b):
        report(size(a) < size(b), '%s: %s (%d) < %s (%d)' % (what, a, size(a), b, size(b)))


smaller('jpeg-q20', 'photo-jpeg', 'JPEG quality 20 < 85')
smaller('photo-jpeg', 'jpeg-q95', 'JPEG quality 85 < 95')
smaller('webp-q30', 'photo-webp', 'WebP quality 30 < 80')
smaller('photo-webp', 'webp-q95', 'WebP quality 80 < 95')
smaller('avif-q20', 'avif-q90', 'AVIF quality 20 < 90')
smaller('jxl-q50', 'jxl-q95', 'JPEG XL quality 50 < 95')
smaller('png8-c2', 'png8-c16', 'PNG-8 2 < 16 colours')
smaller('png8-c16', 'png8-c64', 'PNG-8 16 < 64 colours')
smaller('photo-png', 'png-c0', 'PNG compression 6 < 0')
smaller('png-c9', 'photo-png', 'PNG compression 9 < 6')
smaller('jpeg-baseline', 'jpeg-noopt', 'JPEG optimised Huffman tables')
smaller('photo-webp', 'webp-lossless', 'lossy WebP < lossless')


def same_pixels(a, b, what):
    if a in decoded and b in decoded:
        report(np.array_equal(decoded[a], decoded[b]), '%s: %s and %s decode to the same '
               'pixels' % (what, a, b))


same_pixels('photo-png', 'png-c0', 'PNG compression changes only the size')
same_pixels('photo-png', 'png-c9', 'PNG compression changes only the size')
same_pixels('photo-png', 'png-interlace', 'interlacing changes only the layout')
same_pixels('jpeg-baseline', 'jpeg-noopt', 'Huffman optimisation changes only the size')
same_pixels('photo-png', 'webp-lossless', 'lossless WebP')
if 'avif-lossless' in decoded:
    # (a lossless AVIF of the pixel art has exactly its 4 colours)
    px = decoded['avif-lossless'][:, :, :3].reshape(-1, 3)
    report(len(np.unique(px, axis=0)) == 4, 'avif-lossless: exactly the 4 colours')
if 'jxl-lossless' in cases and 'photo-png' in cases and ok_case('jxl-lossless'):
    report(cases['jxl-lossless']['readback']['md5'] == cases['photo-png']['readback']['md5'],
           'jxl-lossless: GIMP decodes the same pixels as the PNG')

# ------------------------------------------------------------ transparency, layers


def px_at(name, x, y):
    return tuple(int(v) for v in pixels(name)[y, x]) if name in decoded else None


if 'alpha-png' in decoded:
    report(px_at('alpha-png', 10, 10)[3] == 0 and px_at('alpha-png', 200, 60)[3] == 255 and
           80 < px_at('alpha-png', 120, 60)[3] < 180, 'alpha-png: transparent, ramp, opaque '
           'as in the image')
for name, want in (('jpeg-matte-black', 0), ('jpeg-matte-white', 255), ('alpha-jpeg', 255)):
    if name in decoded:
        p = px_at(name, 10, 10)
        report(all(abs(v - want) <= 12 for v in p[:3]),
               '%s: transparent pixels flattened on %s (%s)' % (
                   name, 'black' if want == 0 else 'white', p[:3]))
if 'png8-alpha' in decoded:
    report(px_at('png8-alpha', 10, 10)[3] == 0 and px_at('png8-alpha', 200, 60)[3] == 255,
           'png8-alpha: transparent and opaque kept')
if 'gif-alpha' in decoded:
    report(px_at('gif-alpha', 10, 10)[3] == 0 and px_at('gif-alpha', 200, 60)[3] == 255,
           'gif-alpha: transparent and opaque kept')
if 'layers-png' in decoded:
    px = pixels('layers-png')
    magenta = int(np.sum((px[:, :, 0] > 200) & (px[:, :, 1] < 60) & (px[:, :, 2] > 200)))
    report(magenta == 0, 'layers-png: the hidden magenta layer is not exported (%d pixels)'
           % magenta)
    report(px_at('layers-png', 40, 50)[:3] == (26, 204, 51) and
           px_at('layers-png', 130, 90)[:3] == (26, 51, 204) and
           px_at('layers-png', 165, 90)[:3] == (242, 230, 26),
           'layers-png: the offset layer, the masked half hidden, the other half shown '
           '(%s %s %s)' % (px_at('layers-png', 40, 50)[:3], px_at('layers-png', 130, 90)[:3],
                           px_at('layers-png', 165, 90)[:3]))

# ------------------------------------------------------------ size and crop

for name, dims in (('crop', (200, 120)), ('crop-none', (200, 150)),
                   ('scale-percent', (120, 80)), ('scale-width', (200, 133)),
                   ('scale-height', (150, 100)), ('scale-free', (100, 100)),
                   ('scale-up-none', (64, 48)), ('scale-up-cubic', (64, 48)),
                   ('crop-scale', (100, 60)), ('png8-keep-scaled', (80, 50))):
    if ok_case(name):
        report((cases[name]['width'], cases[name]['height']) == dims,
               '%s: %d x %d' % (name, dims[0], dims[1]))
if 'crop' in decoded and 'photo-png' in decoded:
    report(np.array_equal(pixels('crop'), pixels('photo-png')[50:170, 100:300]),
           'crop: exactly the selection\'s pixels of the full export')
if 'scale-up-none' in decoded:
    px = pixels('scale-up-none')[:, :, :3]
    colours = len(np.unique(px.reshape(-1, 3), axis=0))
    blocks = all(len(np.unique(px[y:y + 4, x:x + 4].reshape(-1, 3), axis=0)) == 1
                 for y in range(0, 48, 4) for x in range(0, 64, 4))
    report(colours == 4 and blocks, 'scale-up-none: 4 colours in 4 x 4 blocks (no '
           'interpolation)')
if 'scale-up-cubic' in decoded:
    px = pixels('scale-up-cubic')[:, :, :3]
    report(len(np.unique(px.reshape(-1, 3), axis=0)) > 4, 'scale-up-cubic: interpolated '
           '(more than 4 colours)')

# ------------------------------------------------------------ target size

for f, kb in (('jpeg', 12.0), ('webp', 8.0), ('avif', 6.0), ('jxl', 10.0), ('png8', 40.0),
              ('gif', 30.0)):
    name = 'target-' + f
    if ok_case(name):
        c = cases[name]
        report(c['fits'] and c['file-size'] <= kb * 1000 and c['quality'] >= 0,
               '%s: %d bytes, under %d, at %s %d' % (name, c['file-size'], kb * 1000,
                                                    'colours' if f in ('png8', 'gif')
                                                    else 'quality', c['quality']))
if ok_case('target-jpeg-impossible'):
    c = cases['target-jpeg-impossible']
    report(not c['fits'] and c['quality'] == 1 and c['note'],
           'target-jpeg-impossible: reported as not fitting, at quality 1: "%s"' % c['note'])
if ok_case('target-jpeg-easy'):
    report(cases['target-jpeg-easy']['quality'] == 100, 'target-jpeg-easy: quality 100 fits')
if ok_case('target-png'):
    c = cases['target-png']
    report(c['quality'] == -1 and 'lossy' in c['note'], 'target-png: PNG-24 has nothing to '
           'search, says so')

# ------------------------------------------------------------ metadata

HAS = {
    'exif': {'jpeg', 'png', 'png8', 'webp', 'avif', 'jxl'},
    'xmp': {'jpeg', 'png', 'png8', 'webp', 'avif', 'jxl'},
    # (file-webp-export takes include-iptc but writes no IPTC: WebP has no
    # place for it)
    'iptc': {'jpeg', 'png', 'png8'},
    'icc': {'jpeg', 'png', 'png8', 'webp'},
    'comment': {'jpeg', 'png', 'png8'},
}
META = {'strip': {}, 'exif': {'exif'}, 'exif-gps': {'exif', 'gps'}, 'xmp': {'xmp'},
        'xmp-gps': {'xmp', 'gps'}, 'iptc': {'iptc'}, 'icc': {'icc'}, 'icc-adobe': {'icc'},
        'comment': {'comment'}, 'all': {'exif', 'xmp', 'iptc', 'icc', 'comment', 'gps'}}
for f in formats:
    for m, kept in META.items():
        name = 'meta-%s-%s' % (f, m)
        if name not in infos:
            continue
        i = infos[name]
        exif = fileinfo.tiff_tags(i['exif']) if i['exif'] else None
        want_exif = 'exif' in kept and f in HAS['exif']
        want_xmp = 'xmp' in kept and f in HAS['xmp']
        problems = []
        if want_exif != (exif is not None):
            problems.append('Exif %s' % ('missing' if want_exif else 'present'))
        if exif is not None:
            if exif['ifd0'].get(0x013b) != 'Test Artist':
                problems.append('Exif Artist %r' % exif['ifd0'].get(0x013b))
            if exif['gps'] != ('gps' in kept):
                problems.append('Exif GPS %s' % ('present' if exif['gps'] else 'missing'))
        if want_xmp != (i['xmp'] is not None):
            problems.append('XMP %s' % ('missing' if want_xmp else 'present'))
        if i['xmp'] is not None:
            if 'Test Creator' not in i['xmp']:
                problems.append('XMP without the creator')
            if ('GPSLatitude' in i['xmp']) != ('gps' in kept):
                problems.append('XMP GPS %s' % ('present' if 'GPSLatitude' in i['xmp']
                                                else 'missing'))
        want_iptc = 'iptc' in kept and f in HAS['iptc']
        if want_iptc != bool(i['iptc']):
            problems.append('IPTC %s' % ('missing' if want_iptc else 'present'))
        want_comment = 'comment' in kept and f in HAS['comment']
        if want_comment != (i['comment'] is not None and 'Test comment' in i['comment']):
            problems.append('comment %s' % ('missing' if want_comment else 'present'))
        want_icc = 'icc' in kept and f in HAS['icc']
        desc = icc_description(i['icc'])
        if f == 'avif':
            # the AVIF exporter has no ICC switch: it writes the image's
            # profile always; after the conversion to sRGB that is sRGB
            want_desc = 'Adobe' if m == 'icc-adobe' else 'sRGB'
            if desc is None or want_desc not in desc:
                problems.append('ICC %r, not %s' % (desc, want_desc))
        else:
            if want_icc != (desc is not None):
                problems.append('ICC %s' % ('missing' if want_icc else 'present'))
            if desc is not None:
                want_desc = 'Adobe' if m == 'icc-adobe' else 'sRGB'
                if want_desc not in desc:
                    problems.append('ICC %r, not %s' % (desc, want_desc))
        report(not problems, '%s: %s%s' % (name, 'kept ' + ', '.join(sorted(kept)) if kept
                                           else 'all stripped', (': ' + '; '.join(problems))
                                           if problems else ''))
        # ImageMagick sees the same (it reads JPEG, PNG, WebP, AVIF)
        if f in ('jpeg', 'png', 'png8', 'webp') and m in ('strip', 'all'):
            prof = magick_profiles(cases[name]['path'])
            want = [] if m == 'strip' else ['exif', 'icc', 'xmp'] + (
                ['iptc'] if f in HAS['iptc'] else [])
            want = sorted(p for p in want if p)
            got = [p for p in prof if p in ('exif', 'icc', 'iptc', 'xmp', '8bim')]
            if '8bim' in got:
                got = sorted(set(got) - {'8bim'} | {'iptc'})
            report(got == want, '%s: ImageMagick sees the profiles %s' % (name, got))
        # and GIMP too
        rb = cases[name].get('readback', {})
        gps_rb = 'Exif.GPSInfo.GPSLatitude' in rb or 'Xmp.exif.GPSLatitude' in rb
        if m == 'strip':
            report(not any(k.startswith(('Exif.', 'Xmp.', 'Iptc.')) for k in rb),
                   '%s: GIMP reads no metadata back' % name)
        elif m in ('exif', 'xmp') and f not in ('gif',):
            report(not gps_rb, '%s: GIMP reads no GPS back' % name)
        elif m in ('exif-gps',) and f in HAS['exif']:
            report(gps_rb, '%s: GIMP reads the GPS back' % name)

# the kept Adobe RGB profile comes back when GIMP loads the file (JPEG
# XL carries the colour space in the codestream: GIMP converts it to sRGB
# on loading and shows no profile; gimp-test.py checks its colours)
for f in formats:
    name = 'meta-%s-icc-adobe' % f
    if not ok_case(name) or f == 'gif':
        continue
    got = cases[name].get('readback', {}).get('profile')
    if f == 'jxl':
        continue
    report(got is not None and 'Adobe' in got, '%s: GIMP reads the Adobe RGB profile back '
           '(%s)' % (name, got))

# ------------------------------------------------------------ preview = file

for name, c in sorted(cases.items()):
    if not c.get('preview'):
        continue
    raw = open(os.path.join(out, 'cases', name + '.decoded.rgba'), 'rb').read()
    prev = np.frombuffer(raw, np.uint8).reshape(c['height'], c['width'], 4)
    ref = np.frombuffer(open(os.path.join(out, 'cases', name + '.reference.rgba'), 'rb').read(),
                        np.uint8).reshape(c['reference-size'][1], c['reference-size'][0], 4)
    report(os.path.getsize(c['path']) == c['file-size'], '%s: the file written is the size '
           'shown (%d bytes)' % (name, c['file-size']))
    if c['path'].endswith('.jxl'):
        continue
    w, h, px = magick_decode(c['path'])
    d = np.abs(px.astype(int) - prev.astype(int))
    lossless = c['path'].endswith(('.png', '.gif')) or c['settings'].get('webp-lossless')
    if lossless:
        report(int(d.max()) == 0, '%s: the preview shows exactly the pixels of the file' % name)
    else:
        # different decoders (GIMP's and ImageMagick's) may round the
        # colour conversion differently
        report(float(d.mean()) <= 1.0 and int(d.max()) <= 12,
               '%s: the preview shows the pixels of the file as another decoder sees them '
               '(mean difference %.3f, max %d)' % (name, float(d.mean()), int(d.max())))
    rgb = (ref[:, :, 3] > 0) | (px[:, :, 3] > 0)
    e = (ref[:, :, :3].astype(float) - px[:, :, :3].astype(float))[rgb]
    mse = float(np.mean(e * e)) if e.size else 0.0
    if c['mse'] is not None:
        tol = max(0.5, 0.1 * mse)
        report(abs(mse - c['mse']) <= tol, '%s: the error shown (MSE %.2f) is the file\'s '
               '(%.2f)' % (name, c['mse'], mse))

before = results['images'].get('before', {})
after = results['images'].get('after', {})
report(before == after and len(before) >= 7, 'the %d test images are unchanged after all the '
       'exports' % len(before))
if results.get('timing'):
    for f, (enc, dec, ref, n) in results['timing'].items():
        print('SFW FILES INFO a 4000 x 3000 preview in %s: %.2f s to encode, %.2f s to decode '
              '(%d bytes)' % (f, enc, dec, n))

print('SFW FILES failures: %d of %d' % (failures, checked))
sys.exit(1 if failures else 0)
