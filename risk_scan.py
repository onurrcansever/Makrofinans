# -*- coding: utf-8 -*-
"""
Jeopolitik / siyasi haber taraması — GDELT + Google News TR (Türkçe finans medyası).
Google News: when:Nd + pubDate ile yalnızca güncel haberler sayılır.
"""
from __future__ import annotations

import email.utils
import html as html_mod
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


def _simdi_utc() -> datetime:
    return datetime.now(timezone.utc)


def _rss_ogeleri(rss: str) -> List[Tuple[str, Optional[datetime]]]:
    """Google News RSS — (başlık, yayın tarihi UTC)."""
    if not rss:
        return []
    ogeler: List[Tuple[str, Optional[datetime]]] = []
    for block in re.findall(r"<item>(.*?)</item>", rss, re.DOTALL):
        title_m = re.search(
            r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
            block,
            re.DOTALL,
        )
        pub_m = re.search(r"<pubDate>(.*?)</pubDate>", block, re.DOTALL)
        if not title_m:
            continue
        baslik = html_mod.unescape(title_m.group(1).strip())
        pub: Optional[datetime] = None
        if pub_m:
            try:
                pub = email.utils.parsedate_to_datetime(pub_m.group(1).strip())
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                else:
                    pub = pub.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pub = None
        if baslik:
            ogeler.append((baslik, pub))
    return ogeler


def rss_basliklari(rss: str) -> List[str]:
    return [t for t, _ in _rss_ogeleri(rss)]


def _when_gun(saat: int) -> int:
    return max(1, min(7, (saat + 23) // 24))


def google_news_rss(
    sorgu: str,
    hl: str = "tr",
    gl: str = "TR",
    ceid: str = "TR:tr",
    saat: int = 48,
) -> str:
    """Google News RSS — sorguya when:Nd eklenir."""
    when = _when_gun(saat)
    q = sorgu if " when:" in sorgu else f"{sorgu} when:{when}d"
    try:
        import requests

        r = requests.get(
            "https://news.google.com/rss/search",
            params={"q": q, "hl": hl, "gl": gl, "ceid": ceid},
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
    saat: int = 48,
    tarih_filtre: bool = True,
) -> int:
    """Google News — yalnızca son `saat` içinde yayınlanan haberler."""
    rss = google_news_rss(sorgu, hl=hl, gl=gl, ceid=ceid, saat=saat)
    if not tarih_filtre:
        return rss.count("<item>")
    cutoff = _simdi_utc() - timedelta(hours=saat)
    n = 0
    for _, pub in _rss_ogeleri(rss):
        if pub is not None and pub >= cutoff:
            n += 1
    return n


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


def jeopolitik_risk_tara(saat: int = 48, hizli: bool = False) -> HaberTaramaSonucu:
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
    pencere = f"son {saat}s"
    if hizli:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        google_max = 0
        google_hit = 0
        with ThreadPoolExecutor(max_workers=min(4, len(google_sorgular))) as ex:
            futs = {
                ex.submit(google_news_sayisi, s, saat=saat): s
                for s in google_sorgular[:2]
            }
            for fut in as_completed(futs, timeout=8):
                try:
                    n = fut.result()
                    google_max = max(google_max, n)
                    if n > 0:
                        google_hit += 1
                except Exception:
                    pass
        return HaberTaramaSonucu(
            sayi=google_max,
            kaynak="Google News TR (canlı, tarih filtreli)",
            guvenilir=True,
            detay=f"{pencere} · hızlı tarama: {google_hit} sorgu",
        )

    google_max = 0
    google_hit = 0
    for sorgu in google_sorgular:
        n = google_news_sayisi(sorgu, saat=saat)
        google_max = max(google_max, n)
        if n > 0:
            google_hit += 1

    gdelt = gdelt_jeopolitik_sayisi(saat)

    if google_max > 0:
        detay = f"{pencere} · Google: {google_hit}/{len(google_sorgular)} sorgu"
        if gdelt is not None:
            detay += f" · GDELT ref: {gdelt}"
        return HaberTaramaSonucu(
            sayi=google_max,
            kaynak="Google News TR + GDELT (tarih filtreli)",
            guvenilir=True,
            detay=detay,
        )

    if gdelt is not None and gdelt > 0:
        return HaberTaramaSonucu(
            sayi=gdelt,
            kaynak="GDELT (Google News eşleşmedi)",
            guvenilir=True,
            detay=f"{pencere} · GDELT: {gdelt} haber",
        )

    if gdelt is not None and gdelt == 0:
        return HaberTaramaSonucu(
            sayi=0,
            kaynak="GDELT boş · Google News boş",
            guvenilir=False,
            detay=f"{pencere} — tarama sonuç vermedi.",
        )

    return HaberTaramaSonucu(
        sayi=0,
        kaynak="Tarama erişilemedi",
        guvenilir=False,
        detay="GDELT/Google News ulaşılamadı.",
    )


def siyasi_risk_say(
    kelimeler: list,
    saat: int = 48,
) -> Tuple[int, str, str]:
    """
    Siyasi iç risk — tüm kelime grupları taranır, en yüksek sayı alınır.
    Dönüş: (sayi, kaynak, detay)
    """
    pencere = f"son {saat}s ({datetime.now().strftime('%d.%m.%Y')} itibarıyla)"
    google_sorgular = getattr(
        config,
        "SIYASI_GOOGLE_SORGULARI",
        [" OR ".join(f'"{k}"' for k in kelimeler[:3]) + " Türkiye"],
    )
    google_max = 0
    google_kaynak_idx = 0
    for idx, sorgu in enumerate(google_sorgular):
        n = google_news_sayisi(sorgu, saat=saat)
        if n > google_max:
            google_max = n
            google_kaynak_idx = idx + 1

    gdelt_max: Optional[int] = None
    for i in range(0, len(kelimeler), 3):
        grup = kelimeler[i : i + 3]
        sorgu = " OR ".join(f'"{k}"' for k in grup) + " sourcelang:turkish"
        n = _gdelt_sorgu(sorgu, saat)
        if n is not None:
            gdelt_max = max(gdelt_max or 0, n)

    n = max(google_max, gdelt_max or 0)
    detay = f"{pencere} · Google sorgu #{google_kaynak_idx}: {google_max}"
    if gdelt_max is not None:
        detay += f" · GDELT max: {gdelt_max}"

    if n > 0:
        kaynak = "Google News TR (tarih filtreli)"
        if gdelt_max is not None:
            kaynak += " + GDELT"
        return n, kaynak, detay

    return 0, "Google News TR (tarih filtreli)", f"{pencere} · eşleşme yok"


def siyasi_risk_tara(kelimeler: list, saat: int = 48) -> Tuple[int, str]:
    """Geriye dönük uyumluluk."""
    n, kaynak, _ = siyasi_risk_say(kelimeler, saat=saat)
    if n > 0:
        return n, kaynak
    return 3, "GDELT/Google yedek (düşük güven)"
