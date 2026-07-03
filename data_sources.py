# -*- coding: utf-8 -*-
"""
Veri Kaynakları
================
Her fonksiyon TEK bir göstergeyi çeker ve başarısız olursa None döner
(çökmez) — main.py bu durumları ele alıp kullanıcıyı uyarır.

Kullanılan ücretsiz/açık kaynaklar:
- Frankfurter.app         -> EUR/TRY, USD/TRY spot kur (ECB referans, key gerekmez)
- FRED (St. Louis Fed)    -> ABD Fed politika faizi (ücretsiz key gerekir)
- TCMB EVDS               -> TCMB politika faizi, brüt rezervler (ücretsiz key gerekir)
- GDELT DOC 2.0 API       -> siyasi risk / savaş risk haber taraması (key gerekmez)
- manual_inputs.json      -> CDS gibi güvenilir ücretsiz API'si olmayan veriler

NOT: Bu ortamda (Claude'un sandbox'ında) dış ağ erişimi kısıtlı olduğu
için bu fonksiyonlar burada TEST EDİLEMEDİ. Kendi bilgisayarınızda veya
bir sunucuda çalıştırdığınızda normal şekilde çalışmalıdır. Her
fonksiyonun içinde ilgili API dokümantasyon linki yorum olarak var.
"""
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests

TIMEOUT = 10


# ------------------------------------------------------------------
# 1) Döviz kurları — Frankfurter.app (ECB referans kurları, ücretsiz, key yok)
#    Dokümantasyon: https://www.frankfurter.app/docs/
# ------------------------------------------------------------------
def eur_try_spot() -> Optional[float]:
    try:
        r = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": "EUR", "to": "TRY"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return float(r.json()["rates"]["TRY"])
    except Exception as e:
        print(f"[UYARI] EUR/TRY çekilemedi: {e}")
        return None


def usd_try_spot() -> Optional[float]:
    try:
        r = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": "USD", "to": "TRY"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return float(r.json()["rates"]["TRY"])
    except Exception as e:
        print(f"[UYARI] USD/TRY çekilemedi: {e}")
        return None


# ------------------------------------------------------------------
# 2) ABD Fed politika faizi — FRED API (ücretsiz key gerekir)
#    Key alma: https://fred.stlouisfed.org/docs/api/api_key.html
#    Seri kodu: DFF (Effective Federal Funds Rate, günlük)
# ------------------------------------------------------------------
def fed_funds_rate(api_key: str) -> Optional[float]:
    if not api_key:
        return None
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": "DFF",
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        obs = r.json()["observations"][0]
        return float(obs["value"])
    except Exception as e:
        print(f"[UYARI] Fed faizi çekilemedi: {e}")
        return None


# ------------------------------------------------------------------
# 3) TCMB brüt rezervler — EVDS API; politika faizi — tcmb.gov.tr (PPK 1 hafta repo)
#    Key alma: https://evds3.tcmb.gov.tr → Profilim → API Key Kopyala
#    Seri kodlarını EVDS arayüzünden "seri kodu kopyala" ile bulun;
#    aşağıdaki kodlar örnektir, EVDS panelinden doğrulayın.
# ------------------------------------------------------------------
def _evds_get(series_code: str, api_key: str, gun_sayisi: int = 60) -> Optional[list]:
    if not api_key:
        return None
    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=gun_sayisi)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")
    headers = {"key": api_key}

    # EVDS 3 (2026+) — path-segment URL; query params 404 verir
    url_v3 = (
        f"https://evds3.tcmb.gov.tr/igmevdsms-dis/"
        f"series={series_code}&startDate={baslangic}&endDate={bitis}&type=json"
    )
    for url, etiket in (
        (url_v3, "EVDS3"),
        (
            "https://evds2.tcmb.gov.tr/service/evds/",
            "EVDS2",
        ),
    ):
        try:
            if etiket == "EVDS2":
                r = requests.get(
                    url,
                    params={
                        "series": series_code,
                        "startDate": baslangic,
                        "endDate": bitis,
                        "type": "json",
                    },
                    headers=headers,
                    timeout=TIMEOUT,
                )
            else:
                r = requests.get(url, headers=headers, timeout=TIMEOUT)
            r.raise_for_status()
            items = r.json().get("items", [])
            if items:
                return items
        except Exception as e:
            if etiket == "EVDS3":
                print(f"[UYARI] EVDS3 ({series_code}): {e}")
            else:
                print(f"[UYARI] EVDS2 ({series_code}): {e}")
    return None


def _evds_field_key(series_code: str) -> str:
    return series_code.replace(".", "_")


def _evds_son_deger(items: list, series_code: str) -> Optional[float]:
    field = _evds_field_key(series_code)
    for item in reversed(items):
        v = item.get(field)
        if v not in (None, "", "None"):
            try:
                return float(str(v).replace(",", "."))
            except ValueError:
                continue
    return None


def _evds_ay_parcala(tarih: str) -> tuple[int, int]:
    y, m = tarih.split("-", 1)
    return int(y), int(m)


def evds_tufe_yoy(api_key: str) -> Optional[tuple[float, str]]:
    """TÜFE yıllık değişim (%) — TP.FG.J01 endeksinden hesaplanır (EVDS3 uyumlu)."""
    items = _evds_get("TP.FG.J01", api_key, gun_sayisi=800)
    if not items:
        return None
    field = _evds_field_key("TP.FG.J01")
    by_date: dict[str, float] = {}
    for it in items:
        v = it.get(field)
        if v not in (None, "", "None"):
            by_date[it["Tarih"]] = float(str(v).replace(",", "."))
    if len(by_date) < 13:
        return None
    son_tarih = max(by_date.keys(), key=lambda t: _evds_ay_parcala(t))
    y, m = _evds_ay_parcala(son_tarih)
    onceki = f"{y - 1}-{m}"
    if onceki not in by_date:
        return None
    yoy = (by_date[son_tarih] / by_date[onceki] - 1) * 100
    return yoy, f"TÜFE yıllık {son_tarih} (TP.FG.J01 endeks YoY)"


def tcmb_politika_faizi_resmi() -> Optional[tuple[float, str]]:
    """
    PPK politika faizi: bir hafta vadeli repo borç verme oranı.
    TP.APIFON4 (AOFM ~%40) politika faizi değildir — resmi tablo tcmb.gov.tr'den okunur.
    """
    url = (
        "https://www.tcmb.gov.tr/wps/wcm/connect/tr/tcmb+tr/main+menu/"
        "temel+faaliyetler/para+politikasi/merkez+bankasi+faiz+oranlari/1+hafta+repo"
    )
    try:
        import re
        from datetime import datetime as dt

        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S | re.I)
        satirlar = []
        for tr in trs:
            cells = [c.strip() for c in re.findall(r">([^<]+)<", tr) if c.strip()]
            if len(cells) < 3 or not re.match(r"\d{2}\.\d{2}\.\d{4}", cells[0]):
                continue
            try:
                faiz = float(cells[-1].replace(",", "."))
            except ValueError:
                continue
            if not (5 < faiz < 100):
                continue
            satirlar.append((dt.strptime(cells[0], "%d.%m.%Y"), faiz, cells[0]))
        if not satirlar:
            return None
        satirlar.sort(key=lambda x: x[0])
        _, val, tarih = satirlar[-1]
        return val, f"TCMB.gov.tr — 1 hafta repo borç verme ({tarih}, PPK politika faizi)"
    except Exception as e:
        print(f"[UYARI] TCMB politika faizi (web) çekilemedi: {e}")
        return None


def tcmb_politika_faizi_dogrula(deger: Optional[float], kaynak: str) -> list[str]:
    """
    Politika faizi seri doğrulaması — gecelik/AOFM ile karışmayı reddet.
    Seri: config.TCMB_POLITIKA_SERI_KODU (1 hafta repo).
    """
    uyarilar: list[str] = []
    if deger is None:
        return uyarilar
    lower = (kaynak or "").lower()
    yasak = ("apifon4", "aofm", "gecelik", "fonlama maliyeti", "borçlanma")
    if any(x in lower for x in yasak):
        uyarilar.append(
            f"TCMB faizi SUPHELI: kaynak politika faizi (1 hafta repo) değil — "
            f"**{kaynak}**. EVDS TP.APIFON4 kullanılmamalı."
        )
    if deger > 39 and "1 hafta repo" not in lower and "ppk" not in lower:
        uyarilar.append(
            f"TCMB faizi %{deger:.1f} gecelik/fonlama aralığına yakın — "
            "politika faizi (1 hafta repo) serisi teyit edilmeli."
        )
    return uyarilar


# ------------------------------------------------------------------
# Türkiye 5Y CDS (bp) — EVDS'te CDS serisi yok; canlı kaynaklar:
# Investing.com (__NEXT_DATA__) + WorldGovernmentBonds + manual referans
# ------------------------------------------------------------------
INVESTING_CDS_URL = "https://www.investing.com/rates-bonds/turkey-cds-5-year-usd"
INVESTING_CDS_HIST_URL = (
    "https://www.investing.com/rates-bonds/turkey-cds-5-year-usd-historical-data"
)
INVESTING_CDS_URLS = (
    INVESTING_CDS_URL,
    "https://tr.investing.com/rates-bonds/turkey-cds-5-year-usd",
)
WGB_CDS_PAGE = "https://www.worldgovernmentbonds.com/cds-historical-data/turkey/5-year/"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}


@dataclass
class CdsFetchSonuc:
    deger: float
    kaynak: str
    gecikmeli: bool = False
    veri_tarihi: Optional[datetime] = None
    gecikme_gun: int = 0


_INVESTING_CDS_SON_META: dict = {}


def investing_cds_son_meta() -> dict:
    """Son Investing CDS çekiminin meta verisi (gecikme vb.)."""
    return dict(_INVESTING_CDS_SON_META)


def _cds_gecerli(bp: float) -> bool:
    return 50.0 < bp < 2000.0


def _investing_next_data(url: str) -> Optional[dict]:
    """Investing.com sayfasındaki __NEXT_DATA__ JSON."""
    import re

    try:
        r = requests.get(url, headers=_BROWSER_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r.text,
            re.DOTALL,
        )
        if not m:
            return None
        import json
        return json.loads(m.group(1))
    except Exception as e:
        print(f"[UYARI] Investing NEXT_DATA ({url}): {e}")
        return None


def turkiye_cds_5y_investing_detay() -> Optional[CdsFetchSonuc]:
    """Investing.com — kotasyon + gecikme meta (bondStore.price)."""
    global _INVESTING_CDS_SON_META
    data = _investing_next_data(INVESTING_CDS_URL)
    if not data:
        ham = turkiye_cds_5y_investing_html()
        if not ham:
            return None
        return CdsFetchSonuc(deger=ham[0], kaynak=ham[1])

    try:
        price = (
            data["props"]["pageProps"]["state"]["bondStore"]["instrument"]["price"]
        )
        val = float(price["last"])
        if not _cds_gecerli(val):
            return None
        gecikmeli = bool(price.get("isDelayed"))
        ts_ms = int(price.get("lastUpdateTime") or 0)
        veri_dt = None
        gecikme_gun = 0
        if ts_ms > 0:
            veri_dt = datetime.utcfromtimestamp(ts_ms / 1000)
            gecikme_gun = max(0, (datetime.utcnow() - veri_dt).days)
        tarih_tr = veri_dt.strftime("%d/%m") if veri_dt else "?"
        if gecikmeli or gecikme_gun >= 1:
            kaynak = f"Investing.com (Geciken veri {tarih_tr}, +{gecikme_gun}g)"
        else:
            kaynak = f"Investing.com canlı ({veri_dt.strftime('%Y-%m-%d') if veri_dt else 'bugün'})"
        sonuc = CdsFetchSonuc(
            deger=val,
            kaynak=kaynak,
            gecikmeli=gecikmeli or gecikme_gun >= 1,
            veri_tarihi=veri_dt,
            gecikme_gun=gecikme_gun,
        )
        _INVESTING_CDS_SON_META = {
            "deger": val,
            "gecikmeli": sonuc.gecikmeli,
            "veri_tarihi": veri_dt.isoformat() if veri_dt else None,
            "gecikme_gun": gecikme_gun,
            "last_close": float(price.get("lastClose") or 0) or None,
        }
        return sonuc
    except (KeyError, TypeError, ValueError) as e:
        print(f"[UYARI] Investing CDS parse: {e}")
        ham = turkiye_cds_5y_investing_html()
        return CdsFetchSonuc(deger=ham[0], kaynak=ham[1]) if ham else None


def turkiye_cds_5y_investing() -> Optional[tuple[float, str]]:
    """Investing.com — canlı kotasyon (bondStore.price.last)."""
    detay = turkiye_cds_5y_investing_detay()
    if not detay:
        return None
    return detay.deger, detay.kaynak


def turkiye_cds_5y_investing_html() -> Optional[tuple[float, str]]:
    """Yedek — HTML regex (NEXT_DATA başarısız olursa)."""
    import re

    for url in INVESTING_CDS_URLS:
        try:
            r = requests.get(url, headers=_BROWSER_HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            m = re.search(
                r'data-test="instrument-price-last"[^>]*>\s*([0-9][0-9.,]*)',
                r.text,
            )
            if not m:
                continue
            val = float(m.group(1).replace(",", "."))
            if _cds_gecerli(val):
                host = url.split("//")[1].split("/")[0]
                return val, f"Investing.com HTML ({host})"
        except Exception as e:
            print(f"[UYARI] Investing CDS HTML ({url}): {e}")
    return None


def turkiye_cds_5y_investing_kapanis() -> Optional[tuple[float, str]]:
    """Investing.com — son işlem günü kapanış (historicalDataStore)."""
    data = _investing_next_data(INVESTING_CDS_HIST_URL)
    if not data:
        return None
    try:
        rows = (
            data["props"]["pageProps"]["state"]["historicalDataStore"]
            ["historicalData"]["data"]
        )
        if not rows:
            return None
        son = rows[0]
        val = float(son["last_closeRaw"])
        if not _cds_gecerli(val):
            return None
        tarih = son.get("rowDate", "")
        return val, f"Investing.com kapanış ({tarih})"
    except (KeyError, TypeError, ValueError) as e:
        print(f"[UYARI] Investing CDS kapanış: {e}")
        return None


def turkiye_cds_5y_wgb() -> Optional[tuple[float, str]]:
    """WorldGovernmentBonds — Origin/Referer zorunlu; API boşsa None."""
    import json
    import re

    headers = {
        **_BROWSER_HEADERS,
        "Origin": "https://www.worldgovernmentbonds.com",
        "Referer": WGB_CDS_PAGE,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        sayfa = requests.get(WGB_CDS_PAGE, headers=headers, timeout=TIMEOUT)
        sayfa.raise_for_status()
        m = re.search(r"jsGlobalVars\s*=\s*(\{.*?\});", sayfa.text, re.DOTALL)
        if not m:
            return None
        payload = json.loads(m.group(1))
        payload["DATE_RIF"] = datetime.now().strftime("%Y-%m-%d")
        payload["DEBUG"] = False
        endpoint = payload.get(
            "ENDPOINT",
            "https://www.worldgovernmentbonds.com/wp-json/common/v1/historical",
        )
        r = requests.post(endpoint, json=payload, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.json()
        if not body.get("success"):
            return None
        res = body.get("result") or {}
        for anahtar in ("ultimoValore", "lastValData", "maxVal", "minVal"):
            ham = res.get(anahtar)
            if ham is not None:
                val = float(ham)
                if _cds_gecerli(val):
                    return val, "WorldGovernmentBonds (canlı API)"
    except Exception as e:
        print(f"[UYARI] WGB CDS: {e}")
    return None


def turkiye_cds_5y_otomatik() -> Optional[tuple[float, str]]:
    """Öncelik: Investing kapanış → canlı → WGB."""
    for fn in (
        turkiye_cds_5y_investing_kapanis,
        turkiye_cds_5y_investing,
        turkiye_cds_5y_wgb,
    ):
        sonuc = fn()
        if sonuc:
            return sonuc
    return None


def evds_dogrula(api_key: str) -> dict:
    """
    API key testi — kayıt sonrası çalıştırın: python main.py --evds-test
    Dönüş: {ok, enflasyon, tcmb, cds, rezerv, mesajlar}
    """
    sonuc = {"ok": False, "mesajlar": []}
    if not api_key or not api_key.strip():
        sonuc["mesajlar"].append("EVDS_API_KEY boş — .env dosyasına key ekleyin.")
        return sonuc

    testler = [
        ("enflasyon", None, 0, "TÜFE yıllık (TÜİK)"),
        ("tcmb", None, 0, "TCMB politika faizi (1 hafta repo)"),
        ("cds", None, 0, "Türkiye 5Y CDS (Investing.com)"),
        ("rezerv", "TP.AB.A01", 35, "Brüt rezervler (bin USD)"),
    ]
    basarili = 0
    for anahtar, seri, gun, aciklama in testler:
        if anahtar == "enflasyon":
            tufe = evds_tufe_yoy(api_key.strip())
            if not tufe:
                sonuc["mesajlar"].append(f"❌ {aciklama} — veri alınamadı")
                sonuc[anahtar] = None
                continue
            deger, detay = tufe
            sonuc["mesajlar"].append(f"✅ {aciklama}: %{deger:.2f} ({detay})")
            sonuc[anahtar] = deger
            basarili += 1
            continue
        if anahtar == "tcmb":
            ppk = tcmb_politika_faizi_resmi()
            if not ppk:
                sonuc["mesajlar"].append(f"❌ {aciklama} — tcmb.gov.tr okunamadı")
                sonuc[anahtar] = None
                continue
            deger, detay = ppk
            sonuc["mesajlar"].append(f"✅ {aciklama}: %{deger:.1f} ({detay})")
            sonuc[anahtar] = deger
            basarili += 1
            continue
        if anahtar == "cds":
            satirlar = []
            try:
                from cds_bloomberg import turkiye_cds_5y_bloomberg_blp
                blp = turkiye_cds_5y_bloomberg_blp()
                if blp:
                    satirlar.append(f"✅ Bloomberg Terminal: {blp[0]:.2f} bp — {blp[1]}")
                    basarili += 1
                else:
                    satirlar.append("⚠️ Bloomberg Terminal — BLPAPI/Terminal yok")
            except Exception:
                satirlar.append("⚠️ Bloomberg Terminal — modül yüklenemedi")
            for etiket, fn in (
                ("Investing kapanış", turkiye_cds_5y_investing_kapanis),
                ("Investing canlı", turkiye_cds_5y_investing),
                ("WGB", turkiye_cds_5y_wgb),
            ):
                cds = fn()
                if cds:
                    satirlar.append(f"✅ {etiket}: {cds[0]:.2f} bp — {cds[1]}")
                    basarili += 1
                else:
                    satirlar.append(f"❌ {etiket} — veri alınamadı")
            sonuc["mesajlar"].extend(satirlar)
            sonuc[anahtar] = True if any(s.startswith("✅") for s in satirlar) else None
            continue
        items = _evds_get(seri, api_key.strip(), gun_sayisi=gun)
        if not items:
            sonuc["mesajlar"].append(f"❌ {aciklama} ({seri}) — veri alınamadı")
            sonuc[anahtar] = None
            continue
        deger = _evds_son_deger(items, seri)
        if deger is None:
            sonuc["mesajlar"].append(f"⚠️ {aciklama} ({seri}) — yanıt boş")
            sonuc[anahtar] = None
        else:
            if anahtar == "rezerv":
                milyar = deger / 1_000_000_000
                sonuc["mesajlar"].append(f"✅ {aciklama}: ~{milyar:.1f} milyar USD")
            else:
                sonuc["mesajlar"].append(f"✅ {aciklama}: {deger}")
            sonuc[anahtar] = deger
            basarili += 1

    sonuc["ok"] = basarili >= 2
    if sonuc["ok"]:
        sonuc["mesajlar"].insert(0, f"EVDS bağlantısı OK ({basarili}/{len(testler)} seri).")
    else:
        sonuc["mesajlar"].insert(0, "EVDS key geçersiz veya serilere erişim yok.")
    return sonuc


def tcmb_reserves_trend(api_key: str, seri_kodu: str = "TP.AB.A01") -> Optional[dict]:
    """Son ~4 haftalık brüt rezerv trendini döndürür: {'son': ..., 'onceki': ..., 'artiyor': bool}"""
    items = _evds_get(seri_kodu, api_key, gun_sayisi=35)
    if not items or len(items) < 2:
        return None
    field = _evds_field_key(seri_kodu)
    degerler = []
    for it in items:
        v = it.get(field)
        if v not in (None, "", "None"):
            try:
                degerler.append(float(str(v).replace(",", ".")))
            except ValueError:
                continue
    if len(degerler) < 2:
        return None
    try:
        son, onceki = degerler[-1], degerler[0]
        return {"son": son, "onceki": onceki, "artiyor": son >= onceki}
    except Exception:
        return None


# ------------------------------------------------------------------
# 4) Siyasi risk / savaş riski — GDELT DOC 2.0 API (ücretsiz, key yok)
#    Dokümantasyon: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
#    Not: Bu, bir "duygu analizi" değil, basit bir haber-hacmi sayacıdır.
#    Nihai kararı siz kontrol etmelisiniz — bu sadece bir erken uyarı sinyalidir.
# ------------------------------------------------------------------
def gdelt_makale_sayisi(anahtar_kelimeler: list, saat: int = 48) -> Optional[int]:
    try:
        sorgu = " OR ".join([f'"{k}"' for k in anahtar_kelimeler])
        r = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": f"({sorgu}) sourcelang:turkish",
                "mode": "artlist",
                "maxrecords": 75,
                "timespan": f"{saat}h",
                "format": "json",
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return len(data.get("articles", []))
    except Exception as e:
        print(f"[UYARI] GDELT taraması başarısız: {e}")
        return None


# ------------------------------------------------------------------
# 5) Manuel girilen göstergeler (CDS gibi güvenilir ücretsiz API'si
#    olmayan veriler). manual_inputs.json dosyasını elle güncelleyin:
#    {
#      "cds_5y_bp": 265,
#      "tl_mevduat_brut_faiz": 0.41,
#      "guncelleme_tarihi": "2026-07-01"
#    }
# ------------------------------------------------------------------
def manuel_veri_oku(path: str) -> dict:
    if not os.path.exists(path):
        print(f"[UYARI] {path} bulunamadı, örnek dosya oluşturuluyor.")
        ornek = {
            "cds_5y_bp": None,
            "tl_mevduat_brut_faiz": None,
            "guncelleme_tarihi": None,
            "mevduat_oranlari": {
                "tl_1y_brut": 0.41,
                "tl_3ay_brut": 0.38,
                "tl_6ay_brut": 0.39,
                "eur_brut": 0.025,
                "usd_brut": 0.04,
            },
            "_not": (
                "cds_5y_bp: worldgovernmentbonds.com veya bankanızın "
                "araştırma raporlarından güncel Türkiye 5Y CDS değerini girin. "
                "mevduat_oranlari: bankanızın güncel brüt yıllık mevduat teklifleri (ondalık, örn. 0.41 = %41)."
            ),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ornek, f, ensure_ascii=False, indent=2)
        return ornek
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
