#!/usr/bin/env python3
"""
Builds the Arabic variant: app/src/main/python/dados_ar_root

 - copies the installer code from the English variant (byte-identical) and
   the Portuguese originals of every data file,
 - rewrites <tag>_menu.bin and <tag>_files.bin for all six tags:
     * UI strings -> Arabic (pre-shaped, visual order, glyph codes >= 0x80)
       or English where the slot is too short,
     * every `jal text` is redirected to ar_text,
     * ar_text/ar_glyph + the Arabic font go into the unused part of the
       Files Used code area (between 'used' and 'state'),
 - updates the two SHA-256 values per profile JSON that vouch for those files.

Run from the repo root:  python3 tools/build_arabic_dados.py [--preview out.png]
Needs: pillow arabic-reshaper python-bidi unicorn capstone (the last two only
for the self-test).
"""
import hashlib
import json
import os
import re
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import arabic_font as AF
from build_english_dados import TR as EN_TR, TAGS

PY = os.path.join("app", "src", "main", "python")
SRC = os.path.join(PY, "dados")
EN_ROOT = os.path.join(PY, "dados_en_root")
AR_ROOT = os.path.join(PY, "dados_ar_root")
DST = os.path.join(AR_ROOT, "dados")

TEXT_VA = 0x3A5A78
CODE_VA = 0x4B0D00
GAP_END = 0x4B1F00          # 'state' starts at 0x4B2000; keep a margin

# Logical Arabic text. Anything not listed here (or too long for its slot) falls
# back to the English text. Latin tokens must be UPPERCASE (the Latin font is A-Z).
AR = {
    "CAMERA LIVRE": "كاميرا حرة",
    "USADO:": "مستخدم",
    "LIVRE:": "متاح:",
    "CONFIGURACOES": "الإعدادات",
    "HP DOS INIMIGOS": "صحة الأعداء",
    "EXIBIR BARRA": "إظهار الشريط",
    "TAMANHO DO HUD": "حجم الواجهة",
    "SETAS: SELECIONAR / AJUSTAR": "الأسهم: اختيار / ضبط",
    "PREVIA": "معاينة",
    "LIGADO": "تشغيل",
    "DESLIGADO": "إيقاف",
    "X CONFIRMAR": "X تأكيد",
    "O VOLTAR": "O رجوع",
    "JOGO PAUSADO": "إيقاف مؤقت",
    "SENSIBILIDADE": "الحساسية",
    "ARMAS": "أسلحة",
    "FACA": "سكين",
    "MULTIPLICADOR DA MIRA": "مضاعف التصويب",
    "ROUPAS DO LEON": "ملابس LEON",
    "PERSONAGEM": "الشخصية",
    "MUDAR MAPA": "الخريطة",
    "CORES DA MIRA": "لون التصويب",
    "SEM COLISAO": "بلا تصادم",
    "ADICIONAR CHAVES": "إضافة مفاتيح",
    "CHAVE - ID HEX": "مفتاح ID HEX",
    "ADICIONAR CHAVE": "إضافة مفتاح",
    "MATAR COM 1 TIRO": "قتل بضربة واحدة",
    "MUNICAO INFINITA": "ذخيرة لا نهائية",
    "JAQUETA": "جاكيت",
    "SEM JAQUETA": "بلا جاكيت",
    "COLETE": "سترة",
    "PARCEIRA DEFAULT": "الشريكة DEFAULT",
    "PARCEIRA NORMAL": "الشريكة عادية",
    "PARCEIRA POPSTAR": "الشريكة POPSTAR",
    "PARCEIRA ARMADURA": "الشريكة بالدرع",
    "JOGAR COM ASHLEY": "العب ASHLEY",
    "ARMAS DO LEON": "أسلحة LEON",
    "DESTINO": "الوجهة",
    "IR PARA MAPA": "اذهب للخريطة",
    "VERMELHO": "أحمر",
    "VERDE": "أخضر",
    "AZUL": "أزرق",
    "AMARELO": "أصفر",
    "CIANO": "سماوي",
    "BRANCO": "أبيض",
    "AJUSTAR FOV": "ضبط FOV",
    "RESTAURAR DEFAULT": "استعادة الافتراضي",
    "FALHOU": "فشل",
    "JA POSSUI": "موجود",
    "ADICIONADO": "أضيف",
    "X CONFIRMAR - O VOLTAR": "X تأكيد - O رجوع",
    "CIMA/BAIXO: NAVEGAR": "أعلى/أسفل: تنقل",
    "APLICA AO CARREGAR CENARIO": "يطبق عند تحميل المشهد",
    "ESQ/DIR AJUSTAR - O VOLTAR": "يسار/يمين ضبط - O رجوع",
    "INVENCIVEL LEON": "LEON منيع",
    "INVENCIVEL ASHLEY": "ASHLEY منيعة",
    "ASHLEY PARCEIRA": "ASHLEY شريكة",
    "ARQUIVO": "الملف",
    "TAMANHO": "الحجم",
    "CIMA/BAIXO: ROLAR LISTA": "أعلى/أسفل: تمرير",
    "X ATUALIZAR": "X تحديث",
    "SOMENTE RECURSOS RESIDENTES": "الموارد المقيمة فقط",
    "LIMITE DO CATALOGO ATINGIDO": "تم بلوغ حد الفهرس",
    "TRIANGULO: SND USED": "المثلث: SND USED",
    "CIMA/BAIXO ROLAR - O FILES USED": "أعلى/أسفل تمرير - O FILES USED",
    "BANCOS ATIVOS - TAMANHO DO ARQUIVO": "البنوك النشطة - حجم الملف",
    # strings that were never Portuguese but are user-facing
    "CHEATS": "الغش",
    "SAVE": "حفظ",
    "MERCHANT": "التاجر",
    "MEMORY VIEWER": "عارض الذاكرة",
    "DEFAULT": "افتراضي",
}

# column header: ARQUIVO + 20 spaces + TAMANHO ; keep the second column where it was
HEADER_PT = "ARQUIVO" + " " * 20 + "TAMANHO"
HEADER_SIZE_COL_PX = 27 * 8

LATIN_OK = set(range(0x20, 0x5B))


# ASCII characters drawn with the Arabic font because the game's own Latin font
# shows them wrongly (its '-' glyph is the same shape as '?').
OWN_GLYPH_ASCII = {"-"}


def needs_glyph(ch):
    return ord(ch) > 0x7F or ch in OWN_GLYPH_ASCII


def encode(visual_str, index):
    out = bytearray()
    for ch in visual_str:
        if needs_glyph(ch):
            out.append(index[ch])
        else:
            assert ord(ch) in LATIN_OK, f"character {ch!r} not in the Latin font"
            out.append(ord(ch))
    return bytes(out)


def collect_strings():
    """pt -> (visual string or None, english)"""
    plan = {}
    for pt, en in EN_TR.items():
        plan[pt] = AR.get(pt)
    for extra in ("CHEATS", "SAVE", "MERCHANT", "MEMORY VIEWER", "DEFAULT"):
        plan[extra] = AR[extra]
    return plan


def main():
    preview = None
    if "--preview" in sys.argv:
        preview = sys.argv[sys.argv.index("--preview") + 1]

    plan = collect_strings()
    # --- visual strings + glyph set
    vis = {}
    for pt, logical in plan.items():
        if logical is None:
            continue
        vis[pt] = AF.visual(logical)
    header_pt_w = lambda s: sum(AF.render_glyph(c)[0] if needs_glyph(c) else 8 for c in s)
    v_file, v_size = AF.visual(AR["ARQUIVO"]), AF.visual(AR["TAMANHO"])
    spaces = max(1, round((HEADER_SIZE_COL_PX - header_pt_w(v_file)) / 8))
    vis[HEADER_PT] = v_file + " " * spaces + v_size

    chars = sorted({c for v in vis.values() for c in v if needs_glyph(c)})
    # --- code + font placement
    code, _ = AF.build_code(CODE_VA, 0x4B0E00, len(chars))
    font_va = (CODE_VA + len(code) + 15) & ~15
    code, labels = AF.build_code(CODE_VA, font_va, len(chars))
    assert CODE_VA + len(code) <= font_va
    font, index = AF.build_font(chars, font_va)
    end = font_va + len(font)
    assert end <= GAP_END, f"font does not fit: ends at {end:#x}"
    ar_text = labels["ar_text"]
    print(f"{len(chars)} glyph forms, code {len(code)} B, font {len(font)} B, "
          f"gap use {CODE_VA:#x}-{end:#x} (limit {GAP_END:#x})")

    # --- final replacement bytes, with slot-length checks
    repl = {}
    overflow = []
    for pt in list(EN_TR) + ["CHEATS", "SAVE", "MERCHANT", "MEMORY VIEWER", "DEFAULT"]:
        v = vis.get(pt)
        if v is not None:
            b = encode(v, index)
            if len(b) > len(pt):
                overflow.append((pt, len(b), len(pt)))
                b = None
        else:
            b = None
        if b is None:
            en = EN_TR.get(pt, pt)
            b = en.encode()
        repl[pt] = b
    b = encode(vis[HEADER_PT], index)
    if len(b) > len(HEADER_PT):
        overflow.append(("<header>", len(b), len(HEADER_PT)))
    else:
        repl[HEADER_PT] = b
    if overflow:
        print("Arabic text too long for its slot, English used instead:")
        for o in overflow:
            print("   ", o)
        for pt, _, _ in overflow:
            if pt != "<header>":
                repl[pt] = EN_TR.get(pt, pt).encode()
    for pt, b in repl.items():
        assert len(b) <= len(pt), (pt, len(b))

    # --- tree
    if os.path.isdir(AR_ROOT):
        shutil.rmtree(AR_ROOT)
    os.makedirs(DST)
    for name in os.listdir(EN_ROOT):
        p = os.path.join(EN_ROOT, name)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(AR_ROOT, name))      # installer code, identical
    for name in os.listdir(SRC):
        shutil.copy2(os.path.join(SRC, name), os.path.join(DST, name))

    jal_old = struct.pack("<I", 0x0C000000 | ((TEXT_VA >> 2) & 0x3FFFFFF))
    jal_new = struct.pack("<I", 0x0C000000 | ((ar_text >> 2) & 0x3FFFFFF))

    def convert(blob, what, has_gap):
        out = bytearray(blob)
        # 1) strings, longest first, null-delimited slots only
        for pt in sorted(repl, key=len, reverse=True):
            new = repl[pt].ljust(len(pt), b"\0")
            pat = re.compile(rb"(?<=\x00)" + re.escape(pt.encode()) + rb"(?=\x00)")
            out = bytearray(pat.sub(lambda m, new=new: new, bytes(out)))
        # 2) redirect text() calls (aligned instruction words only)
        n = 0
        for i in range(0, len(out) - 3, 4):
            if out[i:i + 4] == jal_old:
                out[i:i + 4] = jal_new
                n += 1
        # 3) code + font into the gap
        if has_gap:
            off = CODE_VA - 0x4B0000
            assert not any(out[off:GAP_END - 0x4B0000]), "gap is not empty"
            out[off:off + len(code)] = code
            foff = font_va - 0x4B0000
            out[foff:foff + len(font)] = font
        assert len(out) == len(blob)
        return bytes(out), n

    sha = lambda b: hashlib.sha256(b).hexdigest()
    digest_map = {}
    for tag in TAGS:
        for kind in ("_menu.bin", "_files.bin"):
            path = os.path.join(SRC, tag + kind)
            old = open(path, "rb").read()
            new, n = convert(old, tag + kind, kind == "_files.bin")
            expect = 44 if kind == "_menu.bin" else 24
            assert n == expect, (tag, kind, n)
            open(os.path.join(DST, tag + kind), "wb").write(new)
            digest_map[sha(old)] = sha(new)
        print(f"{tag}: ok")
    for jname in sorted(os.listdir(DST)):
        if jname.endswith(".json"):
            p = os.path.join(DST, jname)
            text = open(p, encoding="utf-8", newline="").read()
            new_text = text
            for old, new in digest_map.items():
                new_text = new_text.replace(old, new)
            if new_text != text:
                open(p, "w", encoding="utf-8", newline="").write(new_text)

    open(os.path.join(DST, "TRANSLATION_NOTE.txt"), "w").write(
        "Arabic variant - see tools/build_arabic_dados.py and tools/arabic_font.py.\n"
        "Regenerate with: python3 tools/build_arabic_dados.py\n")

    if preview:
        make_preview(preview, vis, index, repl)


def make_preview(path, vis, index, repl):
    from PIL import Image
    hud = open(os.path.join(SRC, "SLUS.bin"), "rb").read()
    latin = [struct.unpack_from("<H", hud, 4740 + 2 * i)[0] for i in range(60)]
    items = [v for k, v in vis.items()]
    W, H = 330, 22 * len(items) + 10
    im = Image.new("L", (W, H), 0)
    px = im.load()

    def rect(x, y, w, h):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if 0 <= xx < W and 0 <= yy < H:
                    px[xx, yy] = 255

    tbl = {}
    for ch, code in index.items():
        tbl[code] = AF.render_glyph(ch)
    for r, v in enumerate(items):
        x, y = 8, 6 + r * 22
        for ch in v:
            if needs_glyph(ch):
                adv, rs = tbl[index[ch]]
                for x0, y0, w, h in rs:
                    rect(x + x0, y + AF.BASELINE_Y + y0, w, h)
                x += adv
            else:
                i = ord(ch) - 0x20
                g = latin[i if 0 <= i < 59 else 31]
                for rr in range(5):
                    for cc in range(3):
                        if (g >> (rr * 3 + cc)) & 1:
                            rect(x + cc * 2, y + rr * 2, 2, 2)
                x += 8
    im = im.resize((W * 3, H * 3), Image.NEAREST)
    im.save(path)
    print("preview:", path, im.size)


if __name__ == "__main__":
    main()
