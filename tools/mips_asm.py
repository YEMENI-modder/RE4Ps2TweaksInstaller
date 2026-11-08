"""
Tiny two-pass MIPS (little endian) assembler - just the instructions the
Arabic text renderer needs. Output words are checked against capstone in
tools/build_arabic_dados.py, and the routine is executed in an emulator
(unicorn) by the same script, so the encoder can not silently drift.

Supported: addiu, addu, subu, or, sll, srl, andi, ori, lui, lw, lhu, lbu, sw,
sb, sltiu, beq, bne, j, jal, jr, nop, .word
"""
import struct

REGS = {n: i for i, n in enumerate(
    "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split())}


def _r(x):
    return REGS[x.lstrip("$")]


def _imm(x, labels=None, pc=None):
    return int(x, 0)


def _mem(arg):
    off, base = arg.rstrip(")").split("(")
    return int(off, 0), _r(base)


def assemble(lines, base):
    """lines: list of strings ('label:' or 'op args'). Returns bytes."""
    items = []          # (kind, text)
    labels = {}
    pc = base
    for raw in lines:
        s = raw.split("#")[0].strip()
        if not s:
            continue
        if s.endswith(":"):
            labels[s[:-1]] = pc
            continue
        items.append((pc, s))
        pc += 4

    def target(x):
        return labels[x] if x in labels else int(x, 0)

    out = bytearray()
    for pc, s in items:
        op, _, rest = s.partition(" ")
        a = [t.strip() for t in rest.split(",")] if rest.strip() else []
        w = None
        if op == ".word":
            w = int(a[0], 0)
        elif op == "nop":
            w = 0
        elif op in ("addiu", "andi", "ori", "sltiu"):
            code = {"addiu": 0x09, "andi": 0x0C, "ori": 0x0D, "sltiu": 0x0B}[op]
            w = code << 26 | _r(a[1]) << 21 | _r(a[0]) << 16 | (int(a[2], 0) & 0xFFFF)
        elif op == "lui":
            w = 0x0F << 26 | _r(a[0]) << 16 | (int(a[1], 0) & 0xFFFF)
        elif op in ("lw", "lhu", "lbu", "sw", "sb"):
            code = {"lw": 0x23, "lhu": 0x25, "lbu": 0x24, "sw": 0x2B, "sb": 0x28}[op]
            off, b = _mem(a[1])
            w = code << 26 | b << 21 | _r(a[0]) << 16 | (off & 0xFFFF)
        elif op in ("addu", "subu", "or"):
            fn = {"addu": 0x21, "subu": 0x23, "or": 0x25}[op]
            w = _r(a[1]) << 21 | _r(a[2]) << 16 | _r(a[0]) << 11 | fn
        elif op in ("sll", "srl"):
            fn = {"sll": 0x00, "srl": 0x02}[op]
            w = _r(a[1]) << 16 | _r(a[0]) << 11 | (int(a[2], 0) & 31) << 6 | fn
        elif op in ("beq", "bne"):
            code = 4 if op == "beq" else 5
            off = (target(a[2]) - (pc + 4)) >> 2
            assert -0x8000 <= off < 0x8000
            w = code << 26 | _r(a[0]) << 21 | _r(a[1]) << 16 | (off & 0xFFFF)
        elif op in ("j", "jal"):
            t = target(a[0])
            w = (2 if op == "j" else 3) << 26 | ((t >> 2) & 0x3FFFFFF)
        elif op == "jr":
            w = _r(a[0]) << 21 | 0x08
        else:
            raise ValueError("unsupported: " + s)
        out += struct.pack("<I", w & 0xFFFFFFFF)
    return bytes(out), labels
