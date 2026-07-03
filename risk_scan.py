# -*- coding: utf-8 -*-
"""
Jeopolitik / siyasi haber taraması — GDELT + Google News TR (Türkçe finans medyası).
GDELT tek başına Türkçe yerel siteleri kaçırabiliyor; Google News yedek/ birincil kaynak.
"""
from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Tuple

import config

TIMEOUT = 12
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MakroPortfoyAsistani/1.0)"}


@dataclass
class HaberTaramaSonucu:
    sayi: int
    kaynak: str
    guvenilir: bool
    detay: str = ""


def rss_basliklari(rss: str) -> List[str]:
    """Google News RSS — haber başlıkları (feed başlığı hariç)."""
    import html as html_mod
    import re

    if not rss:
        return []
    basliklar: List[str] = []
    for block in re.findall(r"<item>(.*?)</item>", rss, re.DOTALL):
        m = re.search(
            r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
            block,
            re.DOTALL,
        )
        if not m:
            continue
        t = html_mod.unescape(m.group(1).strip())
        if t:
            basliklar.append(t)
    return basliklar


def google_news_rss(
    sorgu: str,
    hl: str = "tr",
    gl: str = "TR",
    ceid: str = "TR:tr",
) -> str:
    """Google News RSS metni — locale parametreleriyle TR veya EN kaynak."""
    try:
        import requests

        r = requests.get(
            "https://news.google.com/rss/search",
            params={"q": sorgu, "hl": hl, "gl": gl, "ceid": ceid},
            headers=_HEADERS,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.text
    except Exception:
        return ""


def google_news_sayisi(
    sorgu: str,
    hl: str = "tr",
    gl: str = "TR",
    ceid: str = "TR:tr",
) -> int:
    """Google News RSS — haber sayısı (locale seçilebilir)."""
    return google_news_rss(sorgu, hl=hl, gl=gl, ceid=ceid).count("<item>")


def _gdelt_sorgu(sorgu: str, saat: int = 48) -> Optional[int]:
    try:
        import requests

        r = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": sorgu,
                "mode": "artlist",
                "maxrecords": 75,
                "timespan": f"{saat}h",
                "format": "json",
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return len(r.json().get("articles", []))
    except Exception:
        return None


def gdelt_jeopolitik_sayisi(saat: int = 48) -> Optional[int]:
    """Kısa sorgular — uzun OR listesi GDELT'te 0 dönebiliyor."""
    gruplar = [
        "Hormuz Iran",
        "Iran Israel war",
        '("Hürmüz" OR Hormuz) (Iran OR İran)',
        "İsrail İran savaş sourcelang:turkish",
        "Hürmüz Boğazı sourcelang:turkish",
    ]
    toplam = 0
    basarili = 0
    for sorgu in gruplar:
        n = _gdelt_sorgu(sorgu, saat)
        if n is not None:
            basarili += 1
            toplam = max(toplam, n)
        time.sleep(0.3)
    return toplam if basarili else None


def jeopolitik_risk_tara(saat: int = 48) -> HaberTaramaSonucu:
    """Google News TR öncelikli; GDELT destek; 0 = güvenilir değil."""
    google_sorgular = getattr(
        config,
        "SAVAS_GOOGLE_SORGULARI",
        [
            "Hürmüz Boğazı İran",
            "İsrail İran savaş",
            "ABD İran Hürmüz",
            "İran ateşkes görüşme",
        ],
    )
    google_max = 0
    google_hit = 0
    for sorgu in google_sorgular:
        n = google_news_sayisi(sorgu)
        google_max = max(google_max, n)
        if n > 0:
            google_hit += 1

    gdelt = gdelt_jeopolitik_sayisi(saat)

    if google_max > 0:
        detay = f"Google News TR: {google_hit}/{len(google_sorgular)} sorgu eşleşti"
        if gdelt is not None:
            detay += f" · GDELT ref: {gdelt}"
        return HaberTaramaSonucu(
            sayi=google_max,
            kaynak="Google News TR + GDELT",
            guvenilir=True,
            detay=detay,
        )

    if gdelt is not None and gdelt > 0:
        return HaberTaramaSonucu(
            sayi=gdelt,
            kaynak="GDELT (Google News eşleşmedi)",
            guvenilir=True,
            detay=f"GDELT: {gdelt} haber",
        )

    if gdelt is not None and gdelt == 0:
        return HaberTaramaSonucu(
            sayi=0,
            kaynak="GDELT boş · Google News boş",
            guvenilir=False,
            detay="Tarama sonuç vermedi — aktif jeopolitik risk manuel teyit edin.",
        )

    return HaberTaramaSonucu(
        sayi=0,
        kaynak="Tarama erişilemedi",
        guvenilir=False,
        detay="GDELT/Google News ulaşılamadı — jeopolitik kapı güvenilir değil.",
    )


def siyasi_risk_tara(kelimeler: list, saat: int = 48) -> Tuple[int, str]:
    """Siyasi iç risk — GDELT kısa gruplar + Google News yedek."""
    google_n = google_news_sayisi(" ".join(kelimeler[:3]) + " Türkiye")
    gdelt_n = None
    for i in range(0, len(kelimeler), 3):
        grup = kelimeler[i : i + 3]
        sorgu = " OR ".join(f'"{k}"' for k in grup) + " sourcelang:turkish"
        n = _gdelt_sorgu(sorgu, saat)
        if n is not None:
            gdelt_n = max(gdelt_n or 0, n)

    n = max(google_n, gdelt_n or 0)
    if n > 0:
        return n, "Google News TR + GDELT"
    if gdelt_n is not None or google_n == 0:
        return 3, "GDELT/Google yedek (düşük güven)"
    return 3, "GDELT yedek"
