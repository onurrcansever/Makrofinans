#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BIST 52H TL vs EUR sanity check — EREGL, ASELS, MGROS."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bist_52h_eur import bist_52h_eur_hesapla, format_52h_metin  # noqa: E402
from stock_scanner import _close_al, _hisse_analiz, _indir  # noqa: E402

SEMBOLler = ["EREGL.IS", "ASELS.IS", "MGROS.IS"]


def main() -> None:
    df = _indir(SEMBOLler, period="1y")
    eurtry_df = _indir(["EURTRY=X"], period="1y")
    eurtry_close = _close_al(eurtry_df, "EURTRY=X")

    if eurtry_close.empty:
        print("[UYARI] EURTRY=X çekilemedi — EUR bazlı 52H hesaplanamaz")
        return

    print("BIST 52H sanity — TL vs EUR band pozisyonu\n")
    for sym in SEMBOLler:
        close = _close_al(df, sym)
        if close.empty:
            print(f"{sym}: fiyat verisi yok")
            continue
        sonuc = bist_52h_eur_hesapla(close, eurtry_close)
        h = _hisse_analiz(
            df, sym, sym, "BIST", "sanayi", "NOTR", None,
            eurtry_close=eurtry_close,
        )
        tl = h.zirve_52h_pct
        eur = sonuc.eur_pozisyon_pct
        print(f"{sym}:")
        print(f"  join sonrası gün: {sonuc.join_gun}")
        if sonuc.join_gun < 200:
            print(f"  [UYARI] join gün sayısı 200 altında ({sonuc.join_gun})")
        print(f"  TL pozisyon:  {tl:.1f}%" if tl is not None else "  TL pozisyon:  —")
        if sonuc.etiket:
            print(f"  EUR: {sonuc.etiket}")
        elif eur is not None:
            print(f"  EUR pozisyon: {eur:.1f}%")
        else:
            print("  EUR pozisyon: —")
        print(f"  Rapor metni: {format_52h_metin(h)}")
        if tl is not None and eur is not None and eur < tl - 5:
            print("  ✓ EUR, TL'den belirgin düşük — kur düzeltmesi çalışıyor")
        print()


if __name__ == "__main__":
    main()
