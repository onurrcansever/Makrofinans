# -*- coding: utf-8 -*-
"""
TL mevduat kararı — canlı veriye göre dinamik özet.
Her yenilemede rejim + 4 kapı + reel faiz + profil vadesi birlikte değerlendirilir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from allocation_engine import TahsisSonucu
import config
from macro_data import MacroSnapshot
from rates_tr import MevduatKarsilastirma
from siyasi_esik import esikler, esik_metni


@dataclass
class TlDurumOzeti:
    durum: str          # ONERILMIYOR | SINIRLI | CAZIP | GUCLU
    baslik: str
    agirlik_pct: float
    tavan_pct: float
    rejim: str
    nedenler: List[str] = field(default_factory=list)
    alternatif: str = ""


def tl_durum_olustur(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    mevduat: Optional[MevduatKarsilastirma] = None,
) -> TlDurumOzeti:
    v = snap.veri
    rejim = tahsis.rejim.rejim
    w = tahsis.agirliklar.get("tl_deposit", 0) * 100
    tavan = tahsis.tl_tavan_oran * 100
    tcmb = v.tcmb_politika_faizi or 37
    enf = snap.enflasyon_tr_yillik or 35
    reel_politika = tcmb - enf
    cds = v.cds_5y_bp
    siyasi = v.siyasi_risk_makale_sayisi
    nedenler: List[str] = []

    if mevduat and mevduat.profil_vade_reel is not None:
        reel_mevduat = mevduat.profil_vade_reel
        eur_t = mevduat.profil_vade_eur_tahmini
        nedenler.append(
            f"Mevduat reel (banka net − enflasyon): **{reel_mevduat:+.1f} pp** "
            f"({mevduat.profil_vade or 'TL mevduat'}, net %{mevduat.profil_vade_net:.1f})."
        )
        nedenler.append(
            f"Politika faizi reel **{reel_politika:+.1f} pp** (TCMB − enflasyon — makro/rejim göstergesi)."
        )
        nedenler.append(
            f"EUR bazlı tahmini: **{eur_t:+.1f} pp** — kur hızlanırsa negatif olabilir; "
            f"EUR garantisi değildir."
        )
        if mevduat.breakeven_eur_try and mevduat.kur_spot_eur_try:
            oran = mevduat.kur_spot_eur_try / mevduat.breakeven_eur_try
            nedenler.append(
                f"Başa baş kur: spot **{mevduat.kur_spot_eur_try:.2f}** · "
                f"eşit getiri **{mevduat.breakeven_eur_try:.2f}** (oran {oran:.2f})."
            )
    else:
        reel_mevduat = reel_politika
        nedenler.append(
            f"Politika faizi − enflasyon ≈ **{reel_politika:+.1f} pp** "
            f"(makro gösterge — banka net reel mevduat tablosunda ayrı)."
        )

    cds_kaynak = (snap.kaynak_haritasi or {}).get("cds", "")
    if cds is not None:
        cds_ek = ""
        if any(x in cds_kaynak.lower() for x in ("model", "proxy", "vol")):
            cds_ek = " ⚠️ **model tahmini** — gerçek CDS kotasyonu değil; TL tavanı hassas."
        nedenler.append(f"CDS 5Y **{cds:.0f} bp** → 4 kapı TL tavanı **%{tavan:.0f}**.{cds_ek}")
    else:
        nedenler.append("CDS verisi yok → güvenlik için TL tavanı **%0**.")

    if v.rezerv_artiyor is False:
        nedenler.append("TCMB rezerv trendi **azalıyor** — Kapı 4 tavanı ×0,7 uygulandı.")
    elif v.rezerv_artiyor is True:
        nedenler.append("TCMB rezerv trendi **artıyor** — Kapı 4 engeli yok.")
    else:
        nedenler.append(
            "Rezerv trendi **bilinmiyor** — Kapı 4 temkin çarpanı (×0,85) uygulandı; "
            f"EVDS key ile gerçek veri önerilir."
        )

    nedenler.append(f"Aktif makro rejim: **{tahsis.rejim.etiket}**.")

    es = esikler()
    if siyasi is not None and siyasi >= es["kriz"]:
        nedenler.append(
            f"Siyasi haber yoğunluğu yüksek (**{siyasi}**/{config.SIYASI_RISK_TARAMA_SAAT}s, "
            f"kriz eşiği {es['kriz']}) — TL riskli."
        )
    elif siyasi is not None and siyasi >= es["temkin"]:
        nedenler.append(
            f"Siyasi haber yükselmiş (**{siyasi}**/{config.SIYASI_RISK_TARAMA_SAAT}s, "
            f"temkin eşiği {es['temkin']}) — TL fırsatı sınırlı."
        )
    elif siyasi is not None:
        nedenler.append(
            f"Siyasi haber **{siyasi}**/{config.SIYASI_RISK_TARAMA_SAAT}s "
            f"({esik_metni()})."
        )

    savas = v.savas_risk_makale_sayisi
    if savas is not None and savas >= 6:
        nedenler.append(
            f"Jeopolitik/savaş haberleri **{savas}**/48s (Hürmüz, İran vb.) — "
            f"enerji ve kur kanalı riski yüksek."
        )

    if rejim == "KRIZ" or tavan < 0.5 or w < 1:
        return TlDurumOzeti(
            durum="ONERILMIYOR",
            baslik="TL mevduat şu an önerilmiyor",
            agirlik_pct=w,
            tavan_pct=tavan,
            rejim=rejim,
            nedenler=nedenler,
            alternatif="EUR/USD mevduat ve altın ağırlıklı defansif portföy.",
        )

    if reel_mevduat <= 0 or rejim in ("EM_STRES", "ENFLASYON_KORUMA"):
        if w < 5:
            baslik = "TL mevduat önerilmiyor — reel getiri veya stres ortamı"
        else:
            baslik = "TL mevduat sınırlı — enflasyonu yenemiyor veya stres var"
        return TlDurumOzeti(
            durum="SINIRLI" if w >= 1 else "ONERILMIYOR",
            baslik=baslik,
            agirlik_pct=w,
            tavan_pct=tavan,
            rejim=rejim,
            nedenler=nedenler,
            alternatif="EUR mevduat + altın; TL yalnızca çok küçük pay veya sıfır.",
        )

    if rejim == "TL_FIRSAT" and reel_mevduat > 0 and w >= 12:
        return TlDurumOzeti(
            durum="GUCLU",
            baslik="TL mevduat cazip — canlı koşullar uygun",
            agirlik_pct=w,
            tavan_pct=tavan,
            rejim=rejim,
            nedenler=nedenler,
            alternatif="Kalan pay EUR/altın ile dengelenir; kur riski izlenmeli.",
        )

    if w >= 5 and reel_mevduat > 0:
        return TlDurumOzeti(
            durum="CAZIP",
            baslik="TL mevduat kısmen cazip — sınırlı tahsis",
            agirlik_pct=w,
            tavan_pct=tavan,
            rejim=rejim,
            nedenler=nedenler,
            alternatif="Kademeli giriş; rejim değişirse TL payı otomatik düşer.",
        )

    return TlDurumOzeti(
        durum="SINIRLI",
        baslik="TL mevduat minimal — makro nötr veya zayıf sinyal",
        agirlik_pct=w,
        tavan_pct=tavan,
        rejim=rejim,
        nedenler=nedenler,
        alternatif="Ana para EUR'da; TL yalnızca küçük taktik pay.",
    )
