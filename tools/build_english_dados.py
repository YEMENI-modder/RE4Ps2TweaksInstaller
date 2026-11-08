#!/usr/bin/env python3
"""
Rebuilds the English variant's installed text payloads.

Why this exists: the installer only ever writes <tag>_menu.bin and
<tag>_files.bin into the executable. Earlier English builds translated only
the old *_files_v*.bin files (used to recognise previously patched ELFs),
so a fresh install still showed the Portuguese text.

Every translation is same-length-or-shorter and null padded, so all offsets,
pointers and code stay byte-identical. The only other change is the two
SHA-256 values in each profile JSON that vouch for those two files.

Usage (from the repo root):  python3 tools/build_english_dados.py
"""
import hashlib
import json
import os
import re
import struct
import sys

PY = os.path.join("app", "src", "main", "python")
SRC = os.path.join(PY, "dados")                      # Portuguese originals
DST = os.path.join(PY, "dados_en_root", "dados")     # English variant

TAGS = ["SLUS", "SLUS_alternativo", "SLES", "SLES_alternativo", "SLPM", "SLPM_alternativo"]

TR = {
    # --- menu + shared labels
    "CAMERA LIVRE": "FREE CAMERA",
    "USADO:": "USED:",
    "LIVRE:": "FREE:",
    "CONFIGURACOES": "SETTINGS",
    "HP DOS INIMIGOS": "ENEMY HP",
    "EXIBIR BARRA": "SHOW BAR",
    "TAMANHO DO HUD": "HUD SIZE",
    "SETAS: SELECIONAR / AJUSTAR": "ARROWS: SELECT / ADJUST",
    "PREVIA": "VIEW",
    "LIGADO": "ON",
    "DESLIGADO": "OFF",
    "X CONFIRMAR": "X CONFIRM",
    "O VOLTAR": "O BACK",
    "JOGO PAUSADO": "GAME PAUSED",
    "SENSIBILIDADE": "SENSITIVITY",
    "ARMAS": "GUNS",          # slot is 5 bytes incl. terminator
    "FACA": "KNIF",           # slot is 5 bytes incl. terminator
    "MULTIPLICADOR DA MIRA": "AIM MULTIPLIER",
    # --- cheats table
    "ROUPAS DO LEON": "LEON OUTFITS",
    "PERSONAGEM": "CHARACTER",
    "MUDAR MAPA": "CHANGE MAP",
    "CORES DA MIRA": "AIM COLOR",
    "SEM COLISAO": "NO CLIP",
    "ADICIONAR CHAVES": "ADD KEYS",
    "CHAVE - ID HEX": "KEY - HEX ID",
    "ADICIONAR CHAVE": "ADD KEY",
    "MATAR COM 1 TIRO": "ONE-HIT KILL",
    "MUNICAO INFINITA": "INFINITE AMMO",
    "INV LEON": "LEON INV",
    "INV ASHLEY": "ASHLEY INV",
    "JAQUETA": "JACKET",
    "SEM JAQUETA": "NO JACKET",
    "COLETE": "VEST",
    "PARCEIRA DEFAULT": "PARTNER DEFAULT",
    "PARCEIRA NORMAL": "PARTNER NORMAL",
    "PARCEIRA POPSTAR": "PARTNER POPSTAR",
    "PARCEIRA ARMADURA": "PARTNER ARMOR",
    "JOGAR COM ASHLEY": "PLAY AS ASHLEY",
    "ARMAS DO LEON": "LEON WEAPONS",
    "DESTINO": "DEST",
    "IR PARA MAPA": "GO TO MAP",
    "VERMELHO": "RED",
    "VERDE": "GREEN",
    "AZUL": "BLUE",
    "AMARELO": "YELLOW",
    "CIANO": "CYAN",
    "BRANCO": "WHITE",
    "AJUSTAR FOV": "ADJUST FOV",
    "RESTAURAR DEFAULT": "RESET DEFAULT",
    "FALHOU": "FAILED",
    "JA POSSUI": "OWNED",
    "ADICIONADO": "ADDED",
    "X CONFIRMAR - O VOLTAR": "X CONFIRM - O BACK",
    "CIMA/BAIXO: NAVEGAR": "UP/DOWN: NAVIGATE",
    "APLICA AO CARREGAR CENARIO": "APPLIES ON SCENE LOAD",
    "ESQ/DIR AJUSTAR - O VOLTAR": "LEFT/RIGHT ADJUST - O BACK",
    "INVENCIVEL LEON": "LEON INVINCIBLE",
    "INVENCIVEL ASHLEY": "ASHLEY INVINCIBLE",
    "ASHLEY PARCEIRA": "ASHLEY PARTNER",
    # --- Files Used screen
    "ARQUIVO": "FILE",
    "TAMANHO": "SIZE",
    "CIMA/BAIXO: ROLAR LISTA": "UP/DOWN: SCROLL LIST",
    "X ATUALIZAR": "X REFRESH",
    "SOMENTE RECURSOS RESIDENTES": "RESIDENT RESOURCES ONLY",
    "LIMITE DO CATALOGO ATINGIDO": "CATALOG LIMIT REACHED",
    "TRIANGULO: SND USED": "TRIANGLE: SND USED",
    "ARQUIVO" + " " * 20 + "TAMANHO": "FILE" + " " * 23 + "SIZE",
    "CIMA/BAIXO ROLAR - O FILES USED": "UP/DOWN SCROLL - O FILES USED",
    "BANCOS ATIVOS - TAMANHO DO ARQUIVO": "ACTIVE BANKS - FILE SIZE",
}


def translate(blob, tag, name):
    out = bytearray(blob)
    total = 0
    # longest first so a long label is never shadowed by a shorter one
    for pt in sorted(TR, key=len, reverse=True):
        en = TR[pt]
        assert len(en) <= len(pt), (pt, en)
        pat = re.compile(rb"(?<=\x00)" + re.escape(pt.encode()) + rb"(?=\x00)")
        def sub(m, en=en, pt=pt):
            return en.encode().ljust(len(pt), b"\x00")
        out2, n = pat.subn(sub, bytes(out))
        out = bytearray(out2)
        total += n
    assert len(out) == len(blob)
    return bytes(out), total


def restore_old_version_files():
    """
    The old *_files_v*.bin files only exist so the installer can RECOGNISE
    executables patched with an older tweak version. Those executables were
    patched with the Portuguese data, so these files must stay byte-identical
    to the Portuguese originals; translating them would make the English
    variant reject (instead of upgrade) such executables.
    """
    n = 0
    for name in sorted(os.listdir(SRC)):
        if re.search(r"_files_v\d", name) and name.endswith(".bin"):
            with open(os.path.join(SRC, name), "rb") as f:
                data = f.read()
            with open(os.path.join(DST, name), "wb") as f:
                f.write(data)
            n += 1
    print(f"restored {n} old-version *_files_v*.bin files to the Portuguese originals")


def main():
    sha = lambda b: hashlib.sha256(b).hexdigest()
    restore_old_version_files()
    for tag in TAGS:
        info = {}
        for kind in ("_menu.bin", "_files.bin"):
            src = open(os.path.join(SRC, tag + kind), "rb").read()
            new, n = translate(src, tag, tag + kind)
            open(os.path.join(DST, tag + kind), "wb").write(new)
            info[kind] = (sha(src), sha(new), n)
            print(f"{tag}{kind}: {n} strings translated")
        # profile JSON(s) that vouch for these files: swap old digest -> new
        for jname in sorted(os.listdir(DST)):
            if not jname.endswith(".json"):
                continue
            path = os.path.join(DST, jname)
            text = open(path, encoding="utf-8", newline="").read()
            changed = False
            for kind in ("_menu.bin", "_files.bin"):
                old, new, _ = info[kind]
                if old in text:
                    text = text.replace(old, new)
                    changed = True
            if changed:
                open(path, "w", encoding="utf-8", newline="").write(text)
                print("   updated digests in", jname)


if __name__ == "__main__":
    sys.exit(main())
