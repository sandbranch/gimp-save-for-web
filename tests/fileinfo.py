# Reads what a JPEG, PNG, WebP, AVIF, JPEG XL or GIF file carries, from
# its structure, without GIMP or any image library: the metadata (Exif as
# TIFF bytes, XMP as text, ICC profile bytes, IPTC, comment) and the header
# facts the tests check (progressive, chroma sampling, PNG colour type and
# palette, interlace, WebP kind, sizes). Used by tests/check.py.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import struct
import zlib


def info(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:3] == b'\xff\xd8\xff':
        r = jpeg(data)
    elif data[:8] == b'\x89PNG\r\n\x1a\n':
        r = png(data)
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        r = webp(data)
    elif data[:6] in (b'GIF87a', b'GIF89a'):
        r = gif(data)
    elif data[:2] == b'\xff\x0a' or data[:12] == b'\x00\x00\x00\x0cJXL \r\n\x87\n':
        r = jxl(data)
    elif data[4:8] == b'ftyp':
        r = isobmff(data)
    else:
        r = {'format': 'unknown'}
    r['size'] = len(data)
    r.setdefault('exif', None)
    r.setdefault('xmp', None)
    r.setdefault('icc', None)
    r.setdefault('iptc', False)
    r.setdefault('comment', None)
    return r


# ------------------------------------------------------------ Exif (TIFF)

def tiff_tags(tiff):
    """{'ifd0': {tag: value}, 'gps': bool}: the IFD0 tags of a TIFF/Exif
    block (ASCII values as str, others as the raw count), and whether it
    points to a GPS IFD with any entry."""
    if len(tiff) < 8 or tiff[:2] not in (b'II', b'MM'):
        return None
    e = '<' if tiff[:2] == b'II' else '>'
    off = struct.unpack(e + 'I', tiff[4:8])[0]
    tags = {}
    gps = False
    if off + 2 > len(tiff):
        return {'ifd0': tags, 'gps': False}
    n = struct.unpack(e + 'H', tiff[off:off + 2])[0]
    for i in range(n):
        p = off + 2 + 12 * i
        if p + 12 > len(tiff):
            break
        tag, typ, count = struct.unpack(e + 'HHI', tiff[p:p + 8])
        val = tiff[p + 8:p + 12]
        if typ == 2:
            if count <= 4:
                s = val[:count]
            else:
                o = struct.unpack(e + 'I', val)[0]
                s = tiff[o:o + count]
            tags[tag] = s.rstrip(b'\0').decode('latin-1')
        elif typ == 4 and count == 1:
            tags[tag] = struct.unpack(e + 'I', val)[0]
        else:
            tags[tag] = count
        if tag == 0x8825 and typ in (4, 13):
            g = struct.unpack(e + 'I', val)[0]
            if g + 2 <= len(tiff) and struct.unpack(e + 'H', tiff[g:g + 2])[0] > 0:
                gps = True
    return {'ifd0': tags, 'gps': gps}


# ------------------------------------------------------------ JPEG

def jpeg(data):
    r = {'format': 'jpeg', 'progressive': None, 'sampling': None}
    icc = b''
    p = 2
    while p + 4 <= len(data):
        if data[p] != 0xff:
            break
        marker = data[p + 1]
        if marker == 0xd9 or marker == 0xda:
            if marker == 0xda:
                break
        length = struct.unpack('>H', data[p + 2:p + 4])[0]
        seg = data[p + 4:p + 2 + length]
        if marker == 0xe1 and seg[:6] == b'Exif\0\0':
            r['exif'] = seg[6:]
        elif marker == 0xe1 and seg.startswith(b'http://ns.adobe.com/xap/1.0/\0'):
            r['xmp'] = seg[29:].decode('utf-8', 'replace')
        elif marker == 0xe2 and seg[:12] == b'ICC_PROFILE\0':
            icc += seg[14:]
        elif marker == 0xed and seg[:14] == b'Photoshop 3.0\0':
            r['iptc'] = b'8BIM\x04\x04' in seg
        elif marker == 0xfe:
            r['comment'] = seg.decode('latin-1')
        elif marker in (0xc0, 0xc1, 0xc2):
            r['progressive'] = marker == 0xc2
            r['height'], r['width'] = struct.unpack('>HH', seg[1:5])
            ncomp = seg[5]
            factors = [(seg[6 + 3 * i + 1] >> 4, seg[6 + 3 * i + 1] & 15) for i in range(ncomp)]
            r['components'] = ncomp
            if ncomp == 3:
                (h0, v0), (h1, v1) = factors[0], factors[1]
                r['sampling'] = {(1, 1): '444', (2, 1): '422', (1, 2): '440',
                                 (2, 2): '420'}.get((h0 // h1, v0 // v1), '%dx%d' % (h0, v0))
        p += 2 + length
    if icc:
        r['icc'] = icc
    return r


# ------------------------------------------------------------ PNG

def _raw_profile(text):
    """ImageMagick's "Raw profile type ..." text: a name line, a length
    line, then hex."""
    lines = text.strip().split('\n')
    return bytes.fromhex(''.join(lines[2:]))


def png(data):
    r = {'format': 'png', 'chunks': []}
    p = 8
    while p + 8 <= len(data):
        length, typ = struct.unpack('>I4s', data[p:p + 8])
        body = data[p + 8:p + 8 + length]
        t = typ.decode('latin-1')
        r['chunks'].append(t)
        if t == 'IHDR':
            (r['width'], r['height'], r['bit_depth'], r['color_type'], _, _,
             r['interlace']) = struct.unpack('>IIBBBBB', body)
        elif t == 'PLTE':
            r['palette'] = length // 3
        elif t == 'tRNS':
            r['trns'] = length
        elif t == 'iCCP':
            name, rest = body.split(b'\0', 1)
            r['icc'] = zlib.decompress(rest[1:])
        elif t == 'eXIf':
            r['exif'] = body
        elif t in ('tEXt', 'zTXt', 'iTXt'):
            key, rest = body.split(b'\0', 1)
            key = key.decode('latin-1')
            if t == 'tEXt':
                text = rest.decode('latin-1')
            elif t == 'zTXt':
                text = zlib.decompress(rest[1:]).decode('latin-1')
            else:
                flag, method = rest[0], rest[1]
                rest = rest[2:]
                _lang, rest = rest.split(b'\0', 1)
                _tkey, rest = rest.split(b'\0', 1)
                text = (zlib.decompress(rest) if flag else rest).decode('utf-8', 'replace')
            if key == 'XML:com.adobe.xmp':
                r['xmp'] = text
            elif key == 'Raw profile type exif':
                raw = _raw_profile(text)
                r['exif'] = raw[6:] if raw[:6] == b'Exif\0\0' else raw
            elif key == 'Raw profile type iptc':
                r['iptc'] = True
            elif key == 'Comment':
                r['comment'] = text
            elif key == 'Raw profile type xmp':
                r['xmp'] = _raw_profile(text).decode('utf-8', 'replace')
        p += 12 + length
    return r


# ------------------------------------------------------------ WebP

def webp(data):
    r = {'format': 'webp', 'chunks': []}
    p = 12
    while p + 8 <= len(data):
        typ, length = struct.unpack('<4sI', data[p:p + 8])
        body = data[p + 8:p + 8 + length]
        t = typ.decode('latin-1')
        r['chunks'].append(t)
        if t == 'EXIF':
            r['exif'] = body[6:] if body[:6] == b'Exif\0\0' else body
        elif t == 'XMP ':
            r['xmp'] = body.decode('utf-8', 'replace')
        elif t == 'ICCP':
            r['icc'] = body
        elif t == 'VP8X':
            flags = body[0]
            r['alpha'] = bool(flags & 0x10)
            r['width'] = 1 + int.from_bytes(body[4:7], 'little')
            r['height'] = 1 + int.from_bytes(body[7:10], 'little')
        elif t == 'VP8L':
            b = int.from_bytes(body[1:5], 'little')
            r['width'] = 1 + (b & 0x3fff)
            r['height'] = 1 + ((b >> 14) & 0x3fff)
            r.setdefault('alpha', bool((b >> 28) & 1))
        elif t == 'VP8 ':
            r['width'], r['height'] = (v & 0x3fff for v in struct.unpack('<HH', body[6:10]))
        p += 8 + length + (length & 1)
    r['lossless'] = 'VP8L' in r['chunks']
    return r


# ------------------------------------------------------------ GIF

def gif(data):
    r = {'format': 'gif'}
    r['width'], r['height'], packed = struct.unpack('<HHB', data[6:11])
    p = 13
    if packed & 0x80:
        r['palette'] = 2 << (packed & 7)
        p += 3 * r['palette']
    r['interlace'] = None
    r['frames'] = 0
    while p < len(data):
        b = data[p]
        if b == 0x21:           # extension: skip its sub-blocks
            if data[p + 1] == 0xff and data[p + 3:p + 14] == b'XMP DataXMP':
                r['xmp'] = 'present'
            if data[p + 1] == 0xfe:
                r['comment'] = 'present'
            p += 2
            while data[p]:
                p += data[p] + 1
            p += 1
        elif b == 0x2c:         # image
            r['frames'] += 1
            flags = data[p + 9]
            if r['interlace'] is None:
                r['interlace'] = bool(flags & 0x40)
            p += 10
            if flags & 0x80:
                p += 3 * (2 << (flags & 7))
            p += 1              # LZW code size
            while data[p]:
                p += data[p] + 1
            p += 1
        elif b == 0x3b:
            break
        else:
            break
    return r


# ------------------------------------------------------------ AVIF, JPEG XL

def boxes(data, start=0, end=None):
    """(type, body start, body end) of the ISOBMFF boxes in data[start:end]."""
    end = len(data) if end is None else end
    p = start
    while p + 8 <= end:
        size, typ = struct.unpack('>I4s', data[p:p + 8])
        h = 8
        if size == 1:
            size = struct.unpack('>Q', data[p + 8:p + 16])[0]
            h = 16
        elif size == 0:
            size = end - p
        if size < h:
            break
        yield typ.decode('latin-1'), p + h, p + size
        p += size


def isobmff(data):
    r = {'format': 'isobmff'}
    items = {}          # id -> (type, content type)
    locs = {}           # id -> (offset, length)
    for t, s, e in boxes(data):
        if t == 'ftyp':
            r['brand'] = data[s:s + 4].decode('latin-1')
            r['format'] = 'avif' if r['brand'] in ('avif', 'avis') else r['brand']
        elif t == 'meta':
            for t2, s2, e2 in boxes(data, s + 4, e):
                if t2 == 'iinf':
                    version = data[s2]
                    n_off = s2 + 4
                    n = struct.unpack('>H' if version == 0 else '>I',
                                      data[n_off:n_off + (2 if version == 0 else 4)])[0]
                    q = n_off + (2 if version == 0 else 4)
                    for t3, s3, e3 in boxes(data, q, e2):
                        if t3 != 'infe':
                            continue
                        v = data[s3]
                        if v >= 2:
                            if v == 2:
                                iid = struct.unpack('>H', data[s3 + 4:s3 + 6])[0]
                                o = s3 + 8
                            else:
                                iid = struct.unpack('>I', data[s3 + 4:s3 + 8])[0]
                                o = s3 + 10
                            itype = data[o:o + 4].decode('latin-1')
                            rest = data[o + 4:e3].split(b'\0')
                            ctype = rest[1].decode('latin-1') if itype == 'mime' and \
                                len(rest) > 1 else ''
                            items[iid] = (itype, ctype)
                elif t2 == 'iloc':
                    locs.update(_iloc(data, s2, e2))
                elif t2 == 'iprp':
                    for t3, s3, e3 in boxes(data, s2, e2):
                        if t3 == 'ipco':
                            for t4, s4, e4 in boxes(data, s3, e3):
                                if t4 == 'colr':
                                    kind = data[s4:s4 + 4].decode('latin-1')
                                    r.setdefault('colr', []).append(kind)
                                    if kind in ('prof', 'rICC'):
                                        r['icc'] = data[s4 + 4:e4]
                                elif t4 == 'ispe' and 'width' not in r:
                                    r['width'], r['height'] = struct.unpack(
                                        '>II', data[s4 + 4:s4 + 12])
    for iid, (itype, ctype) in items.items():
        if iid not in locs:
            continue
        o, n = locs[iid]
        body = data[o:o + n]
        if itype == 'Exif':
            skip = struct.unpack('>I', body[:4])[0]
            r['exif'] = body[4 + skip:]
        elif itype == 'mime' and 'xmp' in ctype or ctype == 'application/rdf+xml':
            r['xmp'] = body.decode('utf-8', 'replace')
    return r


def _iloc(data, s, e):
    version = data[s]
    p = s + 4
    b1, b2 = data[p], data[p + 1]
    off_size, len_size, base_size = b1 >> 4, b1 & 15, b2 >> 4
    idx_size = b2 & 15 if version in (1, 2) else 0
    p += 2

    def rd(n):
        nonlocal p
        v = int.from_bytes(data[p:p + n], 'big') if n else 0
        p += n
        return v

    count = rd(2 if version < 2 else 4)
    out = {}
    for _ in range(count):
        iid = rd(2 if version < 2 else 4)
        if version in (1, 2):
            rd(2)               # construction method
        rd(2)                   # data reference index
        base = rd(base_size)
        n_ext = rd(2)
        first = None
        total = 0
        for _ in range(n_ext):
            if idx_size:
                rd(idx_size)
            off = rd(off_size)
            ln = rd(len_size)
            if first is None:
                first = base + off
            total += ln
        if first is not None:
            out[iid] = (first, total)
    return out


def jxl(data):
    r = {'format': 'jxl', 'container': data[:2] != b'\xff\x0a'}
    if not r['container']:
        return r
    r['boxes'] = []
    for t, s, e in boxes(data):
        r['boxes'].append(t)
        body = data[s:e]
        if t == 'brob':
            try:
                import brotli
            except ImportError:
                r.setdefault('compressed', []).append(body[:4].decode('latin-1'))
                continue
            t = body[:4].decode('latin-1')
            body = brotli.decompress(body[4:])
        if t == 'Exif':
            skip = struct.unpack('>I', body[:4])[0]
            r['exif'] = body[4 + skip:]
        elif t == 'xml ':
            r['xmp'] = body.decode('utf-8', 'replace')
    return r
