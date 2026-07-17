# -*- coding: utf-8 -*-
"""Varlıklarım — çoklu portföy, kalıcı kayıt, öneri aktarımı."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import config
from birlesik_oneri import AracDagilimSatir, BirlesikOneri, HedefSatir
from etf_universe import REVOLUT_ETFLER

_ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.getenv(
    "VARLIKLARIM_PATH",
    os.path.join(_ROOT, ".varliklarim.json"),
)
# GitHub Actions checkout — workflow scope olmadan portföy (Mac sync → private repo)
CI_SYNC_PATH = os.path.join(_ROOT, "data", "ci_varliklarim.json")


def _store_kaynak_yolu() -> Optional[str]:
    # CI: repo sync dosyası her zaman öncelikli (eski/boş .varliklarim.json'u atla)
    if os.getenv("GITHUB_ACTIONS") and os.path.isfile(CI_SYNC_PATH):
        return CI_SYNC_PATH
    for path in (STATE_PATH, CI_SYNC_PATH):
        if path and os.path.isfile(path):
            return path
    return None

TUR_SECENEKLERI = {
    "nakit_tl": "TL nakit",
    "nakit_eur": "EUR nakit",
    "nakit_usd": "USD nakit",
    "nakit_ron": "RON nakit (Rumen Leyi)",
    "tl_mevduat": "TL vadeli mevduat",
    "tefas": "TEFAS fon",
    "hisse": "BIST hissesi",
    "hisse_us": "ABD hissesi (SP500/NASDAQ)",
    "etf": "ETF (UCITS)",
    "altin": "Altın",
    "gumus": "Gümüş",
    "kripto": "Kripto (BTC)",
}

# miktar = adet/pay/gram; alim_fiyati = birim alış fiyatı (para_birimi cinsinden)
BIRIMLI_TURLER = frozenset({"tefas", "hisse", "hisse_us", "etf", "altin", "gumus", "kripto"})
HISSE_TURLER = frozenset({"hisse", "hisse_us"})
MIKTAR_ETIKET = {
    "nakit_tl": "Tutar (TL)",
    "nakit_eur": "Tutar (EUR)",
    "nakit_usd": "Tutar (USD)",
    "nakit_ron": "Tutar (RON)",
    "tl_mevduat": "Anapara (TL)",
    "tefas": "Pay adedi",
    "hisse": "Lot / adet",
    "hisse_us": "Lot / adet",
    "etf": "Pay adedi",
    "altin": "Gram",
    "gumus": "Gram",
    "kripto": "Miktar (BTC)",
}
ALIM_FIYAT_ETIKET = {
    "tefas": "Alış fiyatı (TL/pay)",
    "hisse": "Alış fiyatı (TL/adet)",
    "hisse_us": "Alış fiyatı (USD/adet)",
    "etf": "Alış fiyatı (birim)",
    "altin": "Alış fiyatı (TL/gram)",
    "gumus": "Alış fiyatı (TL/gram)",
    "kripto": "Alış fiyatı (USD/BTC)",
    "nakit_eur": "Alım kuru (EUR/TL, isteğe bağlı)",
    "nakit_usd": "Alım kuru (USD/TL, isteğe bağlı)",
    "nakit_ron": "Alım kuru (RON/TL, isteğe bağlı)",
}


@dataclass
class VarlikPozisyon:
    id: str
    tur: str
    sembol: str = ""
    ad: str = ""
    miktar: float = 0.0
    maliyet: float = 0.0
    alim_fiyati: float = 0.0
    para_birimi: str = "TL"
    alim_tarihi: str = ""
    banka: str = ""
    vade_gun: int = 0
    brut_faiz: float = 0.0
    notu: str = ""

    def birimli(self) -> bool:
        return self.tur in BIRIMLI_TURLER

    def maliyet_toplam(self) -> float:
        if self.maliyet > 0:
            return self.maliyet
        if self.birimli() and self.alim_fiyati > 0 and self.miktar > 0:
            return self.miktar * self.alim_fiyati
        return self.miktar

    def etiket(self) -> str:
        if self.ad:
            return self.ad
        if self.sembol:
            return self.sembol
        return TUR_SECENEKLERI.get(self.tur, self.tur)


@dataclass
class VarlikPortfoy:
    id: str
    ad: str
    para_birimi: str = "EUR"
    kaynak: str = "manuel"
    olusturma: str = ""
    pozisyonlar: List[VarlikPozisyon] = field(default_factory=list)

    def __post_init__(self):
        if not self.olusturma:
            self.olusturma = date.today().isoformat()


@dataclass
class VarlikStore:
    aktif_id: str = ""
    goruntuleme_pb: str = "TL"
    portfoyler: List[VarlikPortfoy] = field(default_factory=list)
    gunluk_snapshot: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def aktif(self) -> Optional[VarlikPortfoy]:
        for p in self.portfoyler:
            if p.id == self.aktif_id:
                return p
        return self.portfoyler[0] if self.portfoyler else None


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _etf_ticker(kisa: str) -> str:
    k = kisa.strip().upper().replace("ETF ", "")
    for e in REVOLUT_ETFLER:
        if e[4].upper() == k or e[0].upper().startswith(k):
            return e[0]
    return k


def _bist_sembol(kod: str) -> str:
    k = kod.strip().upper()
    if k.endswith(".IS"):
        return k
    return f"{k}.IS"


@dataclass
class PozisyonEvrenSecim:
    sembol: str
    ad: str
    label: str
    para_birimi: str = "TL"


def pozisyon_sembol_normalize(tur: str, sembol: str) -> str:
    """Kayıt öncesi sembol standardizasyonu."""
    s = (sembol or "").strip().upper()
    if not s:
        return ""
    if tur == "hisse":
        return _bist_sembol(s)
    if tur == "hisse_us":
        return s.split(".")[0]
    if tur == "etf":
        return _etf_ticker(s)
    if tur == "tefas":
        return s.split(".")[0]
    return s


def pozisyon_evren_listesi(
    tur: str,
    *,
    tefas_fonlar=None,
    ara: str = "",
) -> List[PozisyonEvrenSecim]:
    """Pozisyon ekleme — tam evren sembol seçenekleri."""
    from stock_universe import tum_hisseler

    q = (ara or "").strip().casefold()
    out: List[PozisyonEvrenSecim] = []

    def _eslesir(*parcalar: str) -> bool:
        if not q:
            return True
        return any(q in (p or "").casefold() for p in parcalar if p)

    if tur == "hisse":
        for s, ad, piyasa, _ in tum_hisseler():
            if piyasa != "BIST":
                continue
            kod = s.split(".")[0]
            if not _eslesir(s, kod, ad):
                continue
            out.append(PozisyonEvrenSecim(
                sembol=s,
                ad=ad,
                label=f"{kod} — {ad}",
                para_birimi="TL",
            ))
    elif tur == "hisse_us":
        for s, ad, piyasa, _ in tum_hisseler():
            if piyasa not in ("SP500", "NASDAQ"):
                continue
            kod = s.split(".")[0]
            if not _eslesir(s, kod, ad, piyasa):
                continue
            out.append(PozisyonEvrenSecim(
                sembol=s,
                ad=ad,
                label=f"{kod} ({piyasa}) — {ad}",
                para_birimi="USD",
            ))
    elif tur == "etf":
        for s, ad, _, _, rt in REVOLUT_ETFLER:
            if not _eslesir(s, rt, ad):
                continue
            out.append(PozisyonEvrenSecim(
                sembol=s,
                ad=ad,
                label=f"{rt or s} — {ad}",
                para_birimi="USD",
            ))
    elif tur == "tefas":
        for f in tefas_fonlar or []:
            kod = (getattr(f, "kod", "") or "").upper()
            ad = getattr(f, "kisa_ad", "") or getattr(f, "ad", "") or kod
            if not kod or not _eslesir(kod, ad):
                continue
            pb = getattr(f, "para_birimi", "TL") or "TL"
            if pb not in ("TL", "EUR", "USD", "RON"):
                pb = "TL"
            out.append(PozisyonEvrenSecim(
                sembol=kod,
                ad=ad,
                label=f"{kod} — {ad}",
                para_birimi=pb,
            ))
    out.sort(key=lambda x: x.label)
    return out


def pozisyon_canli_fiyat(
    sembol: str,
    tur: str,
    tarama=None,
    *,
    tefas_fonlar=None,
) -> tuple:
    """(fiyat, para_birimi) — tarama > live_quote > Yahoo."""
    from fiyat_para import kaynak_para_birimi
    from portfoy_yoneticisi import tarama_hisse_bul

    sym = pozisyon_sembol_normalize(tur, sembol)
    if not sym:
        return None, "TL"

    if tur == "tefas":
        kod = sym
        for f in tefas_fonlar or []:
            if (getattr(f, "kod", "") or "").upper() == kod:
                px = float(getattr(f, "fiyat", 0) or 0)
                if px > 0:
                    pb = getattr(f, "para_birimi", "TL") or "TL"
                    return px, pb if pb in ("TL", "EUR", "USD", "RON") else "TL"
        return None, "TL"

    h = tarama_hisse_bul(tarama, sym)
    if h and getattr(h, "fiyat", None) and float(h.fiyat) > 0:
        pb = kaynak_para_birimi(sym, varlik_turu=tur)
        return float(h.fiyat), pb

    try:
        from signal_engine.data.live_quote import get_live_quote

        q = get_live_quote(sym, allow_stale=True)
        if q and q.price and float(q.price) > 0:
            pb = kaynak_para_birimi(sym, varlik_turu=tur)
            return float(q.price), pb
    except Exception:
        pass

    try:
        import yfinance as yf

        t = yf.Ticker(sym)
        fi = getattr(t, "fast_info", None) or {}
        px = fi.get("lastPrice") or fi.get("regularMarketPrice")
        if px and float(px) > 0:
            return float(px), kaynak_para_birimi(sym, varlik_turu=tur)
    except Exception:
        pass

    return None, kaynak_para_birimi(sym, varlik_turu=tur) if tur in (*HISSE_TURLER, "etf") else "TL"


def pozisyon_emtia_fiyat(tur: str, snap) -> tuple:
    """Altın/gümüş gram TL fiyatı — makro snapshot."""
    from varlik_fiyat import _tl_gram_altin, _tl_gram_gumus

    if tur == "altin":
        px = _tl_gram_altin(snap)
        return (float(px), "TL") if px and px > 0 else (None, "TL")
    if tur == "gumus":
        px = _tl_gram_gumus(snap)
        return (float(px), "TL") if px and px > 0 else (None, "TL")
    return None, "TL"


def varsayilan_store() -> VarlikStore:
    p = VarlikPortfoy(id=_uid(), ad="Varlıklarım 1", para_birimi="EUR")
    return VarlikStore(aktif_id=p.id, goruntuleme_pb="TL", portfoyler=[p])


def yukle_store() -> VarlikStore:
    kaynak = _store_kaynak_yolu()
    if not kaynak:
        return varsayilan_store()
    try:
        with open(kaynak, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return varsayilan_store()
    portfoyler = []
    for p in raw.get("portfoyler", []):
        poz = []
        for x in p.get("pozisyonlar", []):
            x.setdefault("alim_fiyati", 0.0)
            poz.append(VarlikPozisyon(**x))
        portfoyler.append(
            VarlikPortfoy(
                id=p["id"],
                ad=p.get("ad", "Portföy"),
                para_birimi=p.get("para_birimi", "EUR"),
                kaynak=p.get("kaynak", "manuel"),
                olusturma=p.get("olusturma", ""),
                pozisyonlar=poz,
            )
        )
    if not portfoyler:
        return varsayilan_store()
    migrated = False
    for i, p in enumerate(portfoyler):
        if p.ad.strip().lower() == "test":
            p.ad = f"Varlıklarım {i + 1}"
            migrated = True
    store = VarlikStore(
        aktif_id=raw.get("aktif_id") or portfoyler[0].id,
        goruntuleme_pb=raw.get("goruntuleme_pb", "TL"),
        portfoyler=portfoyler,
        gunluk_snapshot=raw.get("gunluk_snapshot", {}),
    )
    if migrated:
        kaydet_store(store)
    return store


def kaydet_store(store: VarlikStore) -> None:
    data = {
        "aktif_id": store.aktif_id,
        "goruntuleme_pb": store.goruntuleme_pb,
        "portfoyler": [
            {
                "id": p.id,
                "ad": p.ad,
                "para_birimi": p.para_birimi,
                "kaynak": p.kaynak,
                "olusturma": p.olusturma,
                "pozisyonlar": [asdict(x) for x in p.pozisyonlar],
            }
            for p in store.portfoyler
        ],
        "gunluk_snapshot": store.gunluk_snapshot,
        "guncelleme": datetime.now().isoformat(timespec="seconds"),
    }
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def yeni_portfoy(store: VarlikStore, ad: Optional[str] = None) -> VarlikPortfoy:
    n = len(store.portfoyler) + 1
    p = VarlikPortfoy(id=_uid(), ad=ad or f"Varlıklarım {n}", para_birimi="EUR")
    store.portfoyler.append(p)
    store.aktif_id = p.id
    kaydet_store(store)
    return p


def portfoy_sil(store: VarlikStore, portfoy_id: str) -> None:
    store.portfoyler = [p for p in store.portfoyler if p.id != portfoy_id]
    if not store.portfoyler:
        store.portfoyler = [VarlikPortfoy(id=_uid(), ad="Varlıklarım 1")]
    if store.aktif_id == portfoy_id:
        store.aktif_id = store.portfoyler[0].id
    kaydet_store(store)


def pozisyon_ekle(store: VarlikStore, portfoy_id: str, poz: VarlikPozisyon) -> None:
    for p in store.portfoyler:
        if p.id == portfoy_id:
            p.pozisyonlar.append(poz)
            kaydet_store(store)
            return


def pozisyon_guncelle(store: VarlikStore, portfoy_id: str, poz: VarlikPozisyon) -> None:
    for p in store.portfoyler:
        if p.id == portfoy_id:
            p.pozisyonlar = [x if x.id != poz.id else poz for x in p.pozisyonlar]
            kaydet_store(store)
            return


def pozisyon_sil(store: VarlikStore, portfoy_id: str, poz_id: str) -> None:
    for p in store.portfoyler:
        if p.id == portfoy_id:
            p.pozisyonlar = [x for x in p.pozisyonlar if x.id != poz_id]
            kaydet_store(store)
            return


def _arac_toplam(oneri: BirlesikOneri, ust_kategori: str) -> float:
    return sum(
        s.tutar for s in oneri.arac_dagilim
        if ust_kategori in s.ust_kategori
    )


def _etf_nakit_kaynak(oneri: BirlesikOneri) -> str:
    """ETF payı hangi nakit satırından düşülür (birlesik_oneri ile aynı mantık)."""
    eur = next((h for h in oneri.hedef_tablo if "EUR nakit" in h.kategori), None)
    usd = next((h for h in oneri.hedef_tablo if "USD nakit" in h.kategori), None)
    if eur and usd:
        return "EUR" if eur.agirlik_pct >= usd.agirlik_pct else "USD"
    if eur:
        return "EUR"
    return "USD"


def _hedef_aktarim_tutar(
    h: HedefSatir,
    *,
    tefas_toplam: float,
    etf_toplam: float,
    etf_kaynak: str,
) -> float:
    """Makro satırdan araç içi dağılım tutarını düş — çift sayımı önler."""
    tutar = h.tutar
    if h.kategori == "TL vadeli mevduat" and tefas_toplam > 0:
        tutar = max(0.0, tutar - tefas_toplam)
    elif "EUR nakit" in h.kategori and etf_toplam > 0 and etf_kaynak == "EUR":
        tutar = max(0.0, tutar - etf_toplam)
    elif "USD nakit" in h.kategori and etf_toplam > 0 and etf_kaynak == "USD":
        tutar = max(0.0, tutar - etf_toplam)
    return tutar


def _hedef_tur(kategori: str) -> str:
    k = kategori.lower()
    if "eur" in k and "nakit" in k:
        return "nakit_eur"
    if "usd" in k and "nakit" in k:
        return "nakit_usd"
    if "tl" in k and "mevduat" in k:
        return "tl_mevduat"
    if "altın" in k or "altin" in k:
        return "altin"
    if "gümüş" in k or "gumus" in k:
        return "gumus"
    if "bist" in k:
        return "hisse"
    if "kripto" in k or "btc" in k:
        return "kripto"
    return "nakit_tl"


def oneri_portfoye_aktar(
    store: VarlikStore,
    portfoy_id: str,
    oneri: BirlesikOneri,
    *,
    para_birimi: str = "EUR",
    mevcut_mevduat: Optional[Any] = None,
) -> int:
    """Birleşik öneriyi seçili portföye pozisyon olarak ekler. Dönen: eklenen satır sayısı."""
    portfoy = next((p for p in store.portfoyler if p.id == portfoy_id), None)
    if not portfoy:
        return 0
    portfoy.pozisyonlar.clear()
    portfoy.kaynak = "oneri"
    portfoy.para_birimi = para_birimi
    portfoy.olusturma = date.today().isoformat()
    eklenen = 0
    bugun = date.today().isoformat()

    detay_kat = {s.ust_kategori for s in oneri.arac_dagilim}
    tefas_toplam = _arac_toplam(oneri, "TEFAS fon")
    etf_toplam = _arac_toplam(oneri, "ETF")
    etf_kaynak = _etf_nakit_kaynak(oneri)

    for h in oneri.hedef_tablo:
        if h.kategori in detay_kat:
            continue
        if "BIST" in h.kategori and any("BIST" in k for k in detay_kat):
            continue
        tutar = _hedef_aktarim_tutar(
            h,
            tefas_toplam=tefas_toplam,
            etf_toplam=etf_toplam,
            etf_kaynak=etf_kaynak,
        )
        if tutar <= 0:
            continue
        tur = _hedef_tur(h.kategori)
        if tur == "tl_mevduat" and mevcut_mevduat:
            poz = VarlikPozisyon(
                id=_uid(),
                tur="tl_mevduat",
                ad=f"{getattr(mevcut_mevduat, 'banka', 'Banka')} vadeli",
                miktar=float(getattr(mevcut_mevduat, "tutar", tutar)),
                maliyet=float(getattr(mevcut_mevduat, "tutar", tutar)),
                para_birimi="TL",
                alim_tarihi=bugun,
                banka=getattr(mevcut_mevduat, "banka", ""),
                vade_gun=int(getattr(mevcut_mevduat, "vade_gun", 90)),
                brut_faiz=float(getattr(mevcut_mevduat, "brut_faiz", 0)),
                notu="Mevcut mevduat + makro hedef",
            )
        else:
            poz = VarlikPozisyon(
                id=_uid(),
                tur=tur,
                ad=h.kategori,
                miktar=tutar,
                maliyet=tutar,
                para_birimi=h.para,
                alim_tarihi=bugun,
                notu=h.arac[:120],
            )
        portfoy.pozisyonlar.append(poz)
        eklenen += 1

    for s in oneri.arac_dagilim:
        if "TEFAS" in s.ust_kategori:
            tur = "tefas"
            sembol = s.arac.strip().upper().split()[0]
            ad = (s.aciklama or s.arac)[:60]
        elif "ETF" in s.ust_kategori:
            tur = "etf"
            sembol = _etf_ticker(s.arac.strip())
            ad = (s.aciklama or s.arac)[:60]
        else:
            tur = "hisse"
            sembol = _bist_sembol(s.arac.split()[0] if " " in s.arac else s.arac)
            ad = (s.aciklama or s.arac)[:60]
        portfoy.pozisyonlar.append(
            VarlikPozisyon(
                id=_uid(),
                tur=tur,
                sembol=sembol,
                ad=ad,
                miktar=s.tutar,
                maliyet=s.tutar,
                para_birimi=s.para,
                alim_tarihi=bugun,
                notu=f"Öneri · kategori içi %{s.kategori_ici_pct:.0f}",
            )
        )
        eklenen += 1

    kaydet_store(store)
    return eklenen


def gunluk_snapshot_kaydet(store: VarlikStore, portfoy_id: str, degerler: Dict[str, float]) -> None:
    """degerler: {TL, EUR, USD} toplam değer."""
    bugun = date.today().isoformat()
    store.gunluk_snapshot.setdefault(bugun, {})[portfoy_id] = degerler
    # Son 180 gün tut
    keys = sorted(store.gunluk_snapshot.keys())[-180:]
    store.gunluk_snapshot = {k: store.gunluk_snapshot[k] for k in keys}
    kaydet_store(store)
