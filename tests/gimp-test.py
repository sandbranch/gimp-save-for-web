# Runs inside a headless GIMP (tests/run.sh): builds the test images,
# records their state, exports them through plug-in-save-for-web in every
# format and with the options under test, and writes what the procedure
# returned, what GIMP reads back from each file, the preview's decoded
# pixels and the state of the images afterwards into
# $SFW_OUT/cases/ and $SFW_OUT/results.json. tests/check.py then checks
# the files outside GIMP. Checks that need GIMP are done here and printed
# as "SFW GIMP PASS/FAIL ...".
#
# SFW_ONLY: only the cases whose names contain it.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import os
import random
import struct
import sys
import time
import traceback

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, Gio, GLib   # noqa: E402

SRC = os.environ['SFW_SRC']
OUT = os.environ['SFW_OUT']
ONLY = os.environ.get('SFW_ONLY', '')
CASES = os.path.join(OUT, 'cases')
os.makedirs(CASES, exist_ok=True)
sys.path.insert(0, os.path.join(SRC, 'save-for-web'))
import sfw_model as model     # noqa: E402
import sfw_engine as engine   # noqa: E402

pdb = Gimp.get_pdb()
failures = 0
results = {'cases': {}, 'images': {}, 'only': ONLY}


def report(ok, what):
    global failures
    print('SFW GIMP %s %s' % ('PASS' if ok else 'FAIL', what), flush=True)
    if not ok:
        failures += 1


# ------------------------------------------------------------ test images

def fill(layer, fn, fmt="R'G'B'A float"):
    w, h = layer.get_width(), layer.get_height()
    n = len(fmt.split()[0].replace("'", ''))
    data = bytearray()
    for y in range(h):
        for x in range(w):
            data += struct.pack('f' * n, *fn(x, y))
    buf = layer.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), fmt, bytes(data))
    buf.flush()


def new_image(w, h, base=Gimp.ImageBaseType.RGB, precision=Gimp.Precision.U8_NON_LINEAR):
    img = Gimp.Image.new_with_precision(w, h, base, precision)
    return img


def add_layer(img, name, w, h, alpha=True, x=0, y=0, visible=True):
    if img.get_base_type() == Gimp.ImageBaseType.GRAY:
        t = Gimp.ImageType.GRAYA_IMAGE if alpha else Gimp.ImageType.GRAY_IMAGE
    else:
        t = Gimp.ImageType.RGBA_IMAGE if alpha else Gimp.ImageType.RGB_IMAGE
    layer = Gimp.Layer.new(img, name, w, h, t, 100, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    layer.set_offsets(x, y)
    layer.set_visible(visible)
    return layer


rng = random.Random(7)
NOISE = [rng.random() for _ in range(4096)]


def photo_pixel(x, y):
    # smooth gradients, a disc, stripes and some noise: something like a
    # photo for the lossy encoders
    n = NOISE[(x * 31 + y * 17) % 4096] * 0.08
    r = 0.55 + 0.4 * (x / 480.0) - 0.2 * (y / 320.0) + n
    g = 0.35 + 0.3 * (y / 320.0) + n
    b = 0.75 - 0.4 * (x / 480.0) + n
    dx, dy = x - 300, y - 150
    if dx * dx + dy * dy < 70 * 70:
        r, g, b = 0.9, 0.8 + n, 0.2
    if 60 <= x < 180 and (y // 6) % 2 == 0 and 200 <= y < 290:
        r, g, b = 0.1, 0.1, 0.12
    return (min(r, 1), min(g, 1), min(b, 1), 1.0)


def make_photo():
    img = new_image(480, 320)
    layer = add_layer(img, 'photo', 480, 320, alpha=False)
    fill(layer, lambda x, y: photo_pixel(x, y)[:3], "R'G'B' float")
    return img


def make_alpha():
    # left third transparent, a vertical alpha ramp in the middle, opaque
    # right third; red
    img = new_image(240, 120)
    layer = add_layer(img, 'alpha', 240, 120)

    def px(x, y):
        a = 0.0 if x < 80 else (y / 119.0 if x < 160 else 1.0)
        return (0.85, 0.1, 0.1, a)
    fill(layer, px)
    return img


def make_layers():
    # a blue background, a green square layer at an offset, a hidden
    # magenta layer over all, and a layer with a mask hiding its left half
    img = new_image(200, 150)
    bg = add_layer(img, 'background', 200, 150, alpha=False)
    fill(bg, lambda x, y: (0.1, 0.2, 0.8), "R'G'B' float")
    sq = add_layer(img, 'square', 50, 40, x=20, y=30)
    fill(sq, lambda x, y: (0.1, 0.8, 0.2, 1.0))
    masked = add_layer(img, 'masked', 60, 60, x=120, y=60)
    fill(masked, lambda x, y: (0.95, 0.9, 0.1, 1.0))
    mask = masked.create_mask(Gimp.AddMaskType.WHITE)
    masked.add_mask(mask)
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 120, 60, 30, 60)
    Gimp.context_push()
    Gimp.context_set_foreground(Gegl.Color.new('black'))
    mask.edit_fill(Gimp.FillType.FOREGROUND)
    Gimp.context_pop()
    Gimp.Selection.none(img)
    hidden = add_layer(img, 'hidden', 200, 150, visible=False)
    fill(hidden, lambda x, y: (1.0, 0.0, 1.0, 1.0))
    return img


def make_gray():
    img = new_image(160, 100, Gimp.ImageBaseType.GRAY)
    layer = add_layer(img, 'gray', 160, 100, alpha=False)
    fill(layer, lambda x, y: (x / 159.0 * 0.7 + NOISE[(x * 7 + y * 13) % 4096] * 0.2,),
         "Y' float")
    return img


def make_indexed():
    img = make_photo()
    img.scale(160, 100)
    img.convert_indexed(Gimp.ConvertDitherType.NONE, Gimp.ConvertPaletteType.GENERATE, 6,
                        False, True, '')
    return img


def make_profile():
    # Adobe RGB, 16 bit, with Exif (artist, GPS), XMP (creator, GPS), IPTC
    # and a comment
    img = new_image(120, 80, precision=Gimp.Precision.U16_NON_LINEAR)
    layer = add_layer(img, 'profile', 120, 80, alpha=False)
    fill(layer, lambda x, y: (0.2, 0.5 + 0.3 * x / 119.0, 0.3 + 0.2 * y / 79.0),
         "R'G'B' float")
    img.set_color_profile(Gimp.ColorProfile.new_rgb_adobe())
    md = img.get_metadata() or Gimp.Metadata.new()
    md.set_tag_string('Exif.Image.Artist', 'Test Artist')
    md.set_tag_string('Exif.Image.Copyright', 'CC0 test image')
    md.set_gps_info(18.0686, 59.3293, 28.0)
    md.set_tag_string('Xmp.dc.creator', 'Test Creator')
    md.set_tag_string('Xmp.exif.GPSLatitude', '59,19.758N')
    md.set_tag_string('Xmp.exif.GPSLongitude', '18,4.116E')
    md.set_tag_string('Iptc.Application2.Byline', 'Test Byline')
    img.set_metadata(md)
    img.attach_parasite(Gimp.Parasite.new('gimp-comment', Gimp.PARASITE_PERSISTENT,
                                          b'Test comment\0'))
    return img


def make_pixelart():
    # 16 x 12 with 4 colours, for resizing with no interpolation
    img = new_image(16, 12)
    layer = add_layer(img, 'pixels', 16, 12, alpha=False)
    cols = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0)]
    fill(layer, lambda x, y: cols[(x // 4 + y // 3) % 4], "R'G'B' float")
    return img


# ------------------------------------------------------------ state

def state(img):
    """Everything about the image that Export for Web must not change."""
    st = {'size': [img.get_width(), img.get_height()],
          'base': int(img.get_base_type()), 'precision': int(img.get_precision()),
          'dirty': img.is_dirty(), 'profile': None, 'layers': [], 'parasites': [],
          'selection': list(Gimp.Selection.bounds(img))}
    p = img.get_color_profile()
    if p is not None:
        st['profile'] = p.get_description()
    md = img.get_metadata()
    if md is not None:
        st['metadata'] = sorted('%s=%s' % (t, md.get_tag_string(t)) for t in
                                list(md.get_exif_tags() or []) + list(md.get_xmp_tags() or []) +
                                list(md.get_iptc_tags() or []) if 'DateTime' not in t)
    st['parasites'] = sorted(img.get_parasite_list())
    for layer in img.get_layers():
        rect = Gegl.Rectangle.new(0, 0, layer.get_width(), layer.get_height())
        data = layer.get_buffer().get(rect, 1.0, "R'G'B'A float", Gegl.AbyssPolicy.NONE)
        mask = layer.get_mask()
        if mask is not None:
            data = bytes(data) + bytes(mask.get_buffer().get(rect, 1.0, 'Y float',
                                                              Gegl.AbyssPolicy.NONE))
        st['layers'].append({'name': layer.get_name(), 'visible': layer.get_visible(),
                             'offsets': list(layer.get_offsets()[1:]),
                             'size': [layer.get_width(), layer.get_height()],
                             'mask': layer.get_mask() is not None,
                             'md5': hashlib.md5(bytes(data)).hexdigest()})
    return st


# ------------------------------------------------------------ running

def run_proc(img, settings, path):
    proc = pdb.lookup_procedure('plug-in-save-for-web')
    c = proc.create_config()
    c.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
    c.set_property('image', img)
    c.set_core_object_array('drawables', img.get_selected_layers() or img.get_layers()[:1])
    c.set_property('file', Gio.File.new_for_path(path))
    for k, v in settings.items():
        c.set_property(k, v)
    t0 = time.time()
    r = proc.run(c)
    status = r.index(0)
    out = {'status': status.value_nick, 'seconds': round(time.time() - t0, 3)}
    if status == Gimp.PDBStatusType.SUCCESS:
        out.update({'file-size': r.index(1), 'width': r.index(2), 'height': r.index(3),
                    'quality': r.index(4), 'fits': r.index(5), 'note': r.index(6)})
    else:
        err = r.index(1) if r.length() > 1 else None
        out['error'] = getattr(err, 'message', str(err))
    return out


def read_back(path):
    """What GIMP reads from the file: size, type, profile, metadata."""
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
    try:
        r = {'size': [img.get_width(), img.get_height()], 'base': int(img.get_base_type()),
             'profile': None, 'layers': len(img.get_layers())}
        p = img.get_color_profile()
        if p is not None:
            r['profile'] = p.get_description()
        md = img.get_metadata()
        if md is not None:
            for tag in ('Exif.Image.Artist', 'Xmp.dc.creator', 'Iptc.Application2.Byline',
                        'Exif.GPSInfo.GPSLatitude', 'Xmp.exif.GPSLatitude'):
                if md.try_has_tag(tag):
                    r[tag] = md.get_tag_string(tag)
        w, h, px = engine.image_pixels(img)
        r['md5'] = hashlib.md5(px).hexdigest()
        return r
    finally:
        img.delete()


def case(name, img_name, settings, readback=True):
    if ONLY and ONLY not in name:
        return None
    img = images[img_name]
    s = model.check(settings)
    path = os.path.join(CASES, '%s.%s' % (name, model.EXTENSIONS[s['format']]))
    try:
        n_images = len(Gimp.get_images())
        out = run_proc(img, settings, path)
        out['image'] = img_name
        out['settings'] = settings
        out['path'] = path
        out['leaked-images'] = len(Gimp.get_images()) - n_images
        if out['status'] == 'success' and readback:
            out['readback'] = read_back(path)
        results['cases'][name] = out
        print('SFW case %s: %s %s bytes q=%s (%.2f s)%s' % (
            name, out['status'], out.get('file-size'), out.get('quality'), out['seconds'],
            (' ' + out.get('note', '')) if out.get('note') else (
                ' ' + out['error'] if 'error' in out else '')), flush=True)
        return out
    except Exception:
        traceback.print_exc()
        report(False, '%s: an exception' % name)
        return None


def preview_case(name, img_name, settings):
    """The engine as the dialog uses it: render, decode for the preview;
    the file and the decoded pixels are written for check.py to compare
    with a decoder outside GIMP."""
    if ONLY and ONLY not in name:
        return
    img = images[img_name]
    s = model.check(settings)
    session = engine.Session(img)
    try:
        enc = session.render(s)
        path = os.path.join(CASES, '%s.%s' % (name, enc.ext))
        engine.write_file(path, enc.data)
        w, h, px = session.decode(enc)
        rw, rh, ref = session.reference(s)
        with open(os.path.join(CASES, name + '.decoded.rgba'), 'wb') as f:
            f.write(px)
        with open(os.path.join(CASES, name + '.reference.rgba'), 'wb') as f:
            f.write(ref)
        mse = engine.mse(ref, px) if (rw, rh) == (w, h) else None
        results['cases'][name] = {'status': 'success', 'preview': True, 'path': path,
                                  'file-size': enc.size, 'width': w, 'height': h,
                                  'reference-size': [rw, rh], 'mse': mse,
                                  'settings': settings, 'image': img_name}
        print('SFW case %s: preview %d bytes, %d x %d, mse %s' % (name, enc.size, w, h, mse),
              flush=True)
    finally:
        session.close()


# ------------------------------------------------------------ the cases

images = {}
for name, make in (('photo', make_photo), ('alpha', make_alpha), ('layers', make_layers),
                   ('gray', make_gray), ('indexed', make_indexed), ('profile', make_profile),
                   ('pixelart', make_pixelart)):
    img = make()
    img.clean_all()
    images[name] = img
# a selection on the photo, kept through all the exports
images['photo'].select_rectangle(Gimp.ChannelOps.REPLACE, 100, 50, 200, 120)
before = {n: state(i) for n, i in images.items()}
n_images = len(Gimp.get_images())
formats = engine.available_formats()
results['formats'] = formats
report(set(formats) >= {'jpeg', 'png', 'png8', 'webp', 'gif'},
       'GIMP has the exporters: %s' % ', '.join(formats))

# every format with its defaults, on each image
for img_name in ('photo', 'alpha', 'layers', 'gray', 'indexed', 'profile'):
    for f in formats:
        case('%s-%s' % (img_name, f), img_name, {'format': f})

# JPEG options
case('jpeg-q20', 'photo', {'format': 'jpeg', 'jpeg-quality': 20})
case('jpeg-q95', 'photo', {'format': 'jpeg', 'jpeg-quality': 95})
case('jpeg-baseline', 'photo', {'format': 'jpeg', 'jpeg-progressive': False})
for sub in ('444', '422', '440', '420'):
    case('jpeg-sub%s' % sub, 'photo', {'format': 'jpeg', 'jpeg-subsampling': sub})
case('jpeg-noopt', 'photo', {'format': 'jpeg', 'jpeg-optimize': False,
                             'jpeg-progressive': False})
case('jpeg-smooth', 'photo', {'format': 'jpeg', 'jpeg-smoothing': 0.5})
case('jpeg-matte-black', 'alpha', {'format': 'jpeg', 'matte': 'black'})
case('jpeg-matte-white', 'alpha', {'format': 'jpeg', 'matte': 'white'})

# PNG and PNG-8
case('png-interlace', 'photo', {'format': 'png', 'png-interlace': True})
case('png-c0', 'photo', {'format': 'png', 'png-compression': 0})
case('png-c9', 'photo', {'format': 'png', 'png-compression': 9})
for n in (2, 16, 64):
    case('png8-c%d' % n, 'photo', {'format': 'png8', 'colors': n})
for d in ('none', 'fs', 'fs-low-bleed', 'positioned'):
    case('png8-dither-%s' % d, 'photo', {'format': 'png8', 'colors': 16, 'dither': d})
case('png8-web', 'photo', {'format': 'png8', 'palette': 'web'})
case('png8-mono', 'photo', {'format': 'png8', 'palette': 'mono'})
case('png8-keep', 'indexed', {'format': 'png8', 'palette': 'keep'})
case('png8-keep-scaled', 'indexed', {'format': 'png8', 'palette': 'keep', 'scale-mode': 'percent',
                                     'percent': 50.0})
case('png8-alpha', 'alpha', {'format': 'png8', 'colors': 8})
case('png8-alpha-dither', 'alpha', {'format': 'png8', 'colors': 8, 'alpha-dither': True})
case('gif-c32', 'photo', {'format': 'gif', 'colors': 32})
case('gif-interlace', 'photo', {'format': 'gif', 'gif-interlace': True})
case('gif-alpha', 'alpha', {'format': 'gif'})

# WebP, AVIF, JPEG XL
case('webp-q30', 'photo', {'format': 'webp', 'webp-quality': 30})
case('webp-q95', 'photo', {'format': 'webp', 'webp-quality': 95})
case('webp-lossless', 'photo', {'format': 'webp', 'webp-lossless': True})
case('webp-alpha', 'alpha', {'format': 'webp'})
case('webp-sharp', 'photo', {'format': 'webp', 'webp-sharp-yuv': True, 'webp-preset': 'photo'})
if 'avif' in formats:
    case('avif-q20', 'photo', {'format': 'avif', 'avif-quality': 20})
    case('avif-q90', 'photo', {'format': 'avif', 'avif-quality': 90})
    case('avif-lossless', 'pixelart', {'format': 'avif', 'avif-lossless': True})
    case('avif-444', 'photo', {'format': 'avif', 'avif-pixel-format': 'yuv444'})
    case('avif-alpha', 'alpha', {'format': 'avif'})
if 'jxl' in formats:
    case('jxl-q50', 'photo', {'format': 'jxl', 'jxl-quality': 50})
    case('jxl-q95', 'photo', {'format': 'jxl', 'jxl-quality': 95})
    case('jxl-lossless', 'photo', {'format': 'jxl', 'jxl-lossless': True})
    case('jxl-alpha', 'alpha', {'format': 'jxl'})

# resize and crop
case('crop', 'photo', {'format': 'png', 'crop-to-selection': True})
case('crop-none', 'layers', {'format': 'png', 'crop-to-selection': True})
case('scale-percent', 'photo', {'format': 'jpeg', 'scale-mode': 'percent', 'percent': 25.0})
case('scale-width', 'photo', {'format': 'webp', 'scale-mode': 'size', 'width': 200,
                              'keep-aspect': True})
case('scale-height', 'photo', {'format': 'png', 'scale-mode': 'size', 'height': 100,
                               'width': 0, 'keep-aspect': True})
case('scale-free', 'photo', {'format': 'png', 'scale-mode': 'size', 'width': 100,
                             'height': 100, 'keep-aspect': False})
case('scale-up-none', 'pixelart', {'format': 'png', 'scale-mode': 'percent', 'percent': 400.0,
                                   'interpolation': 'none'})
case('scale-up-cubic', 'pixelart', {'format': 'png', 'scale-mode': 'percent', 'percent': 400.0,
                                    'interpolation': 'cubic'})
case('crop-scale', 'photo', {'format': 'jpeg', 'crop-to-selection': True, 'scale-mode': 'percent',
                             'percent': 50.0})

# target size
for f, kb in (('jpeg', 12.0), ('webp', 8.0), ('avif', 6.0), ('jxl', 10.0), ('png8', 40.0),
              ('gif', 30.0)):
    if f in formats:
        case('target-%s' % f, 'photo', {'format': f, 'target-size': True, 'target-kb': kb})
case('target-jpeg-impossible', 'photo', {'format': 'jpeg', 'target-size': True,
                                         'target-kb': 0.3})
case('target-jpeg-easy', 'photo', {'format': 'jpeg', 'target-size': True, 'target-kb': 5000.0})
case('target-png', 'photo', {'format': 'png', 'target-size': True, 'target-kb': 10.0})
# the search's answer is the highest quality that fits: one step more
# does not (JPEG sizes rise with the quality)
t = results['cases'].get('target-jpeg')
if t and t.get('status') == 'success' and t['quality'] < 100:
    nxt = case('target-jpeg-next', 'photo', {'format': 'jpeg',
                                             'jpeg-quality': t['quality'] + 1})
    if nxt:
        report(nxt['file-size'] > 12000, 'target-jpeg: quality %d fits (%d bytes), %d does not '
               '(%d bytes)' % (t['quality'], t['file-size'], t['quality'] + 1, nxt['file-size']))

# metadata and colour
META = {'strip': {},
        'exif': {'keep-exif': True},
        'exif-gps': {'keep-exif': True, 'remove-gps': False},
        'xmp': {'keep-xmp': True},
        'xmp-gps': {'keep-xmp': True, 'remove-gps': False},
        'iptc': {'keep-iptc': True},
        'icc': {'keep-color-profile': True},
        'icc-adobe': {'keep-color-profile': True, 'convert-srgb': False},
        'comment': {'keep-comment': True},
        'all': {'keep-exif': True, 'keep-xmp': True, 'keep-iptc': True,
                'keep-color-profile': True, 'keep-comment': True, 'remove-gps': False}}
for f in formats:
    for m, extra in META.items():
        case('meta-%s-%s' % (f, m), 'profile', dict(extra, format=f))
case('meta-png-nosrgb', 'profile', {'format': 'png', 'convert-srgb': False})
if 'jxl' in formats:
    # (lossless, so that only the colour handling can differ)
    case('meta-jxl-nosrgb', 'profile', {'format': 'jxl', 'convert-srgb': False,
                                        'jxl-lossless': True})

# the preview's pixels
for f in formats:
    preview_case('preview-%s' % f, 'photo', {'format': f})
preview_case('preview-alpha-png', 'alpha', {'format': 'png'})
preview_case('preview-alpha-jpeg', 'alpha', {'format': 'jpeg'})
preview_case('preview-target-webp', 'photo', {'format': 'webp', 'target-size': True,
                                              'target-kb': 8.0})

# how long the dialog waits for a preview of a 12-megapixel image: the
# encode, the decode and the reference pixels (measured, not checked:
# it depends on the machine)
if not ONLY or 'timing' in ONLY:
    big = images['photo'].duplicate()
    big.scale(4000, 3000)
    big.clean_all()
    images_timing = engine.Session(big)
    try:
        for f in formats:
            s = model.check({'format': f})
            t0 = time.time()
            enc = images_timing.render(s)
            t1 = time.time()
            images_timing.decode(enc)
            t2 = time.time()
            images_timing.reference(s)
            t3 = time.time()
            results.setdefault('timing', {})[f] = [round(t1 - t0, 2), round(t2 - t1, 2),
                                                   round(t3 - t2, 2), enc.size]
            print('SFW GIMP INFO 4000 x 3000 %s: encode %.2f s, decode %.2f s, reference '
                  '%.2f s, %d bytes' % (f, t1 - t0, t2 - t1, t3 - t2, enc.size), flush=True)
    finally:
        images_timing.close()
        big.delete()

# errors: no file; a format this GIMP does not have is refused by the
# choice itself
proc = pdb.lookup_procedure('plug-in-save-for-web')
c = proc.create_config()
c.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
c.set_property('image', images['photo'])
r = proc.run(c)
report(r.index(0) == Gimp.PDBStatusType.CALLING_ERROR, 'no file: a calling error (%s)' %
       r.index(0).value_nick)

# ------------------------------------------------------------ after

# sRGB conversion: the PNG of the Adobe RGB image holds the pixels of
# GIMP's own conversion of it to sRGB (to 1 level: GIMP rounds the 16-bit
# values of a merged layer slightly differently), and without the
# conversion the pixels are clearly different
def max_diff_to(case_name, px):
    c = results['cases'].get(case_name)
    if not c or c.get('status') != 'success':
        return None
    rb = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(c['path']))
    _, _, got = engine.image_pixels(rb)
    rb.delete()
    return max(abs(a - b) for a, b in zip(px, got))


if 'meta-png-strip' in results['cases']:
    ref = images['profile'].duplicate()
    ref.convert_color_profile(Gimp.ColorProfile.new_rgb_srgb(),
                              Gimp.ColorRenderingIntent.PERCEPTUAL, True)
    ref.convert_precision(Gimp.Precision.U8_NON_LINEAR)
    _, _, px = engine.image_pixels(ref)
    ref.delete()
    d1 = max_diff_to('meta-png-strip', px)
    d2 = max_diff_to('meta-png-nosrgb', px)
    report(d1 is not None and d1 <= 1,
           'convert to sRGB: the PNG has the pixels of GIMP\'s own conversion (max '
           'difference %s)' % d1)
    report(d2 is not None and d2 >= 10,
           'without the conversion the pixels are the Adobe RGB values (max difference to '
           'sRGB %s)' % d2)
    # JPEG XL carries its colour space: GIMP decodes the unconverted
    # (lossless) file to the sRGB colours
    if 'jxl' in formats:
        d3 = max_diff_to('meta-jxl-nosrgb', px)
        report(d3 is not None and d3 <= 2,
               'JPEG XL without the conversion still decodes to the right colours (max '
               'difference to sRGB %s)' % d3)

after = {n: state(i) for n, i in images.items()}
for n in images:
    same = before[n] == after[n]
    if not same:
        for k in before[n]:
            if before[n][k] != after[n][k]:
                print('SFW   %s %s: %r -> %r' % (n, k, before[n][k], after[n][k]))
    report(same, 'the %s image is unchanged (pixels of %d layers, size, type, profile, '
           'metadata, parasites, selection, clean)' % (n, len(before[n]['layers'])))
report(len(Gimp.get_images()) == n_images, 'no image left behind: %d open, %d before' % (
    len(Gimp.get_images()), n_images))
leaks = [n for n, c in results['cases'].items() if c.get('leaked-images')]
report(not leaks, 'no case leaves an image behind%s' % (': ' + ', '.join(leaks) if leaks else ''))
tmp = os.path.dirname(Gimp.temp_file('x').get_path())
left = [f for f in os.listdir(tmp) if f.startswith('gimp-temp-')] if os.path.isdir(tmp) else []
report(not left, 'no temporary file left in %s%s' % (tmp, (': ' + ' '.join(left[:5])) if left
                                                     else ''))
results['images'] = {'before': before, 'after': after}
with open(os.path.join(OUT, 'results.json'), 'w') as f:
    json.dump(results, f, indent=1, default=str)
for img in images.values():
    img.delete()
print('SFW GIMP failures: %d' % failures, flush=True)
