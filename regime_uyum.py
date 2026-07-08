# -*- coding: utf-8 -*-
"""
Rejim ↔ TL kapıları ↔ danışman metni uyumu.
Skor/rejim state ile 4 kapı sonucu çelişmesin.
"""
from __future__ import annotations

from copy import deepcopy
from typing import List, Optional

from macro_data import MacroSnapshot
from regime import REJIMLER, RejimSonucu
from siyasi_esik import esikler
from siyasi_etkin import kap1_haber_sayisi, siyasi_kriz_mi
from tl_engine import TlKararPaketi


def tl_firsat_askida_mi(snap: MacroSnapshot, ham: RejimSonucu) -> bool:
    v = snap.veri
    if v.tl_makro_risk_aktif:
        return True
    if any("askıya alındı" in a for a in (ham.adimlar or [])):
        return True
    if ham.rejim != "TL_FIRSAT":
        return True
    return False


def tl_askida_aciklama(snap: MacroSnapshot) -> str:
    v = snap.veri
    parcalar: List[str] = []
    if v.tl_erken_secim_anormal and v.tl_erken_secim_haber:
        parcalar.append(f"erken seçim haber yoğunluğu ({v.tl_erken_secim_haber} haber)")
    elif v.tl_faiz_indirim_haber and v.tl_faiz_indirim_haber >= 8:
        parcalar.append(f"faiz indirimi beklentisi ({v.tl_faiz_indirim_haber} haber)")
    elif v.tl_makro_risk_aktif:
        parcalar.append("TL makro haber riski")
    if not parcalar:
        parcalar.append("makro kısıt")
    return (
        f"Reel faiz lehte olabilir; ancak {parcalar[0]} nedeniyle "
        f"TL fırsat rejimi askıda — 4 kapı tahsisi kısıtlı veya kapalı."
    )


def _aciklama_duzelt(rejim_kodu: str, ham: Optional[RejimSonucu] = None) -> str:
    if ham and ham.rejim == rejim_kodu and ham.aciklama:
        return ham.aciklama
    sabit = {
        "TL_FIRSAT": "TL mevduat cazip; 4 kapılı tavan kuralları geçerli.",
        "NOTR": "Dengeli dağılım; mevcut makro verilere göre kademeli tahsis.",
        "EM_STRES": "Gelişen piyasa stresi; EUR/USD ve altın ağırlığı artırılmalı.",
        "KRIZ": "Pozisyon açmayın; likit ve güvenli varlıklara yönelin.",
        "BELIRSIZ": "Eşik yakınında; komşu rejim ortalaması kullanılır.",
        "RISK_ON": "Piyasa sakin; kontrollü risk iştahı değerlendirilebilir.",
        "ENFLASYON_KORUMA": "Satın alma gücü koruma modu; altın ve EUR ağırlığı artırılır.",
    }
    return sabit.get(rejim_kodu, REJIMLER.get(rejim_kodu, rejim_kodu))


def rejim_skorla_uyumla(
    rejim: RejimSonucu,
    ham: RejimSonucu,
    snap: MacroSnapshot,
    etkin_siyasi: Optional[int] = None,
    ham_siyasi: Optional[int] = None,
) -> RejimSonucu:
    """Skor v2 çıktısını ham rejim + çift kapılı siyasi kriz eşiği ile hizala."""
    raw = ham_siyasi if ham_siyasi is not None else (snap.veri.siyasi_risk_makale_sayisi or 0)
    etkin = etkin_siyasi if etkin_siyasi is not None else raw
    kap1 = kap1_haber_sayisi(raw, etkin)
    r = deepcopy(rejim)
    adimlar = list(r.adimlar or [])

    if siyasi_kriz_mi(raw, etkin):
        adimlar.append(
            f"Siyasi kapı sayımı {kap1} (ham {raw}, etkin {etkin}) — rejim KRİZ"
        )
        return RejimSonucu(
            rejim="KRIZ",
            etiket=REJIMLER["KRIZ"],
            aciklama=_aciklama_duzelt("KRIZ", ham),
            guven=0.9,
            adimlar=adimlar,
        )

    if ham.rejim in ("KRIZ", "EM_STRES", "ENFLASYON_KORUMA") and r.rejim == "TL_FIRSAT":
        adimlar.append(f"Ham rejim {ham.rejim} — skor TL_FIRSAT hedefi iptal")
        r.rejim = ham.rejim
        r.etiket = REJIMLER.get(ham.rejim, ham.etiket)
        r.aciklama = ham.aciklama
        r.adimlar = adimlar
        return r

    if r.rejim == "TL_FIRSAT" and tl_firsat_askida_mi(snap, ham):
        adimlar.extend(a for a in (ham.adimlar or []) if "askıya" in a)
        r.etiket = "TL fırsat (askıda)"
        r.aciklama = tl_askida_aciklama(snap)
        r.adimlar = adimlar
        return r

    r.etiket = REJIMLER.get(r.rejim, r.etiket)
    r.aciklama = _aciklama_duzelt(r.rejim, ham if r.rejim == ham.rejim else None)
    r.adimlar = adimlar
    return r


def rejim_kapilarla_uyumla(
    rejim: RejimSonucu,
    ham: RejimSonucu,
    snap: MacroSnapshot,
    tl_paket: TlKararPaketi,
) -> RejimSonucu:
    """TL karar motoru sonrası gösterim rejimini kesinleştir."""
    r = deepcopy(rejim)
    adimlar = list(r.adimlar or [])
    sonuc = tl_paket.sonuc

    if not sonuc.kapi1_gecti or sonuc.tavan_oran < 0.001:
        adimlar.append("Kapı 1 / TL tavan: pozisyon kapalı — rejim gösterimi güncellendi")
        if siyasi_kriz_mi(
            tl_paket.sentiment.siyasi.haber_sayisi,
            tl_paket.sentiment.etkin_siyasi,
        ):
            etiket = REJIMLER["KRIZ"]
            aciklama = sonuc.kapi1_gerekce or "Kapı 1 — TL tahsisi kapalı."
        else:
            etiket = "Yüksek siyasi haber yoğunluğu"
            aciklama = (
                sonuc.kapi1_gerekce
                or "Siyasi haber eşiği aşıldı; jeopolitik kriz değil — TL tahsisi kapalı."
            )
        return RejimSonucu(
            rejim="KRIZ",
            etiket=etiket,
            aciklama=aciklama,
            guven=0.88,
            adimlar=adimlar,
        )

    if r.rejim == "TL_FIRSAT" and tl_firsat_askida_mi(snap, ham):
        r.etiket = "TL fırsat (askıda)"
        r.aciklama = tl_askida_aciklama(snap)
        r.adimlar = adimlar
        return r

    if r.rejim == "TL_FIRSAT" and sonuc.tavan_oran < 0.05:
        r.etiket = "TL fırsat (sınırlı)"
        r.aciklama = (
            f"TL fırsat koşulları kısmen sağlanıyor; 4 kapı tavanı "
            f"%{sonuc.tavan_oran*100:.0f} — kademeli ve küçük pay."
        )
        r.adimlar = adimlar
        return r

    r.aciklama = _aciklama_duzelt(r.rejim, ham if r.rejim == ham.rejim else None)
    r.etiket = REJIMLER.get(r.rejim, r.etiket)
    return r


def rejim_gosterim_metni(rejim: RejimSonucu, tl_tavan: float) -> str:
    """UI banner — tek satır, çelişkisiz."""
    if rejim.etiket.startswith("TL fırsat") and tl_tavan < 0.01:
        return f"**{rejim.etiket}** — TL tavanı %0 (Kapı 1/kriz)."
    return f"**{rejim.etiket}** — {rejim.aciklama}"
