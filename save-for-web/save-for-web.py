#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Save for Web for GIMP 3
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

"""Save for Web for GIMP 3: File > Export for Web...

One dialog to choose a web format and its settings while looking at the
real result: the file is encoded with GIMP's own exporter and decoded
again for the preview, with its exact size and download time. JPEG, PNG,
PNG-8, WebP, AVIF, JPEG XL and GIF; resize, crop to the selection,
metadata kept or stripped, and a target size. The user's image is never
changed: all work is done on a duplicate. After Save for Web by Aurimas
Juska (GIMP 2); a rewrite, see PLAN.md."""

import os
import sys
import traceback

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, Gio, GLib, GObject   # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sfw_model as model     # noqa: E402
import sfw_engine as engine   # noqa: E402

PLUG_IN_BINARY = 'save-for-web'
PROC = 'plug-in-save-for-web'
MENU = '<Image>/File/[Export]'
AUTHOR = 'David'
COPYRIGHT = 'David'
DATE = '2026'

def make_choice(table):
    choice = Gimp.Choice.new()
    for i, (nick, label) in enumerate(table):
        choice.add(nick, i, label, '')
    return choice


def settings_from_config(config):
    return {k: config.get_property(k) for k in model.SETTINGS}




# ------------------------------------------------------------ run

def export(image, s, path, session=None):
    """Encodes and writes the file; returns the Encoded."""
    own = session is None
    if own:
        session = engine.Session(image)
    try:
        enc = session.render(s)
        engine.write_file(path, enc.data)
        return enc
    finally:
        if own:
            session.close()


def return_values(procedure, enc):
    # (new_return_values fills in every return value with its default:
    # each one is replaced)
    rv = procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
    for i, (value, t) in enumerate(((enc.size, GObject.TYPE_INT), (enc.width, GObject.TYPE_INT),
                                    (enc.height, GObject.TYPE_INT),
                                    (-1 if enc.quality is None else enc.quality,
                                     GObject.TYPE_INT),
                                    (bool(enc.fits) if enc.fits is not None else True,
                                     GObject.TYPE_BOOLEAN),
                                    (enc.note, GObject.TYPE_STRING)), 1):
        rv.remove(i)
        rv.insert(i, GObject.Value(t, value))
    return rv


def error(procedure, message, status=Gimp.PDBStatusType.EXECUTION_ERROR):
    return procedure.new_return_values(status, GLib.Error(message))


def run_main(procedure, run_mode, image, drawables, config, data):
    try:
        available = engine.available_formats()
        if run_mode == Gimp.RunMode.NONINTERACTIVE:
            s = settings_from_config(config)
            path = model.config_path(config)
            if not path:
                return error(procedure, 'No file given.', Gimp.PDBStatusType.CALLING_ERROR)
            if s['format'] not in available:
                return error(procedure, 'This GIMP has no %s export (%s).' % (
                    dict(model.FORMATS)[s['format']], model.EXPORTERS[s['format']]),
                    Gimp.PDBStatusType.CALLING_ERROR)
            return return_values(procedure, export(image, s, path))
        # interactive, and with the last values (Repeat): the dialog, with
        # the last settings
        import sfw_dialog
        result = sfw_dialog.run(procedure, config, image, available)
        if result is None:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
        return return_values(procedure, result)
    except engine.ExportError as e:
        return error(procedure, str(e))
    except Exception as e:
        traceback.print_exc()
        return error(procedure, 'Export for Web failed: %s' % e)


class SaveForWeb(Gimp.PlugIn):

    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        Gegl.init(None)
        flags = GObject.ParamFlags.READWRITE
        procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_main, None)
        procedure.set_menu_label('Export for _Web...')
        procedure.set_documentation(
            'Export the image for the web with a live preview of the result and its size.',
            'One dialog to choose JPEG, PNG, PNG-8, WebP, AVIF, JPEG XL or GIF and their '
            'settings while looking at the encoded and decoded result, its exact file '
            'size and download time. Resize, crop to the selection, strip metadata or keep '
            'Exif, XMP, IPTC and the colour profile, convert to sRGB, and a target size '
            '(the highest quality that fits). The image itself is never changed.', name)
        procedure.add_file_argument('file', '_File', 'The file to write',
                                    Gimp.FileChooserAction.SAVE, True, None, flags)
        for k, (default, kind, extra) in model.SETTINGS.items():
            label, blurb = model.LABELS[k]
            if kind == 'choice':
                procedure.add_choice_argument(k, label, blurb, make_choice(extra), default,
                                              flags)
            elif kind == 'int':
                procedure.add_int_argument(k, label, blurb, extra[0], extra[1], default, flags)
            elif kind == 'double':
                procedure.add_double_argument(k, label, blurb, extra[0], extra[1], default,
                                              flags)
            else:
                procedure.add_boolean_argument(k, label, blurb, default, flags)
        # the dialog's own state, remembered but not part of the PDB call
        # (strings: choice aux arguments fail an assertion in libgimp 3.2.6)
        procedure.add_string_aux_argument('view', 'View', 'Preview mode: ' +
                                          ', '.join(n for n, _ in model.VIEWS), 'result', flags)
        procedure.add_string_aux_argument('zoom', 'Zoom', 'Preview zoom: ' +
                                          ', '.join(n for n, _ in model.ZOOMS), '100', flags)
        procedure.add_int_aux_argument('connection', 'Connection',
                                       'Connection for the download time', 0,
                                       len(model.CONNECTIONS) - 1, 1, flags)
        procedure.add_int_aux_argument('dialog-width', 'Dialog width', '', 0, 10000, 0, flags)
        procedure.add_int_aux_argument('dialog-height', 'Dialog height', '', 0, 10000, 0,
                                       flags)
        procedure.add_int_return_value('file-size', 'File size', 'Size of the file in bytes',
                                       0, GLib.MAXINT32, 0, flags)
        procedure.add_int_return_value('width', 'Width', 'Width of the exported image', 0,
                                       GLib.MAXINT32, 0, flags)
        procedure.add_int_return_value('height', 'Height', 'Height of the exported image', 0,
                                       GLib.MAXINT32, 0, flags)
        procedure.add_int_return_value('quality', 'Quality',
                                       'With a target size: the quality (or number of '
                                       'colours) found; otherwise -1', -1, 1000, -1, flags)
        procedure.add_boolean_return_value('fits', 'Fits',
                                           'The file is within the target size (always '
                                           'TRUE without one)', True, flags)
        procedure.add_string_return_value('note', 'Note', 'What the user should know', '',
                                          flags)
        procedure.set_image_types('*')
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES |
                                       Gimp.ProcedureSensitivityMask.NO_DRAWABLES)
        procedure.set_attribution(AUTHOR, COPYRIGHT, DATE)
        procedure.add_menu_path(MENU)
        return procedure


if __name__ == '__main__':
    Gimp.main(SaveForWeb.__gtype__, sys.argv)
