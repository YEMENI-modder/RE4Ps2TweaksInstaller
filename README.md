# RE4 Tweaks PS2 Installer (Android)

**English** | [العربية](README.ar.md)

**Version 1.0.1**

[![Stars](https://img.shields.io/github/stars/YEMENI-modder/RE4Ps2TweaksInstaller?style=for-the-badge&logo=github)](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/stargazers)
[![Downloads](https://img.shields.io/github/downloads/YEMENI-modder/RE4Ps2TweaksInstaller/total?style=for-the-badge&logo=android&label=Downloads)](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/releases/tag/V1)
[![Build](https://img.shields.io/github/actions/workflow/status/YEMENI-modder/RE4Ps2TweaksInstaller/build.yml?style=for-the-badge&label=Build)](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/actions)

An Android app that installs the **RE4 Menu Tweaks PS2** into your own Resident Evil 4
(PS2) game image (**ISO or CHD**), entirely on your phone. No PC, no Winlator, no `.bat`
file: pick the image, pick a menu language, tap *Apply patch*.

It reads the image, extracts the boot executable, applies the tweak with the original
installer's own verification and patch logic, and writes the result back into the image.

> This is only an installer wrapper. The tweak itself is the work of its original
> authors, see [Credits](#credits).

## Features

- **Supports ISO and CHD.** Pick either one, the app detects the type
  automatically. See [CHD support](#chd-support).
- **Patches the ISO in place.** `Re4.iso` stays `Re4.iso`. No second 4 GB file, and
  only the new executable (a few MB) is written.
- **Automatic backup (on by default).** Before patching, your untouched ISO is copied
  to `Re4_Og.iso` next to it. You can switch it off in step 3. An existing `_Og` file is
  never overwritten, so patching again can't destroy your clean copy.
- **Safe writing.** The patch is fully computed and verified before the ISO is touched,
  and if writing fails the ISO is rolled back to exactly what it was.
- **Region auto-detection** (SLES / SLUS / SLPM) from the boot executable at the image root.
- **Three menu languages:** Portuguese (original), English, Arabic.
- **Language conversion.** An ISO that already carries the tweak in another language is
  converted to the one you pick, in any direction.
- **App in English and Arabic** (with RTL), switchable from the top bar.

## How to use

1. Install the APK (see [Releases](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/releases) or [build it yourself](#building-from-source)).
2. Open the app, allow file access when asked, and tap **Select ISO** (an `.iso` or a `.chd`).
3. Choose the menu language: Portuguese, English or Arabic.
4. Leave **Create a backup** on (recommended) and tap **Apply patch**.

When it finishes, `Re4.iso` contains the tweak and `Re4_Og.iso` is your original
(the same applies to `Re4.chd` / `Re4_Og.chd`).

If the app can't get write access to the ISO's real location (for example, file access
was not granted), it leaves your ISO untouched and saves a patched copy to
`Download/<name>_Patched.iso` (or `.chd`) instead.

You need your own legally obtained ISO. No game files are included in this repository.

## CHD support

CHD files work just like ISOs: pick the `.chd`, choose a language, tap *Apply patch*.
No conversion needed.

- Only **DVD-type CHDs** are supported (the kind made by `chdman createdvd`, which is what
  PS2 games use). If a CHD can't be read, the app tells you why; converting it to an ISO
  always works as a fallback.
- The result is saved in the same file, with the same backup option as ISOs. Patching a
  CHD takes longer than an ISO and needs free space of up to about **3x the CHD's size**
  while it works (original + backup + temporary file); the temporary file is removed when
  it finishes.
- CHD support is new. Keep **Create a backup** on and report any problem you run into.

## Menu variants

| Variant | What it is |
|---|---|
| **Original** | The stock Portuguese menu, exactly as shipped by the tweak's authors. |
| **English** | Full English translation of the menu text (tabs, options, colors, weapons, outfits...). Only text strings were changed, no code, offsets or hooks. Details, including the files deliberately left untranslated, are in [`TRANSLATION_NOTE.txt`](app/src/main/python/dados_en_root/dados/TRANSLATION_NOTE.txt). |
| **Arabic** | Arabic menu text, drawn by a small Arabic renderer placed in unused space of the Files Used code area (the menu uses its own pixel font, so the game's fonts are untouched). Text is pre-shaped and stored in visual order. Where an Arabic phrase doesn't fit its fixed-size slot, English is used. |

## How it works

- **Kotlin**: UI, file picking, background work.
- **Python** via [Chaquopy](https://chaquo.com/chaquopy/): the patch logic, taken from the
  original installer without modification.
- **[pycdlib](https://github.com/clalancette/pycdlib)**: reading the ISO9660 filesystem.
- **`chd_handler.py`**: reading and rewriting CHD images.

The patch usually makes the executable larger (the Files Used extension adds a segment).
Rather than rebuilding the filesystem, which would move every file, the new executable is
appended after the last sector and only its directory record (and the volume size) is
updated. Every other file keeps its sector. If the size is unchanged, the bytes are simply
overwritten at the existing location. The result is verified by reading it back.

Each menu variant ships as a complete, independent copy of the installer logic
(`installer_core.py`, `FilesUsed.py`, `RemoveWeaponSwap.py`, `dados/`) instead of one
shared copy with swapped data, so the original patch code stays byte-identical to the
upstream PC tool in every variant.

Implementation notes live in the code itself:
`app/src/main/python/iso_handler.py`, `app/src/main/python/chd_handler.py` and
`app/src/main/java/com/yemeni/re4tweaksinstaller/MainActivity.kt`.

## Building from source

### Requirements

| Tool | Version |
|---|---|
| JDK | 17 |
| Android SDK | Platform 34 (`compileSdk 34`), minSdk 24 |
| Python | On your `PATH` (CI uses 3.11); Chaquopy runs it at build time to fetch `pycdlib` |
| Internet | The first build downloads Gradle, the Android Gradle Plugin and Chaquopy (`chaquo.com/maven`) |

The Gradle wrapper (8.4) is included, so you don't need to install Gradle.

### Android Studio

1. **File > Open** and select the project folder.
2. Let Gradle sync finish (Android Studio offers to install a missing SDK platform).
3. Select the `app` configuration and press **Run**, or use **Build > Build APK(s)**.

### Command line

```bash
# Linux / macOS
./gradlew assembleDebug

# Windows
gradlew.bat assembleDebug
```

The APK is written to `app/build/outputs/apk/debug/app-debug.apk`.

If Gradle can't find the Android SDK, create a `local.properties` file in the project root:

```properties
sdk.dir=/path/to/Android/sdk
```

### GitHub Actions

`.github/workflows/build.yml` builds the debug APK on every push to `main` and on manual
runs (**Actions** tab, *Run workflow*), then publishes it as a zip in the `build-test`
release.

### Notes

- Debug builds are signed with Gradle's debug keystore. That's fine for installing on your
  own device; a public release would need its own signing configuration (none is set up
  in this repository).
- `arm64-v8a` and `armeabi-v7a` are bundled.

## Project layout

```
app/src/main/java/.../MainActivity.kt    UI and orchestration
app/src/main/python/iso_handler.py       ISO/CHD reading, backup, injection
app/src/main/python/chd_handler.py       CHD v5 reader / writer
app/src/main/python/installer_core.py    original patch logic (Portuguese menu)
app/src/main/python/dados/               original data files
app/src/main/python/dados_en_root/       English variant (full copy)
app/src/main/python/dados_ar_root/       Arabic variant (full copy)
tools/                                   scripts that generate the English / Arabic data
```

## Rebuilding the translations

The English and Arabic data files are generated by the scripts in `tools/`, so the
translations can be reviewed and corrected at the source. Run from the repository root:

```bash
python3 tools/build_english_dados.py
python3 tools/build_arabic_dados.py [--preview out.png]
```

The Arabic script needs `pillow`, `arabic-reshaper` and `python-bidi`, plus `unicorn` and
`capstone` for its self-test. The scripts also update the SHA-256 values in the profile
JSON files, because the installer refuses data whose hash doesn't match.

## Credits

**Menu Tweaks PS2** (Enemy HP, Memory Viewer, Free Camera, Cheats and more) is **not** the
work of this repository's owner. This project is only an installer wrapper around the
original modding team's work. The following YouTube channels are known in the RE4 PS2
modding community for publishing and covering the tweak, and are credited here out of
respect for their work:

- https://youtube.com/@dn_e_voce
- https://youtube.com/@hardrainmodder
- https://youtube.com/@eusoujeffgamers
- https://youtube.com/@o_ceifeiro_x
- https://youtube.com/@walymodder
- https://youtube.com/@herikre4ps2

Original tweak download / showcase video: https://youtu.be/Sn5NMTdCEzw

### Special thanks

- **q8tp1**: for discovering a bug in the app.
- **scorpion**: for sharing the app, testing it and suggesting CHD support.
- **Ahmed | Weto**: for trying the beta version and finding issues.

The same credits are shown inside the app.

### AI transparency

The code of this project was designed and written entirely by **Claude** (Anthropic's AI
assistant), including the Android app, the ISO handling and backup logic, the Arabic
renderer and translation tools, the GitHub Actions build, and this README. **YEMENI**
directed the work with technical instructions and reviews, made the design decisions,
and built and tested the app on real devices.

- Project owner, direction and testing: **YEMENI** ([github.com/YEMENI-modder](https://github.com/YEMENI-modder))
- English and Arabic menu translations: **YEMENI**

If you are one of the original tweak's developers (or know their confirmed identity) and
want a credit corrected, a license added, or this project taken down, please open an
[Issue](https://github.com/YEMENI-modder/RE4Ps2TweaksInstaller/issues) on this repository.

## License

No license has been set for this repository yet. The rights to the original tweak's files
(`app/src/main/python/dados/`, `dados_en_root/`, `dados_ar_root/` and their accompanying
`.py` files) belong to their original authors, and no license information came with them.
This is pending clarification from the true source.
