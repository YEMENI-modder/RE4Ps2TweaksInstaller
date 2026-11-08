"""
iso_handler.py
---------------
Responsible for: opening a PS2 ISO (ISO9660), auto-detecting the region
(SLES/SLUS/SLPM) by scanning the root for the boot executable, extracting
that executable to a temp file, and finally re-injecting the patched
executable back into the ISO in-place.

How the patched executable gets back into the ISO:
The Menu Tweaks patch usually makes the executable LARGER (the Files Used
extension appends a new ELF segment). The ISO is therefore never rebuilt;
instead the new executable is appended after the last sector of a COPY of
the image and only its directory record is repointed, so every other file
keeps its sector. If the size happens to be unchanged, the bytes are
simply overwritten at the existing extent.

Two output modes:
  * IN PLACE (output path == source path): the ISO itself is patched, so
    no 4 GB copy is made. Optionally, a pristine backup of the ISO is
    created first as <name>_Og.iso (see make_backup).
  * NEW FILE (output path != source path): a copy is patched and the
    source is left untouched (used when the real path of the picked ISO
    is unknown or not writable).

Language conversion: an executable already patched with one variant
(Portuguese / English / Arabic) can be converted to another because only
two verified blobs differ between the variants (see _swap_language_text).
"""

import os
import json
import shutil
import struct
import hashlib
import tempfile
import importlib.util
import pycdlib


REGION_PREFIXES = ("SLES_", "SLUS_", "SLPM_")


def _load_patch_fn(variant):
    """
    Loads the correct installer_core.patch() for the requested variant.

    Both the "original" and "english" variants ship their OWN complete
    copy of installer_core.py (see get_dados_root's docstring for why).
    We load each copy under a distinct module name so Python doesn't
    confuse the two if both get loaded in the same process (e.g. the
    user patches an "original" ISO then an "english" one in the same
    app session without restarting).
    """
    root = get_dados_root(variant)
    module_name = f"installer_core_{variant}"
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(root, "installer_core.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.patch


def get_dados_root(variant="original"):
    """
    Returns the on-disk root directory patch() should use as its `root`
    argument — the folder containing dados/, FilesUsed.py and
    RemoveWeaponSwap.py — after Chaquopy extracts the app's bundled
    Python sources on first run.

    variant:
      "original" -> the stock Portuguese menu, exactly as shipped with
                    the original Menu Tweaks PS2 (unmodified)
      "english"  -> the community English translation (see
                    dados_en_root/dados/TRANSLATION_NOTE.txt for exactly
                    which files were changed and why 6 specific ones
                    were deliberately left untranslated)

    Both variants are COMPLETE, independent copies of installer_core.py
    + FilesUsed.py + RemoveWeaponSwap.py + dados/ — not a single shared
    installer_core.py with a swapped dados/ folder. This was a
    deliberate choice: it means patch()'s own logic (including its
    hardcoded 'dados' folder name in load()) never has to be touched
    to support both variants, keeping the original, security-relevant
    code 100% byte-identical to the upstream PC tool in both cases.

    This function asks Python itself for the path (via __file__, which
    Chaquopy resolves to the real on-disk extracted location at
    runtime) rather than having the Kotlin side guess Chaquopy's
    internal extraction directory layout, which has changed between
    Chaquopy SDK versions before.
    """
    base = os.path.dirname(os.path.abspath(__file__))
    if variant == "english":
        return os.path.join(base, "dados_en_root")
    if variant == "arabic":
        # Arabic text + font; built by tools/build_arabic_dados.py
        return os.path.join(base, "dados_ar_root")
    return base


VARIANTS = ("original", "english", "arabic")
VARIANT_NAMES = {"original": "Portuguese", "english": "English", "arabic": "Arabic"}


class IsoHandlerError(Exception):
    pass


def find_boot_executable(iso_path):
    """
    Scans the ISO root directory for a file whose name starts with
    SLES_ / SLUS_ / SLPM_ (the PS2 boot executable naming convention).
    Returns (region, iso_internal_path) e.g. ("SLUS", "/SLUS_211.34;1")

    We deliberately do NOT trust SYSTEM.CNF parsing alone as the sole
    source, because some ISOs have been re-mastered with tools that
    leave stale SYSTEM.CNF entries. Scanning the root directly for the
    known filename prefixes is more robust and is what the original
    installer's region argument already assumes.
    """
    iso = pycdlib.PyCdlib()
    iso.open(iso_path)
    try:
        # list the root directory entries (ISO9660 "/" level)
        for child in iso.list_children(iso_path="/"):
            # pycdlib keeps the ;1 version suffix in the identifier
            name = child.file_identifier().decode("utf-8", errors="ignore")
            base = name.split(";")[0]
            for prefix in REGION_PREFIXES:
                if base.startswith(prefix):
                    region = prefix.rstrip("_")
                    return region, "/" + name
        raise IsoHandlerError(
            "No SLES_/SLUS_/SLPM_ boot executable found at ISO root. "
            "This may not be a valid PS2 game ISO, or it uses an "
            "unusual layout this tool doesn't recognize."
        )
    finally:
        iso.close()


def extract_executable(iso_path, iso_internal_path, dest_path):
    """Pulls the boot executable out of the ISO to a plain file on disk."""
    iso = pycdlib.PyCdlib()
    iso.open(iso_path)
    try:
        with open(dest_path, "wb") as f:
            iso.get_file_from_iso_fp(f, iso_path=iso_internal_path)
    finally:
        iso.close()


def get_executable_size_on_iso(iso_path, iso_internal_path):
    iso = pycdlib.PyCdlib()
    iso.open(iso_path)
    try:
        record = iso.get_record(iso_path=iso_internal_path)
        return record.get_data_length()
    finally:
        iso.close()


_SECTOR = 2048


def _find_root_record(f, iso_internal_path):
    """
    Locates a ROOT-level file's ISO9660 directory record by reading the
    raw image (no pycdlib involved), so the record can be patched in place.

    Returns (record_byte_offset, extent_lba, data_length).
    """
    wanted = iso_internal_path.lstrip("/").upper()
    wanted_base = wanted.split(";")[0]

    f.seek(16 * _SECTOR)
    pvd = f.read(_SECTOR)
    if len(pvd) < _SECTOR or pvd[0] != 1 or pvd[1:6] != b"CD001":
        raise IsoHandlerError(
            "Primary Volume Descriptor not found at sector 16; "
            "this does not look like a plain 2048-byte-sector ISO9660 image."
        )

    root = pvd[156:190]
    root_lba = struct.unpack_from("<I", root, 2)[0]
    root_len = struct.unpack_from("<I", root, 10)[0]

    f.seek(root_lba * _SECTOR)
    data = f.read(root_len)

    pos = 0
    while pos < len(data):
        rec_len = data[pos]
        if rec_len == 0:
            # Directory records never cross a sector boundary; padding
            # at the end of a sector is zero, so jump to the next one.
            pos = (pos // _SECTOR + 1) * _SECTOR
            continue
        name_len = data[pos + 32]
        name = data[pos + 33:pos + 33 + name_len].decode("latin-1").upper()
        if name == wanted or name.split(";")[0] == wanted_base:
            lba = struct.unpack_from("<I", data, pos + 2)[0]
            length = struct.unpack_from("<I", data, pos + 10)[0]
            return root_lba * _SECTOR + pos, lba, length
        pos += rec_len

    raise IsoHandlerError(
        f"Could not find {iso_internal_path} in the ISO root directory."
    )


def _has_udf(iso_path):
    """True if the image has a UDF Anchor Volume Descriptor Pointer."""
    try:
        with open(iso_path, "rb") as f:
            f.seek(256 * _SECTOR)
            return f.read(2) == b"\x02\x00"
    except OSError:
        return False


def _inject_by_appending(output_iso_path, iso_internal_path, patched_bytes):
    """
    Used when the patched executable is NOT the same size as the original
    (the FilesUsed extension appends a new ELF segment, so it grows).

    Instead of rebuilding the filesystem (which would move every file and
    can break anything that relies on fixed sector positions), the new
    executable is written after the last sector of the image and only the
    executable's own directory record (extent + length) and the volume
    size in the PVD are updated. Every other file keeps its sector.

    Write order is chosen so that an interruption can never leave the ISO
    pointing at missing data: first the new data (appended), then the PVD
    volume size, and only last the directory record. If anything fails
    before the verification step, the previous record / PVD bytes are
    restored and the appended data is truncated away, which matters when
    this runs directly on the user's only copy of the ISO.
    """
    with open(output_iso_path, "r+b") as f:
        record_off, _old_lba, _old_len = _find_root_record(f, iso_internal_path)

        f.seek(0, os.SEEK_END)
        orig_size = f.tell()

        f.seek(record_off + 2)
        old_record_bytes = f.read(16)
        f.seek(16 * _SECTOR + 80)
        old_pvd_bytes = f.read(8)

        try:
            size = orig_size
            pad = (-size) % _SECTOR
            if pad:
                f.seek(0, os.SEEK_END)
                f.write(bytes(pad))
                size += pad
            new_lba = size // _SECTOR

            f.seek(0, os.SEEK_END)
            f.write(patched_bytes)
            tail = (-len(patched_bytes)) % _SECTOR
            if tail:
                f.write(bytes(tail))

            new_len = len(patched_bytes)
            total_sectors = new_lba + (new_len + _SECTOR - 1) // _SECTOR
            if total_sectors >= 2 ** 32 or new_len >= 2 ** 32:
                raise IsoHandlerError("ISO would exceed the ISO9660 size limits.")
            f.flush()

            # PVD volume space size (both-endian) - only ever grow it.
            f.seek(16 * _SECTOR + 80)
            current_sectors = struct.unpack("<I", f.read(4))[0]
            if total_sectors > current_sectors:
                f.seek(16 * _SECTOR + 80)
                f.write(
                    struct.pack("<I", total_sectors)
                    + struct.pack(">I", total_sectors)
                )
                f.flush()

            # Directory record LAST: extent LBA and data length, both-endian.
            f.seek(record_off + 2)
            f.write(
                struct.pack("<I", new_lba) + struct.pack(">I", new_lba)
                + struct.pack("<I", new_len) + struct.pack(">I", new_len)
            )
            f.flush()
        except BaseException:
            # Roll back to exactly what the file was before this call.
            try:
                f.seek(record_off + 2)
                f.write(old_record_bytes)
                f.seek(16 * _SECTOR + 80)
                f.write(old_pvd_bytes)
                f.truncate(orig_size)
                f.flush()
            except OSError:
                pass
            raise

    # Verify by reading the record back from the file we just wrote.
    with open(output_iso_path, "rb") as f:
        _off, lba, length = _find_root_record(f, iso_internal_path)
        if length != len(patched_bytes):
            raise IsoHandlerError("Verification failed: executable size in ISO is wrong.")
        f.seek(lba * _SECTOR)
        written = f.read(length)
    if hashlib.sha256(written).digest() != hashlib.sha256(patched_bytes).digest():
        raise IsoHandlerError("Verification failed: executable data in ISO does not match.")


def _check_free_bytes(folder, needed):
    folder = folder or "."
    free = shutil.disk_usage(folder).free
    if free < needed:
        raise IsoHandlerError(
            f"Not enough free space in {folder}: need about "
            f"{needed // (1024 * 1024)} MB, only {free // (1024 * 1024)} MB free."
        )


def _same_file(a, b):
    return os.path.abspath(a) == os.path.abspath(b)


def make_backup(iso_path, backup_path):
    """
    Copies the ISO, byte for byte, to backup_path (<name>_Og.iso).

    An existing backup is NEVER overwritten: after a first patch the ISO
    already carries the tweak, so replacing <name>_Og.iso on a later run
    would destroy the only untouched copy. Returns "created" or "exists".

    The copy goes to a .part file first and is renamed only when complete,
    so a half-written file can never be mistaken for a valid backup.
    """
    if os.path.exists(backup_path):
        return "exists"
    folder = os.path.dirname(os.path.abspath(backup_path))
    _check_free_bytes(folder, os.path.getsize(iso_path) + 16 * 1024 * 1024)
    part = backup_path + ".part"
    try:
        shutil.copyfile(iso_path, part)
        os.replace(part, backup_path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return "created"


def _write_executable(target_iso, iso_internal_path, patched_bytes, original_size):
    """Same size: overwrite at the existing extent. Otherwise: append."""
    if len(patched_bytes) == original_size:
        iso = pycdlib.PyCdlib()
        iso.open(target_iso)
        try:
            record = iso.get_record(iso_path=iso_internal_path)
            byte_offset = record.extent_location() * _SECTOR
        finally:
            iso.close()
        with open(target_iso, "r+b") as out:
            out.seek(byte_offset)
            out.write(patched_bytes)
    else:
        _inject_by_appending(target_iso, iso_internal_path, patched_bytes)


def inject_executable(iso_path, iso_internal_path, patched_file_path, output_iso_path):
    """
    Writes patched_file_path into the ISO.

    - output_iso_path == iso_path: the ISO is patched IN PLACE. Only the
      new executable (a few MB) is appended, so no copy of the image is
      made. The file is never deleted on failure; _inject_by_appending
      rolls its own changes back.
    - output_iso_path != iso_path: the ISO is copied to output_iso_path
      first and the copy is patched; the source is never modified, and a
      half-written copy is deleted on failure.

    Same size as the original executable: overwrite the bytes at the
    file's existing extent. Different size (the normal case when the
    FilesUsed extension adds a segment): append at the end of the image
    and repoint its directory record (see _inject_by_appending).
    """
    original_size = get_executable_size_on_iso(iso_path, iso_internal_path)
    patched_size = os.path.getsize(patched_file_path)

    with open(patched_file_path, "rb") as pf:
        patched_bytes = pf.read()

    if _same_file(output_iso_path, iso_path):
        if not os.access(iso_path, os.W_OK):
            raise IsoHandlerError(
                "The ISO is not writable (read-only file or folder). "
                "Grant file access to the app and try again."
            )
        folder = os.path.dirname(os.path.abspath(iso_path))
        _check_free_bytes(folder, patched_size + 16 * 1024 * 1024)
        _write_executable(iso_path, iso_internal_path, patched_bytes, original_size)
        return output_iso_path

    _check_free_bytes(
        os.path.dirname(os.path.abspath(output_iso_path)),
        os.path.getsize(iso_path) + patched_size + 16 * 1024 * 1024,
    )
    try:
        shutil.copyfile(iso_path, output_iso_path)
        _write_executable(output_iso_path, iso_internal_path, patched_bytes, original_size)
    except BaseException:
        # Never leave a half-written copy behind.
        try:
            os.remove(output_iso_path)
        except OSError:
            pass
        raise

    return output_iso_path


def _swap_language_text(data, region, variant):
    """
    If the executable already carries Menu Tweaks text/UI of ANOTHER variant
    (Portuguese, English or Arabic), rewrite just those parts to `variant` so
    the unchanged installer logic recognises the executable as a known
    install and updates it, instead of refusing it as an unknown menu.

    The variants differ in exactly two blobs per tag:
      1. the menu blob (<tag>_menu.bin at the profile's menu_offset): text,
         plus - in the Arabic variant - the redirected text() calls;
      2. the Files Used extension segment (<tag>_files.bin payload): text,
         plus the Arabic renderer and font in its unused code area.
    Each is swapped ONLY on an exact match with the other variant's data
    (menu: every byte where the two variants differ; extension: the whole
    segment, ignoring the 4-byte size field the installer fills in).
    Anything else is left untouched and still goes through the installer's
    own verification, so unknown or foreign data is rejected as before.

    Returns (new_data, list_of_what_was_converted).
    """
    target_root = get_dados_root(variant)
    others = [v for v in VARIANTS if v != variant and os.path.isdir(get_dados_root(v))]

    def load(root, name):
        with open(os.path.join(root, "dados", name), "rb") as f:
            return f.read()

    buf = bytearray(data)
    converted = []
    tags = [region, region + "_alternativo"]

    # 1) menu blob
    for tag in tags:
        try:
            p = json.loads(load(target_root, tag + ".json"))
            mo, ms = p["menu_offset"], p["menu_size"]
            tgt = load(target_root, tag + "_menu.bin")
        except (OSError, KeyError, ValueError):
            continue
        if mo < 0 or mo + ms > len(buf) or len(tgt) != ms:
            continue
        for other in others:
            try:
                oth = load(get_dados_root(other), tag + "_menu.bin")
            except OSError:
                continue
            if len(oth) != ms:
                continue
            diff = [i for i in range(ms) if tgt[i] != oth[i]]
            if diff and all(buf[mo + i] == oth[i] for i in diff):
                for i in diff:
                    buf[mo + i] = tgt[i]
                converted.append("menu")
                break

    # 2) Files Used extension segment
    if len(buf) >= 64:
        ph = struct.unpack_from("<I", buf, 28)[0]
        stride, count = struct.unpack_from("<HH", buf, 42)
        for tag in tags:
            try:
                p = json.loads(load(target_root, tag + ".json"))
                cp = p["files_used"]
                ftag = region + ("_alternativo" if p["menu_offset"] < 0x2A0000 else "")
                tgt = load(target_root, ftag + "_files.bin")
            except (OSError, KeyError, ValueError):
                continue
            for i in range(count if 0 < count < 128 and stride >= 32 else 0):
                at = ph + i * stride
                if at + 32 > len(buf):
                    break
                t, fo, va, _pa, fs, _ms, _fl, _al = struct.unpack_from("<8I", buf, at)
                if (t != 1 or va != cp["base"] or fs != cp["filesz"]
                        or fo + fs > len(buf) or len(tgt) != fs):
                    continue
                blob = bytearray(buf[fo:fo + fs])
                core = bytes(blob[0x2010:0x2014])      # size field set by the installer
                blob[0x2010:0x2014] = bytes(4)
                for other in others:
                    try:
                        oth = load(get_dados_root(other), ftag + "_files.bin")
                    except OSError:
                        continue
                    if len(oth) == fs and bytes(blob) == oth:
                        new = bytearray(tgt)
                        new[0x2010:0x2014] = core
                        buf[fo:fo + fs] = new
                        converted.append("files")
                        break

    return bytes(buf), converted


def _success_message(region, old_size, new_size, output_iso_path, converted_to=None,
                     in_place=False, backup_path=None, backup_status=None):
    msg = f"Patched successfully as {region}.\n"
    if converted_to:
        msg += f"The tweak already in this ISO was converted to the {converted_to} menu text.\n"
    if old_size != new_size:
        msg += (
            f"The executable grew from {old_size} to {new_size} bytes, so it "
            "was stored at the end of the ISO; all other files stayed where "
            "they were.\n"
        )
        if _has_udf(output_iso_path):
            msg += (
                "Note: this image also has a UDF table, which was not updated "
                "(PS2 emulators read the ISO9660 table, so this is normally fine).\n"
            )
    if in_place:
        if backup_status == "created":
            msg += f"Backup of the ISO as it was before patching:\n{backup_path}\n"
        elif backup_status == "exists":
            msg += (
                f"A backup already exists, so it was kept untouched:\n{backup_path}\n"
            )
        else:
            msg += "No backup was made.\n"
        return msg + f"Patched in place:\n{output_iso_path}"
    return msg + f"Saved to:\n{output_iso_path}"


def run_full_patch(iso_path, output_iso_path, variant="original", region_override=None,
                   backup_path=None):
    """
    High-level orchestration called from Kotlin via Chaquopy, e.g.:

        from com.chaquo.python import Python
        val py = Python.getInstance()
        val result = py.getModule("iso_handler").callAttr(
            "run_full_patch", isoPath, outputIsoPath, "english"
        )

    variant: "original" (stock Portuguese menu text), "english" or "arabic"
    (community translation — see get_dados_root() docstring). Defaults
    to "original" so existing calls from before this option existed
    keep working unchanged.

    region_override: pass "SLES"/"SLUS"/"SLPM" to force a region instead
    of auto-detecting from the ISO root. Useful for ISOs with unusual
    filenames, or for advanced users who know their region already.

    output_iso_path: pass the SAME path as iso_path to patch the ISO in
    place. Anything else patches a copy saved at that path.

    backup_path: only used for in-place patching. If given, the untouched
    ISO is copied there (e.g. Re4_Og.iso) BEFORE it is modified, unless a
    file already exists at that path (it is never overwritten). Pass None
    to patch without a backup.

    Returns a dict with status info for the Kotlin side to display.
    """
    tmp_dir = tempfile.mkdtemp(prefix="re4tweaks_")
    try:
        detected_region, iso_internal_path = find_boot_executable(iso_path)
        region = region_override if region_override else detected_region

        extracted_path = os.path.join(tmp_dir, "extracted_elf")
        extract_executable(iso_path, iso_internal_path, extracted_path)

        with open(extracted_path, "rb") as f:
            data = f.read()

        # Convert a tweak installed in the other language first (no-op otherwise).
        data, converted = _swap_language_text(data, region, variant)

        dados_root = get_dados_root(variant)
        patch_fn = _load_patch_fn(variant)
        result_bytes, serial = patch_fn(data, region, dados_root)

        patched_path = os.path.join(tmp_dir, "patched_elf")
        with open(patched_path, "wb") as f:
            f.write(result_bytes)

        # Everything that can fail on the data itself (region check, hash
        # verification, patch) has run by now, so the ISO is only touched
        # once we know the patched executable is good.
        in_place = _same_file(iso_path, output_iso_path)
        backup_status = None
        if in_place and backup_path:
            backup_status = make_backup(iso_path, backup_path)

        inject_executable(iso_path, iso_internal_path, patched_path, output_iso_path)

        return {
            "ok": True,
            "region": region,
            "serial": serial,
            "output_iso": output_iso_path,
            "backup_iso": backup_path if backup_status else None,
            "message": _success_message(
                region, len(data), len(result_bytes), output_iso_path,
                converted_to=VARIANT_NAMES.get(variant, variant) if converted else None,
                in_place=in_place, backup_path=backup_path, backup_status=backup_status,
            ),
        }
    except IsoHandlerError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        # Surface the original installer's own ValueError messages
        # (region mismatch, Parry conflict, corrupted data, etc.) as-is,
        # since those are already written to be user-facing in Portuguese.
        return {"ok": False, "error": str(e)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
