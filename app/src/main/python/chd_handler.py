"""
chd_handler.py
--------------
Minimal CHD (MAME "Compressed Hunks of Data") support for PS2 DVD images, so
iso_handler.py can accept a .chd exactly like an .iso.

What it does
  * ChdReader : opens a CHD v5, decodes the hunk map and reads hunks
                (codecs: zlib, lzma, and zstd when a zstd module is present).
  * ChdImage  : a file-like view (seek/read/write) of the decoded disc. Reads
                come from the CHD; writes are kept in memory as modified hunks,
                so the original file is never touched while patching.
  * write_chd : builds a NEW CHD from the original plus the modified hunks.
                Every unchanged hunk is copied byte for byte (no
                recompression, so it is fast and lossless); modified or newly
                appended hunks are stored uncompressed.

Limits (raised as ChdError with a readable message)
  * CHD version 5 only (what chdman has written for years).
  * DVD style images (2048-byte units, `chdman createdvd`) and CD style
    images (2448-byte frames, `chdman createcd`; codecs cdzl, cdlz and cdzs).
    A CD-style CHD must hold ONE data track whose ISO9660 file system is
    read as 2048-byte sectors (MODE1/2048, MODE1_RAW or MODE2 form 1 raw).
    Audio hunks (cdfl/FLAC) are not needed for the data track and are only
    copied untouched. Sectors added to a raw track get a sync/header but no
    EDC/ECC (emulators only read the 2048 data bytes).
  * CHDs with a parent are not supported.
  * Only hunks that must be READ (the ISO9660 volume descriptor, the root
    directory and the boot executable) need a supported codec; all other
    hunks are copied untouched whatever codec they use.

The header SHA-1 fields are copied unchanged, so `chdman verify` will report
the patched file as not matching; emulators do not check them.
"""

import binascii
import os
import re
import struct
import zlib

try:
    import lzma
except ImportError:  # pragma: no cover
    lzma = None

MAGIC = b"MComprHD"
HEADER_LEN = 124

# Map entry compression types (CHD v5)
C_TYPE_0, C_TYPE_1, C_TYPE_2, C_TYPE_3 = 0, 1, 2, 3
C_NONE = 4
C_SELF = 5
C_PARENT = 6
C_RLE_SMALL = 7
C_RLE_LARGE = 8
C_SELF_0 = 9
C_SELF_1 = 10
C_PARENT_SELF = 11
C_PARENT_0 = 12
C_PARENT_1 = 13

SECTOR = 2048

# CD-style CHDs: one "frame" is 2352 bytes of sector data + 96 bytes of subcode
CD_SECTOR = 2352
CD_SUB = 96
CD_FRAME = CD_SECTOR + CD_SUB          # 2448 = unit size of a CD CHD
CD_SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


class ChdError(Exception):
    pass


def is_chd(path):
    """True when the file starts with the CHD magic (detection is by content,
    never by file extension)."""
    try:
        with open(path, "rb") as f:
            return f.read(8) == MAGIC
    except OSError:
        return False


def crc16(data):
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF), as used by CHD."""
    return binascii.crc_hqx(bytes(data), 0xFFFF)


def _tag(value):
    return struct.pack(">I", value)


# --------------------------------------------------------------------------
# bit I/O (MSB first) and the canonical Huffman code used by the compressed map
# --------------------------------------------------------------------------

class _BitReader:
    def __init__(self, data):
        self.data = data
        self.i = 0
        self.buf = 0
        self.nbits = 0

    def read(self, n):
        if n == 0:
            return 0
        while self.nbits < n:
            b = self.data[self.i] if self.i < len(self.data) else 0
            self.i += 1
            self.buf = (self.buf << 8) | b
            self.nbits += 8
        self.nbits -= n
        value = (self.buf >> self.nbits) & ((1 << n) - 1)
        self.buf &= (1 << self.nbits) - 1
        return value


class _BitWriter:
    def __init__(self):
        self.out = bytearray()
        self.buf = 0
        self.nbits = 0

    def write(self, value, n):
        if n == 0:
            return
        self.buf = (self.buf << n) | (value & ((1 << n) - 1))
        self.nbits += n
        while self.nbits >= 8:
            self.nbits -= 8
            self.out.append((self.buf >> self.nbits) & 0xFF)
        self.buf &= (1 << self.nbits) - 1

    def finish(self):
        if self.nbits:
            self.out.append((self.buf << (8 - self.nbits)) & 0xFF)
            self.buf = 0
            self.nbits = 0
        return bytes(self.out)


def _canonical_codes(lengths):
    """Assigns canonical Huffman codes from code lengths, the way CHD does
    (longest codes get the numerically smallest values)."""
    maxlen = max(lengths) if lengths else 0
    histo = [0] * (max(maxlen, 32) + 1)
    for n in lengths:
        if n > 0:
            histo[n] += 1
    curstart = 0
    for codelen in range(len(histo) - 1, 0, -1):
        nextstart = (curstart + histo[codelen]) >> 1
        if codelen != 1 and nextstart * 2 != (curstart + histo[codelen]):
            raise ChdError("Corrupt Huffman table in the CHD map.")
        histo[codelen] = curstart
        curstart = nextstart
    codes = [0] * len(lengths)
    for sym, n in enumerate(lengths):
        if n > 0:
            codes[sym] = histo[n]
            histo[n] += 1
    return codes


def _import_tree_rle(br, numcodes, maxbits):
    numbits = 5 if maxbits >= 16 else (4 if maxbits >= 8 else 3)
    lengths = [0] * numcodes
    cur = 0
    while cur < numcodes:
        nb = br.read(numbits)
        if nb != 1:
            lengths[cur] = nb
            cur += 1
        else:
            nb = br.read(numbits)
            if nb == 1:
                lengths[cur] = 1
                cur += 1
            else:
                rep = br.read(numbits) + 3
                for _ in range(rep):
                    if cur >= numcodes:
                        raise ChdError("Corrupt Huffman table in the CHD map.")
                    lengths[cur] = nb
                    cur += 1
    return lengths


def _make_decoder(lengths):
    codes = _canonical_codes(lengths)
    table = {}
    for sym, n in enumerate(lengths):
        if n > 0:
            table[(n, codes[sym])] = sym
    return table, max(lengths) if lengths else 0


def _decode_symbol(br, decoder):
    table, maxlen = decoder
    code = 0
    for n in range(1, maxlen + 1):
        code = (code << 1) | br.read(1)
        sym = table.get((n, code))
        if sym is not None:
            return sym
    raise ChdError("Corrupt Huffman data in the CHD map.")


# --------------------------------------------------------------------------
# codecs
# --------------------------------------------------------------------------

def _lzma_dict_size(hunkbytes):
    # Same normalisation chdman's LZMA encoder applies for small inputs.
    for i in range(11, 31):
        if hunkbytes <= (2 << i):
            return 2 << i
        if hunkbytes <= (3 << i):
            return 3 << i
    return 1 << 26


def _decode_zstd(data, hunkbytes):
    try:
        import zstandard  # type: ignore
        return zstandard.ZstdDecompressor().decompressobj().decompress(data)
    except ImportError:
        pass
    try:
        from compression import zstd  # type: ignore  (Python 3.14+)
        return zstd.decompress(data)
    except ImportError:
        raise ChdError(
            "This CHD uses zstd compression, which is not available in this "
            "app. Re-create the CHD without zstd (chdman createdvd -c lzma,zlib "
            "or chdman createcd -c cdlz,cdzl), or convert it to an ISO first."
        )


def _inflate(data, size):
    return zlib.decompressobj(-15).decompress(data, size)


def _unlzma(data, size):
    if lzma is None:
        raise ChdError("LZMA support is missing in this Python build.")
    filt = [{
        "id": lzma.FILTER_LZMA1, "dict_size": _lzma_dict_size(size),
        "lc": 3, "lp": 0, "pb": 2,
    }]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filt)
    return dec.decompress(data, max_length=size)


def _decode_cd_hunk(codec, data, hunkbytes):
    """
    CD codecs (cdzl / cdlz / cdzs). The stored hunk is:
        [ecc bitmap: 1 bit per frame][length of base stream: 2 or 3 bytes]
        [base stream: all 2352-byte sectors][subcode stream: all 96-byte blocks]
    The result is re-interleaved to frames of 2448 bytes. For frames flagged
    in the ECC bitmap chdman removed the sync pattern and the P/Q parity;
    the sync pattern is put back here, the parity bytes are left zero
    (nothing that reads the 2048 data bytes needs them).
    """
    frames = hunkbytes // CD_FRAME
    ecc_bytes = (frames + 7) // 8
    len_bytes = 2 if hunkbytes < 65536 else 3
    head = ecc_bytes + len_bytes
    if len(data) < head:
        raise ChdError("A CHD hunk is too short (corrupt CHD?).")
    complen = int.from_bytes(data[ecc_bytes:head], "big")
    base = data[head:head + complen]
    sub = data[head + complen:]
    sec_len = frames * CD_SECTOR
    sub_len = frames * CD_SUB

    if codec == b"cdzl":
        base_out = _inflate(base, sec_len)
        sub_out = _inflate(sub, sub_len) if sub else bytes(sub_len)
    elif codec == b"cdlz":
        base_out = _unlzma(base, sec_len)
        sub_out = _inflate(sub, sub_len) if sub else bytes(sub_len)
    elif codec == b"cdzs":
        base_out = _decode_zstd(base, sec_len)
        sub_out = _decode_zstd(sub, sub_len) if sub else bytes(sub_len)
    else:
        raise ChdError(
            "This CD-type CHD stores a data hunk with the 'cdfl' (FLAC) "
            "codec, which is only meant for audio tracks and is not supported."
        )
    if len(base_out) != sec_len or len(sub_out) != sub_len:
        raise ChdError("A CHD hunk decompressed to the wrong size (corrupt CHD?).")

    out = bytearray(hunkbytes)
    for fr in range(frames):
        o = fr * CD_FRAME
        out[o:o + CD_SECTOR] = base_out[fr * CD_SECTOR:(fr + 1) * CD_SECTOR]
        out[o + CD_SECTOR:o + CD_FRAME] = sub_out[fr * CD_SUB:(fr + 1) * CD_SUB]
        if data[fr >> 3] & (1 << (fr & 7)):
            out[o:o + 12] = CD_SYNC
    return bytes(out)


def _decode_hunk(codec, data, hunkbytes):
    if codec == b"zlib":
        out = _inflate(data, hunkbytes)
    elif codec == b"lzma":
        out = _unlzma(data, hunkbytes)
    elif codec == b"zstd":
        out = _decode_zstd(data, hunkbytes)
    elif codec in (b"cdzl", b"cdlz", b"cdfl", b"cdzs"):
        if hunkbytes % CD_FRAME:
            raise ChdError("A CD codec is used in a CHD that is not CD-type.")
        return _decode_cd_hunk(codec, data, hunkbytes)
    else:
        name = codec.decode("latin-1", "replace")
        raise ChdError(
            f"The CHD uses the '{name}' codec for a hunk this tool must read, "
            "which is not supported. Re-create it with: "
            "chdman createdvd -c lzma,zlib"
        )
    if len(out) != hunkbytes:
        raise ChdError("A CHD hunk decompressed to the wrong size (corrupt CHD?).")
    return out


# --------------------------------------------------------------------------
# reader
# --------------------------------------------------------------------------

class ChdReader:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        try:
            self._parse()
        except BaseException:
            self.f.close()
            raise
        self._cache = {}

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- header -----------------------------------------------------------
    def _parse(self):
        f = self.f
        f.seek(0)
        hdr = f.read(HEADER_LEN)
        if len(hdr) < 16 or hdr[:8] != MAGIC:
            raise ChdError("Not a CHD file.")
        length, version = struct.unpack_from(">II", hdr, 8)
        if version != 5 or length != HEADER_LEN or len(hdr) < HEADER_LEN:
            raise ChdError(
                f"Unsupported CHD version {version}. Only CHD v5 is supported "
                "(re-create it with a current chdman)."
            )
        self.header = bytearray(hdr)
        self.compressors = [hdr[16 + 4 * i:20 + 4 * i] for i in range(4)]
        (self.logicalbytes, self.mapoffset, self.metaoffset) = struct.unpack_from(">QQQ", hdr, 32)
        (self.hunkbytes, self.unitbytes) = struct.unpack_from(">II", hdr, 56)
        if hdr[104:124] != bytes(20):
            raise ChdError("CHD files that need a parent CHD are not supported.")
        if self.hunkbytes == 0 or self.unitbytes == 0:
            raise ChdError("Corrupt CHD header.")
        if self.unitbytes == SECTOR and self.hunkbytes % SECTOR == 0:
            self.kind = "dvd"
        elif self.unitbytes == CD_FRAME and self.hunkbytes % CD_FRAME == 0:
            self.kind = "cd"
        else:
            raise ChdError(
                f"Unsupported CHD unit size ({self.unitbytes}). Only DVD-type "
                "(2048) and CD-type (2448) CHDs are supported."
            )
        self.hunkcount = -(-self.logicalbytes // self.hunkbytes)
        self.compressed = self.compressors[0] != bytes(4)
        self.map_info = None
        self.map_crc_ok = True
        if self.compressed:
            self._load_compressed_map()
        else:
            self._load_plain_map()

    def _load_plain_map(self):
        self.f.seek(self.mapoffset)
        raw = self.f.read(4 * self.hunkcount)
        if len(raw) != 4 * self.hunkcount:
            raise ChdError("Truncated CHD map.")
        vals = struct.unpack(">%dI" % self.hunkcount, raw)
        self.entries = [(C_NONE, self.hunkbytes, v * self.hunkbytes, 0) for v in vals]

    def _load_compressed_map(self):
        f = self.f
        f.seek(self.mapoffset)
        raw = f.read(16)
        if len(raw) < 16:
            raise ChdError("Truncated CHD map.")
        mapbytes = struct.unpack_from(">I", raw, 0)[0]
        firstoffs = int.from_bytes(raw[4:10], "big")
        mapcrc = struct.unpack_from(">H", raw, 10)[0]
        lengthbits, selfbits, parentbits = raw[12], raw[13], raw[14]
        comp = f.read(mapbytes)
        if len(comp) != mapbytes:
            raise ChdError("Truncated CHD map.")
        self.map_info = (lengthbits, selfbits, parentbits)

        br = _BitReader(comp)
        decoder = _make_decoder(_import_tree_rle(br, 16, 8))

        n = self.hunkcount
        types = [0] * n
        rep = 0
        last = 0
        for i in range(n):
            if rep > 0:
                types[i] = last
                rep -= 1
                continue
            val = _decode_symbol(br, decoder)
            if val == C_RLE_SMALL:
                types[i] = last
                rep = 2 + _decode_symbol(br, decoder)
            elif val == C_RLE_LARGE:
                types[i] = last
                rep = 2 + 16 + (_decode_symbol(br, decoder) << 4)
                rep += _decode_symbol(br, decoder)
            else:
                types[i] = last = val

        entries = []
        curoffset = firstoffs
        last_self = 0
        raw_map = bytearray()
        for i in range(n):
            t = types[i]
            offset = curoffset
            length = 0
            crc = 0
            if t in (C_TYPE_0, C_TYPE_1, C_TYPE_2, C_TYPE_3):
                length = br.read(lengthbits)
                curoffset += length
                crc = br.read(16)
            elif t == C_NONE:
                length = self.hunkbytes
                curoffset += length
                crc = br.read(16)
            elif t == C_SELF:
                last_self = offset = br.read(selfbits)
            elif t in (C_SELF_0, C_SELF_1):
                if t == C_SELF_1:
                    last_self += 1
                t = C_SELF
                offset = last_self
            else:
                raise ChdError("CHD files that need a parent CHD are not supported.")
            entries.append((t, length, offset, crc))
            raw_map += bytes([t]) + length.to_bytes(3, "big") + offset.to_bytes(6, "big") + crc.to_bytes(2, "big")

        self.map_crc_ok = (crc16(raw_map) == mapcrc)
        self.entries = entries

    # -- hunks ------------------------------------------------------------
    def read_hunk(self, index, _depth=0):
        if index < 0 or index >= self.hunkcount:
            raise ChdError("Hunk index out of range.")
        cached = self._cache.get(index)
        if cached is not None:
            return cached
        t, length, offset, _crc = self.entries[index]
        if t == C_NONE:
            self.f.seek(offset)
            data = self.f.read(self.hunkbytes)
            if len(data) != self.hunkbytes:
                raise ChdError("The CHD file is truncated.")
        elif t == C_SELF:
            if _depth > 64:
                raise ChdError("Corrupt CHD (reference loop).")
            data = self.read_hunk(offset, _depth + 1)
        elif t in (C_TYPE_0, C_TYPE_1, C_TYPE_2, C_TYPE_3):
            self.f.seek(offset)
            comp = self.f.read(length)
            if len(comp) != length:
                raise ChdError("The CHD file is truncated.")
            data = _decode_hunk(self.compressors[t], comp, self.hunkbytes)
        else:
            raise ChdError("Unsupported CHD map entry.")
        if len(self._cache) >= 32:
            self._cache.pop(next(iter(self._cache)))
        self._cache[index] = data
        return data

    def cd_tracks(self):
        """Track list of a CD-type CHD, from its CHT2 / CHTR metadata."""
        tracks = []
        for tag, _flags, data in self.read_metadata():
            if tag in (b"CHGT", b"CHGD"):
                raise ChdError("GD-ROM CHDs are not supported.")
            if tag not in (b"CHT2", b"CHTR"):
                continue
            text = data.rstrip(b"\0").decode("latin-1")
            fields = dict(re.findall(r"(\w+):(\S+)", text))
            try:
                tracks.append({
                    "track": int(fields["TRACK"]),
                    "type": fields.get("TYPE", ""),
                    "frames": int(fields["FRAMES"]),
                })
            except (KeyError, ValueError):
                continue
        tracks.sort(key=lambda t: t["track"])
        return tracks

    def read_metadata(self):
        """Returns the metadata chain as a list of (tag, flags, data)."""
        out = []
        off = self.metaoffset
        seen = 0
        while off and seen < 4096:
            self.f.seek(off)
            h = self.f.read(16)
            if len(h) < 16:
                raise ChdError("The CHD file is truncated or its metadata is corrupt.")
            tag = h[0:4]
            flags = h[4]
            length = int.from_bytes(h[5:8], "big")
            nxt = struct.unpack_from(">Q", h, 8)[0]
            data = self.f.read(length)
            out.append((tag, flags, data))
            off = nxt
            seen += 1
        return out


# --------------------------------------------------------------------------
# file-like view with an in-memory overlay
# --------------------------------------------------------------------------

class ChdImage:
    """Behaves like a binary file opened 'r+b' on the decoded disc image.
    Nothing is written to disk until write_chd() is called."""

    def __init__(self, reader):
        self.r = reader
        self.size = reader.logicalbytes
        self.pos = 0
        self.overlay = {}  # hunk index -> bytearray(hunkbytes)

    # file protocol
    def seek(self, offset, whence=0):
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        else:
            self.pos = self.size + offset
        if self.pos < 0:
            raise ValueError("negative seek")
        return self.pos

    def tell(self):
        return self.pos

    def flush(self):
        pass

    def close(self):
        pass

    # used by write_chd
    def logical_size(self):
        return self.size

    def adjust_metadata(self, meta):
        return meta

    def _hunk_for_read(self, i):
        if i in self.overlay:
            return self.overlay[i]
        if i < self.r.hunkcount:
            return self.r.read_hunk(i)
        return bytes(self.r.hunkbytes)

    def read(self, n=-1):
        if n is None or n < 0 or self.pos + n > self.size:
            n = max(0, self.size - self.pos)
        hb = self.r.hunkbytes
        out = bytearray()
        pos = self.pos
        end = pos + n
        while pos < end:
            i = pos // hb
            within = pos % hb
            take = min(hb - within, end - pos)
            out += self._hunk_for_read(i)[within:within + take]
            pos += take
        self.pos = pos
        return bytes(out)

    def write(self, data):
        hb = self.r.hunkbytes
        pos = self.pos
        mv = memoryview(bytes(data))
        done = 0
        while done < len(mv):
            i = pos // hb
            within = pos % hb
            take = min(hb - within, len(mv) - done)
            h = self.overlay.get(i)
            if h is None:
                h = bytearray(self._hunk_for_read(i))
                self.overlay[i] = h
            h[within:within + take] = mv[done:done + take]
            pos += take
            done += take
        self.pos = pos
        if pos > self.size:
            self.size = pos
        return len(mv)


class ChdCdImage:
    """
    File-like view of the ISO9660 data inside a CD-type CHD, as plain
    2048-byte sectors (same interface as ChdImage). Sector n of the ISO is
    frame (base + n) of the CHD; its 2048 data bytes sit at `data_off` inside
    the frame: 0 for MODE1/2048, 16 for MODE1_RAW, 24 for MODE2 form 1 raw.
    Writing past the end appends sectors to the (single) data track.
    """

    def __init__(self, reader):
        self.r = reader
        self.fph = reader.hunkbytes // CD_FRAME          # frames per hunk
        self.overlay = {}
        self.pos = 0
        tracks = reader.cd_tracks()
        self.single_track = len(tracks) <= 1
        meta_frames = tracks[0]["frames"] if tracks else reader.logicalbytes // CD_FRAME
        self.base, self.data_off = self._probe()
        self.raw = self.data_off != 0
        self.orig_sectors = max(meta_frames - self.base, 0)
        self.size = self.orig_sectors * SECTOR
        self._inited = set()

    def _frame(self, frame):
        h, fi = divmod(frame, self.fph)
        if h >= self.r.hunkcount:
            return bytes(CD_FRAME)
        return self.r.read_hunk(h)[fi * CD_FRAME:(fi + 1) * CD_FRAME]

    def _probe(self):
        for base in (0, 150):
            fr = self._frame(base + 16)
            for off in (0, 16, 24):
                if fr[off] == 1 and fr[off + 1:off + 6] == b"CD001":
                    return base, off
        raise ChdError(
            "No ISO9660 file system was found in this CD-type CHD "
            "(is it really a PS2 game image?)."
        )

    # file protocol
    def seek(self, offset, whence=0):
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        else:
            self.pos = self.size + offset
        if self.pos < 0:
            raise ValueError("negative seek")
        return self.pos

    def tell(self):
        return self.pos

    def flush(self):
        pass

    def close(self):
        pass

    def _hunk_for_read(self, h):
        if h in self.overlay:
            return self.overlay[h]
        if h < self.r.hunkcount:
            return self.r.read_hunk(h)
        return bytes(self.r.hunkbytes)

    def read(self, n=-1):
        if n is None or n < 0 or self.pos + n > self.size:
            n = max(0, self.size - self.pos)
        out = bytearray()
        pos = self.pos
        end = pos + n
        while pos < end:
            sector, within = divmod(pos, SECTOR)
            take = min(SECTOR - within, end - pos)
            h, fi = divmod(self.base + sector, self.fph)
            o = fi * CD_FRAME + self.data_off + within
            out += self._hunk_for_read(h)[o:o + take]
            pos += take
        self.pos = pos
        return bytes(out)

    def _init_raw_frame(self, ba, fi, sector):
        """Sync + header (+ XA subheader) for a sector added to a raw track."""
        o = fi * CD_FRAME
        ba[o:o + 12] = CD_SYNC
        total = self.base + sector + 150
        m, rest = divmod(total, 60 * 75)
        sec, fr = divmod(rest, 75)
        bcd = lambda x: ((x // 10) << 4) | (x % 10)
        ba[o + 12:o + 16] = bytes([bcd(m), bcd(sec), bcd(fr), 1 if self.data_off == 16 else 2])
        if self.data_off == 24:
            ba[o + 16:o + 24] = bytes([0, 0, 8, 0, 0, 0, 8, 0])

    def write(self, data):
        mv = memoryview(bytes(data))
        pos = self.pos
        if pos + len(mv) > self.size and not self.single_track:
            raise ChdError(
                "This CD-type CHD has several tracks, so the patched file "
                "cannot be added to it. Convert it to an ISO first."
            )
        done = 0
        while done < len(mv):
            sector, within = divmod(pos, SECTOR)
            take = min(SECTOR - within, len(mv) - done)
            h, fi = divmod(self.base + sector, self.fph)
            ba = self.overlay.get(h)
            if ba is None:
                ba = bytearray(self._hunk_for_read(h))
                self.overlay[h] = ba
            if self.raw and sector >= self.orig_sectors and sector not in self._inited:
                self._inited.add(sector)
                self._init_raw_frame(ba, fi, sector)
            o = fi * CD_FRAME + self.data_off + within
            ba[o:o + take] = mv[done:done + take]
            pos += take
            done += take
        self.pos = pos
        if pos > self.size:
            self.size = pos
        return len(mv)

    # used by write_chd
    def _sectors(self):
        return -(-self.size // SECTOR)

    def logical_size(self):
        total = self.r.logicalbytes // CD_FRAME
        if self._sectors() > self.orig_sectors:
            frames = self.base + self._sectors()
            total = max(total, -(-frames // 4) * 4)     # tracks are padded to 4 frames
        return total * CD_FRAME

    def adjust_metadata(self, meta):
        grown = self._sectors() - self.orig_sectors
        if grown <= 0:
            return meta
        out = []
        done = False
        for tag, flags, data in meta:
            if not done and tag in (b"CHT2", b"CHTR"):
                text = data.decode("latin-1")
                if re.search(r"TRACK:1\b", text):
                    m = re.search(r"FRAMES:(\d+)", text)
                    if m:
                        text = text[:m.start(1)] + str(int(m.group(1)) + grown) + text[m.end(1):]
                        data = text.encode("latin-1")
                        done = True
            out.append((tag, flags, data))
        return out


def open_image(reader):
    """Returns the right file-like disc view for the CHD kind."""
    if reader.kind == "cd":
        return ChdCdImage(reader)
    return ChdImage(reader)


# --------------------------------------------------------------------------
# writer
# --------------------------------------------------------------------------

def _encode_map(entries, hunkbytes, firstoffs, old_info):
    """entries: list of (type, length, crc, selfidx) with base types only."""
    n = len(entries)
    maxlen = max([e[1] for e in entries if e[0] <= C_NONE] + [1])
    lengthbits = max(maxlen.bit_length(), old_info[0] if old_info else 0, 1)
    selfbits = max(n.bit_length(), old_info[1] if old_info else 0, 1)
    parentbits = old_info[2] if old_info else 0

    bw = _BitWriter()
    # Huffman tree: all 16 symbols with 4-bit codes (code value == symbol).
    for _ in range(16):
        bw.write(4, 4)
    for t, _l, _c, _s in entries:
        bw.write(t, 4)
    raw_map = bytearray()
    cur = firstoffs
    for t, length, crc, selfidx in entries:
        if t <= C_TYPE_3:
            bw.write(length, lengthbits)
            bw.write(crc, 16)
            offset = cur
            cur += length
        elif t == C_NONE:
            bw.write(crc, 16)
            offset = cur
            length = hunkbytes
            cur += length
        elif t == C_SELF:
            bw.write(selfidx, selfbits)
            offset = selfidx
            length = 0
            crc = 0
        else:
            raise ChdError("internal: unsupported entry type")
        raw_map += bytes([t]) + length.to_bytes(3, "big") + offset.to_bytes(6, "big") + crc.to_bytes(2, "big")
    body = bw.finish()
    head = bytearray(16)
    struct.pack_into(">I", head, 0, len(body))
    head[4:10] = firstoffs.to_bytes(6, "big")
    struct.pack_into(">H", head, 10, crc16(raw_map))
    head[12] = lengthbits
    head[13] = selfbits
    head[14] = parentbits
    return bytes(head) + body


def write_chd(reader, image, out_path):
    """
    Writes a new CHD at out_path: the disc described by `image` (the original
    plus its in-memory changes). Unchanged hunks are copied raw.
    """
    hb = reader.hunkbytes
    new_logical = image.logical_size()
    new_count = -(-new_logical // hb)
    if new_count < reader.hunkcount:
        raise ChdError("Internal error: the image shrank.")
    modified = set(image.overlay)

    plan = []
    for i in range(new_count):
        if i in modified or i >= reader.hunkcount:
            plan.append(("mem", i))
            continue
        t, length, offset, crc = reader.entries[i]
        if t == C_SELF:
            if offset in modified:
                plan.append(("orig", i))      # content must stay as it was
            else:
                plan.append(("self", offset))
        else:
            plan.append(("copy", t, length, offset, crc))

    def hunk_bytes(kind, i):
        if kind == "mem":
            return bytes(image.overlay[i]) if i in image.overlay else bytes(hb)
        return reader.read_hunk(i)

    entries = []
    for item in plan:
        kind = item[0]
        if kind in ("mem", "orig"):
            entries.append((C_NONE, hb, crc16(hunk_bytes(kind, item[1])), 0))
        elif kind == "self":
            entries.append((C_SELF, 0, 0, item[1]))
        else:
            _k, t, length, _offset, crc = item
            entries.append((t, length, crc, 0))

    meta = image.adjust_metadata(reader.read_metadata())

    header = bytearray(reader.header)
    struct.pack_into(">Q", header, 32, new_logical)

    with open(out_path, "wb") as out:
        out.write(bytes(HEADER_LEN))

        if reader.compressed:
            mapblob = _encode_map(entries, hb, 0, reader.map_info)
            firstoffs = HEADER_LEN + len(mapblob)
            mapblob = _encode_map(entries, hb, firstoffs, reader.map_info)
            # map size does not depend on firstoffs, so the layout is stable
            if HEADER_LEN + len(mapblob) != firstoffs:
                raise ChdError("Internal error: map layout changed.")
            out.write(mapblob)
            data_start = firstoffs
        else:
            map_len = 4 * new_count
            data_start = -(-(HEADER_LEN + map_len) // hb) * hb
            offs = []
            nxt = data_start
            for _ in range(new_count):
                offs.append(nxt // hb)
                nxt += hb
            out.write(struct.pack(">%dI" % new_count, *offs))
            out.write(bytes(data_start - HEADER_LEN - map_len))

        src = reader.f
        run_src = run_len = 0

        def flush_run():
            nonlocal run_src, run_len
            if run_len:
                src.seek(run_src)
                left = run_len
                while left:
                    chunk = src.read(min(left, 8 * 1024 * 1024))
                    if not chunk:
                        raise ChdError("The source CHD is truncated.")
                    out.write(chunk)
                    left -= len(chunk)
            run_src = run_len = 0

        for item in plan:
            kind = item[0]
            if kind == "self":
                continue
            if kind == "copy" and reader.compressed:
                _k, _t, length, offset, _crc = item
                if run_len and offset == run_src + run_len:
                    run_len += length
                else:
                    flush_run()
                    run_src, run_len = offset, length
                continue
            flush_run()
            if kind == "copy":      # uncompressed CHD: whole hunk
                _k, _t, length, offset, _crc = item
                src.seek(offset)
                out.write(src.read(hb))
            else:
                out.write(hunk_bytes(kind, item[1]))
        flush_run()

        meta_pos = 0
        if meta:
            meta_pos = out.tell()
            pos = meta_pos
            for k, (tag, flags, data) in enumerate(meta):
                nxt = pos + 16 + len(data) if k + 1 < len(meta) else 0
                out.write(tag + bytes([flags]) + len(data).to_bytes(3, "big")
                          + struct.pack(">Q", nxt) + data)
                pos += 16 + len(data)

        struct.pack_into(">Q", header, 40, HEADER_LEN)
        struct.pack_into(">Q", header, 48, meta_pos)
        out.seek(0)
        out.write(bytes(header))
        out.flush()
