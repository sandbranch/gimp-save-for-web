# -*- coding: utf-8 -*-
#
# Save for Web for GIMP 3: the work inside GIMP
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

"""The encoding pipeline of Save for Web.

A Session belongs to one user image. It never changes that image: it
makes a duplicate of its visible layers (the base: cropped, scaled,
converted to sRGB and 8 bit, with the metadata filtered), encodes the
base with GIMP's own export procedure into a temporary file, reads the
file's bytes and deletes it. The bytes are what Export writes, so the
size shown is the size on disk. For the preview the bytes are decoded
again with GIMP's loader.

The base, its flattened version (JPEG) and its indexed version (PNG-8,
GIF) are kept for the next call, so that changing only a quality
re-encodes without redoing the rest."""

import os

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, Gio   # noqa: E402

import sfw_model as model   # noqa: E402

RGBA8 = "R'G'B'A u8"


class ExportError(Exception):
    pass


def available_formats():
    """The format nicks whose export procedure this GIMP has."""
    pdb = Gimp.get_pdb()
    return [f for f, _ in model.FORMATS if pdb.lookup_procedure(model.EXPORTERS[f]) is not None]


class Encoded:
    """One encoded result: the file's bytes and what they are."""

    def __init__(self, data, fmt, width, height, channels):
        self.data = data
        self.size = len(data)
        self.format = fmt
        self.ext = model.EXTENSIONS[fmt]
        self.width = width
        self.height = height
        # the size of the image uncompressed (8-bit channels)
        self.raw_size = width * height * channels
        # set by Session.render
        self.quality = None     # the searched parameter's value, or None
        self.fits = None        # with a target size: under it or not
        self.tried = []         # with a target size: (value, size) tried
        self.note = ''


def _color(name):
    c = Gegl.Color.new('white')
    c.set_rgba(*{'white': (1, 1, 1, 1), 'black': (0, 0, 0, 1)}[name])
    return c


def _set(config, proc, name, value):
    """Sets an argument if this GIMP's procedure has it (older or newer
    exporters differ in their metadata switches)."""
    if proc.find_argument(name) is not None:
        config.set_property(name, value)


def image_pixels(image):
    """(width, height, bytes) of the image's composite as R'G'B'A u8:
    the image must have one layer covering it (the base images and the
    decoded files do)."""
    layers = image.get_layers()
    if len(layers) != 1:
        layer = image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
    else:
        layer = layers[0]
    w, h = image.get_width(), image.get_height()
    buf = layer.get_buffer()
    ox, oy = layer.get_offsets()[1:]
    data = buf.get(Gegl.Rectangle.new(-ox, -oy, w, h), 1.0, RGBA8, Gegl.AbyssPolicy.NONE)
    return w, h, bytes(data)


class Session:

    def __init__(self, image):
        self.image = image
        self._base = None           # (key, image)
        self._flat = None           # (key, image) the base flattened on the matte
        self._indexed = None        # (key, image)
        self._encoded = {}          # full key -> Encoded, for the last render only
        self.temp_files = 0         # temporary files made (for the tests)

    # ------------------------------------------------------------ cleanup

    def close(self):
        for slot in ('_base', '_flat', '_indexed'):
            item = getattr(self, slot)
            if item is not None:
                _delete(item[1])
                setattr(self, slot, None)
        self._encoded = {}

    # ------------------------------------------------------------ base

    def source_rect(self, s):
        """(x, y, width, height) of the part of the user image exported:
        the selection's bounds with crop-to-selection, else all."""
        w, h = self.image.get_width(), self.image.get_height()
        if s['crop-to-selection']:
            r = Gimp.Selection.bounds(self.image)
            # (success, non_empty, x1, y1, x2, y2)
            if r[1]:
                x1, y1, x2, y2 = r[2:6]
                if x2 > x1 and y2 > y1:
                    return x1, y1, x2 - x1, y2 - y1
        return 0, 0, w, h

    def _keep_indexed(self, s):
        return (self.image.get_base_type() == Gimp.ImageBaseType.INDEXED
                and s['format'] in ('png8', 'gif') and s['palette'] == 'keep')

    def base(self, s):
        k = model.key(s, model.BASE_KEYS) + (self._keep_indexed(s), self.source_rect(s))
        if self._base is not None and self._base[0] == k:
            return self._base[1]
        if self._base is not None:
            _delete(self._base[1])
            self._base = None
        for slot in ('_flat', '_indexed'):
            if getattr(self, slot) is not None:
                _delete(getattr(self, slot)[1])
                setattr(self, slot, None)
        img = self._make_base(s)
        self._base = (k, img)
        return img

    def _make_base(self, s):
        dup = self.image.duplicate()
        try:
            dup.undo_disable()
            Gimp.Selection.none(dup)
            # only what is visible is exported, as File > Export does
            for layer in dup.get_layers():
                if not layer.get_visible():
                    dup.remove_layer(layer)
            if not dup.get_layers():
                raise ExportError('The image has no visible layer.')
            x, y, w, h = self.source_rect(s)
            if (x, y, w, h) != (0, 0, dup.get_width(), dup.get_height()):
                dup.crop(w, h, x, y)
            layer = dup.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
            layer.resize_to_image_size()

            indexed = dup.get_base_type() == Gimp.ImageBaseType.INDEXED
            if indexed and not self._keep_indexed(s):
                dup.convert_rgb()
                indexed = False

            if not indexed and s['convert-srgb']:
                gray = dup.get_base_type() == Gimp.ImageBaseType.GRAY
                profile = dup.get_color_profile()
                if profile is not None:
                    target = (Gimp.ColorProfile.new_d65_gray_srgb_trc() if gray
                              else Gimp.ColorProfile.new_rgb_srgb())
                    if not profile.is_equal(target):
                        dup.convert_color_profile(target, Gimp.ColorRenderingIntent.PERCEPTUAL,
                                                  True)
                    # the built-in sRGB: no profile of its own, so exporters
                    # that always write one write the plain sRGB
                    if not s['keep-color-profile']:
                        dup.set_color_profile(None)

            ow, oh = model.output_size(w, h, s)
            if (ow, oh) != (w, h):
                Gimp.context_push()
                try:
                    Gimp.context_set_interpolation(
                        getattr(Gimp.InterpolationType, s['interpolation'].upper()))
                    dup.scale(ow, oh)
                finally:
                    Gimp.context_pop()

            if not indexed and dup.get_precision() != Gimp.Precision.U8_NON_LINEAR:
                dup.convert_precision(Gimp.Precision.U8_NON_LINEAR)

            layer = dup.get_layers()[0]
            # an alpha channel that is opaque everywhere is dropped: it
            # only makes the file bigger
            if not indexed and layer.has_alpha() and _all_opaque(layer):
                layer.flatten()

            self._filter_metadata(dup, s)
            return dup
        except Exception:
            _delete(dup)
            raise

    def _filter_metadata(self, dup, s):
        md = dup.get_metadata()
        if md is None:
            return
        if s['remove-gps']:
            md.delete_gps_info()
            for tag in list(md.get_xmp_tags() or []):
                if tag.startswith('Xmp.exif.GPS'):
                    md.clear_tag(tag)
        dup.set_metadata(md)

    # ------------------------------------------------------------ per format

    def flat(self, s):
        """The base without alpha, flattened on the matte colour (JPEG)."""
        base = self.base(s)
        layer = base.get_layers()[0]
        if not layer.has_alpha():
            return base
        k = self._base[0] + (s['matte'],)
        if self._flat is not None and self._flat[0] == k:
            return self._flat[1]
        if self._flat is not None:
            _delete(self._flat[1])
        img = base.duplicate()
        img.undo_disable()
        Gimp.context_push()
        try:
            if s['matte'] != 'background':
                Gimp.context_set_background(_color(s['matte']))
            img.flatten()
        finally:
            Gimp.context_pop()
        self._flat = (k, img)
        return img

    def indexed(self, s):
        """The base converted to indexed colours (PNG-8, GIF)."""
        base = self.base(s)
        if base.get_base_type() == Gimp.ImageBaseType.INDEXED:
            return base
        k = self._base[0] + model.key(s, model.INDEXED_KEYS)
        if self._indexed is not None and self._indexed[0] == k:
            return self._indexed[1]
        if self._indexed is not None:
            _delete(self._indexed[1])
            self._indexed = None
        img = base.duplicate()
        img.undo_disable()
        try:
            dither = {'none': Gimp.ConvertDitherType.NONE, 'fs': Gimp.ConvertDitherType.FS,
                      'fs-low-bleed': Gimp.ConvertDitherType.FS_LOWBLEED,
                      'positioned': Gimp.ConvertDitherType.FIXED}[s['dither']]
            palette = {'optimum': Gimp.ConvertPaletteType.GENERATE,
                       'web': Gimp.ConvertPaletteType.WEB,
                       'mono': Gimp.ConvertPaletteType.MONO,
                       # an RGB image asked to keep its palette has none:
                       # the optimum one
                       'keep': Gimp.ConvertPaletteType.GENERATE}[s['palette']]
            if not img.convert_indexed(dither, palette, s['colors'], s['alpha-dither'],
                                       s['remove-unused'], ''):
                raise ExportError('The conversion to indexed colours failed.')
        except Exception:
            _delete(img)
            raise
        self._indexed = (k, img)
        return img

    def image_for(self, s):
        f = s['format']
        if f == 'jpeg':
            return self.flat(s)
        if f in ('png8', 'gif'):
            return self.indexed(s)
        return self.base(s)

    # ------------------------------------------------------------ encoding

    def encode(self, s):
        """Encodes with the settings s (checked) and returns an Encoded."""
        k = model.key(s, model.BASE_KEYS) + (s['format'],) + model.key(
            s, model.FORMAT_KEYS[s['format']])
        if k in self._encoded:
            return self._encoded[k]
        img = self.image_for(s)
        data = self._export(img, s)
        layer = img.get_layers()[0]
        base_type = img.get_base_type()
        channels = (1 if base_type == Gimp.ImageBaseType.GRAY else 3) + (
            1 if layer.has_alpha() else 0)
        if base_type == Gimp.ImageBaseType.INDEXED:
            channels = 3 + (1 if layer.has_alpha() else 0)
        enc = Encoded(data, s['format'], img.get_width(), img.get_height(), channels)
        self._encoded[k] = enc
        return enc

    def _export(self, img, s):
        f = s['format']
        pdb = Gimp.get_pdb()
        proc = pdb.lookup_procedure(model.EXPORTERS[f])
        if proc is None:
            raise ExportError('This GIMP has no %s export (%s).' % (
                dict(model.FORMATS)[f], model.EXPORTERS[f]))
        gfile = Gimp.temp_file(model.EXTENSIONS[f])
        path = gfile.get_path()
        self.temp_files += 1
        c = proc.create_config()
        c.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
        c.set_property('image', img)
        c.set_property('file', gfile)
        _set(c, proc, 'include-exif', s['keep-exif'])
        _set(c, proc, 'include-xmp', s['keep-xmp'])
        _set(c, proc, 'include-iptc', s['keep-iptc'])
        _set(c, proc, 'include-color-profile', s['keep-color-profile'])
        _set(c, proc, 'include-comment', s['keep-comment'])
        _set(c, proc, 'include-thumbnail', False)
        layer = img.get_layers()[0]
        if f == 'jpeg':
            c.set_property('quality', s['jpeg-quality'] / 100.0)
            c.set_property('smoothing', s['jpeg-smoothing'])
            c.set_property('optimize', s['jpeg-optimize'])
            c.set_property('progressive', s['jpeg-progressive'])
            c.set_property('sub-sampling', model.JPEG_SUBSAMPLING[s['jpeg-subsampling']])
            c.set_property('baseline', True)
            c.set_property('restart', 0)
            _set(c, proc, 'cmyk', False)
        elif f in ('png', 'png8'):
            c.set_property('interlaced', s['png-interlace'])
            c.set_property('compression', s['png-compression'])
            for chunk in ('bkgd', 'offs', 'phys', 'time', 'save-transparent'):
                c.set_property(chunk, False)
            if f == 'png8':
                c.set_property('optimize-palette', s['remove-unused'])
                c.set_property('format', 'auto')
            else:
                gray = img.get_base_type() == Gimp.ImageBaseType.GRAY
                c.set_property('format', ('gray' if gray else 'rgb') +
                               ('a' if layer.has_alpha() else '') + '8')
        elif f == 'webp':
            c.set_property('preset', s['webp-preset'])
            c.set_property('lossless', s['webp-lossless'])
            c.set_property('quality', float(s['webp-quality']))
            c.set_property('alpha-quality', float(s['webp-alpha-quality']))
            c.set_property('use-sharp-yuv', s['webp-sharp-yuv'])
            c.set_property('animation', False)
        elif f == 'avif':
            c.set_property('quality', s['avif-quality'])
            c.set_property('lossless', s['avif-lossless'])
            c.set_property('save-bit-depth', 8)
            c.set_property('pixel-format', s['avif-pixel-format'])
            c.set_property('encoder-speed', s['avif-speed'])
        elif f == 'jxl':
            c.set_property('lossless', s['jxl-lossless'])
            c.set_property('compression', model.jxl_distance(s['jxl-quality']))
            c.set_property('save-bit-depth', 8)
            c.set_property('speed', s['jxl-effort'])
            _set(c, proc, 'cmyk', False)
        elif f == 'gif':
            c.set_property('interlace', s['gif-interlace'])
            c.set_property('as-animation', False)
        try:
            result = proc.run(c)
            status = result.index(0)
            if status != Gimp.PDBStatusType.SUCCESS:
                err = result.index(1) if result.length() > 1 else None
                raise ExportError('%s failed: %s' % (model.EXPORTERS[f], getattr(
                    err, 'message', None) or status.value_nick))
            with open(path, 'rb') as fh:
                return fh.read()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def render(self, s):
        """Encodes with the settings s (not yet checked), searching the
        quality for the target size if asked. Returns an Encoded."""
        s = model.check(s)
        self._encoded = {}
        if not s['target-size']:
            return self.encode(s)
        param = model.search_parameter(s)
        if param is None:
            enc = self.encode(s)
            enc.note = ('The target size needs a lossy format (JPEG, WebP, AVIF, JPEG XL) or '
                        'an optimum palette (PNG-8, GIF): exported as set.')
            enc.fits = enc.size <= s['target-kb'] * 1000
            return enc
        name, lo, hi = param
        target = int(s['target-kb'] * 1000)

        def size_of(v):
            t = dict(s)
            t[name] = v
            return self.encode(t).size

        v, _, fits, tried = model.search_target(lo, hi, size_of, target)
        t = dict(s)
        t[name] = v
        enc = self.encode(t)
        enc.quality = v
        enc.fits = fits
        enc.tried = tried
        if not fits:
            enc.note = ('Even at the lowest %s (%d) the file is %s, over the target: make '
                        'the image smaller.' % ('number of colours' if name == 'colors'
                                                else 'quality', v,
                                                model.format_size(enc.size)))
        return enc

    # ------------------------------------------------------------ decoding

    def decode(self, enc):
        """(width, height, R'G'B'A u8 bytes) of the encoded file decoded by
        GIMP's own loader: what a browser would show."""
        gfile = Gimp.temp_file(enc.ext)
        path = gfile.get_path()
        self.temp_files += 1
        try:
            with open(path, 'wb') as fh:
                fh.write(enc.data)
            img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)
            if img is None:
                raise ExportError('GIMP could not load its own %s back.' % enc.ext)
            try:
                return image_pixels(img)
            finally:
                _delete(img)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def reference(self, s):
        """(width, height, bytes) of what was encoded, before encoding: the
        base (flattened on the matte for JPEG). The "original" of the
        comparison."""
        s = model.check(s)
        img = self.flat(s) if s['format'] == 'jpeg' else self.base(s)
        return image_pixels(img)


def _all_opaque(layer):
    r = layer.histogram(Gimp.HistogramChannel.ALPHA, 1.0, 1.0)
    # (success, mean, std_dev, median, pixels, count, percentile)
    return r[0] and r[5] == r[4]


def _delete(img):
    try:
        if img is not None and img.is_valid():
            img.delete()
    except Exception:
        pass


def mse(a, b):
    """The mean squared error between two R'G'B'A u8 pixel strings of the
    same size, over R, G and B, for pixels that are not transparent in
    both. Plain Python on a sample of at most about 250 000 pixels."""
    n = len(a) // 4
    step = max(1, n // 250000)
    total = 0
    count = 0
    for i in range(0, n, step):
        j = i * 4
        if a[j + 3] == 0 and b[j + 3] == 0:
            continue
        d0 = a[j] - b[j]
        d1 = a[j + 1] - b[j + 1]
        d2 = a[j + 2] - b[j + 2]
        total += d0 * d0 + d1 * d1 + d2 * d2
        count += 3
    return total / count if count else 0.0


def write_file(path, data):
    """Writes the bytes to path through GIO (also for paths GIO maps),
    replacing the file only when all was written."""
    f = Gio.File.new_for_path(path)
    f.replace_contents(data, None, False, Gio.FileCreateFlags.REPLACE_DESTINATION, None)
