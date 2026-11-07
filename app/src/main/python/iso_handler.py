"""
iso_handler.py
---------------
Responsible for: opening a PS2 ISO (ISO9660), auto-detecting the region
(SLES/SLUS/SLPM) by scanning the root for the boot executable, extracting
that executable to a temp file, and finally re-injecting the patched
executable back into the ISO in-place.

Why in-place injection works here (and why it's fast):
PS2 .bin patches produced by Instalar-Portatil.py are the SAME SIZE as the
original executable (the tool only overwrites existing zero-padding /
known regions, it never appends data). That means we never need to
rebuild the whole ISO9660 filesystem — we can seek directly to the file's
extent on disk and overwrite those bytes. This avoids reimplementing a
full ISO9660 writer and is the main reason this stays simple.

If pycdlib reports a size mismatch (patched data longer than original),
we refuse and surface a clear error rather than silently corrupting the
disc layout.
"""

import os
import shutil
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
      "original" -> the stock Portuguese menu (PLAGA... no wait, just
                    the original Menu Tweaks PS2 text, unmodified)
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
    return base


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


def inject_executable(iso_path, iso_internal_path, patched_file_path, output_iso_path):
    """
    Writes patched_file_path's bytes back into output_iso_path at the
    exact same ISO location as iso_internal_path originally occupied.

    Strategy: copy the whole ISO byte-for-byte first (fast, it's a single
    file copy), then use pycdlib in read-write ("rw") mode is not
    reliably supported across pycdlib versions for raw byte overwrites,
    so instead we:
      1. Copy iso_path -> output_iso_path
      2. Re-open output_iso_path with pycdlib to find the *physical*
         byte offset of the file's extent on disc
      3. Open output_iso_path in r+b mode and overwrite those bytes
         directly — this is safe ONLY because size matches exactly.
    """
    original_size = get_executable_size_on_iso(iso_path, iso_internal_path)
    patched_size = os.path.getsize(patched_file_path)

    if patched_size != original_size:
        raise IsoHandlerError(
            f"Patched executable size ({patched_size} bytes) does not match "
            f"the original on-disc size ({original_size} bytes). "
            "In-place injection requires an exact size match; refusing to "
            "avoid corrupting the ISO layout. This should not normally "
            "happen with Menu Tweaks patches — check that the correct "
            "source executable was used."
        )

    shutil.copyfile(iso_path, output_iso_path)

    iso = pycdlib.PyCdlib()
    iso.open(output_iso_path)
    try:
        record = iso.get_record(iso_path=iso_internal_path)
        # extent_location() returns the logical block number; ISO9660
        # logical blocks are 2048 bytes each.
        extent_lba = record.extent_location()
        byte_offset = extent_lba * 2048
    finally:
        iso.close()

    with open(patched_file_path, "rb") as pf:
        patched_bytes = pf.read()

    with open(output_iso_path, "r+b") as out:
        out.seek(byte_offset)
        out.write(patched_bytes)

    return output_iso_path


def run_full_patch(iso_path, output_iso_path, variant="original", region_override=None):
    """
    High-level orchestration called from Kotlin via Chaquopy, e.g.:

        from com.chaquo.python import Python
        val py = Python.getInstance()
        val result = py.getModule("iso_handler").callAttr(
            "run_full_patch", isoPath, outputIsoPath, "english"
        )

    variant: "original" (stock Portuguese menu text) or "english"
    (community translation — see get_dados_root() docstring). Defaults
    to "original" so existing calls from before this option existed
    keep working unchanged.

    region_override: pass "SLES"/"SLUS"/"SLPM" to force a region instead
    of auto-detecting from the ISO root. Useful for ISOs with unusual
    filenames, or for advanced users who know their region already.

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

        dados_root = get_dados_root(variant)
        patch_fn = _load_patch_fn(variant)
        result_bytes, serial = patch_fn(data, region, dados_root)

        patched_path = os.path.join(tmp_dir, "patched_elf")
        with open(patched_path, "wb") as f:
            f.write(result_bytes)

        inject_executable(iso_path, iso_internal_path, patched_path, output_iso_path)

        return {
            "ok": True,
            "region": region,
            "serial": serial,
            "output_iso": output_iso_path,
            "message": f"Patched successfully as {region}. Output: {output_iso_path}",
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
