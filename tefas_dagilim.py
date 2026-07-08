# -*- coding: utf-8 -*-
"""TEFAS portföy dağılımı — hisse/bono/döviz oranları."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd


@dataclass
class FonDagilim:
    hisse_pct: float = 0.0
    bono_repo_pct: float = 0.0
    doviz_borc_pct: float = 0.0
    mevduat_pct: float = 0.0
    altin_pct: float = 0.0
    fon_sepeti_pct: float = 0.0
    diger_pct: float = 0.0
    etkin_kategori: str = "diger"
    ozet: str = ""

    def etiket_satir(self) -> str:
        parcalar = []
        if self.hisse_pct >= 5:
            parcalar.append(f"Hisse %{self.hisse_pct:.0f}")
        if self.bono_repo_pct >= 5:
            parcalar.append(f"Bono/Repo %{self.bono_repo_pct:.0f}")
        if self.doviz_borc_pct >= 5:
            parcalar.append(f"Döviz borç %{self.doviz_borc_pct:.0f}")
        if self.mevduat_pct >= 5:
            parcalar.append(f"Mevduat %{self.mevduat_pct:.0f}")
        if self.altin_pct >= 3:
            parcalar.append(f"Altın %{self.altin_pct:.0f}")
        if self.fon_sepeti_pct >= 5:
            parcalar.append(f"Fon sepeti %{self.fon_sepeti_pct:.0f}")
        return " · ".join(parcalar) if parcalar else "Dağılım bilinmiyor"


def _f(row, col: str) -> float:
    v = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
    try:
        return float(v) if v is not None and pd.notna(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def satirdan_dagilim(row) -> FonDagilim:
    hisse = _f(row, "stock_pct")
    bono = sum(
        _f(row, c)
        for c in (
            "government_bond_pct",
            "treasury_bill_pct",
            "financing_bill_pct",
            "private_sector_bond_pct",
            "bank_bill_pct",
            "asset_backed_securities_pct",
            "repo_pct",
            "reverse_repo_pct",
            "takasbank_money_market_pct",
            "bist_money_market_pct",
        )
    )
    doviz = sum(
        _f(row, c)
        for c in (
            "eurobond_pct",
            "government_external_debt_pct",
            "private_sector_external_debt_pct",
            "fx_government_internal_debt_pct",
            "fx_payable_bill_pct",
            "fx_payable_bond_pct",
            "deposit_fx_pct",
        )
    )
    mevduat = _f(row, "deposit_tl_pct") + _f(row, "term_deposit_pct") + _f(row, "participation_account_tl_pct")
    altin = _f(row, "precious_metals_pct") + _f(row, "precious_metals_etf_pct") + _f(row, "deposit_gold_pct")
    fon_sepeti = _f(row, "investment_fund_pct")
    toplam = hisse + bono + doviz + mevduat + altin + fon_sepeti
    diger = max(0.0, 100.0 - toplam) if toplam <= 100.5 else 0.0

    etkin = _etkin_kategori(hisse, bono, doviz, mevduat, altin, fon_sepeti)
    d = FonDagilim(
        hisse_pct=round(hisse, 1),
        bono_repo_pct=round(bono, 1),
        doviz_borc_pct=round(doviz, 1),
        mevduat_pct=round(mevduat, 1),
        altin_pct=round(altin, 1),
        fon_sepeti_pct=round(fon_sepeti, 1),
        diger_pct=round(diger, 1),
        etkin_kategori=etkin,
    )
    d.ozet = d.etiket_satir()
    return d


def _etkin_kategori(hisse, bono, doviz, mevduat, altin, fon_sepeti) -> str:
    if hisse >= 40:
        return "hisse"
    if altin >= 25:
        return "altin_emtia"
    if doviz >= 40:
        return "serbest_doviz"
    if bono + mevduat >= 50:
        return "borclanma" if bono >= mevduat else "para_piyasasi"
    if bono + mevduat >= 30:
        return "borclanma"
    if fon_sepeti >= 35:
        return "fon_sepeti"
    if hisse >= 20:
        return "hisse"
    return "degisken"
