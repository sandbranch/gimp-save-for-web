# Runs inside GIMP on a Broadway display (tests/gui/start.sh): makes a
# generated scene (SFW_SCENE, 640x400 by default) with a selection, names
# it SFW_OUT/scene.xcf (so the dialog proposes SFW_OUT/scene.<ext>),
# shows it and opens Export for Web. When the dialog closes it writes the
# return values and whether the image is unchanged to SFW_OUT/result.txt,
# and quits GIMP.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import os
import struct

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, Gio

out = os.environ['SFW_OUT']
W, H = (int(v) for v in os.environ.get('SFW_SCENE', '640x400').split('x'))
image = Gimp.Image.new(W, H, Gimp.ImageBaseType.RGB)
layer = Gimp.Layer.new(image, 'scene', W, H, Gimp.ImageType.RGB_IMAGE, 100,
                       Gimp.LayerMode.NORMAL)
image.insert_layer(layer, None, 0)
data = bytearray()
for Y in range(H):
    for X in range(W):
        x, y = X * 640.0 / W, Y * 400.0 / H
        n = ((X * 7919 + Y * 104729) % 97) / 97.0 * 0.06
        if (x - 430) ** 2 + (y - 170) ** 2 < 90 ** 2:
            p = (0.95, 0.78 + n, 0.2)
        elif y > 300:
            p = (0.25 + n, 0.45 + 0.1 * ((int(x) // 16 + int(y) // 8) % 2), 0.2)
        else:
            p = (0.35 + 0.3 * y / 300 + n, 0.55 + 0.25 * y / 300 + n, 0.95 - n)
        if 80 <= x < 240 and 120 <= y < 300 and (int(x) // 10) % 2 == 0:
            p = (0.2, 0.15 + n, 0.12)
        data += struct.pack('fff', *p)
buf = layer.get_buffer()
buf.set(Gegl.Rectangle.new(0, 0, W, H), "R'G'B' float", bytes(data))
buf.flush()
image.select_rectangle(Gimp.ChannelOps.REPLACE, W // 8, H // 8, W // 2, H // 2)
image.set_file(Gio.File.new_for_path(os.path.join(out, 'scene.xcf')))
image.clean_all()


def md5():
    b = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, W, H), 1.0, "R'G'B'A float",
                               Gegl.AbyssPolicy.NONE)
    return hashlib.md5(bytes(b)).hexdigest()


before = md5()
Gimp.Display.new(image)
proc = Gimp.get_pdb().lookup_procedure('plug-in-save-for-web')
config = proc.create_config()
config.set_property('run-mode', Gimp.RunMode.INTERACTIVE)
config.set_property('image', image)
config.set_core_object_array('drawables', [layer])
result = proc.run(config)
status = result.index(0)
with open(os.path.join(out, 'result.txt.part'), 'w') as f:
    f.write('status %s\n' % status.value_nick)
    if status == Gimp.PDBStatusType.SUCCESS:
        f.write('file-size %d\nwidth %d\nheight %d\nquality %d\nfits %s\n' % (
            result.index(1), result.index(2), result.index(3), result.index(4),
            result.index(5)))
    f.write('unchanged %s\n' % (md5() == before and not image.is_dirty() and
                                list(Gimp.Selection.bounds(image))[1:] ==
                                [True, W // 8, H // 8, W // 8 + W // 2, H // 8 + H // 2]))
    f.write('images %d\n' % len(Gimp.get_images()))
os.rename(os.path.join(out, 'result.txt.part'), os.path.join(out, 'result.txt'))
quit = Gimp.get_pdb().lookup_procedure('gimp-quit')
quit_config = quit.create_config()
quit_config.set_property('force', True)
quit.run(quit_config)
