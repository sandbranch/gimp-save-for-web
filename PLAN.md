# Save for Web for GIMP 3: plan and findings

## The original

Save for Web by Aurimas Juška, github.com/auris/gimp-save-for-web, read at
commit 5b8c713 (2021-08-12; the only release is 0.29.0 from 2009). GIMP 2,
C, GTK 2, 5347 lines in `src/*.c`. It was number 2 of the old GIMP
registry's all-time "Popular content" (see gimp-devtools
`docs/candidates.md`, item 5).

### Licence, as the files say

- `src/webx_*.c` (all of the plug-in's own code): "Copyright (C) 2006-2007,
  Aurimas Juška", GNU **Lesser** General Public License, version 2 or later.
- `src/webx_prefs.c`: "Copyright (C) 1998-2005 Maurits Rijk" (taken from
  GIMP's ImageMap plug-in), GNU GPL version 2 or later.
- `src/cursors.c`: "Copyright (C) 2000 The Free Software Foundation", GNU
  GPL version 2 or later.
- `COPYING`: an MIT-style permission text with no name in it, which
  contradicts the file headers (upstream issue #8).

Taken together: GPL-2.0-or-later. This rewrite reuses **no code** from it
(see below), so it is GPL-3.0-or-later, which is compatible with that in
any case.

### What it does (read from the code)

- Menu File > Export > "Export for Web..." (`file-web-export`),
  interactive only; refuses images over 10000 pixels a side.
- One dialog: a preview on the left, settings on the right (a paned
  window whose position and the dialog's size are remembered, through
  `webx_prefs.c`; no format settings are remembered).
- Formats: JPEG, PNG-8, PNG-24, GIF. A "JPEG 2000" radio button exists but
  has no target behind it (`target = NULL`), so it does nothing.
  - JPEG: quality, smoothing, optimise, progressive, baseline, "strip
    EXIF" (detaches the `exif-data` and `gimp-metadata` parasites).
  - PNG-8 and GIF (shared indexed options): reuse the existing palette,
    optimum palette with N colours, web palette, black and white; remove
    unused colours; dither none, Floyd-Steinberg, Floyd-Steinberg reduced
    bleeding, positioned; dither transparency. PNG-8 also interlace and
    compression level; GIF interlace.
  - PNG-24: interlace, compression level.
- The preview shows the real result: every change (after 150 ms) saves
  the image with GIMP's own `file-*-save` to a temporary file, loads it
  back with `gimp_file_load` and shows those pixels, with the file size
  in kB. Zoom 12.5 % to 1600 %, fit width, fit visible; pan with the
  hand; a navigation pop-up; a "show preview" toggle (off shows the
  original).
- Resize (width and height with a chain button for the aspect) and crop
  (offset and size fields, and crop handles dragged in the preview).
- Export: a file chooser, then the image is saved again with the same
  settings (not the temporary file), so the saved size can differ from
  the one shown in some cases.
- It works on duplicates of the image, flattened for JPEG.

## Port or rewrite: rewrite, in Python 3

A port would keep almost nothing:

- The GIMP 2 API it is built on is gone: integer image IDs,
  `gimp_run_procedure` with `GimpParam` arrays, `file-*-save`, parasites
  for metadata. GIMP 3 has objects, `GimpProcedureConfig`, `file-*-export`
  with `GimpExportOptions`, and `GimpMetadata`.
- About two thirds of the code is GTK 2 widgets: a custom preview with
  its own hand and crop dragging and a navigation pop-up
  (`webx_preview.c`, 1825 lines), a pipeline object on `GtkObject`,
  table layouts. GTK 3 has none of `GtkObject`, `GtkTable` or the old
  drawing model; this is a rewrite of the widget code whatever the
  language.
- What is worth keeping is the design (one dialog, the encoded then
  decoded pixels as the preview, a size read-out, duplicates of the
  image), and that is small.

So it is a rewrite, and Python 3 fits it best:

- The heavy work is done by GIMP's own exporters and conversions (C), in
  GIMP's process; the plug-in only duplicates, scales, converts, calls the
  exporter and reads the pixels back. Python adds no measurable time to
  an encode.
- No build step and no compiler: it runs the same in the Flatpak and a
  distro GIMP, like gimp-tileset-export.
- GTK 3 and GimpUi through GObject introspection are complete enough for
  a custom preview (a `Gtk.DrawingArea` with cairo).

## GIMP 3.2.6 (Flatpak) procedures used, checked with the PDB

Read with `lookup_procedure(...).get_arguments()` in the Flatpak GIMP
3.2.6 (all `file-*-export` take run-mode, image, file, options first):

| Format | Procedure | Arguments used |
|---|---|---|
| JPEG | `file-jpeg-export` | quality 0..1, smoothing 0..1, optimize, progressive, sub-sampling (`sub-sampling-1x1`, `-2x1`, `-1x2`, `-2x2`), baseline, include-exif/-iptc/-xmp/-color-profile/-thumbnail/-comment |
| PNG | `file-png-export` | interlaced, compression 0..9, bkgd, offs, phys, time, save-transparent, optimize-palette, format (`auto`, `rgb8`, `rgba8`, `gray8`, `graya8`, 16-bit ones), include-exif/-iptc/-xmp/-color-profile/-thumbnail/-comment |
| WebP | `file-webp-export` | preset (`default`, `picture`, `photo`, `drawing`, `icon`, `text`), lossless, quality 0..100, alpha-quality 0..100, use-sharp-yuv, include-exif/-iptc/-xmp/-color-profile/-thumbnail |
| AVIF | `file-heif-av1-export` | quality 0..100 (int), lossless, save-bit-depth 8..12, pixel-format (`rgb`, `yuv444`, `yuv420`), encoder-speed (`slow`, `balanced`, `fast`), include-exif/-xmp (no ICC or IPTC switch) |
| JPEG XL | `file-jpegxl-export` | lossless, compression 0.1..15 (the Butteraugli distance), save-bit-depth 8..16, speed (`lightning` ... `tortoise`), include-exif/-xmp (no ICC switch) |
| GIF | `file-gif-export` | interlace, loop, as-animation (no metadata at all) |

Also: `gimp-image-convert-indexed` (dither NONE, FS, FS_LOWBLEED, FIXED;
palette GENERATE, WEB, MONO, CUSTOM; there is no "reuse" palette type in
GIMP 3), `Gimp.Image.convert_color_profile`, `Gimp.Image.scale` with the
context interpolation (NONE, LINEAR, CUBIC, NOHALO, LOHALO),
`Gimp.Image.crop`, `Gimp.Metadata`, `Gimp.file_load` for decoding.

First measured on a 64 x 48 test image carrying Exif, XMP and a non-sRGB
profile, exported from a duplicate with every include switch off and then
on (ImageMagick `identify -verbose` and GIMP loading the file back); the
tests now check all of it on every run:

- JPEG, PNG and WebP follow the switches exactly: nothing with them off;
  Exif, XMP and ICC with them on.
- AVIF writes an ICC profile even with everything off (the exporter has
  no switch for it); Exif and XMP follow the switches.
- JPEG XL: Exif and XMP follow the switches.
- GIF never carries metadata.
- `Gimp.Image.duplicate` copies the metadata and the colour profile, and
  the original keeps its own.

## Design

- `save-for-web/sfw_model.py`: plain Python, no GIMP: the settings and
  their defaults, the choices, the resize arithmetic, the JPEG XL
  quality to distance mapping, the target-size search, the download time
  estimate. Unit-tested on the host (`tests/unit.py`).
- `save-for-web/sfw_engine.py`: works in GIMP: builds the base image
  (a duplicate of the visible image, cropped, scaled, converted to sRGB,
  8 bit, metadata filtered), encodes it with the exporter into memory
  (a temporary file read back and deleted), decodes it with `Gimp.file_load`
  for the preview, and runs the target-size search. Caches the base and
  the indexed conversions so that a quality change re-encodes only.
- `save-for-web/save-for-web.py`: the plug-in: `plug-in-save-for-web`,
  File > Export for Web..., with every setting as a procedure argument
  (so GIMP remembers the last ones, and scripts can call it without the
  dialog), and the dialog.
- The file written by Export is the very bytes that were measured and
  decoded for the preview: the size shown is the size on disk.

## Test plan

- `tests/unit.py` on the host: the model.
- `tests/gimp-test.py` in a headless GIMP (throwaway profile and home,
  `tests/isolate.sh`): generated images with Exif (with GPS), XMP, IPTC
  and a non-sRGB profile; every format and option exported through the
  procedure; results written to `tests/output/cases/`, and a record of
  the original image (pixels, layers, metadata, dirty flag, undo) before
  and after.
- `tests/check.py` on the host: each file decodes (ImageMagick; JPEG XL
  in GIMP), its size equals the size the procedure returned, the header
  says what was asked (progressive SOF2, sampling factors, PNG colour
  type and palette length, interlace, WebP VP8/VP8L, AVIF and JPEG XL
  signatures), target-size results are under the target, metadata is
  there or not as chosen (read from the file structure by our own
  parser and by ImageMagick), the preview's decoded pixels equal those
  decoded from the written file, the original image is unchanged.
- `tests/gui/`: the dialog on a Broadway display with a headless Chrome;
  screenshots, and an export through the dialog.

## Status (2026-09-28)

Done and tested: everything in "Design" above, the dialog included.
`tests/run.sh` runs the unit tests, the headless GIMP exports, the file
checks and the Broadway dialog tests; the counts are in README.md.

## Findings while building it

- `file-webp-export` has `include-iptc` but writes no IPTC (checked in
  the file structure and by loading it back in GIMP).
- `file-heif-av1-export` always writes an ICC profile.
- JPEG XL: GIMP loads its own JPEG XL converted to sRGB and shows no
  profile, with the right colours: an Adobe RGB image exported without
  the conversion, lossless, decodes within 1 level of GIMP's own sRGB
  conversion. A lossy JPEG XL is the same bytes with or without the
  conversion (8-bit gradient in Adobe RGB, 1836 bytes both times).
- PNG compression 9 against 6 on a noisy 4000 x 3000 image: 34.9 s
  against 2.5 s for 13 % fewer bytes; on a smooth one the same size and
  time. Hence the default of 6.
- `Gimp.Procedure.new_return_values` fills in every return value with
  its default: a plug-in in Python must replace them (`remove`, `insert`),
  not append.
- `add_choice_aux_argument` fails an assertion in libgimp 3.2.6
  (`gimp_param_spec_choice: assertion 'GIMP_IS_CHOICE (choice)'`); the
  dialog's view and zoom are string aux arguments.
- Merging a 16-bit Adobe RGB layer and then converting differs by at most
  1 level from converting the unmerged image (43 of 38400 values).
- Broadway tests: End in a GtkSpinButton sets it to its maximum; the test
  clears the field with Backspace and Delete.

## Not done

- Animation (GIF, WebP, APNG), JPEG 2000, CMYK JPEG, AVIF and JPEG XL
  above 8 bits.
- Crop handles dragged in the preview and the navigation pop-up of the
  original; translations.
- Encoding in the background: one long encode (PNG compression 9 on a
  big image) blocks the dialog until it is done; a target-size search
  lets events through between its encodes.
- Not tried: a native (non-Flatpak) GIMP, Windows, macOS, GIMP 3.0.

## Notes

- 2026-09-28: one probe run reported a change in
  `~/.var/app/org.gimp.GIMP/.ld.so` (its cache switched from another
  hash to the plain runtime's). The run itself had its own `.ld.so` in the
  throwaway home, unchanged, and the same run repeated passed: something
  else ran `flatpak run org.gimp.GIMP` with the real home at that moment.
