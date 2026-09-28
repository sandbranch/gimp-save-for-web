# -*- coding: utf-8 -*-
#
# Save for Web for GIMP 3: the settings and the arithmetic, without GIMP
# Copyright 2026 David
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The settings of Save for Web and everything about them that needs no
GIMP: defaults, choices, the output size, the quality to JPEG XL distance
mapping, the target-size search and the download time estimate. Tested
on its own by tests/unit.py."""

import math
import re

# ------------------------------------------------------------ choices
# (nick, label); the nick is what the procedure argument takes

FORMATS = [
    ('jpeg', 'JPEG'),
    ('png', 'PNG (24/32 bit)'),
    ('png8', 'PNG-8 (indexed)'),
    ('webp', 'WebP'),
    ('avif', 'AVIF'),
    ('jxl', 'JPEG XL'),
    ('gif', 'GIF'),
]
EXTENSIONS = {'jpeg': 'jpg', 'png': 'png', 'png8': 'png', 'webp': 'webp',
              'avif': 'avif', 'jxl': 'jxl', 'gif': 'gif'}
# the GIMP export procedure of each format
EXPORTERS = {'jpeg': 'file-jpeg-export', 'png': 'file-png-export',
             'png8': 'file-png-export', 'webp': 'file-webp-export',
             'avif': 'file-heif-av1-export', 'jxl': 'file-jpegxl-export',
             'gif': 'file-gif-export'}

SUBSAMPLING = [
    ('420', '4:2:0 (smallest)'),
    ('422', '4:2:2'),
    ('440', '4:4:0'),
    ('444', '4:4:4 (best colour)'),
]
# file-jpeg-export's sub-sampling choice for each
JPEG_SUBSAMPLING = {'444': 'sub-sampling-1x1', '422': 'sub-sampling-2x1',
                    '440': 'sub-sampling-1x2', '420': 'sub-sampling-2x2'}

PALETTES = [
    ('optimum', 'Optimum palette'),
    ('web', 'Web palette (216 colours)'),
    ('mono', 'Black and white'),
    ('keep', 'Keep the image\'s palette'),
]
DITHERS = [
    ('none', 'None'),
    ('fs', 'Floyd-Steinberg'),
    ('fs-low-bleed', 'Floyd-Steinberg, reduced bleeding'),
    ('positioned', 'Positioned'),
]
WEBP_PRESETS = [
    ('default', 'Default'), ('picture', 'Picture'), ('photo', 'Photo'),
    ('drawing', 'Drawing'), ('icon', 'Icon'), ('text', 'Text'),
]
AVIF_PIXEL_FORMATS = [
    ('yuv420', 'YUV 4:2:0 (smallest)'),
    ('yuv444', 'YUV 4:4:4'),
    ('rgb', 'RGB'),
]
AVIF_SPEEDS = [('slow', 'Slow (smaller)'), ('balanced', 'Balanced'), ('fast', 'Fast')]
JXL_EFFORTS = [
    ('lightning', '1 lightning (fastest)'), ('thunder', '2 thunder'),
    ('falcon', '3 falcon'), ('cheetah', '4 cheetah'), ('hare', '5 hare'),
    ('wombat', '6 wombat'), ('squirrel', '7 squirrel'), ('kitten', '8 kitten'),
    ('tortoise', '9 tortoise (smallest)'),
]
SCALE_MODES = [
    ('none', 'Original size'),
    ('size', 'Width and height'),
    ('percent', 'Percent'),
]
INTERPOLATIONS = [
    ('none', 'None (pixel art)'),
    ('linear', 'Linear'),
    ('cubic', 'Cubic'),
    ('nohalo', 'NoHalo'),
    ('lohalo', 'LoHalo'),
]
MATTES = [
    ('white', 'White'),
    ('black', 'Black'),
    ('background', 'GIMP\'s background colour'),
]

# ------------------------------------------------------------ settings
# name: (default, kind, extra); kind is 'choice' (extra: the choices),
# 'int' or 'double' (extra: (min, max)) or 'bool'. The names are those of
# the procedure's arguments.

SETTINGS = {
    'format': ('jpeg', 'choice', FORMATS),
    # JPEG
    'jpeg-quality': (85, 'int', (0, 100)),
    'jpeg-progressive': (True, 'bool', None),
    'jpeg-subsampling': ('420', 'choice', SUBSAMPLING),
    'jpeg-optimize': (True, 'bool', None),
    'jpeg-smoothing': (0.0, 'double', (0.0, 1.0)),
    # PNG
    'png-compression': (9, 'int', (0, 9)),
    'png-interlace': (False, 'bool', None),
    # PNG-8 and GIF
    'colors': (256, 'int', (2, 256)),
    'palette': ('optimum', 'choice', PALETTES),
    'dither': ('fs', 'choice', DITHERS),
    'alpha-dither': (False, 'bool', None),
    'remove-unused': (True, 'bool', None),
    'gif-interlace': (False, 'bool', None),
    # WebP
    'webp-lossless': (False, 'bool', None),
    'webp-quality': (80, 'int', (0, 100)),
    'webp-alpha-quality': (100, 'int', (0, 100)),
    'webp-preset': ('default', 'choice', WEBP_PRESETS),
    'webp-sharp-yuv': (False, 'bool', None),
    # AVIF
    'avif-lossless': (False, 'bool', None),
    'avif-quality': (60, 'int', (0, 100)),
    'avif-pixel-format': ('yuv420', 'choice', AVIF_PIXEL_FORMATS),
    'avif-speed': ('balanced', 'choice', AVIF_SPEEDS),
    # JPEG XL
    'jxl-lossless': (False, 'bool', None),
    'jxl-quality': (85, 'int', (1, 100)),
    'jxl-effort': ('squirrel', 'choice', JXL_EFFORTS),
    # target size
    'target-size': (False, 'bool', None),
    'target-kb': (100.0, 'double', (0.1, 1000000.0)),
    # size and crop
    'crop-to-selection': (False, 'bool', None),
    'scale-mode': ('none', 'choice', SCALE_MODES),
    'width': (0, 'int', (0, 65535)),
    'height': (0, 'int', (0, 65535)),
    'percent': (100.0, 'double', (1.0, 1000.0)),
    'keep-aspect': (True, 'bool', None),
    'interpolation': ('lohalo', 'choice', INTERPOLATIONS),
    # colour and metadata
    'convert-srgb': (True, 'bool', None),
    'keep-color-profile': (False, 'bool', None),
    'keep-exif': (False, 'bool', None),
    'remove-gps': (True, 'bool', None),
    'keep-xmp': (False, 'bool', None),
    'keep-iptc': (False, 'bool', None),
    'keep-comment': (False, 'bool', None),
    'matte': ('white', 'choice', MATTES),
}


def defaults():
    return {k: v[0] for k, v in SETTINGS.items()}


def check(s):
    """The settings s completed with defaults and clamped to their ranges;
    unknown keys are kept as they are. Raises ValueError for an unknown
    choice."""
    out = defaults()
    out.update(s)
    for k, (default, kind, extra) in SETTINGS.items():
        v = out[k]
        if kind == 'choice':
            if v not in [n for n, _ in extra]:
                raise ValueError('%s: %r is not one of %s' %
                                 (k, v, ', '.join(n for n, _ in extra)))
        elif kind == 'int':
            out[k] = min(max(int(v), extra[0]), extra[1])
        elif kind == 'double':
            out[k] = min(max(float(v), extra[0]), extra[1])
        else:
            out[k] = bool(v)
    return out


# which settings each part of the work depends on: the base image (crop,
# scale, colour, metadata), the encoding of each format
BASE_KEYS = ('crop-to-selection', 'scale-mode', 'width', 'height', 'percent',
             'keep-aspect', 'interpolation', 'convert-srgb', 'keep-color-profile',
             'keep-exif', 'remove-gps', 'keep-xmp', 'keep-iptc', 'keep-comment')
INDEXED_KEYS = ('colors', 'palette', 'dither', 'alpha-dither', 'remove-unused')
FORMAT_KEYS = {
    'jpeg': ('jpeg-quality', 'jpeg-progressive', 'jpeg-subsampling', 'jpeg-optimize',
             'jpeg-smoothing', 'matte'),
    'png': ('png-compression', 'png-interlace'),
    'png8': INDEXED_KEYS + ('png-compression', 'png-interlace'),
    'webp': ('webp-lossless', 'webp-quality', 'webp-alpha-quality', 'webp-preset',
             'webp-sharp-yuv'),
    'avif': ('avif-lossless', 'avif-quality', 'avif-pixel-format', 'avif-speed'),
    'jxl': ('jxl-lossless', 'jxl-quality', 'jxl-effort'),
    'gif': INDEXED_KEYS + ('gif-interlace',),
}


def key(s, keys):
    return tuple(s[k] for k in keys)


# ------------------------------------------------------------ size

def output_size(src_w, src_h, s):
    """The size of the exported image for a source of src_w x src_h (after
    the crop), as (width, height), each at least 1.

    - scale-mode 'none': the source size
    - 'percent': the source size times percent / 100, rounded
    - 'size' with keep-aspect: width wins if it is given (not 0), else
      height; the other follows the aspect ratio, rounded
    - 'size' without keep-aspect: width and height, 0 meaning the source's
    """
    mode = s['scale-mode']
    if mode == 'none':
        return src_w, src_h
    if mode == 'percent':
        f = s['percent'] / 100.0
        return max(1, int(round(src_w * f))), max(1, int(round(src_h * f)))
    w, h = s['width'], s['height']
    if s['keep-aspect']:
        if w > 0:
            return w, max(1, int(round(src_h * w / src_w)))
        if h > 0:
            return max(1, int(round(src_w * h / src_h))), h
        return src_w, src_h
    return (w if w > 0 else src_w), (h if h > 0 else src_h)


# ------------------------------------------------------------ JPEG XL

def jxl_distance(quality):
    """The Butteraugli distance for a quality of 0..100, as libjxl's
    JxlEncoderDistanceFromQuality maps it (cjxl -q), clamped to the
    range of file-jpegxl-export's compression (0.1..15)."""
    q = float(quality)
    if q >= 100:
        d = 0.0
    elif q >= 30:
        d = 0.1 + (100 - q) * 0.09
    else:
        d = 53.0 / 3000.0 * q * q - 23.0 / 20.0 * q + 25.0
    return min(max(d, 0.1), 15.0)


# ------------------------------------------------------------ target size

# the parameter the target-size search varies, per format: (setting, lowest,
# highest). Lossless PNG and lossless modes have none.
SEARCH = {
    'jpeg': ('jpeg-quality', 1, 100),
    'webp': ('webp-quality', 0, 100),
    'avif': ('avif-quality', 0, 100),
    'jxl': ('jxl-quality', 1, 100),
    'png8': ('colors', 2, 256),
    'gif': ('colors', 2, 256),
}


def search_parameter(s):
    """(setting, lowest, highest) for the target-size search with these
    settings, or None if the format has no size knob (PNG-24, lossless,
    a fixed palette)."""
    f = s['format']
    if f not in SEARCH:
        return None
    if s.get(f + '-lossless'):
        return None
    if f in ('png8', 'gif') and s['palette'] != 'optimum':
        return None
    return SEARCH[f]


def search_target(lo, hi, size_of, target):
    """The highest value v in lo..hi with size_of(v) <= target, found by
    bisection, assuming the size grows with v (encoders are nearly but
    not strictly monotonic: the result always fits when found, it may
    just not be the very highest that would).

    Returns (value, size, fits, tried): fits is False when even lo is
    too big (then value is lo); tried is the list of (value, size) in
    the order they were encoded."""
    tried = []
    cache = {}

    def size(v):
        if v not in cache:
            cache[v] = size_of(v)
            tried.append((v, cache[v]))
        return cache[v]

    if size(hi) <= target:
        return hi, cache[hi], True, tried
    if size(lo) > target:
        return lo, cache[lo], False, tried
    good, bad = lo, hi          # size(good) fits, size(bad) does not
    while bad - good > 1:
        mid = (good + bad) // 2
        if size(mid) <= target:
            good = mid
        else:
            bad = mid
    return good, cache[good], True, tried


# ------------------------------------------------------------ download time

# (label, bits per second, round-trip latency in seconds)
CONNECTIONS = [
    ('Slow 3G (400 kbit/s)', 400e3, 0.4),
    ('Fast 3G (1.6 Mbit/s)', 1.6e6, 0.15),
    ('4G (12 Mbit/s)', 12e6, 0.07),
    ('Cable (50 Mbit/s)', 50e6, 0.02),
    ('56k modem', 56e3, 0.12),
]


def download_seconds(nbytes, bits_per_second, latency=0.0):
    """Time to fetch nbytes: one round trip plus the transfer."""
    return latency + nbytes * 8.0 / bits_per_second


def format_seconds(t):
    if t < 0.1:
        return '%d ms' % max(1, int(round(t * 1000)))
    if t < 10:
        return '%.1f s' % t
    if t < 120:
        return '%d s' % int(round(t))
    return '%d min %02d s' % (int(t) // 60, int(round(t)) % 60)


def format_size(nbytes):
    """'812 bytes', '12.3 kB (12,601 bytes)', '1.24 MB (1,301,512 bytes)'
    with kB = 1000 bytes, as browsers and web tools count them."""
    if nbytes < 1000:
        return '%d bytes' % nbytes
    if nbytes < 1000 * 1000:
        return '%.1f kB (%s bytes)' % (nbytes / 1000.0, '{:,}'.format(nbytes))
    return '%.2f MB (%s bytes)' % (nbytes / 1e6, '{:,}'.format(nbytes))


def ratio_text(nbytes, reference):
    """How big nbytes is against reference (the uncompressed RGB(A) size),
    as '12.5 % of uncompressed'."""
    if reference <= 0:
        return ''
    p = 100.0 * nbytes / reference
    return '%s %% of uncompressed' % (('%.1f' % p) if p < 10 else ('%d' % round(p)))


def psnr(mse):
    """Peak signal-to-noise ratio in dB for 8-bit values from the mean
    squared error; infinite for identical images."""
    if mse <= 0:
        return math.inf
    return 10.0 * math.log10(255.0 * 255.0 / mse)


# ------------------------------------------------------------ the dialog

# label and description of each setting (the procedure's arguments)
LABELS = {
    'format': ('_Format', 'The file format'),
    'jpeg-quality': ('_Quality', 'JPEG quality, 0 to 100'),
    'jpeg-progressive': ('_Progressive', 'Progressive JPEG (shows early in a slow browser, '
                         'often smaller)'),
    'jpeg-subsampling': ('_Subsampling', 'Chroma subsampling'),
    'jpeg-optimize': ('_Optimize', 'Optimized Huffman tables (smaller, same pixels)'),
    'jpeg-smoothing': ('S_moothing', 'Smoothing before compression, 0 to 1'),
    'png-compression': ('Co_mpression', 'zlib compression level, 0 to 9 (same pixels)'),
    'png-interlace': ('_Interlace (Adam7)', 'Interlaced PNG'),
    'colors': ('_Colours', 'Number of colours of the optimum palette, 2 to 256'),
    'palette': ('_Palette', 'Palette of PNG-8 and GIF'),
    'dither': ('_Dither', 'Dithering of PNG-8 and GIF'),
    'alpha-dither': ('Dither _transparency', 'Dither the transparency of PNG-8 and GIF'),
    'remove-unused': ('_Remove unused colours', 'Drop unused colours from the palette'),
    'gif-interlace': ('_Interlace', 'Interlaced GIF'),
    'webp-lossless': ('_Lossless', 'Lossless WebP'),
    'webp-quality': ('_Quality', 'WebP quality, 0 to 100'),
    'webp-alpha-quality': ('_Alpha quality', 'WebP quality of the transparency, 0 to 100'),
    'webp-preset': ('P_reset', 'WebP encoder preset'),
    'webp-sharp-yuv': ('_Sharp YUV', 'Sharper colour edges (slower)'),
    'avif-lossless': ('_Lossless', 'Lossless AVIF'),
    'avif-quality': ('_Quality', 'AVIF quality, 0 to 100'),
    'avif-pixel-format': ('_Pixels', 'AVIF pixel format'),
    'avif-speed': ('_Speed', 'AVIF encoder speed'),
    'jxl-lossless': ('_Lossless', 'Lossless JPEG XL'),
    'jxl-quality': ('_Quality', 'JPEG XL quality, 1 to 100 (as cjxl -q; 90 is about '
                    'distance 1, visually lossless)'),
    'jxl-effort': ('_Effort', 'JPEG XL encoder effort'),
    'target-size': ('_Target size', 'Find the highest quality (or number of colours) whose '
                    'file fits in the target size'),
    'target-kb': ('Target (_kB)', 'The target size in kB (1 kB = 1000 bytes)'),
    'crop-to-selection': ('_Crop to selection', 'Export only the bounding box of the '
                          'selection'),
    'scale-mode': ('_Resize', 'How the exported size is given'),
    'width': ('_Width', 'Width in pixels (0: from the height and the aspect)'),
    'height': ('_Height', 'Height in pixels (0: from the width and the aspect)'),
    'percent': ('_Percent', 'Scale in percent'),
    'keep-aspect': ('_Keep aspect ratio', 'Keep the aspect ratio when resizing'),
    'interpolation': ('_Interpolation', 'Interpolation of the resize'),
    'convert-srgb': ('Con_vert to sRGB', 'Convert to sRGB (what browsers assume without '
                     'a profile)'),
    'keep-color-profile': ('Keep colour _profile (ICC)', 'Embed the colour profile'),
    'keep-exif': ('Keep _Exif', 'Keep the Exif metadata'),
    'remove-gps': ('Remove _GPS location', 'Remove the GPS tags from the kept Exif and XMP'),
    'keep-xmp': ('Keep _XMP', 'Keep the XMP metadata'),
    'keep-iptc': ('Keep IPT_C', 'Keep the IPTC metadata (JPEG and PNG; GIMP writes none '
                  'into WebP)'),
    'keep-comment': ('Keep co_mment', 'Keep the image comment (JPEG, PNG)'),
    'matte': ('_Matte', 'The colour transparent pixels are flattened onto (JPEG)'),
}

VIEWS = [('result', 'Result'), ('side', 'Side by side'), ('split', 'Split'),
         ('original', 'Original')]
ZOOMS = [('fit', 'Fit'), ('25', '25 %'), ('50', '50 %'), ('100', '100 %'), ('200', '200 %'),
         ('400', '400 %'), ('800', '800 %')]


def config_path(config):
    """The path of the procedure config's file argument, or ''."""
    f = config.get_property('file')
    path = f.get_path() if f is not None else ''
    # GIMP 3.2 keeps a file argument's last value as "file:////home/...",
    # which comes back as "//home/..."
    return re.sub(r'^//+', '/', path or '')
