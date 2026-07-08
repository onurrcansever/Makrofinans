# -*- coding: utf-8 -*-
"""
Yatırımcı Profili
==================
Risk toleransı ve yatırım vadesine göre tahsis sınırlarını ve skorları ayarlar.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

RISK_SECENEKLERI = {
    "dusuk": "Düşük risk — sermayeyi korumak öncelik",
    "orta": "Orta risk — denge (mevduat + sınırlı büyüme)",
    "yuksek": "Yüksek risk — getiri odaklı, dalgalanmaya tolerans",
}

VADE_SECENEKLERI = {
    "kisa_3": "Çok kısa vade (0–3 ay)",
    "kisa_6": "Kısa vade (0–6 ay)",
    "kisa": "Orta-kısa vade (0–12 ay)",
    "orta": "Orta vade (1–3 yıl)",
    "uzun": "Uzun vade (3+ yıl)",
}

VADE_GUN = {
    "kisa_3": 90,
    "kisa_6": 181,
    "kisa": 365,
    "orta": 730,
    "uzun": 1095,
}

# Profil vadesine karşılık gelen mevduat tenörü (Yapı Kredi vadeleri)
VADE_MEVDUAT_ESLESTIRME = {
    "kisa_3": ("TL 3 ay", 92),
    "kisa_6": ("TL 6 ay", 181),
    "kisa": ("TL 6 ay", 181),
    "orta": ("TL 6 ay", 181),
    "uzun": ("TL 1 yıl", 365),
}

VADELER_KISA = frozenset({"kisa_3", "kisa_6", "kisa"})
VADELER_COK_KISA = frozenset({"kisa_3", "kisa_6"})


def vade_kisa_mi(vade: str) -> bool:
    return vade in VADELER_KISA


def vade_cok_kisa_mi(vade: str) -> bool:
    return vade in VADELER_COK_KISA


@dataclass
class YatirimProfili:
    risk: str = "orta"
    vade: str = "orta"
    amac: str = "sermaye_koruma"  # sermaye_koruma | dengeli | buyume

    def ozet(self) -> str:
        return (
            f"{RISK_SECENEKLERI.get(self.risk, self.risk)} · "
            f"{VADE_SECENEKLERI.get(self.vade, self.vade)}"
        )


def profil_mevduat_vadesi(profil: YatirimProfili) -> Tuple[str, int]:
    return VADE_MEVDUAT_ESLESTIRME.get(profil.vade, VADE_MEVDUAT_ESLESTIRME["orta"])


def profil_sinirlari(profil: YatirimProfili) -> Tuple[Dict[str, float], Dict[str, float], int, float]:
    """
    MIN/MAX ağırlık, kalan_gun, mutlak_tavan döner.
    """
    min_a = {
        "eur_cash": 0.10, "usd_cash": 0.05, "tl_deposit": 0.00,
        "gold": 0.05, "silver": 0.00, "bist": 0.00, "crypto": 0.00,
    }
    max_a = {
        "eur_cash": 0.55, "usd_cash": 0.30, "tl_deposit": 0.50,
        "gold": 0.35, "silver": 0.08, "bist": 0.15, "crypto": 0.08,
    }
    kalan_gun = VADE_GUN.get(profil.vade, 730)
    mutlak_tavan = 0.50

    if profil.risk == "dusuk":
        min_a["eur_cash"] = 0.25
        min_a["usd_cash"] = 0.10
        min_a["gold"] = 0.10
        max_a["tl_deposit"] = 0.20
        max_a["bist"] = 0.05
        max_a["crypto"] = 0.00
        max_a["silver"] = 0.05
        mutlak_tavan = 0.35

    elif profil.risk == "yuksek":
        max_a["bist"] = 0.22
        max_a["crypto"] = 0.12
        max_a["tl_deposit"] = 0.50
        max_a["silver"] = 0.15
        mutlak_tavan = 0.60

    if profil.vade == "kisa_3":
        min_a["eur_cash"] = max(min_a["eur_cash"], 0.30)
        min_a["usd_cash"] = max(min_a["usd_cash"], 0.10)
        max_a["bist"] = min(max_a["bist"], 0.03)
        max_a["crypto"] = min(max_a["crypto"], 0.00)
        max_a["gold"] = min(max_a["gold"], 0.20)
        max_a["silver"] = min(max_a["silver"], 0.03)
        kalan_gun = VADE_GUN["kisa_3"]

    elif profil.vade == "kisa_6":
        min_a["eur_cash"] = max(min_a["eur_cash"], 0.25)
        max_a["bist"] = min(max_a["bist"], 0.05)
        max_a["crypto"] = min(max_a["crypto"], 0.02)
        kalan_gun = VADE_GUN["kisa_6"]

    elif profil.vade == "kisa":
        min_a["eur_cash"] = max(min_a["eur_cash"], 0.20)
        if profil.risk == "yuksek":
            max_a["bist"] = min(max_a["bist"], 0.12)
            max_a["crypto"] = min(max_a["crypto"], 0.05)
            max_a["silver"] = min(max_a["silver"], 0.10)
        elif profil.risk == "orta":
            max_a["bist"] = min(max_a["bist"], 0.08)
            max_a["crypto"] = min(max_a["crypto"], 0.03)
        else:
            max_a["bist"] = min(max_a["bist"], 0.06)
            max_a["crypto"] = min(max_a["crypto"], 0.02)
            max_a["silver"] = min(max_a["silver"], 0.05)
        kalan_gun = VADE_GUN["kisa"]

    elif profil.vade == "uzun":
        max_a["bist"] = min(max_a["bist"] + 0.05, 0.25)
        max_a["gold"] = min(max_a["gold"] + 0.05, 0.40)
        kalan_gun = VADE_GUN["uzun"]

    return min_a, max_a, kalan_gun, mutlak_tavan


def profil_skor_ayari(profil: YatirimProfili) -> Dict[str, float]:
    """Varlık skorlarına eklenecek delta."""
    delta = {k: 0.0 for k in [
        "eur_cash", "usd_cash", "tl_deposit", "gold", "silver", "bist", "crypto"
    ]}

    if profil.risk == "dusuk":
        delta["eur_cash"] += 15
        delta["usd_cash"] += 10
        delta["gold"] += 12
        delta["bist"] -= 20
        delta["crypto"] -= 25
        delta["tl_deposit"] -= 5

    elif profil.risk == "yuksek":
        delta["bist"] += 12
        delta["crypto"] += 10
        delta["tl_deposit"] += 8
        delta["silver"] += 5
        delta["eur_cash"] -= 5

    if profil.vade == "kisa_3":
        delta["eur_cash"] += 18
        delta["usd_cash"] += 12
        if profil.risk == "yuksek":
            delta["tl_deposit"] += 2
        elif profil.risk == "orta":
            delta["tl_deposit"] += 0
        else:
            delta["tl_deposit"] -= 12
        delta["bist"] -= 18
        delta["crypto"] -= 25
        delta["gold"] -= 5

    elif profil.vade == "kisa_6":
        delta["eur_cash"] += 14
        delta["usd_cash"] += 10
        if profil.risk == "dusuk":
            delta["tl_deposit"] -= 8
        elif profil.risk == "orta":
            delta["tl_deposit"] += 1
        else:
            delta["tl_deposit"] += 3
        delta["bist"] -= 14
        delta["crypto"] -= 18

    elif profil.vade == "kisa":
        delta["eur_cash"] += 10
        delta["usd_cash"] += 8
        delta["bist"] -= 8
        delta["crypto"] -= 15
        if profil.risk == "yuksek":
            delta["bist"] += 10
            delta["tl_deposit"] += 4
            delta["silver"] -= 10
        elif profil.risk == "orta":
            delta["bist"] -= 2
            delta["silver"] -= 3

    elif profil.vade == "uzun":
        delta["bist"] += 8
        delta["gold"] += 5
        delta["tl_deposit"] += 5

    return delta


def profil_degerlendirme(profil: YatirimProfili, rejim: str) -> List[str]:
    """Profil + makro uyumu hakkında kısa yorumlar."""
    notlar = [f"Profiliniz: {profil.ozet()}"]

    if profil.risk == "dusuk" and rejim in ("EM_STRES", "KRIZ", "ENFLASYON_KORUMA"):
        notlar.append("Düşük risk profilinizle uyumlu: öneri defansif (EUR/altın ağırlıklı).")
    elif profil.risk == "yuksek" and rejim == "TL_FIRSAT":
        if profil.vade == "kisa":
            notlar.append(
                "Yüksek risk + TL fırsat rejimi: **0–12 ay vade** ana belirleyici — "
                "BIST tavanı risk seviyesine göre **%12'ye** kadar kademelenir; "
                "TL payı 4 kapı + vade tabanı ile sınırlı kalabilir."
            )
        elif vade_kisa_mi(profil.vade):
            notlar.append(
                "Yüksek risk + TL fırsat rejimi: kısa vade tavanları TL/BIST artışını "
                "sınırlar — risk profili bu vadede **kademeli** etki eder."
            )
        else:
            notlar.append(
                "Yüksek risk + TL fırsat rejimi: TL/BIST payı artırılabilir (4 kapı tavanına kadar)."
            )
    elif profil.risk == "yuksek" and rejim == "KRIZ":
        notlar.append("Yüksek risk profili olsa da KRİZ rejiminde sistem yine defansife çeker — bu bilinçli bir koruma.")

    if profil.vade == "kisa_3":
        notlar.append(
            "0–3 ay: vade filtresi risk profilinizi büyük ölçüde **eziyor** — "
            "BIST/kripto kapalı veya minimal; yüksek risk seçseniz bile portföy mevduat ağırlıklı kalır."
        )
        if profil.risk == "yuksek":
            notlar.append(
                "Yüksek risk + 0–3 ay: getiri beklentiniz kısa vade kısıtı nedeniyle "
                "tahsis tablosuna yansımaz — bu bilinçli bir tasarım tercihidir."
            )
    elif profil.vade == "kisa_6":
        notlar.append(
            "0–6 ay: volatil varlıklar sınırlı; **TL 6 ay** mevduat ve EUR likidite öncelikli."
        )
    elif profil.vade == "kisa":
        if profil.risk == "yuksek":
            notlar.append(
                "0–12 ay + yüksek risk: BIST tavanı **%12**, gümüş yerine BIST skoruna "
                "öncelik verilir; mevduat/emtia ağırlığı yine baskın kalabilir."
            )
        else:
            notlar.append(
                "0–12 ay: volatil varlıklar (BIST, kripto) üst sınırları düşürüldü — "
                "risk profili bu vadede **sınırlı** etki eder."
            )
    elif profil.vade == "uzun":
        notlar.append("Uzun vade: büyüme varlıklarına (BIST, altın) daha fazla alan tanındı.")

    return notlar
