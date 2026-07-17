# -*- coding: utf-8 -*-
"""Favoriler — izleme listesi (portföyden bağımsız, kalıcı kayıt)."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import List, Optional, Tuple

STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".favoriler.json",
)

TUR_ETIKET = {
    "hisse": "Hisse",
    "etf": "ETF",
    "emtia": "Emtia",
    "tefas": "TEFAS fon",
    "endeks": "Endeks",
}


@dataclass
class FavoriItem:
    id: str
    tur: str
    sembol: str
    ad: str = ""
    eklenme: str = ""
    notu: str = ""


@dataclass
class FavoriStore:
    items: List[FavoriItem] = field(default_factory=list)


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _bist_kokleri() -> set:
    try:
        from stock_universe import BIST_HISSELER
        return {s.replace(".IS", "").upper() for s, _, _ in BIST_HISSELER}
    except Exception:
        return set()


def _us_global_kokleri() -> set:
    try:
        from stock_universe import NASDAQ_HISSELER, SP500_HISSELER
        return {s.upper() for s, _, _ in list(NASDAQ_HISSELER) + list(SP500_HISSELER)}
    except Exception:
        return set()


def tur_etiket(tur: str, sembol: str = "") -> str:
    """UI etiketi — BIST vs ABD ayrımı."""
    if tur == "hisse":
        s = (sembol or "").upper()
        if s.endswith(".IS"):
            return "BIST hissesi"
        return "ABD / global hisse"
    return TUR_ETIKET.get(tur, tur)


def normalize_sembol(tur: str, sembol: str) -> str:
    """
    Hisse: BIST → .IS; ABD (AMAT, CSCO, UNH…) → soneksiz.
    Yanlış kaydedilmiş AMAT.IS → AMAT düzeltilir.
    """
    s = (sembol or "").strip().upper()
    if not s:
        return ""
    if tur == "hisse":
        us = _us_global_kokleri()
        bist = _bist_kokleri()
        if s.endswith(".IS"):
            kok = s[:-3]
            # ABD ticker'ına yanlışlıkla .IS eklenmişse geri al
            if kok in us and kok not in bist:
                return kok
            return s
        if "." in s:
            return s  # zaten borsa eki var (.L vb.)
        if s in bist:
            return f"{s}.IS"
        return s  # ABD / global — Yahoo soneksiz
    if tur == "tefas":
        return s.replace(".IS", "")
    if tur == "etf":
        from signal_engine.decisions.history import canonical_decision_symbol

        return canonical_decision_symbol(s)
    return s


def favori_anahtar(tur: str, sembol: str) -> Tuple[str, str]:
    """Anahtar: (tur, canonical_sembol) — örn. ('tefas','YLR'), ('etf','EQQQ.L')."""
    return (tur, normalize_sembol(tur, sembol))


def varsayilan_store() -> FavoriStore:
    return FavoriStore()


def yukle_store() -> FavoriStore:
    if not os.path.isfile(STATE_PATH):
        return varsayilan_store()
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return varsayilan_store()
    items = []
    degisti = False
    for x in raw.get("items", []):
        x.setdefault("notu", "")
        tur = x.get("tur", "hisse")
        eski = x.get("sembol", "")
        yeni = normalize_sembol(tur, eski)
        if yeni and yeni != eski:
            x["sembol"] = yeni
            degisti = True
        items.append(FavoriItem(**x))
    store = FavoriStore(items=items)
    if degisti:
        try:
            kaydet_store(store)
        except Exception:
            pass
    return store


def kaydet_store(store: FavoriStore) -> None:
    """Atomik yazma — tmp + os.replace (decision_history deseni)."""
    data = {
        "items": [asdict(x) for x in store.items],
        "guncelleme": date.today().isoformat(),
    }
    directory = os.path.dirname(os.path.abspath(STATE_PATH)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".favoriler.", suffix=".tmp", dir=directory,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def favori_var(store: FavoriStore, tur: str, sembol: str) -> bool:
    key = favori_anahtar(tur, sembol)
    return any(favori_anahtar(x.tur, x.sembol) == key for x in store.items)


def favori_ekle(
    store: FavoriStore,
    tur: str,
    sembol: str,
    *,
    ad: str = "",
    notu: str = "",
) -> bool:
    """Favori ekle. Zaten varsa False döner."""
    tur = tur if tur in TUR_ETIKET else "hisse"
    sym = normalize_sembol(tur, sembol)
    if not sym:
        return False
    if favori_var(store, tur, sym):
        return False
    store.items.append(
        FavoriItem(
            id=_uid(),
            tur=tur,
            sembol=sym,
            ad=(ad or sym).strip(),
            eklenme=date.today().isoformat(),
            notu=notu.strip(),
        )
    )
    kaydet_store(store)
    return True


def favori_sil(store: FavoriStore, item_id: str) -> None:
    store.items = [x for x in store.items if x.id != item_id]
    kaydet_store(store)


def favori_bul(store: FavoriStore, tur: str, sembol: str) -> Optional[FavoriItem]:
    key = favori_anahtar(tur, sembol)
    for x in store.items:
        if favori_anahtar(x.tur, x.sembol) == key:
            return x
    return None


def favori_sil_sembol(store: FavoriStore, tur: str, sembol: str) -> bool:
    item = favori_bul(store, tur, sembol)
    if not item:
        return False
    favori_sil(store, item.id)
    return True


def favori_toggle(store: FavoriStore, tur: str, sembol: str, *, ad: str = "") -> bool:
    """Favori durumunu tersine çevir. True = eklendi, False = çıkarıldı."""
    sym = normalize_sembol(tur, sembol)
    if favori_var(store, tur, sym):
        favori_sil_sembol(store, tur, sym)
        return False
    favori_ekle(store, tur, sym, ad=ad or sym)
    return True


def favori_toplu_ekle(
    store: FavoriStore,
    kayitlar: List[Tuple[str, str, str]],
) -> int:
    """(tur, sembol, ad) listesinden ekle; eklenen adet."""
    n = 0
    for tur, sembol, ad in kayitlar:
        if favori_ekle(store, tur, sembol, ad=ad):
            n += 1
    return n


def data_column_lock(df) -> list:
    """Değer kilidi — ⭐ dışı (tur/sembol/fiyat) parmak izi. NaN → None (karşılaştırma stabil)."""
    import pandas as pd

    if df is None or getattr(df, "empty", True):
        return []
    cols = [c for c in df.columns if c != "⭐"]
    out = []
    for _, row in df[cols].iterrows():
        vals = []
        for c in cols:
            v = row.get(c)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                vals.append(None)
            else:
                vals.append(v)
        out.append(tuple(vals))
    return out
