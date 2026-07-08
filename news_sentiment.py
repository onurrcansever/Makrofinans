# -*- coding: utf-8 -*-
"""
Haber başlığı duygu analizi — sözlük tabanlı, deterministik.
Kapı 1 / 1b etkin haber sayısı ve kritik olay vetosu için kullanılır.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# Negatif (−1.0)
_NEG_KRITIK: Dict[str, float] = {
    "istifa": -1.0,
    "görevden alındı": -1.0,
    "gorevden alindi": -1.0,
    "soruşturma": -1.0,
    "sorusturma": -1.0,
    "yaptırım": -1.0,
    "yaptirim": -1.0,
    "sermaye kontrolü": -1.0,
    "sermaye kontrolu": -1.0,
    "moratoryum": -1.0,
    "not indirimi": -1.0,
    "rezerv eridi": -1.0,
    "müdahale": -1.0,
    "mudahale": -1.0,
    "olağanüstü": -1.0,
    "olaganustu": -1.0,
    "kayyum": -1.0,
    "gözaltı": -1.0,
    "gozalti": -1.0,
    "saldırı": -1.0,
    "saldir": -1.0,
    "abluka": -1.0,
    "boğaz kapandı": -1.0,
    "bogaz kapandi": -1.0,
    "füze": -1.0,
    "fuze": -1.0,
    "sıcak çatışma": -1.0,
    "sicak catisma": -1.0,
}

# Negatif (−0.5)
_NEG_ORTA: Dict[str, float] = {
    "gerilim": -0.5,
    "belirsizlik": -0.5,
    "endişe": -0.5,
    "endise": -0.5,
    "riskli": -0.5,
    "düşüş": -0.5,
    "dusus": -0.5,
    "zayıfladı": -0.5,
    "zayifladi": -0.5,
    "baskı": -0.5,
    "baski": -0.5,
    "kriz": -0.5,
    "tartışma": -0.5,
    "tartisma": -0.5,
    "protesto": -0.5,
    "erken seçim": -0.5,
    "erken secim": -0.5,
    "enflasyon yükseldi": -0.5,
    "enflasyon yukseldi": -0.5,
}

# Pozitif (+0.5)
_POS_ORTA: Dict[str, float] = {
    "rekor": 0.5,
    "yükseliş": 0.5,
    "yukselis": 0.5,
    "toparlanma": 0.5,
    "anlaşma": 0.5,
    "anlasma": 0.5,
    "uzlaşma": 0.5,
    "uzlasma": 0.5,
    "not artışı": 0.5,
    "not artisi": 0.5,
    "rezerv arttı": 0.5,
    "rezerv artti": 0.5,
    "yabancı girişi": 0.5,
    "yabanci girisi": 0.5,
    "güven arttı": 0.5,
    "guven artti": 0.5,
}

# Pozitif (+1.0)
_POS_GUCLU: Dict[str, float] = {
    "ateşkes": 1.0,
    "ateskes": 1.0,
    "barış anlaşması": 1.0,
    "baris anlasmasi": 1.0,
    "not artırıldı": 1.0,
    "not artirildi": 1.0,
    "kredi notu yükseltildi": 1.0,
    "kredi notu yukseltildi": 1.0,
    "sermaye girişi rekoru": 1.0,
    "sermaye girisi rekoru": 1.0,
}

# Olay vetosu — yalnızca somut kriz olayları (metafor / jeopolitik arka plan değil)
_OLAY_VETOSU: Dict[str, float] = {
    "istifa etti": -1.0,
    "istifa et": -1.0,
    "görevden alındı": -1.0,
    "gorevden alindi": -1.0,
    "kayyum atand": -1.0,
    "gözaltına alınd": -1.0,
    "gozaltina alind": -1.0,
    "tutukland": -1.0,
    "OHAL ilan": -1.0,
    "olaganustu hal": -1.0,
    "olağanüstü hal": -1.0,
    "darbe girişimi": -1.0,
    "darbe girisimi": -1.0,
    "sermaye kontrolü": -1.0,
    "sermaye kontrolu": -1.0,
    "not indirimi": -1.0,
    "moratoryum": -1.0,
    "devre kesici": -1.0,
}

_OLAY_VETOSU_LIST: List[Tuple[str, float]] = sorted(
    _OLAY_VETOSU.items(), key=lambda x: len(x[0]), reverse=True
)
_SOZLUK: List[Tuple[str, float]] = sorted(
    list(_NEG_KRITIK.items())
    + list(_NEG_ORTA.items())
    + list(_POS_ORTA.items())
    + list(_POS_GUCLU.items()),
    key=lambda x: len(x[0]),
    reverse=True,
)


@dataclass
class HaberDuyguSonucu:
    haber_sayisi: int
    ort_duygu: float
    neg_sayisi: int
    kritik_neg_sayisi: int
    olay_vetosu_sayisi: int = 0
    en_negatif_5_baslik: List[Tuple[str, float]] = field(default_factory=list)
    baslik_kaynaklar: List[Tuple[str, str, float]] = field(default_factory=list)


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def baslik_skoru(baslik: str) -> float:
    """Tek başlık skoru −1.0 .. +1.0; eşleşme yoksa 0."""
    norm = _normalize(baslik)
    if not norm:
        return 0.0
    skorlar: List[float] = []
    for kelime, skor in _SOZLUK:
        kn = _normalize(kelime)
        if kn and kn in norm:
            skorlar.append(skor)
    if not skorlar:
        return 0.0
    neg = [s for s in skorlar if s < 0]
    if neg:
        return min(neg)
    return max(skorlar)


def olay_vetosu_skoru(baslik: str) -> float:
    """Sert olay vetosu — erken seçim spekülasyonu dahil değil."""
    norm = _normalize(baslik)
    if not norm:
        return 0.0
    for kelime, skor in _OLAY_VETOSU_LIST:
        kn = _normalize(kelime)
        if kn and kn in norm:
            return skor
    return 0.0


def baslik_kaynak_ayir(baslik: str) -> Tuple[str, str]:
    """Google News formatı: 'Haber - Kaynak'"""
    if " - " in baslik:
        parcalar = baslik.rsplit(" - ", 1)
        return parcalar[0].strip(), parcalar[1].strip()
    return baslik.strip(), ""


def _dedupe_indeks(basliklar: Sequence[str]) -> List[int]:
    """Normalize başlık dedupe — ilk görülen indeksleri döner."""
    gorulen: Dict[str, int] = {}
    indeksler: List[int] = []
    for i, b in enumerate(basliklar):
        key = _normalize(b.split(" - ")[0] if " - " in b else b)
        if key and key not in gorulen:
            gorulen[key] = i
            indeksler.append(i)
    return indeksler


def haberleri_analiz_et(basliklar: Sequence[str]) -> HaberDuyguSonucu:
    """Başlık listesinden duygu özeti."""
    if not basliklar:
        return HaberDuyguSonucu(
            haber_sayisi=0,
            ort_duygu=0.0,
            neg_sayisi=0,
            kritik_neg_sayisi=0,
            olay_vetosu_sayisi=0,
        )

    uniq_idx = _dedupe_indeks(basliklar)
    skorlu: List[Tuple[str, str, float]] = []
    for i in uniq_idx:
        ham = basliklar[i]
        govde, kaynak = baslik_kaynak_ayir(ham)
        sk = baslik_skoru(govde)
        skorlu.append((govde, kaynak, sk))

    n = len(skorlu)
    ort = sum(s for _, _, s in skorlu) / n if n else 0.0
    neg = sum(1 for _, _, s in skorlu if s < 0)
    kritik = sum(1 for _, _, s in skorlu if s <= -1.0)
    olay_v = sum(1 for b, _, _ in skorlu if olay_vetosu_skoru(b) <= -1.0)

    en_neg = sorted(skorlu, key=lambda x: x[2])[:5]
    en_neg_list = [(b, s) for b, _, s in en_neg if s < 0]

    return HaberDuyguSonucu(
        haber_sayisi=n,
        ort_duygu=round(ort, 3),
        neg_sayisi=neg,
        kritik_neg_sayisi=kritik,
        olay_vetosu_sayisi=olay_v,
        en_negatif_5_baslik=en_neg_list,
        baslik_kaynaklar=skorlu,
    )


def etkin_haber_sayisi(haber_sayisi: int, ort_duygu: float) -> int:
    """Kapı 1/1b — negatif duygu haber sayısını artırır."""
    carpan = 1.0 + max(0.0, -ort_duygu)
    return max(0, int(round(haber_sayisi * carpan)))


def kritik_veto_aktif(sonuc: HaberDuyguSonucu, min_kritik: int = 3, min_kaynak: int = 2) -> bool:
    """≥3 sert olay başlığı ve ≥2 farklı kaynak (erken seçim spekülasyonu sayılmaz)."""
    if sonuc.olay_vetosu_sayisi < min_kritik:
        return False
    kritik_kaynaklar = set()
    for baslik, kaynak, _ in sonuc.baslik_kaynaklar:
        if olay_vetosu_skoru(baslik) <= -1.0:
            kritik_kaynaklar.add(_normalize(kaynak) or _normalize(baslik)[:40])
    return len(kritik_kaynaklar) >= min_kaynak


def veto_basliklari(sonuc: HaberDuyguSonucu) -> List[Tuple[str, float]]:
    """Olay vetosu tetikleyen dedupe başlıklar."""
    return [(b, olay_vetosu_skoru(b)) for b, _, _ in sonuc.baslik_kaynaklar if olay_vetosu_skoru(b) <= -1.0]
