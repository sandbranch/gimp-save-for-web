# -*- coding: utf-8 -*-
#
# Save for Web for GIMP 3: the dialog
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

"""The Export for Web dialog: the preview of the encoded and decoded
result (alone, side by side with the original, or split with a divider
to drag), its size, download time and error, and the settings. Every
change re-encodes after a short pause; Export writes the very bytes
shown."""

import os
import time

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gimp, GimpUi, Gtk, Gdk, GdkPixbuf, GLib, Gio   # noqa: E402
import cairo   # noqa: E402

import sfw_model as model     # noqa: E402
import sfw_engine as engine   # noqa: E402

PLUG_IN_BINARY = 'save-for-web'
UPDATE_DELAY_MS = 250

# which formats each metadata switch works in (as tested: file-webp-export
# takes include-iptc but writes none; GIF has no metadata; AVIF always
# writes the colour profile)
META_FORMATS = {
    'keep-exif': {'jpeg', 'png', 'png8', 'webp', 'avif', 'jxl'},
    'keep-xmp': {'jpeg', 'png', 'png8', 'webp', 'avif', 'jxl'},
    'keep-iptc': {'jpeg', 'png', 'png8'},
    'keep-color-profile': {'jpeg', 'png', 'png8', 'webp'},
    'keep-comment': {'jpeg', 'png', 'png8'},
}


def pixbuf_of(w, h, data):
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(data), GdkPixbuf.Colorspace.RGB,
                                           True, 8, w, h, w * 4)


# ------------------------------------------------------------ the preview

class View:
    """Zoom and position shared by the preview panes: the image point at
    the centre of each pane, and the zoom (None: fit)."""

    def __init__(self):
        self.zoom = 1.0
        self.cx = None
        self.cy = None
        self.panes = []

    def scale(self, pw, ph, iw, ih):
        if self.zoom is None:
            return min(1.0, pw / max(iw, 1), ph / max(ih, 1))
        return self.zoom

    def clamp(self, iw, ih):
        if self.cx is None:
            self.cx, self.cy = iw / 2.0, ih / 2.0
        self.cx = min(max(self.cx, 0.0), float(iw))
        self.cy = min(max(self.cy, 0.0), float(ih))

    def redraw(self):
        for p in self.panes:
            p.queue_draw()


def _checker():
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, 16, 16)
    cr = cairo.Context(s)
    cr.set_source_rgb(0.8, 0.8, 0.8)
    cr.paint()
    cr.set_source_rgb(0.6, 0.6, 0.6)
    cr.rectangle(0, 0, 8, 8)
    cr.rectangle(8, 8, 8, 8)
    cr.fill()
    p = cairo.SurfacePattern(s)
    p.set_extend(cairo.EXTEND_REPEAT)
    return p


class Pane(Gtk.DrawingArea):
    """Shows one pixbuf (or, split, the original left of a divider and the
    result right of it) at the shared view; drag to pan, the wheel to
    scroll, Ctrl+wheel to zoom."""

    def __init__(self, view, caption=''):
        super().__init__()
        self.view = view
        view.panes.append(self)
        self.pixbuf = None
        self.left = None            # split: the pixbuf left of the divider
        self.split = 0.5            # the divider, as a fraction of the width
        self.caption = caption
        self.message = ''
        self.drag = None
        self.checker = _checker()
        self.set_size_request(200, 160)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK |
                        Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect('draw', self.on_draw)
        self.connect('button-press-event', self.on_press)
        self.connect('button-release-event', self.on_release)
        self.connect('motion-notify-event', self.on_motion)
        self.connect('scroll-event', self.on_scroll)

    def image_size(self):
        pb = self.pixbuf or self.left
        return (pb.get_width(), pb.get_height()) if pb is not None else (0, 0)

    def geometry(self):
        pw, ph = self.get_allocated_width(), self.get_allocated_height()
        iw, ih = self.image_size()
        self.view.clamp(iw, ih)
        z = self.view.scale(pw, ph, iw, ih)
        if self.view.zoom is None:
            ox, oy = (pw - iw * z) / 2.0, (ph - ih * z) / 2.0
        else:
            ox, oy = pw / 2.0 - self.view.cx * z, ph / 2.0 - self.view.cy * z
        return pw, ph, iw, ih, z, ox, oy

    def _paint(self, cr, pb, z, ox, oy, iw, ih):
        cr.save()
        cr.rectangle(ox, oy, iw * z, ih * z)
        cr.clip()
        cr.set_source(self.checker)
        cr.paint()
        cr.translate(ox, oy)
        cr.scale(z, z)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST if z >= 1 else cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()

    def on_draw(self, widget, cr):
        pw, ph, iw, ih, z, ox, oy = self.geometry()
        cr.set_source_rgb(0.25, 0.25, 0.25)
        cr.paint()
        if self.left is not None and self.pixbuf is not None:
            sx = pw * self.split
            cr.save()
            cr.rectangle(0, 0, sx, ph)
            cr.clip()
            self._paint(cr, self.left, z, ox, oy, iw, ih)
            cr.restore()
            cr.save()
            cr.rectangle(sx, 0, pw - sx, ph)
            cr.clip()
            self._paint(cr, self.pixbuf, z, ox, oy, iw, ih)
            cr.restore()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(2)
            cr.move_to(sx, 0)
            cr.line_to(sx, ph)
            cr.stroke()
            cr.arc(sx, ph / 2.0, 9, 0, 6.2832)
            cr.fill()
            self._label(cr, 'Original', 8, 8)
            self._label(cr, self.caption, sx + 8, 8)
        elif self.pixbuf is not None:
            self._paint(cr, self.pixbuf, z, ox, oy, iw, ih)
            self._label(cr, self.caption, 8, 8)
        if self.message:
            self._label(cr, self.message, 8, ph - 30)
        return False

    def _label(self, cr, text, x, y):
        if not text:
            return
        cr.save()
        cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12)
        ext = cr.text_extents(text)
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.rectangle(x - 4, y - 2, ext.x_advance + 8, 20)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(x, y + 13)
        cr.show_text(text)
        cr.restore()

    def near_divider(self, x):
        return self.left is not None and abs(x - self.get_allocated_width() * self.split) < 16

    def on_press(self, widget, ev):
        if ev.button != 1:
            return False
        if self.near_divider(ev.x):
            self.drag = ('split',)
        else:
            self.drag = ('pan', ev.x, ev.y, self.view.cx, self.view.cy)
        return True

    def on_release(self, widget, ev):
        self.drag = None
        return True

    def on_motion(self, widget, ev):
        if self.drag is None:
            return False
        if self.drag[0] == 'split':
            self.split = min(max(ev.x / max(self.get_allocated_width(), 1), 0.0), 1.0)
            self.queue_draw()
            return True
        _, x0, y0, cx, cy = self.drag
        pw, ph, iw, ih, z, ox, oy = self.geometry()
        if self.view.zoom is None:
            return True
        self.view.cx = cx - (ev.x - x0) / z
        self.view.cy = cy - (ev.y - y0) / z
        self.view.clamp(iw, ih)
        self.view.redraw()
        return True

    def on_scroll(self, widget, ev):
        ok, dx, dy = ev.get_scroll_deltas()
        if not ok:
            dx, dy = {Gdk.ScrollDirection.UP: (0, -1), Gdk.ScrollDirection.DOWN: (0, 1),
                      Gdk.ScrollDirection.LEFT: (-1, 0),
                      Gdk.ScrollDirection.RIGHT: (1, 0)}.get(ev.direction, (0, 0))
        if ev.state & Gdk.ModifierType.CONTROL_MASK and self.on_zoom_step:
            self.on_zoom_step(-1 if dy > 0 else 1)
            return True
        pw, ph, iw, ih, z, ox, oy = self.geometry()
        if self.view.zoom is None:
            return True
        self.view.cx += dx * 40 / z
        self.view.cy += dy * 40 / z
        self.view.clamp(iw, ih)
        self.view.redraw()
        return True

    on_zoom_step = None


# ------------------------------------------------------------ the dialog

class WebDialog:

    def __init__(self, procedure, config, image, available):
        self.procedure = procedure
        self.config = config
        self.image = image
        self.available = available
        s = {k: config.get_property(k) for k in model.SETTINGS}
        s = model.check(s)
        if s['format'] not in available:
            s['format'] = 'jpeg'
        self.s = s
        self.session = engine.Session(image)
        self.enc = None                 # the last encoded result
        self.enc_settings = None        # the settings it was made with
        self.pending = None             # the timeout of the next update
        self.busy = False               # an encode is running
        self.widgets = {}
        self.blocked = False
        self.src_w, self.src_h = self.session.source_rect(s)[2:]
        self.has_selection = not Gimp.Selection.is_empty(image)
        self.build()
        self.load_view_state()

    # ------------------------------------------------------------ widgets

    def label(self, text, widget=None):
        lab = Gtk.Label.new_with_mnemonic(text)
        lab.set_xalign(0.0)
        if widget is not None:
            lab.set_mnemonic_widget(widget)
        return lab

    def tooltip(self, widget, key):
        if key in model.LABELS:
            widget.set_tooltip_text(model.LABELS[key][1])

    def check(self, key, text):
        w = Gtk.CheckButton.new_with_mnemonic(text)
        w.set_active(bool(self.s[key]))
        w.connect('toggled', lambda b: self.set(key, b.get_active()))
        self.widgets[key] = w
        self.tooltip(w, key)
        return w

    def combo(self, key, choices):
        w = Gtk.ComboBoxText()
        for nick, text in choices:
            w.append(nick, text)
        w.set_active_id(self.s[key])
        w.connect('changed', lambda c: c.get_active_id() and self.set(key, c.get_active_id()))
        self.widgets[key] = w
        self.tooltip(w, key)
        return w

    def spin(self, key, digits=0, step=1.0, lo=None):
        _, kind, (mn, mx) = model.SETTINGS[key]
        adj = Gtk.Adjustment.new(self.s[key], mn if lo is None else lo, mx, step, step * 10, 0)
        w = Gtk.SpinButton.new(adj, step, digits)
        w.set_numeric(True)
        conv = int if kind == 'int' else float
        w.connect('value-changed', lambda b: self.set(key, conv(b.get_value())))
        self.widgets[key] = w
        self.tooltip(w, key)
        return w

    def slider(self, key, text):
        """A GIMP spin scale (a slider with the value in it)."""
        _, kind, (mn, mx) = model.SETTINGS[key]
        adj = Gtk.Adjustment.new(self.s[key], mn, mx, 1, 10, 0)
        w = GimpUi.SpinScale.new(adj, text.replace('_', ''), 0)
        w.set_hexpand(True)
        w.connect('value-changed', lambda b: self.set(key, int(round(b.get_value()))))
        self.widgets[key] = w
        self.tooltip(w, key)
        return w

    def grid(self):
        g = Gtk.Grid()
        g.set_row_spacing(4)
        g.set_column_spacing(8)
        return g

    def frame(self, title, child):
        f = GimpUi.Frame.new(title)
        f.add(child)
        return f

    def build(self):
        GimpUi.init(PLUG_IN_BINARY)
        dlg = GimpUi.Dialog(title='Export for Web', role=PLUG_IN_BINARY)
        dlg.add_button('_Cancel', Gtk.ResponseType.CANCEL)
        self.export_button = dlg.add_button('_Export', Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        self.dialog = dlg

        paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        paned.set_border_width(8)
        dlg.get_content_area().pack_start(paned, True, True, 0)

        # --- left: the preview
        left = Gtk.Box.new(Gtk.Orientation.VERTICAL, 6)
        bar = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 6)
        self.view_combo = Gtk.ComboBoxText()
        for nick, text in model.VIEWS:
            self.view_combo.append(nick, text)
        self.zoom_combo = Gtk.ComboBoxText()
        for nick, text in model.ZOOMS:
            self.zoom_combo.append(nick, text)
        self.conn_combo = Gtk.ComboBoxText()
        for i, (text, bps, lat) in enumerate(model.CONNECTIONS):
            self.conn_combo.append(str(i), text)
        bar.pack_start(self.label('_View:', self.view_combo), False, False, 0)
        bar.pack_start(self.view_combo, False, False, 0)
        bar.pack_start(self.label('_Zoom:', self.zoom_combo), False, False, 0)
        bar.pack_start(self.zoom_combo, False, False, 0)
        bar.pack_start(self.label('Co_nnection:', self.conn_combo), False, False, 0)
        bar.pack_start(self.conn_combo, False, False, 0)
        left.pack_start(bar, False, False, 0)

        self.view = View()
        self.panes_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 4)
        self.pane_orig = Pane(self.view, 'Original')
        self.pane_result = Pane(self.view)
        for p in (self.pane_orig, self.pane_result):
            p.on_zoom_step = self.zoom_step
            self.panes_box.pack_start(p, True, True, 0)
        left.pack_start(self.panes_box, True, True, 0)

        info = Gtk.Grid()
        info.set_column_spacing(16)
        self.size_label = Gtk.Label()
        self.size_label.set_xalign(0.0)
        self.size_label.set_selectable(True)
        self.detail_label = Gtk.Label()
        self.detail_label.set_xalign(0.0)
        self.time_label = Gtk.Label()
        self.time_label.set_xalign(0.0)
        self.status_label = Gtk.Label()
        self.status_label.set_xalign(1.0)
        self.note_label = Gtk.Label()
        self.note_label.set_xalign(0.0)
        self.note_label.set_line_wrap(True)
        info.attach(self.size_label, 0, 0, 1, 1)
        info.attach(self.status_label, 1, 0, 1, 1)
        self.status_label.set_hexpand(True)
        info.attach(self.detail_label, 0, 1, 2, 1)
        info.attach(self.time_label, 0, 2, 2, 1)
        info.attach(self.note_label, 0, 3, 2, 1)
        left.pack_start(info, False, False, 0)
        paned.pack1(left, True, False)

        # --- right: the settings
        right = Gtk.Box.new(Gtk.Orientation.VERTICAL, 10)
        right.set_border_width(4)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(right)
        scroll.set_size_request(340, -1)
        paned.pack2(scroll, False, False)

        g = self.grid()
        fmt = self.combo('format', [(n, t) for n, t in model.FORMATS if n in self.available])
        g.attach(self.label('_Format:', fmt), 0, 0, 1, 1)
        g.attach(fmt, 1, 0, 1, 1)
        fmt.set_hexpand(True)
        self.format_boxes = {}
        row = 1
        for part, build in (('jpeg', self.build_jpeg), ('png', self.build_png),
                            ('indexed', self.build_indexed), ('gif', self.build_gif),
                            ('webp', self.build_webp), ('avif', self.build_avif),
                            ('jxl', self.build_jxl)):
            box = build()
            self.format_boxes[part] = box
            g.attach(box, 0, row, 2, 1)
            row += 1
        right.pack_start(self.frame('Format', g), False, False, 0)

        g = self.grid()
        t = self.check('target-size', 'Fit in a _target size of')
        g.attach(t, 0, 0, 1, 1)
        kb = self.spin('target-kb', digits=1, step=1.0)
        g.attach(kb, 1, 0, 1, 1)
        g.attach(Gtk.Label.new('kB'), 2, 0, 1, 1)
        self.target_label = Gtk.Label()
        self.target_label.set_xalign(0.0)
        self.target_label.set_line_wrap(True)
        self.target_label.set_max_width_chars(38)
        g.attach(self.target_label, 0, 1, 3, 1)
        right.pack_start(self.frame('Target size', g), False, False, 0)

        right.pack_start(self.frame('Size', self.build_size()), False, False, 0)
        right.pack_start(self.frame('Colour and metadata', self.build_meta()), False, False, 0)

        g = self.grid()
        self.path_entry = Gtk.Entry()
        self.path_entry.set_hexpand(True)
        self.path_entry.set_text(self.default_path())
        browse = Gtk.Button.new_with_mnemonic('_Browse...')
        browse.connect('clicked', self.on_browse)
        g.attach(self.label('Export _to:', self.path_entry), 0, 0, 2, 1)
        g.attach(self.path_entry, 0, 1, 1, 1)
        g.attach(browse, 1, 1, 1, 1)
        right.pack_start(self.frame('File', g), False, False, 0)

        self.view_combo.connect('changed', lambda c: self.set_view(c.get_active_id()))
        self.zoom_combo.connect('changed', lambda c: self.set_zoom(c.get_active_id()))
        self.conn_combo.connect('changed', lambda c: self.show_times())
        dlg.connect('response', self.on_response)
        dlg.show_all()

    def build_jpeg(self):
        g = self.grid()
        g.attach(self.slider('jpeg-quality', '_Quality'), 0, 0, 2, 1)
        g.attach(self.label('_Subsampling:', None), 0, 1, 1, 1)
        sub = self.combo('jpeg-subsampling', model.SUBSAMPLING)
        g.get_child_at(0, 1).set_mnemonic_widget(sub)
        g.attach(sub, 1, 1, 1, 1)
        g.attach(self.check('jpeg-progressive', '_Progressive'), 0, 2, 1, 1)
        g.attach(self.check('jpeg-optimize', '_Optimize'), 1, 2, 1, 1)
        sm = self.spin('jpeg-smoothing', digits=2, step=0.05)
        g.attach(self.label('S_moothing:', sm), 0, 3, 1, 1)
        g.attach(sm, 1, 3, 1, 1)
        matte = self.combo('matte', model.MATTES)
        self.matte_label = self.label('M_atte:', matte)
        g.attach(self.matte_label, 0, 4, 1, 1)
        g.attach(matte, 1, 4, 1, 1)
        return g

    def build_png(self):
        g = self.grid()
        c = self.spin('png-compression')
        g.attach(self.label('Co_mpression (0-9):', c), 0, 0, 1, 1)
        g.attach(c, 1, 0, 1, 1)
        g.attach(self.check('png-interlace', '_Interlace (Adam7)'), 0, 1, 2, 1)
        return g

    def build_indexed(self):
        g = self.grid()
        pal = self.combo('palette', [p for p in model.PALETTES if p[0] != 'keep' or
                                     self.image.get_base_type() == Gimp.ImageBaseType.INDEXED])
        g.attach(self.label('_Palette:', pal), 0, 0, 1, 1)
        g.attach(pal, 1, 0, 1, 1)
        g.attach(self.slider('colors', '_Colours'), 0, 1, 2, 1)
        d = self.combo('dither', model.DITHERS)
        g.attach(self.label('_Dither:', d), 0, 2, 1, 1)
        g.attach(d, 1, 2, 1, 1)
        g.attach(self.check('alpha-dither', 'Dither _transparency'), 0, 3, 2, 1)
        g.attach(self.check('remove-unused', '_Remove unused colours'), 0, 4, 2, 1)
        return g

    def build_gif(self):
        g = self.grid()
        g.attach(self.check('gif-interlace', '_Interlace'), 0, 0, 1, 1)
        return g

    def build_webp(self):
        g = self.grid()
        g.attach(self.check('webp-lossless', '_Lossless'), 0, 0, 2, 1)
        g.attach(self.slider('webp-quality', '_Quality'), 0, 1, 2, 1)
        g.attach(self.slider('webp-alpha-quality', '_Alpha quality'), 0, 2, 2, 1)
        p = self.combo('webp-preset', model.WEBP_PRESETS)
        g.attach(self.label('P_reset:', p), 0, 3, 1, 1)
        g.attach(p, 1, 3, 1, 1)
        g.attach(self.check('webp-sharp-yuv', '_Sharp YUV'), 0, 4, 2, 1)
        return g

    def build_avif(self):
        g = self.grid()
        g.attach(self.check('avif-lossless', '_Lossless'), 0, 0, 2, 1)
        g.attach(self.slider('avif-quality', '_Quality'), 0, 1, 2, 1)
        p = self.combo('avif-pixel-format', model.AVIF_PIXEL_FORMATS)
        g.attach(self.label('_Pixels:', p), 0, 2, 1, 1)
        g.attach(p, 1, 2, 1, 1)
        sp = self.combo('avif-speed', model.AVIF_SPEEDS)
        g.attach(self.label('_Speed:', sp), 0, 3, 1, 1)
        g.attach(sp, 1, 3, 1, 1)
        return g

    def build_jxl(self):
        g = self.grid()
        g.attach(self.check('jxl-lossless', '_Lossless'), 0, 0, 2, 1)
        g.attach(self.slider('jxl-quality', '_Quality'), 0, 1, 2, 1)
        e = self.combo('jxl-effort', model.JXL_EFFORTS)
        g.attach(self.label('_Effort:', e), 0, 2, 1, 1)
        g.attach(e, 1, 2, 1, 1)
        self.jxl_label = Gtk.Label()
        self.jxl_label.set_xalign(0.0)
        g.attach(self.jxl_label, 0, 3, 2, 1)
        return g

    def build_size(self):
        g = self.grid()
        crop = self.check('crop-to-selection', '_Crop to the selection')
        crop.set_sensitive(self.has_selection)
        if not self.has_selection:
            crop.set_tooltip_text('The image has no selection.')
        g.attach(crop, 0, 0, 3, 1)
        mode = self.combo('scale-mode', model.SCALE_MODES)
        g.attach(self.label('_Resize:', mode), 0, 1, 1, 1)
        g.attach(mode, 1, 1, 2, 1)
        w = self.spin('width', lo=1)
        h = self.spin('height', lo=1)
        # (the entries show the size that will be exported: see
        # size_changed for the aspect ratio)
        g.attach(self.label('_Width:', w), 0, 2, 1, 1)
        g.attach(w, 1, 2, 1, 1)
        g.attach(Gtk.Label.new('px'), 2, 2, 1, 1)
        g.attach(self.label('_Height:', h), 0, 3, 1, 1)
        g.attach(h, 1, 3, 1, 1)
        g.attach(Gtk.Label.new('px'), 2, 3, 1, 1)
        g.attach(self.check('keep-aspect', '_Keep aspect ratio'), 0, 4, 3, 1)
        pc = self.spin('percent', digits=1, step=1.0)
        g.attach(self.label('P_ercent:', pc), 0, 5, 1, 1)
        g.attach(pc, 1, 5, 1, 1)
        g.attach(Gtk.Label.new('%'), 2, 5, 1, 1)
        ip = self.combo('interpolation', model.INTERPOLATIONS)
        g.attach(self.label('_Interpolation:', ip), 0, 6, 1, 1)
        g.attach(ip, 1, 6, 2, 1)
        self.size_info = Gtk.Label()
        self.size_info.set_xalign(0.0)
        self.size_info.set_line_wrap(True)
        self.size_info.set_max_width_chars(38)
        g.attach(self.size_info, 0, 7, 3, 1)
        return g

    def build_meta(self):
        g = self.grid()
        g.attach(self.check('convert-srgb', 'Con_vert to sRGB'), 0, 0, 1, 1)
        g.attach(self.check('keep-color-profile', 'Keep colour _profile (ICC)'), 0, 1, 1, 1)
        g.attach(self.check('keep-exif', 'Keep _Exif'), 0, 2, 1, 1)
        g.attach(self.check('keep-xmp', 'Keep _XMP'), 0, 3, 1, 1)
        g.attach(self.check('keep-iptc', 'Keep IPT_C'), 0, 4, 1, 1)
        g.attach(self.check('keep-comment', 'Keep co_mment'), 0, 5, 1, 1)
        g.attach(self.check('remove-gps', 'Remove _GPS location from Exif and XMP'), 0, 6, 1, 1)
        self.meta_info = Gtk.Label()
        self.meta_info.set_xalign(0.0)
        self.meta_info.set_line_wrap(True)
        self.meta_info.set_max_width_chars(40)
        self.meta_info.set_text(self.source_metadata_text())
        g.attach(self.meta_info, 0, 7, 1, 1)
        return g

    def source_metadata_text(self):
        parts = []
        md = self.image.get_metadata()
        if md is not None:
            exif = list(md.get_exif_tags() or [])
            xmp = list(md.get_xmp_tags() or [])
            if exif:
                parts.append('Exif')
            if xmp:
                parts.append('XMP')
            if md.get_iptc_tags():
                parts.append('IPTC')
            if any('GPS' in t for t in exif + xmp):
                parts.append('GPS location')
        p = self.image.get_color_profile()
        if p is not None:
            parts.append('the profile "%s"' % p.get_label())
        if self.image.get_parasite('gimp-comment') is not None:
            parts.append('a comment')
        return 'The image has: %s.' % (', '.join(parts) if parts else 'no metadata, sRGB')

    # ------------------------------------------------------------ state

    def load_view_state(self):
        c = self.config
        if not self.view_combo.set_active_id(c.get_property('view') or 'result'):
            self.view_combo.set_active_id('result')
        if not self.zoom_combo.set_active_id(c.get_property('zoom') or '100'):
            self.zoom_combo.set_active_id('100')
        self.conn_combo.set_active_id(str(c.get_property('connection')))
        w, h = c.get_property('dialog-width'), c.get_property('dialog-height')
        if w > 200 and h > 200:
            self.dialog.resize(w, h)
        else:
            self.dialog.resize(1180, 780)
        self.set_view(self.view_combo.get_active_id())
        self.set_zoom(self.zoom_combo.get_active_id())
        self.update_sensitivity()
        self.update_size_entries()

    def save_state(self, path):
        c = self.config
        for k in model.SETTINGS:
            c.set_property(k, self.s[k])
        c.set_property('file', Gio.File.new_for_path(path))
        c.set_property('view', self.view_combo.get_active_id() or 'result')
        c.set_property('zoom', self.zoom_combo.get_active_id() or '100')
        c.set_property('connection', int(self.conn_combo.get_active_id() or 1))
        w, h = self.dialog.get_size()
        c.set_property('dialog-width', w)
        c.set_property('dialog-height', h)

    def default_path(self):
        last = model.config_path(self.config)
        folder = None
        if last and os.path.isdir(os.path.dirname(last)):
            folder = os.path.dirname(last)
        name = 'image'
        for f in (self.image.get_file(), self.image.get_imported_file(),
                  self.image.get_exported_file()):
            p = f.get_path() if f is not None else None
            if p:
                name = os.path.splitext(os.path.basename(p))[0]
                if folder is None:
                    folder = os.path.dirname(p)
                break
        if folder is None:
            folder = (GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or
                      GLib.get_home_dir())
        return os.path.join(folder, name + '.' + model.EXTENSIONS[self.s['format']])

    # ------------------------------------------------------------ changes

    def set(self, key, value):
        if self.blocked:
            return
        self.s[key] = value
        if key == 'format':
            self.fix_extension()
        if key in ('width', 'height', 'keep-aspect', 'scale-mode', 'percent',
                   'crop-to-selection'):
            self.size_changed(key)
        self.update_sensitivity()
        self.schedule()

    def size_changed(self, key):
        if key == 'crop-to-selection':
            self.src_w, self.src_h = self.session.source_rect(self.s)[2:]
        if self.s['keep-aspect']:
            if key == 'height':
                self.s['width'] = 0
            elif key in ('width', 'keep-aspect'):
                self.s['height'] = 0
        self.update_size_entries()

    def update_size_entries(self):
        ow, oh = model.output_size(self.src_w, self.src_h, self.s)
        self.blocked = True
        try:
            if self.s['scale-mode'] != 'size':
                self.widgets['width'].set_value(ow)
                self.widgets['height'].set_value(oh)
            elif self.s['keep-aspect']:
                if self.s['width'] > 0:
                    self.widgets['height'].set_value(oh)
                else:
                    self.widgets['width'].set_value(ow)
                    if self.s['height'] == 0:
                        self.widgets['height'].set_value(oh)
        finally:
            self.blocked = False
        self.size_info.set_text('Exported at %d x %d pixels (from %d x %d%s).' % (
            ow, oh, self.src_w, self.src_h, ', the selection' if self.s['crop-to-selection']
            and self.has_selection else ''))

    def fix_extension(self):
        path = self.path_entry.get_text()
        base, ext = os.path.splitext(path)
        if ext.lstrip('.').lower() in ('jpg', 'jpeg', 'png', 'webp', 'avif', 'jxl', 'gif', ''):
            self.path_entry.set_text(base + '.' + model.EXTENSIONS[self.s['format']])

    def update_sensitivity(self):
        f = self.s['format']
        shown = {'jpeg': f == 'jpeg', 'png': f in ('png', 'png8'),
                 'indexed': f in ('png8', 'gif'), 'gif': f == 'gif', 'webp': f == 'webp',
                 'avif': f == 'avif', 'jxl': f == 'jxl'}
        for part, box in self.format_boxes.items():
            box.set_visible(shown[part])
        w = self.widgets
        w['webp-quality'].set_sensitive(not self.s['webp-lossless'])
        w['avif-quality'].set_sensitive(not self.s['avif-lossless'])
        w['jxl-quality'].set_sensitive(not self.s['jxl-lossless'])
        w['jxl-effort'].set_sensitive(True)
        w['colors'].set_sensitive(self.s['palette'] in ('optimum', 'keep') and
                                  not (self.s['palette'] == 'keep' and self.image.get_base_type()
                                       == Gimp.ImageBaseType.INDEXED))
        self.jxl_label.set_text('Distance %.2f (1.0 is visually lossless)' %
                                model.jxl_distance(self.s['jxl-quality'])
                                if not self.s['jxl-lossless'] else 'Lossless')
        mode = self.s['scale-mode']
        for k in ('width', 'height', 'keep-aspect'):
            w[k].set_sensitive(mode == 'size')
        w['percent'].set_sensitive(mode == 'percent')
        w['interpolation'].set_sensitive(mode != 'none')
        search = model.search_parameter(self.s)
        w['target-kb'].set_sensitive(self.s['target-size'])
        if self.s['target-size'] and search is None:
            self.target_label.set_text('Nothing to search in %s with these settings: choose a '
                                       'lossy format or an optimum palette.' %
                                       dict(model.FORMATS)[f])
        elif not self.s['target-size']:
            self.target_label.set_text('')
        for k, fmts in META_FORMATS.items():
            w[k].set_sensitive(f in fmts)
            if f not in fmts:
                w[k].set_tooltip_text('%s cannot keep this.' % dict(model.FORMATS)[f])
            else:
                self.tooltip(w[k], k)
        w['remove-gps'].set_sensitive((self.s['keep-exif'] or self.s['keep-xmp']) and
                                      f in META_FORMATS['keep-exif'])
        w['keep-color-profile'].set_sensitive(f in META_FORMATS['keep-color-profile'])
        rgb = self.image.get_base_type() != Gimp.ImageBaseType.INDEXED
        w['convert-srgb'].set_sensitive(rgb)
        has_alpha = any(layer.has_alpha() for layer in self.image.get_layers())
        w['matte'].set_sensitive(has_alpha)
        self.matte_label.set_sensitive(has_alpha)

    def set_view(self, mode):
        mode = mode or 'result'
        self.mode = mode
        self.pane_orig.set_visible(mode in ('side', 'original'))
        self.pane_result.set_visible(mode in ('result', 'side', 'split'))
        self.show_pixbufs()

    def set_zoom(self, nick):
        self.view.zoom = None if nick in (None, 'fit') else int(nick) / 100.0
        self.view.redraw()

    def zoom_step(self, direction):
        nicks = [n for n, _ in model.ZOOMS]
        cur = self.zoom_combo.get_active_id() or '100'
        i = nicks.index(cur) if cur in nicks else 3
        i = min(max(i + direction, 1 if cur != 'fit' else 0), len(nicks) - 1)
        self.zoom_combo.set_active_id(nicks[i])

    # ------------------------------------------------------------ updates

    def schedule(self):
        if self.pending is not None:
            GLib.source_remove(self.pending)
        self.status_label.set_text('...')
        self.pending = GLib.timeout_add(UPDATE_DELAY_MS, self.on_timeout)

    def on_timeout(self):
        self.pending = None
        if self.busy:
            # an encode is running (its progress lets events through):
            # try again after it
            self.schedule()
            return False
        self.update()
        return False

    def flush(self):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

    def progress(self, value, size):
        self.status_label.set_text('Trying %d: %s...' % (value, model.format_size(size).split(
            ' (')[0]))
        self.flush()

    def update(self):
        s = dict(self.s)
        self.status_label.set_text('Encoding...')
        self.export_button.set_sensitive(False)
        self.flush()
        t0 = time.time()
        self.busy = True
        try:
            enc = self.session.render(s, self.progress)
            dw, dh, dec = self.session.decode(enc)
            rw, rh, ref = self.session.reference(s)
        except Exception as e:
            self.enc = None
            self.enc_settings = None
            self.size_label.set_markup('<b>Not exported</b>')
            self.detail_label.set_text('')
            self.time_label.set_text('')
            self.note_label.set_text(str(e))
            self.status_label.set_text('')
            self.pane_result.pixbuf = None
            self.view.redraw()
            return
        finally:
            self.busy = False
        self.export_button.set_sensitive(True)
        self.enc = enc
        self.enc_settings = s
        self.result_pixbuf = pixbuf_of(dw, dh, dec)
        self.orig_pixbuf = pixbuf_of(rw, rh, ref)
        mse = engine.mse(ref, dec) if (rw, rh) == (dw, dh) else None
        seconds = time.time() - t0
        self.size_label.set_markup('<big><b>%s</b></big>' % GLib.markup_escape_text(
            model.format_size(enc.size)))
        parts = ['%s, %d x %d px' % (dict(model.FORMATS)[enc.format], enc.width, enc.height),
                 model.ratio_text(enc.size, enc.raw_size)]
        if mse is not None:
            p = model.psnr(mse)
            parts.append('lossless (PSNR infinite)' if p == float('inf') else
                         'PSNR %.1f dB' % p)
        self.detail_label.set_text(', '.join(parts))
        note = enc.note
        if enc.quality is not None:
            name = model.search_parameter(s)[0]
            self.target_label.set_text('%s %d found in %d encodes: %s.' % (
                'Colours' if name == 'colors' else 'Quality', enc.quality, len(enc.tried),
                'fits' if enc.fits else 'does NOT fit'))
        self.note_label.set_text(note)
        self.status_label.set_text('%.2f s' % seconds)
        self.show_times()
        self.show_pixbufs()

    def show_times(self):
        if self.enc is None:
            return
        i = int(self.conn_combo.get_active_id() or 1)
        text, bps, lat = model.CONNECTIONS[i]
        t = model.download_seconds(self.enc.size, bps, lat)
        others = []
        for j, (text2, bps2, lat2) in enumerate(model.CONNECTIONS):
            if j != i and j in (0, 2, 3):
                others.append('%s on %s' % (model.format_seconds(
                    model.download_seconds(self.enc.size, bps2, lat2)), text2.split(' (')[0]))
        self.time_label.set_markup('<b>%s</b> on %s (%s)' % (
            model.format_seconds(t), GLib.markup_escape_text(text),
            GLib.markup_escape_text(', '.join(others))))

    def show_pixbufs(self):
        if not hasattr(self, 'result_pixbuf'):
            return
        mode = getattr(self, 'mode', 'result')
        cap = self.caption()
        size = (self.result_pixbuf.get_width(), self.result_pixbuf.get_height())
        if size != getattr(self, 'shown_size', None):
            # another size (crop, resize): start from the centre again
            self.shown_size = size
            self.view.cx = self.view.cy = None
        self.pane_orig.pixbuf = self.orig_pixbuf
        self.pane_orig.caption = 'Original'
        self.pane_result.pixbuf = self.result_pixbuf
        self.pane_result.caption = cap
        self.pane_result.left = self.orig_pixbuf if mode == 'split' else None
        self.view.redraw()

    def caption(self):
        if self.enc is None:
            return ''
        s = self.enc_settings
        f = s['format']
        q = {'jpeg': 'jpeg-quality', 'webp': 'webp-quality', 'avif': 'avif-quality',
             'jxl': 'jxl-quality'}.get(f)
        text = dict(model.FORMATS)[f].split(' (')[0]
        if s.get(f + '-lossless'):
            text += ' lossless'
        elif q:
            text += ' %d' % (self.enc.quality if self.enc.quality is not None else s[q])
        elif f in ('png8', 'gif'):
            text += ' %d colours' % (self.enc.quality if self.enc.quality is not None
                                     else s['colors'])
        return '%s: %s' % (text, model.format_size(self.enc.size).split(' (')[0])

    # ------------------------------------------------------------ export

    def on_browse(self, button):
        chooser = Gtk.FileChooserDialog(title='Export for Web to', parent=self.dialog,
                                        action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons('_Cancel', Gtk.ResponseType.CANCEL, '_Select', Gtk.ResponseType.OK)
        chooser.set_do_overwrite_confirmation(False)
        path = self.path_entry.get_text()
        if os.path.isdir(os.path.dirname(path)):
            chooser.set_current_folder(os.path.dirname(path))
        chooser.set_current_name(os.path.basename(path))
        if chooser.run() == Gtk.ResponseType.OK:
            self.path_entry.set_text(chooser.get_filename())
            self.fix_extension()
        chooser.destroy()

    def on_response(self, dlg, response):
        self.response = response

    def confirm(self, text):
        m = Gtk.MessageDialog(transient_for=self.dialog, modal=True,
                              message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.OK_CANCEL, text=text)
        r = m.run()
        m.destroy()
        return r == Gtk.ResponseType.OK

    def error(self, text):
        m = Gtk.MessageDialog(transient_for=self.dialog, modal=True,
                              message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.CLOSE, text=text)
        m.run()
        m.destroy()

    def run(self):
        self.update()
        try:
            while True:
                r = self.dialog.run()
                if r != Gtk.ResponseType.OK:
                    return None
                if self.pending is not None or self.enc_settings != self.s:
                    if self.pending is not None:
                        GLib.source_remove(self.pending)
                        self.pending = None
                    self.update()
                if self.enc is None:
                    continue
                path = os.path.expanduser(self.path_entry.get_text().strip())
                if not path:
                    self.error('Give the file to export to.')
                    continue
                if os.path.isdir(path):
                    self.error('%s is a folder.' % path)
                    continue
                if os.path.exists(path) and not self.confirm(
                        '%s exists already. Replace it?' % os.path.basename(path)):
                    continue
                try:
                    engine.write_file(path, self.enc.data)
                except GLib.Error as e:
                    self.error('Could not write %s: %s' % (path, e.message))
                    continue
                self.save_state(path)
                return self.enc
        finally:
            self.dialog.destroy()
            self.session.close()


def run(procedure, config, image, available):
    """Shows the dialog; returns the Encoded that was written, or None if
    cancelled."""
    return WebDialog(procedure, config, image, available).run()
