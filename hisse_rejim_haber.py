# -*- coding: utf-8 -*-
"""
Hisse taraması — makro rejim + haber filtreleri.
Teknik sinyalden sonra skor ayarlanır; olumsuz haber veya uyumsuz rejimde alım düşürülür.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import config

OLUMSUZ_HABER = (
    "iflas", "dava", "ceza", "skandal", "iptal", "erteleme",
    "temettü kes", "temettu kes", "zarar açıklad", "zarar aciklad",
)

OLUMSUZ_HABER_EN = (
    "bankruptcy", "lawsuit", "scandal", "recall", "downgrade",
    "layoff", "layoffs", "investigation", "fraud", "cut dividend",
    "guidance cut", "sec charges", "profit warning", "earnings miss",
)

GUCU_OLUMSUZ = OLUMSUZ_HABER + (
    "iflas", "skandal", "dava", "bankruptcy", "fraud", "scandal", "lawsuit",
)

# (sorgu, hl, gl, ceid)
_HaberSorgu = Tuple[str, str, str, str]


def _haber_sorgulari(ad: str, sembol: str, piyasa: str) -> Tuple[List[_HaberSorgu], Tuple[str, ...], str]:
    """Piyasaya göre Google News sorguları, olumsuz kelimeler ve kaynak etiketi."""
    temiz_ad = ad.split("(")[0].strip()
    if piyasa == "BIST":
        kod = sembol.replace(".IS", "")
        return (
            [
                (f"{temiz_ad} hisse", "tr", "TR", "TR:tr"),
                (f"{kod} borsa", "tr", "TR", "TR:tr"),
                (f"{temiz_ad} BIST", "tr", "TR", "TR:tr"),
            ],
            OLUMSUZ_HABER,
            "Google News TR",
        )

    if piyasa == "ETF":
        rt = sembol.split(".")[0]
        return (
            [
                (f"{rt} ETF", "en", "US", "US:en"),
                (f"{temiz_ad} ETF", "en", "US", "US:en"),
                (f"{rt} UCITS", "en", "GB", "GB:en"),
            ],
            OLUMSUZ_HABER_EN,
            "Google News EN",
        )

    ticker = sembol.replace(".IS", "")
    piyasa_etiket = "NASDAQ" if piyasa == "NASDAQ" else "S&P 500"
    return (
        [
            (f"{ticker} stock", "en", "US", "US:en"),
            (f"{temiz_ad} stock", "en", "US", "US:en"),
            (f"{ticker} earnings", "en", "US", "US:en"),
            (f"{temiz_ad} {piyasa_etiket}", "en", "US", "US:en"),
            (f"{temiz_ad} hisse", "tr", "TR", "TR:tr"),
        ],
        OLUMSUZ_HABER + OLUMSUZ_HABER_EN,
        "Google News EN+TR",
    )


def _haber_basliklari(rss_parcalari: List[Tuple[str, str]], piyasa: str) -> List[str]:
    """Piyasaya göre öncelikli RSS kaynaklarından haber başlıkları."""
    from risk_scan import rss_basliklari

    if piyasa in ("SP500", "NASDAQ", "ETF"):
        for hl, rss in rss_parcalari:
            if hl == "en":
                basliklar = rss_basliklari(rss)
                if basliklar:
                    return basliklar
    basliklar: List[str] = []
    for _, rss in rss_parcalari:
        basliklar.extend(rss_basliklari(rss))
    return basliklar


def _baslik_ilgili(baslik: str, ad: str, sembol: str, piyasa: str = "") -> bool:
    """Başlık ilgili varlığa mı ait — genel piyasa haberlerini ele."""
    b = baslik.lower()
    ad_k = ad.split("(")[0].strip().lower()
    if len(ad_k) >= 4 and ad_k in b:
        return True
    ticker = sembol.replace(".IS", "").split(".")[0].lower()
    if piyasa == "ETF":
        if len(ticker) >= 3 and ticker in b:
            return True
        if "etf" in b and any(k in b for k in ("ucits", "vanguard", "ishares", "xtrackers", "spdr")):
            if any(w in b for w in ad_k.split()[:2] if len(w) >= 4):
                return True
    if len(ticker) >= 3 and re.search(rf"\b{re.escape(ticker)}\b", b):
        return True
    return False


def _haber_sentiment(
    basliklar: List[str],
    ad: str,
    sembol: str,
    olumsuz_kelimeler: Tuple[str, ...],
    piyasa: str = "",
) -> Tuple[int, List[str], bool]:
    """
    Yalnızca şirketle ilgili başlıklarda olumsuz kelime arar.
    Returns: (olumsuz_baslik_sayisi, kelimeler, alim_iptal)
    """
    eslesen: List[str] = []
    olumsuz_say = 0
    guclu = False
    for baslik in basliklar:
        if not _baslik_ilgili(baslik, ad, sembol, piyasa):
            continue
        lower = baslik.lower()
        for k in GUCU_OLUMSUZ:
            if k in lower:
                olumsuz_say += 1
                eslesen.append(k)
                guclu = True
                break
        else:
            for k in olumsuz_kelimeler:
                if k in lower:
                    olumsuz_say += 1
                    eslesen.append(k)
                    break
    alim_iptal = guclu or olumsuz_say >= 2
    return olumsuz_say, eslesen, alim_iptal


@dataclass
class RejimHaberSonucu:
    skor_delta: float
    sinyal: str
    rejim_notu: str
    haber_notu: str
    haber_sayisi: int


def _jeopolitik_yuksek(snap) -> bool:
    if not snap or not snap.veri:
        return False
    v = snap.veri
    if v.savas_risk_guvenilir is False:
        return True
    return (v.savas_risk_makale_sayisi or 0) >= config.SAVAS_RISK_ESIGI


def rejim_hisse_ayarla(
    sinyal: str,
    skor: float,
    gerekce: str,
    piyasa: str,
    sektor: str,
    makro_rejim: str,
    snap=None,
) -> RejimHaberSonucu:
    delta = 0.0
    notlar: List[str] = []
    yeni = sinyal
    jeo = _jeopolitik_yuksek(snap)

    # ── Makro rejim × piyasa/sektör ──
    if makro_rejim in ("KRIZ", "EM_STRES"):
        if piyasa == "BIST":
            delta -= 25
            notlar.append(f"Rejim {makro_rejim}: BIST riski yüksek")
            if yeni in ("ALIM_FIRSATI", "TREND_ALIM"):
                yeni = "BEKLE"
        elif sektor in ("buyume", "teknoloji"):
            delta -= 12
            notlar.append(f"Rejim {makro_rejim}: büyüme/teknoloji baskılanır")
        elif sektor == "defansif":
            delta += 5
            notlar.append("Defansif hisse — stres rejiminde göreli dayanıklı")

    elif makro_rejim == "TL_FIRSAT":
        if piyasa == "BIST" and sektor in ("finans", "sanayi", "holding"):
            delta += 10
            notlar.append("TL fırsat rejimi: yerel finans/sanayi desteklenir")
        if piyasa in ("SP500", "NASDAQ") and sektor == "buyume":
            delta -= 5
            notlar.append("TL fırsat: ABD büyüme hissesi ikincil")

    elif makro_rejim == "ENFLASYON_KORUMA":
        if sektor in ("defansif", "enerji"):
            delta += 8
            notlar.append("Enflasyon koruma: defansif/enerji tercih")
        if sektor == "buyume":
            delta -= 8
            notlar.append("Enflasyon koruma: spekülatif büyüme baskılanır")

    elif makro_rejim == "RISK_ON":
        if piyasa in ("NASDAQ", "SP500") and sektor in ("teknoloji", "buyume"):
            delta += 10
            notlar.append("Risk-on: ABD teknoloji/büyüme desteklenir")
        if piyasa == "ETF" and sektor in ("teknoloji", "abd", "gelisen"):
            delta += 10
            notlar.append("Risk-on: büyüme/teknoloji ETF desteklenir")
        if piyasa == "BIST":
            delta += 3
            notlar.append("Risk-on: BIST sınırlı destek")

    # ── ETF × makro rejim ──
    if piyasa == "ETF":
        if makro_rejim == "ENFLASYON_KORUMA":
            if sektor == "altin":
                delta += 12
                notlar.append("Enflasyon koruma: altın ETF öncelikli")
            elif sektor == "tahvil":
                delta += 6
                notlar.append("Enflasyon koruma: tahvil ETF destek")
            elif sektor in ("teknoloji", "gelisen"):
                delta -= 6
                notlar.append("Enflasyon koruma: riskli ETF baskılanır")
        elif makro_rejim in ("KRIZ", "EM_STRES"):
            if sektor in ("tahvil", "altin"):
                delta += 10
                notlar.append("Stres rejimi: koruma ETF (altın/tahvil) tercih")
            elif sektor in ("teknoloji", "gelisen"):
                delta -= 8
                notlar.append("Stres rejimi: riskli ETF baskılanır")
            elif sektor in ("dunya", "abd") and yeni in ("ALIM_FIRSATI",):
                yeni = "TREND_ALIM"
                notlar.append("Stres rejimi: tek hisse yerine geniş ETF — kademeli")
        elif makro_rejim == "TL_FIRSAT":
            if sektor in ("dunya", "abd", "temettu"):
                delta += 5
                notlar.append("TL fırsat: EUR bazlı küresel ETF cazip (Revolut)")
            if sektor == "gelisen":
                delta -= 4
                notlar.append("TL fırsat: gelişen piyasa ETF ikincil")
        if sektor == "dunya":
            delta += 3
            notlar.append("Çekirdek küresel ETF — portföy diversifikasyonu")

    # ── Jeopolitik / savaş haberleri ──
    if jeo:
        if sektor in ("hava", "enerji"):
            delta -= 15
            notlar.append("Jeopolitik gündem: hava/enerji hassas")
            if yeni == "ALIM_FIRSATI":
                yeni = "BEKLE"
        if sektor == "savunma" and piyasa == "BIST":
            delta += 8
            notlar.append("Jeopolitik gündem: savunma sektörü göreli dayanıklı")
        if sektor == "defansif":
            delta += 4
            notlar.append("Jeopolitik gündem: defansif tercih")

    yeni_skor = max(0, min(100, skor + delta))
    if yeni_skor < 55 and yeni in ("ALIM_FIRSATI", "TREND_ALIM"):
        yeni = "BEKLE"
        notlar.append("Rejim/haber sonrası skor <55 — alım kaldırıldı")

    return RejimHaberSonucu(
        skor_delta=delta,
        sinyal=yeni,
        rejim_notu="; ".join(notlar) if notlar else "Rejim uyumlu",
        haber_notu="",
        haber_sayisi=0,
    )


def hisse_haber_kontrol(ad: str, sembol: str, piyasa: str) -> Tuple[int, str, float, bool]:
    """
    Google News — BIST için TR, ABD (S&P/NASDAQ) için EN+TR haber taraması.
    Returns: (haber_sayisi, not, skor_delta, alim_iptal)
    """
    from risk_scan import google_news_rss

    sorgular, olumsuz_kelimeler, kaynak = _haber_sorgulari(ad, sembol, piyasa)

    max_n = 0
    rss_parcalari: List[Tuple[str, str]] = []
    for sorgu, hl, gl, ceid in sorgular:
        rss = google_news_rss(sorgu, hl=hl, gl=gl, ceid=ceid)
        if rss:
            max_n = max(max_n, rss.count("<item>"))
            rss_parcalari.append((hl, rss))

    if max_n == 0:
        return 0, f"Son 48s: haber taraması boş ({kaynak}, nötr)", 0.0, False

    delta = 0.0
    alim_iptal = False
    haber_ozet = f"Son 48s: ~{max_n} haber ({kaynak})"
    basliklar = _haber_basliklari(rss_parcalari, piyasa)
    if basliklar:
        olumsuz_say, kelimeler, alim_iptal = _haber_sentiment(
            basliklar, ad, sembol, olumsuz_kelimeler, piyasa,
        )
        if alim_iptal:
            delta -= 12
            haber_ozet += f" · olumsuz başlık ({olumsuz_say}): {', '.join(list(dict.fromkeys(kelimeler))[:3])}"
        elif max_n >= 15:
            delta += 3
            haber_ozet += " · yoğun gündem (nötr/pozitif varsayım)"
        elif olumsuz_say == 1:
            delta -= 4
            haber_ozet += f" · hafif olumsuz: {kelimeler[0]}"
    elif max_n >= 15:
        delta += 3
        haber_ozet += " · yoğun gündem (nötr/pozitif varsayım)"

    return max_n, haber_ozet, delta, alim_iptal


def haber_filtresi_uygula(
    adaylar: list,
    max_kontrol: int = 25,
) -> None:
    """HisseAnaliz listesine yerinde haber + skor uygular (adaylar zaten sıralı)."""
    for h in adaylar[:max_kontrol]:
        if h.sinyal not in ("ALIM_FIRSATI", "TREND_ALIM") and h.skor < 50:
            continue
        n, haber_ozet, delta, alim_iptal = hisse_haber_kontrol(h.ad, h.sembol, h.piyasa)
        h.haber_sayisi = n
        h.haber_notu = haber_ozet
        h.skor = max(0, min(100, h.skor + delta))
        if alim_iptal and h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM"):
            if h.skor < 55:
                h.sinyal = "BEKLE"
                h.gerekce += "; Olumsuz haber — alım kaldırıldı"
            else:
                h.gerekce += "; Olumsuz haber uyarısı — skor düşürüldü"
        elif h.haber_notu:
            h.gerekce += f"; {h.haber_notu}"
