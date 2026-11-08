"""
Arabic text support data for the Arabic variant: shaping, glyph bitmaps and
the machine code that draws them.

The Menu Tweaks UI draws text with its own routines (in the HUD cave):
  text(a0=string, a1=x, a2=y)  ->  glyph(a0=char, ...) per byte
  glyph: Latin only, 3x5 pixel font, one 2x2 'rect' per lit pixel.
The Arabic variant adds ar_text/ar_glyph in unused space of the Files Used
segment. Bytes >= 0x80 select a pre-shaped Arabic glyph form, drawn as a few
filled rectangles through the SAME rect routine; everything below 0x80 still
goes through the original glyph routine.

Build-time only deps: pillow, arabic-reshaper, python-bidi.
Glyph outlines come from DejaVu Sans Bold (Bitstream Vera / DejaVu license,
which allows embedding) rasterised to 1 bit.
"""
import struct

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from mips_asm import assemble

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SIZE = 14
CELL_X = 8            # glyph origin inside the render canvas
DX_BIAS = 6           # stored dx = x + DX_BIAS  (ink may start left of the origin)
DY_BIAS = 20          # stored dy = row relative to baseline + DY_BIAS
BASELINE_Y = 10       # Latin glyphs span y..y+10; Arabic baseline is aligned to it

RECT, GLYPH = 0x3A57D0, 0x3A5974


def visual(logical):
    """Logical (typed) Arabic -> visual left-to-right string of presentation forms."""
    return get_display(arabic_reshaper.reshape(logical), base_dir="R")


_font = None


def _f():
    global _font
    if _font is None:
        _font = ImageFont.truetype(FONT_PATH, FONT_SIZE, layout_engine=ImageFont.Layout.BASIC)
    return _font


def render_glyph(ch):
    """Return (advance, [(x0, y0_rel_baseline, w, h), ...]) for one presentation form."""
    f = _f()
    adv = int(round(f.getlength(ch)))
    W, H = adv + 2 * CELL_X, FONT_SIZE * 3
    base = FONT_SIZE * 2
    im = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(im)
    d.fontmode = "1"
    d.text((CELL_X, base), ch, font=f, anchor="ls", fill=1)
    px = im.load()
    rows = [[1 if px[x, y] else 0 for x in range(W)] for y in range(H)]
    rows.append([0] * W)
    open_, out = {}, []
    for y, row in enumerate(rows):
        runs, x = set(), 0
        while x < W:
            if row[x]:
                s = x
                while x < W and row[x]:
                    x += 1
                runs.add((s, x))
            else:
                x += 1
        for key in list(open_):
            if key not in runs:
                ys = open_.pop(key)
                out.append((key[0] - CELL_X, ys - base, key[1] - key[0], y - ys))
        for key in runs:
            open_.setdefault(key, y)
    out.sort(key=lambda r: (r[1], r[0]))
    return adv, out


def build_font(chars, font_va):
    """chars: sorted list of presentation-form characters. Returns (blob, index_by_char)."""
    n = len(chars)
    assert n <= 127, "too many glyph forms for codes 0x80-0xFF"
    table, data, index = bytearray(), bytearray(), {}
    base = 4 * n
    for i, ch in enumerate(chars):
        adv, rects = render_glyph(ch)
        index[ch] = 0x80 + i
        table += struct.pack("<HBB", base + len(data), adv, len(rects))
        for x0, y0, w, h in rects:
            dx, dy = x0 + DX_BIAS, y0 + DY_BIAS
            assert 0 <= dx < 256 and 0 <= dy < 256 and 0 < w < 256 and 0 < h < 256, (ch, x0, y0, w, h)
            data += bytes((dx, dy, w, h))
    return bytes(table + data), index


def build_code(code_va, font_va, n_glyphs):
    """ar_text / ar_glyph. Only touches t0-t4, a0-a3 (and s1, restored) like the original."""
    hi, lo = font_va >> 16, font_va & 0xFFFF
    assert lo < 0x8000
    src = f"""
ar_text:
  addiu sp, sp, -0x20
  .word 0xffbf0000
  sw a0, 8(sp)
t_loop:
  lw t0, 8(sp)
  lbu a0, 0(t0)
  beq a0, zero, t_end
  nop
  addiu t0, t0, 1
  sw t0, 8(sp)
  sltiu t1, a0, 0x80
  beq t1, zero, t_arab
  nop
  jal {GLYPH:#x}
  nop
  j t_loop
  nop
t_arab:
  jal ar_glyph
  nop
  j t_loop
  nop
t_end:
  .word 0xdfbf0000
  addiu sp, sp, 0x20
  jr ra
  nop
ar_glyph:
  addiu sp, sp, -0x30
  .word 0xffbf0000
  sw a1, 8(sp)
  sw a2, 0xc(sp)
  sw s1, 0x10(sp)
  addiu t0, a0, -0x80
  sltiu t1, t0, {n_glyphs}
  beq t1, zero, g_end_adv
  nop
  sll t0, t0, 2
  lui t1, {hi:#x}
  addiu t1, t1, {lo:#x}
  addu t0, t0, t1
  lhu t2, 0(t0)
  lbu t3, 2(t0)
  lbu t4, 3(t0)
  addu t2, t2, t1
  sw t2, 0x14(sp)
  sw t3, 0x18(sp)
  sw t4, 0x1c(sp)
  lui s1, 0x8100
  addiu s1, s1, -1
g_loop:
  lw t4, 0x1c(sp)
  beq t4, zero, g_end
  nop
  addiu t4, t4, -1
  sw t4, 0x1c(sp)
  lw t2, 0x14(sp)
  lbu t0, 0(t2)
  lbu t1, 1(t2)
  lbu a2, 2(t2)
  lbu a3, 3(t2)
  addiu t2, t2, 4
  sw t2, 0x14(sp)
  lw a0, 8(sp)
  addu a0, a0, t0
  addiu a0, a0, -{DX_BIAS}
  lw a1, 0xc(sp)
  addu a1, a1, t1
  addiu a1, a1, {BASELINE_Y - DY_BIAS}
  jal {RECT:#x}
  nop
  j g_loop
  nop
g_end:
  lw a1, 8(sp)
  lw t3, 0x18(sp)
  addu a1, a1, t3
  j g_out
  nop
g_end_adv:
  lw a1, 8(sp)
  addiu a1, a1, 8
g_out:
  lw a2, 0xc(sp)
  lw s1, 0x10(sp)
  .word 0xdfbf0000
  addiu sp, sp, 0x30
  jr ra
  nop
"""
    code, labels = assemble(src.strip().splitlines(), code_va)
    return code, labels
