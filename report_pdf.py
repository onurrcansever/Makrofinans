# -*- coding: utf-8 -*-
"""
PDF rapor — fpdf2 + Unicode font, Türkçe karakter destekli, antetli düzen.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Any, List, Optional

import config
from advice_engine import DanismanRaporu
from allocation_engine import TahsisSonucu, VARLIKLAR
from investor_profile import VADE_SECENEKLERI, YatirimProfili
from macro_data import MacroSnapshot
from rates_tr import MevduatKarsilastirma, _eur_bazli_tahmini
from stock_scanner import SINYAL_ETIKET, TaramaSonucu
from stock_universe import SEKTOR_ETIKET
from tl_durum import TlDurumOzeti
from veri_kalitesi import VeriKaliteRaporu, veri_kalite_olustur
from backtest import backtest_calistir, backtest_karsilastirma_uret
from scenario_analysis import senaryo_analizi_uret
from alim_uygunluk import alim_aksiyon_hucre
from bist_52h_eur import format_52h_metin

_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_FONT_REGULAR = os.path.join(_FONT_DIR, "ArialUnicode.ttf")

# A4 — alt kenar payı
_ALT_BOSLUK = 20


def _font_hazirla() -> str:
    if os.path.isfile(_FONT_REGULAR):
        return _FONT_REGULAR
    adaylar = (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for p in adaylar:
        if os.path.isfile(p):
            os.makedirs(_FONT_DIR, exist_ok=True)
            try:
                import shutil
                shutil.copy2(p, _FONT_REGULAR)
                return _FONT_REGULAR
            except Exception:
                return p
    raise RuntimeError("Unicode font bulunamadı (Arial Unicode / DejaVu)")


def _temiz(text: Any, max_len: int = 0) -> str:
    if text is None:
        return "—"
    s = str(text)
    s = re.sub(r"\*\*", "", s)
    s = re.sub(r"\*", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if max_len and len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _sayi(val: Any, nd: int = 2) -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        if nd == 0:
            return f"{f:,.0f}".replace(",", ".")
        return f"{f:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return _temiz(val)


def _zaman_kisa(z: str) -> str:
    if not z:
        return "—"
    try:
        dt = datetime.fromisoformat(z.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return _temiz(z, 16)


def _pct(val: Optional[float], nd: int = 1) -> str:
    if val is None:
        return "—"
    return f"{val:+.{nd}f}%"


_UYGUN_SIRA = {"UYGUN": 0, "SINIRLI": 1, "IZLE": 2, "UYGUN_DEGIL": 3}

_PLAIN_ONERI = {
    "UYGUN": "Şu an alınabilir",
    "SINIRLI": "Sınırlı miktarda değerlendirilebilir",
    "UYGUN_DEGIL": "Şu an uygun değil",
    "IZLE": "İzle, henüz erken",
}

_SINYAL_SADE = {
    "ALIM_FIRSATI": "Teknik alım sinyali veriyor",
    "TREND_ALIM": "Yükseliş trendinde, alım destekli",
    "BEKLE": "Net sinyal yok, beklenebilir",
    "ASIRI_ALIM": "Fiyat yüksek — aşırı alım bölgesinde",
    "UZAK_DUR": "Olumsuz görünüm, kaçınılmalı",
    "VERI_YOK": "Fiyat verisi alınamadı",
}


def _plain_oneri(h) -> str:
    """Teknik uygunluk kodunu sade Türkçe öneriye dönüştürür."""
    return _PLAIN_ONERI.get(getattr(h, "alim_uygun", "IZLE"), "İzle, henüz erken")


def _sinyal_sade(sinyal: str) -> str:
    """Teknik sinyal kodunu yatırımcı dostu metne dönüştürür."""
    return _SINYAL_SADE.get(sinyal, sinyal)


def _neden_kisa(h, max_len: int = 110) -> str:
    """
    Hisse/ETF için kısa ve sade Türkçe neden açıklaması üretir.
    Kaynak: alim_uygun_not > trend_notu > profil_notu > temel_not > sinyal
    """
    parcalar = []
    not1 = _temiz(getattr(h, "alim_uygun_not", "") or "")
    not2 = _temiz(getattr(h, "trend_notu", "") or "")
    not3 = _temiz(getattr(h, "profil_notu", "") or "")
    not4 = _temiz(getattr(h, "temel_not", "") or "")
    sinyal = getattr(h, "sinyal", "")
    uygun = getattr(h, "alim_uygun", "IZLE")

    for n in (not1, not2, not3, not4):
        if n and n not in ("—", "Trend filtresi OK", "Rejim uyumlu",
                           "Faktör nötr", "Profil uyumlu"):
            parcalar.append(n)
            break

    if not parcalar and sinyal:
        parcalar.append(_sinyal_sade(sinyal))

    if not parcalar:
        parcalar.append(_PLAIN_ONERI.get(uygun, "—"))

    metin = "; ".join(parcalar)
    if len(metin) > max_len:
        return metin[:max_len - 1] + "…"
    return metin


def _uygun_tablo_hucre(h) -> str:
    return alim_aksiyon_hucre(h)


def _hisse_sirala(hisseler: list) -> list:
    return sorted(
        hisseler,
        key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor),
    )


def _isin_birlestir_gosterim(hisseler: list) -> list:
    """Aynı ISIN — tek satır; kotasyonlar not sütununda."""
    goren: dict = {}
    cikis: list = []
    for h in _hisse_sirala(hisseler):
        isin = (getattr(h, "isin", "") or "").strip()
        if not isin:
            cikis.append(h)
            continue
        if isin in goren:
            mevcut = goren[isin]
            tickers = getattr(mevcut, "_kotasyonlar", [mevcut.sembol])
            if h.sembol not in tickers:
                tickers.append(h.sembol)
            mevcut._kotasyonlar = tickers
            rt = getattr(h, "revolut_ticker", "") or ""
            if rt and rt not in (getattr(mevcut, "_revolut_list", []) or []):
                mevcut._revolut_list = (getattr(mevcut, "_revolut_list", []) or []) + [rt]
            continue
        h._kotasyonlar = [h.sembol]
        goren[isin] = h
        cikis.append(h)
    return cikis


def _kotasyon_notu(h) -> str:
    tickers = getattr(h, "_kotasyonlar", None) or [h.sembol]
    if len(tickers) > 1:
        return f"Kot: {', '.join(tickers[:4])}"
    rt = getattr(h, "revolut_ticker", "") or ""
    if rt and rt != h.sembol.split(".")[0]:
        return f"Revolut: {rt}"
    return _temiz(getattr(h, "alim_uygun_not", ""), 22)


def _madde_ek_bilgi(h) -> Optional[str]:
    """Tabloda olmayan ek uyarı — temel not, haber, rejim."""
    parcalar = []
    if getattr(h, "temel_not", ""):
        parcalar.append(h.temel_not[:80])
    if getattr(h, "haber_notu", ""):
        parcalar.append(f"Haber: {_temiz(h.haber_notu, 60)}")
    if getattr(h, "rejim_notu", "") and h.rejim_notu not in ("", "Rejim uyumlu"):
        parcalar.append(f"Rejim: {_temiz(h.rejim_notu, 50)}")
    return " · ".join(parcalar) if parcalar else None


def _skor_sirala(hisseler: list) -> list:
    return sorted(
        hisseler,
        key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor),
    )


def _uygunluk_ozet_metin(tarama: TaramaSonucu) -> str:
    say = {"UYGUN": 0, "SINIRLI": 0, "UYGUN_DEGIL": 0, "IZLE": 0}
    for h in tarama.hisseler or []:
        k = getattr(h, "alim_uygun", "IZLE")
        say[k] = say.get(k, 0) + 1
    return (
        f"Şu an alınabilir: {say['UYGUN']}  ·  Sınırlı/Dikkat: {say['SINIRLI']}  ·  "
        f"Uygun değil: {say['UYGUN_DEGIL']}  ·  İzle: {say['IZLE']}"
    )


def _hisse_detay_madde(h) -> str:
    ek = ""
    neden = _neden_kisa(h, 80)
    if neden:
        ek = f" — {neden}"
    return _temiz(
        f"{_plain_oneri(h)} · {h.ad} ({h.sembol}) · "
        f"{_sinyal_sade(h.sinyal)} · "
        f"Son 1 Ay: {_pct(h.degisim_1ay)} · Son 3 Ay: {_pct(getattr(h, 'degisim_3ay', None))}"
        f"{ek}",
        220,
    )


def _hisse_ozet_satir(
    h,
    *,
    detayli: bool = False,
    ilk_sutun: str = "uygunluk",
    sira: int = 0,
) -> List[str]:
    if ilk_sutun == "sira":
        col0 = f"#{sira}"
    else:
        col0 = _plain_oneri(h)
    row = [
        col0,
        _temiz(h.ad, 18),
        h.sembol,
        h.piyasa,
        _temiz(_sinyal_sade(h.sinyal), 22),
        _pct(h.degisim_1ay, 0),
        _pct(getattr(h, "degisim_3ay", None), 0),
    ]
    if detayli:
        row.append(_neden_kisa(h, 60))
    return row


def _tablo_hisse_ozet(
    doc: "RaporPDF",
    hisseler: list,
    *,
    detayli: bool = False,
    font: float = 8.0,
    ilk_sutun: str = "uygunluk",
) -> None:
    if not hisseler:
        return
    w = doc._w()
    ilk_baslik = "Sıra" if ilk_sutun == "sira" else "Öneri"
    baslik = [
        ilk_baslik, "Varlık Adı", "Sembol", "Piyasa", "Durum", "Son 1 Ay", "Son 3 Ay",
    ]
    cols = [0.13, 0.22, 0.09, 0.07, 0.18, 0.08, 0.08]
    if detayli:
        baslik.append("Kısa Not")
        toplam = sum(cols)
        cols = [c * (1 - 0.15) for c in cols] + [0.15]
    rows = [
        _hisse_ozet_satir(h, detayli=detayli, ilk_sutun=ilk_sutun, sira=i + 1)
        for i, h in enumerate(hisseler)
    ]
    doc.tablo(baslik, rows, font_boyut=font, satir_yuk=4.5, col_w=[w * c for c in cols])


def _girdi_dogrulama_bolumu(doc: "RaporPDF", snap: MacroSnapshot) -> None:
    from girdi_dogrulama import girdi_rapor_uyarilari

    uyarilar = girdi_rapor_uyarilari(snap)
    if not uyarilar and not getattr(snap, "rejim_donduruldu", False):
        return
    doc.bolum("Girdi Doğrulama (Faz 1)")
    if getattr(snap, "rejim_donduruldu", False):
        gd = getattr(snap, "girdi_dogrulama", None)
        bekleyen = ", ".join(gd.onay_bekleyen) if gd else "—"
        doc.kutu(
            "Makro rejim donduruldu — girdi sıçraması",
            f"Onay bekleyen göstergeler: {bekleyen}. "
            f"Rejim hesabında önceki değer kullanılıyor; ikinci ardışık okumada teyit edilir.",
        )
    for u in uyarilar:
        doc.madde(_temiz(u, 200))


def _veri_kalite_bolumu(doc: "RaporPDF", vk: VeriKaliteRaporu) -> None:
    doc.bolum("Veri Kalitesi & Kaynak Şeffaflığı")
    doc.kutu(f"Genel skor: {vk.genel_skor:.0f}/100 ({vk.genel_duzey})", vk.ozet)
    for u in vk.uyarilar[:4]:
        doc.madde(_temiz(u, 160))
    w = doc._w()
    rows = []
    for g in vk.gostergeler:
        tz = f"{g.tazelik_saat:.0f}s" if g.tazelik_saat is not None else "—"
        rows.append([
            _temiz(g.etiket, 18),
            _temiz(g.deger_gosterim, 10),
            _temiz(g.kalite_etiket, 12),
            _temiz(g.kaynak, 28),
            tz,
        ])
    doc.tablo(
        ["Gösterge", "Değer", "Kalite", "Kaynak", "Yaş"],
        rows,
        font_boyut=7,
        satir_yuk=4,
        col_w=[w * 0.22, w * 0.12, w * 0.14, w * 0.40, w * 0.12],
    )


def _senaryo_bolumu(doc: "RaporPDF", snap, tahsis, vade_gun: int, tarama=None, birlesik_oneri=None) -> None:
    try:
        senaryolar = senaryo_analizi_uret(
            snap, tahsis, vade_gun, tarama=tarama, birlesik_oneri=birlesik_oneri,
        )
    except Exception:
        return
    if not senaryolar:
        return
    doc.bolum("Senaryo Analizi")
    for s in senaryolar:
        doc.kutu(s.ad, _temiz(s.ozet, 320))
        if s.tablo_satirlar:
            doc.tablo(s.tablo_baslik, s.tablo_satirlar)


def _kanonik_aday_tablo(doc: "RaporPDF", hisseler: list) -> None:
    """Kanonik alım adayları tablosu — tam isim, sade Türkçe öneri, neden açıklaması."""
    if not hisseler:
        return
    birlestir = _isin_birlestir_gosterim(hisseler)
    w = doc._w()
    rows = []
    for h in birlestir[:25]:
        rt = getattr(h, "revolut_ticker", "") or h.sembol.split(".")[0]
        sembol_goster = rt if h.piyasa == "ETF" else h.sembol
        # Tam isim — kesmeden göster
        tam_ad = _temiz(h.ad)
        # ISIN varsa kotasyon bilgisi "Neden?" sütununa ek olarak ekle
        kotasyon = _kotasyon_notu(h)
        neden = _neden_kisa(h, 100)
        if kotasyon and kotasyon.startswith("Kot:"):
            neden = f"{neden} ({kotasyon})" if neden else kotasyon
        rows.append([
            _plain_oneri(h),
            tam_ad,
            sembol_goster,
            h.piyasa,
            _pct(h.degisim_1ay, 0),
            neden,
        ])
    doc.tablo(
        ["Öneri", "Varlık Adı", "Sembol / Kod", "Piyasa", "Son 1 Ay", "Neden?"],
        rows,
        font_boyut=8.5,
        satir_yuk=4.5,
        col_w=[w * x for x in (0.15, 0.21, 0.09, 0.07, 0.08, 0.40)],
    )


def _backtest_bolumu(
    doc: "RaporPDF",
    rejim: str,
    profil: YatirimProfili,
    ay: int = 12,
    sabit_agirliklar: Optional[dict] = None,
) -> None:
    try:
        satirlar = backtest_calistir(ay, profil=profil)
        kars = backtest_karsilastirma_uret(
            satirlar, rejim, bugun_agirliklar=sabit_agirliklar, profil=profil
        )
    except Exception:
        return
    if not kars:
        return

    met = kars.dinamik
    karsi = kars.karsi_olgusal
    ref = kars.referans_statik
    rejim_hic_gorulmedi = (
        rejim and met.mevcut_rejim_oran_pct is not None
        and met.mevcut_rejim_oran_pct < 1
    )
    bilgi_amacli = (
        met.model_drift
        or (rejim and met.mevcut_rejim_oran_pct < config.BACKTEST_REJIM_MIN_ORAN)
    )

    doc.bolum("Backtest — Dinamik Rejim vs Statik Karşılaştırma")

    # Güçlü çift-koşul uyarısı: dinamik kötü VE rejim hiç görülmemiş
    if kars.dinamik_dezavantaj and rejim_hic_gorulmedi:
        doc.kutu(
            "Önemli Uyarı — Bu Raporun Önerisini Nasıl Okumalısınız",
            f"Backtest iki kritik sorunu aynı anda gösteriyor: "
            f"(1) Son {ay} ayda dinamik rejim modeli statik tahsisten DAHA KÖTÜ performans sergiledi "
            f"(Sharpe: Dinamik {met.sharpe_yillik:.2f} vs Statik {ref.sharpe_yillik:.2f}). "
            f"(2) Mevcut rejim ({rejim.replace('_', ' ')}) bu dönemde hiç "
            f"görülmedi (%{met.mevcut_rejim_oran_pct:.0f}) — dolayısıyla bugünkü "
            "öneri seti test edilmemiş koşullara dayanıyor. "
            "Bu durumda rapordaki spesifik yüzdelerden çok çerçeveyi (başabaş kur, "
            "TL tavan mantığı, reel getiri ayrımı) esas alınız. "
            "Büyük pozisyon değişikliği yapmadan önce yaklaşan merkez bankası "
            "kararlarını beklemek raporun kendi verileriyle uyumludur.",
        )
    elif kars.dinamik_dezavantaj and kars.uyari_mesaji:
        doc.kutu("Dinamik Katman Uyarısı", _temiz(kars.uyari_mesaji, 420))
    elif rejim_hic_gorulmedi:
        doc.kutu(
            "Dikkat — Test Edilmemiş Rejim",
            f"Mevcut rejim ({rejim.replace('_', ' ')}) geçmiş {ay} aylık simülasyonda "
            f"%{met.mevcut_rejim_oran_pct:.0f} ile temsil edildi — tarihsel referans çok sınırlı. "
            "Önerilen tahsis bu koşullarda daha önce test edilmemiştir.",
        )

    doc.paragraf(_temiz(kars.ozet.replace("**", ""), 420))

    def _sh(m):
        return f"{m.sharpe_yillik:.2f}" if m.sharpe_yillik is not None else "—"

    w = doc._w()
    basliklar = ["Metrik", "Dinamik rejim", f"Referans statik ({profil.risk})"]
    if karsi:
        basliklar.append("Bugünkü ağırlıklar")
    satirlar_tab = [
        ["Toplam getiri", f"{met.toplam_getiri_pct:+.1f}%", f"{ref.toplam_getiri_pct:+.1f}%"]
        + ([f"{karsi.toplam_getiri_pct:+.1f}%"] if karsi else []),
        ["Sharpe (yıllık)", _sh(met), _sh(ref)] + ([_sh(karsi)] if karsi else []),
        ["Max drawdown", f"{met.max_drawdown_pct:.1f}%", f"{ref.max_drawdown_pct:.1f}%"]
        + ([f"{karsi.max_drawdown_pct:.1f}%"] if karsi else []),
        ["Volatilite", f"{met.volatilite_yillik_pct:.1f}%", f"{ref.volatilite_yillik_pct:.1f}%"]
        + ([f"{karsi.volatilite_yillik_pct:.1f}%"] if karsi else []),
    ]
    col_n = len(basliklar)
    doc.paragraf(
        "Üç yollu simülasyon: her ay rejime göre yeniden tahsis (dinamik) · "
        "profil bazlı pasif referans · bugünkü ağırlıklar sabit (karşı-olgusal)."
    )
    doc.tablo(
        basliklar,
        satirlar_tab,
        font_boyut=7,
        satir_yuk=4,
        col_w=[w / col_n] * col_n,
    )

    if kars.en_iyi_strateji != "Dinamik rejim":
        doc.madde(
            _temiz(
                f"Son {ay} ayda en iyi sonuç: **{kars.en_iyi_strateji}** — "
                "dinamik rejim katmanı otomatik tahsis emri olarak kullanılmamalı.",
                200,
            )
        )

    if kars.rejim_dagilimi:
        doc.paragraf("Rejim dağılımı (simülasyon dönemi):")
        rej_rows = [
            [r.replace("_", " "), f"%{p:.0f}"]
            for r, p in kars.rejim_dagilimi.items()
        ]
        doc.tablo(
            ["Rejim", "Süre"],
            rej_rows,
            font_boyut=7,
            satir_yuk=3.5,
            col_w=[w * 0.55, w * 0.45],
        )
        if kars.belirsiz_oran_pct >= 30:
            doc.madde(
                _temiz(
                    f"BELIRSIZ oranı %{kars.belirsiz_oran_pct:.0f} — "
                    "rejim sınıflandırması ayırt edici değil; statik referansa öncelik verin.",
                    180,
                )
            )

    if bilgi_amacli:
        if met.drift_mesaji:
            doc.madde(_temiz(met.drift_mesaji, 160))
        elif rejim:
            doc.madde(
                _temiz(
                    f"Mevcut rejim ({rejim}) simülasyonda yalnızca "
                    f"%{met.mevcut_rejim_oran_pct:.0f} görüldü — metrikler sınırlı güvenilirlikte.",
                    180,
                )
            )

    for n in met.notlar[:2]:
        doc.madde(_temiz(n, 160))
    doc.madde(_temiz(ref.notlar[0], 160))

    if satirlar:
        rows = []
        for s in satirlar[-6:]:
            rows.append([
                s.tarih,
                _temiz(s.rejim_etiket, 18),
                _sayi(s.eur_try, 1),
                f"{s.agirliklar.get('gold', 0) * 100:.0f}%",
                f"{s.agirliklar.get('tl_deposit', 0) * 100:.0f}%",
                f"{s.agirliklar.get('bist', 0) * 100:.0f}%",
            ])
        doc.paragraf(f"Son {min(6, len(satirlar))} ay tahsis geçmişi:")
        doc.tablo(
            ["Ay", "Rejim", "EUR/TRY", "Altın", "TL", "BIST"],
            rows,
            font_boyut=7,
            satir_yuk=4,
            col_w=[w * 0.12, w * 0.30, w * 0.14, w * 0.14, w * 0.14, w * 0.16],
        )


def _tarama_bolumu(doc: "RaporPDF", tarama: TaramaSonucu, rejim_etiket: str) -> None:
    doc.bolum("Hisse & ETF Yatırım Önerileri")
    profil_oz = getattr(tarama, "profil_ozet", "") or ""
    if profil_oz:
        doc.kutu("Tarama profili", profil_oz)
        for n in (getattr(tarama, "profil_notlari", None) or [])[:5]:
            doc.madde(_temiz(n, 160))

    ozet_str = getattr(tarama, "tarama_ozet", "") or ""
    doc.kutu(
        "Öneri özeti",
        f"{_uygunluk_ozet_metin(tarama)}"
        + (f"  —  {ozet_str}" if ozet_str else "")
        + f"  |  Rejim: {rejim_etiket}",
    )
    doc.paragraf(
        '"Şu an alınabilir" = teknik ve makro koşullar uygun  ·  '
        '"Sınırlı" = bazı uyarılar var, küçük pay ile değerlendirilebilir  ·  '
        '"Şu an uygun değil" = koşullar olumsuz  ·  '
        '"İzle" = net sinyal yok. Veriler Yahoo Finance (gecikmeli). Yatırım tavsiyesi değildir.'
    )
    for u in (tarama.uyarilar or [])[:3]:
        doc.madde(_temiz(u, 140))

    if tarama.endeksler:
        doc.paragraf("Ana endeksler — BIST 100 · NASDAQ · S&P 500")
        w = doc._w()
        endeks_rows = []
        for e in tarama.endeksler:
            fiyat = _sayi(e.fiyat, 0 if (e.fiyat or 0) >= 100 else 2)
            endeks_rows.append([
                _temiz(e.ad, 24),
                fiyat,
                _pct(e.degisim_1g),
                _pct(e.degisim_1ay),
                _pct(e.degisim_3ay),
                _temiz(_sinyal_sade(e.sinyal), 28),
            ])
        doc.tablo(
            ["Endeks", "Fiyat", "1 Gün", "Son 1 Ay", "Son 3 Ay", "Durum"],
            endeks_rows,
            font_boyut=8.5,
            satir_yuk=4.5,
            col_w=[w * 0.26, w * 0.12, w * 0.09, w * 0.10, w * 0.10, w * 0.33],
        )

    uygun_list = _hisse_sirala([h for h in (tarama.hisseler or []) if getattr(h, "alim_uygun", "") == "UYGUN"])
    sinirli_list = _hisse_sirala([h for h in (tarama.hisseler or []) if getattr(h, "alim_uygun", "") == "SINIRLI"])
    etf_firsat = getattr(tarama, "etf_firsatlari", None) or []

    kanonik = _hisse_sirala(uygun_list + sinirli_list + etf_firsat)
    if kanonik:
        al_n = len(uygun_list)
        dikkat_n = len(sinirli_list)
        etf_n = len(etf_firsat)
        trunc_not = ""
        if al_n == 0 and len(kanonik) > config.TARAMA_KANONIK_MAX_SATIR:
            trunc_not = (
                f" Şu an alınabilir aday yok; tablo özet için {config.TARAMA_KANONIK_MAX_SATIR} satırla "
                f"sınırlandı ({len(kanonik)} aday tarandı)."
            )
            kanonik = kanonik[: config.TARAMA_KANONIK_MAX_SATIR]
        doc.paragraf(
            f"Yatırım önerileri — Şu an alınabilir: {al_n}  ·  Dikkat/Sınırlı: {dikkat_n}  ·  ETF: {etf_n}"
            f"{trunc_not}"
        )
        _kanonik_aday_tablo(doc, kanonik)
    elif not kanonik:
        doc.paragraf(
            "Şu an profil ve piyasa koşullarınıza uygun hisse/ETF alım adayı bulunmuyor. "
            "Bu dönem makro tahsis (mevduat / altın / EUR) öncelikli."
        )


class RaporPDF:
    """fpdf2 sarmalayıcı — antet, tablo, bölüm."""

    def __init__(self):
        from fpdf import FPDF
        from fpdf.enums import Align, XPos, YPos

        self._Align = Align
        self._XPos = XPos
        self._YPos = YPos
        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.pdf.set_auto_page_break(auto=True, margin=_ALT_BOSLUK)
        font = _font_hazirla()
        self.pdf.add_font("TR", "", font)
        self.pdf.add_font("TR", "B", font)
        self.pdf.add_page()
        self._kenar = 15
        self.pdf.set_left_margin(self._kenar)
        self.pdf.set_right_margin(self._kenar)

    def _w(self) -> float:
        return self.pdf.w - self.pdf.l_margin - self.pdf.r_margin

    def _sol(self) -> None:
        self.pdf.set_x(self.pdf.l_margin)

    def _sayfa_yeterli(self, yukseklik: float = 12) -> None:
        if self.pdf.get_y() + yukseklik > self.pdf.h - _ALT_BOSLUK:
            self.pdf.add_page()
            self._sol()

    def _metin_satirlari(self, text: str, genislik: float) -> List[str]:
        """Metni hücre genişliğine göre satırlara böler."""
        text = _temiz(text)
        if not text:
            return [""]
        kelimeler = text.split(" ")
        satirlar: List[str] = []
        mevcut = ""
        for kelime in kelimeler:
            aday = kelime if not mevcut else f"{mevcut} {kelime}"
            if self.pdf.get_string_width(aday) <= genislik - 1:
                mevcut = aday
            else:
                if mevcut:
                    satirlar.append(mevcut)
                # Tek kelime sütundan genişse parçala
                if self.pdf.get_string_width(kelime) > genislik - 1:
                    parca = ""
                    for ch in kelime:
                        if self.pdf.get_string_width(parca + ch) <= genislik - 1:
                            parca += ch
                        else:
                            if parca:
                                satirlar.append(parca)
                            parca = ch
                    mevcut = parca
                else:
                    mevcut = kelime
        if mevcut:
            satirlar.append(mevcut)
        return satirlar or [""]

    def _yaz(self, genislik: float, satir_yuk: float, text: str, kalin: bool = False, boyut: float = 9.5) -> None:
        self._sayfa_yeterli(satir_yuk * 2)
        self._sol()
        self.pdf.set_font("TR", "B" if kalin else "", boyut)
        self.pdf.multi_cell(
            genislik,
            satir_yuk,
            _temiz(text),
            align=self._Align.L,
            new_x=self._XPos.LMARGIN,
            new_y=self._YPos.NEXT,
        )

    def antet(self, profil: YatirimProfili, snap: MacroSnapshot) -> None:
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        veri = _zaman_kisa(snap.veri_zamani)
        self.pdf.set_fill_color(0, 51, 102)
        self.pdf.rect(0, 0, 210, 30, "F")
        self.pdf.set_text_color(255, 255, 255)
        self.pdf.set_xy(self._kenar, 8)
        self.pdf.set_font("TR", "B", 18)
        self.pdf.cell(
            self._w(), 8, "Yatırım Raporu",
            new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT,
        )
        self._sol()
        self.pdf.set_x(self._kenar)
        self.pdf.set_font("TR", "", 10)
        self.pdf.cell(
            self._w(), 5, "Kişisel Portföy Asistanı  ·  Makro Analiz & Hisse Taraması",
            new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT,
        )
        self.pdf.ln(6)
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.set_font("TR", "", 8.5)
        self.paragraf(f"Rapor tarihi: {now}  ·  Veri güncellemesi: {veri}  ·  Mod: {snap.veri_kaynak.upper()}")
        self.paragraf(f"Yatırımcı profili: {profil.ozet()}")
        self.pdf.ln(2)

    def bolum(self, baslik: str) -> None:
        self._sayfa_yeterli(16)
        self.pdf.ln(3)
        self._sol()
        self.pdf.set_font("TR", "B", 12)
        self.pdf.set_text_color(0, 51, 102)
        self.pdf.cell(self._w(), 7, baslik, new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT)
        self.pdf.set_draw_color(0, 51, 102)
        y = self.pdf.get_y()
        self.pdf.line(self.pdf.l_margin, y, self.pdf.w - self.pdf.r_margin, y)
        self.pdf.ln(2.5)
        self.pdf.set_text_color(0, 0, 0)

    def paragraf(self, metin: str) -> None:
        self._yaz(self._w(), 4.8, metin, boyut=9.5)

    def madde(self, metin: str) -> None:
        self._yaz(self._w(), 4.5, "• " + _temiz(metin), boyut=9)

    def kutu(self, baslik: str, metin: str) -> None:
        self._sayfa_yeterli(18)
        w = self._w()
        self.pdf.set_fill_color(240, 244, 248)
        self._sol()
        self.pdf.set_font("TR", "B", 9.5)
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.multi_cell(
            w, 5.2, _temiz(baslik), fill=True, align=self._Align.L,
            new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT,
        )
        self._sol()
        self.pdf.set_font("TR", "", 9)
        self.pdf.multi_cell(
            w, 4.5, _temiz(metin), fill=True, align=self._Align.L,
            new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT,
        )
        self.pdf.ln(2)

    def tablo(
        self,
        basliklar: List[str],
        satirlar: List[List[str]],
        col_w: Optional[List[float]] = None,
        font_boyut: float = 8,
        satir_yuk: float = 4.2,
    ) -> None:
        if not satirlar:
            return
        n = len(basliklar)
        w = self._w()
        if not col_w:
            col_w = [w / n] * n
        # Sütun toplamı taşmasın
        toplam = sum(col_w)
        if abs(toplam - w) > 0.5:
            col_w = [c * w / toplam for c in col_w]

        pad = 1.2

        def _hucre_ciz(x: float, y: float, cw: float, rh: float, text: str, kalin: bool, fill: bool, baslik_renk: bool) -> None:
            self.pdf.set_xy(x, y)
            if baslik_renk:
                self.pdf.set_fill_color(0, 51, 102)
                self.pdf.set_text_color(255, 255, 255)
            elif fill:
                self.pdf.set_fill_color(248, 249, 250)
                self.pdf.set_text_color(0, 0, 0)
            else:
                self.pdf.set_text_color(0, 0, 0)
            self.pdf.set_font("TR", "B" if kalin else "", font_boyut)
            self.pdf.rect(x, y, cw, rh, style="DF" if (fill or baslik_renk) else "D")
            satirlar_txt = self._metin_satirlari(text, cw - 2 * pad)
            ty = y + pad
            for sat in satirlar_txt:
                self.pdf.set_xy(x + pad, ty)
                self.pdf.cell(cw - 2 * pad, satir_yuk, sat, new_x=self._XPos.RIGHT, new_y=self._YPos.TOP)
                ty += satir_yuk

        def _satir_yuksekligi(hucreler: List[str], cw_list: List[float]) -> float:
            self.pdf.set_font("TR", "", font_boyut)
            max_sat = 1
            for txt, cw in zip(hucreler, cw_list):
                max_sat = max(max_sat, len(self._metin_satirlari(txt, cw - 2 * pad)))
            return max(satir_yuk * max_sat + 2 * pad, satir_yuk + 2 * pad)

        # Başlık satırı
        rh = _satir_yuksekligi(basliklar, col_w)
        self._sayfa_yeterli(rh + 4)
        y0 = self.pdf.get_y()
        x = self.pdf.l_margin
        for i, h in enumerate(basliklar):
            _hucre_ciz(x, y0, col_w[i], rh, h, True, True, True)
            x += col_w[i]
        self.pdf.set_y(y0 + rh)

        # Veri satırları
        fill = False
        for row in satirlar:
            hucreler = (row + [""] * n)[:n]
            rh = _satir_yuksekligi(hucreler, col_w)
            self._sayfa_yeterli(rh + 2)
            y0 = self.pdf.get_y()
            x = self.pdf.l_margin
            for i, cell in enumerate(hucreler):
                _hucre_ciz(x, y0, col_w[i], rh, cell, False, fill, False)
                x += col_w[i]
            self.pdf.set_y(y0 + rh)
            fill = not fill
        self.pdf.ln(2)

    def footer_disclaimer(self) -> None:
        self._sayfa_yeterli(16)
        self.pdf.ln(4)
        self.pdf.set_draw_color(180, 180, 180)
        y = self.pdf.get_y()
        self.pdf.line(self.pdf.l_margin, y, self.pdf.w - self.pdf.r_margin, y)
        self.pdf.ln(2)
        self.pdf.set_font("TR", "", 7.5)
        self.pdf.set_text_color(100, 100, 100)
        self._sol()
        self.pdf.multi_cell(
            self._w(), 3.8,
            "Yasal uyarı: Bu rapor otomatik üretilmiş bir karar-destek belgesidir; yatırım tavsiyesi "
            "niteliği taşımaz. Geçmiş performans gelecek getirileri garanti etmez. "
            "Nihai yatırım kararı tamamen yatırımcıya aittir. © Kişisel Portföy Asistanı",
            align=self._Align.L,
            new_x=self._XPos.LMARGIN,
            new_y=self._YPos.NEXT,
        )

    def bytes(self) -> bytes:
        buf = io.BytesIO()
        self.pdf.output(buf)
        return buf.getvalue()


def rapor_pdf_direkt_olustur(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    profil: YatirimProfili,
    danisman: DanismanRaporu,
    mevduat: Optional[MevduatKarsilastirma] = None,
    tl_durum: Optional[TlDurumOzeti] = None,
    toplam_eur: float = None,
    tarama: Optional[TaramaSonucu] = None,
    tl_mevduat_tutar_tl: Optional[float] = None,
    birlesik_oneri=None,
    varlik_store=None,
    kullanici_portfoy=None,
    para_birimi: str = "EUR",
) -> bytes:
    toplam_eur = toplam_eur or config.TOPLAM_EUR
    if kullanici_portfoy is None:
        from kullanici_portfoy import varsayilan_portfoy
        kullanici_portfoy = varsayilan_portfoy()
    v = snap.veri
    vade = VADE_SECENEKLERI.get(profil.vade, profil.vade)
    doc = RaporPDF()
    doc.antet(profil, snap)

    # ── Backtest özet uyarısı — section 1'e taşı ─────────────────────────────
    _bt_ozet_uyari = ""
    try:
        _bt_s = backtest_calistir(12, profil=profil)
        _bt_k = backtest_karsilastirma_uret(
            _bt_s, tahsis.rejim.rejim,
            bugun_agirliklar=tahsis.agirliklar, profil=profil
        )
        if _bt_k:
            _bt_m = _bt_k.dinamik
            _bt_r = _bt_k.referans_statik
            _bt_rejim_hic = (
                tahsis.rejim.rejim
                and _bt_m.mevcut_rejim_oran_pct is not None
                and _bt_m.mevcut_rejim_oran_pct < 1
            )
            if _bt_k.dinamik_dezavantaj and _bt_rejim_hic:
                _bt_ozet_uyari = (
                    f"Model sınırı: Son 12 ayda dinamik rejim modeli statik tahsisten "
                    f"daha kötü performans sergiledi (Sharpe: {_bt_m.sharpe_yillik:.2f} vs "
                    f"{_bt_r.sharpe_yillik:.2f}). Mevcut rejim "
                    f"({tahsis.rejim.rejim.replace('_', ' ')}) simülasyon döneminde "
                    "hiç görülmedi — öneri seti test edilmemiş koşullara dayanıyor. "
                    "Spesifik yüzdelerden çok çerçeveyi esas alınız. "
                    "Tam analiz: Teknik Ekler > Backtest bölümü."
                )
            elif _bt_k.dinamik_dezavantaj:
                _bt_ozet_uyari = (
                    f"Model uyarısı: Dinamik rejim modeli son 12 ayda statik referanstan "
                    f"geride (Sharpe: {_bt_m.sharpe_yillik:.2f} vs {_bt_r.sharpe_yillik:.2f}). "
                    "Önerileri rehber olarak kullanın, kesin emir olarak değil."
                )
    except Exception:
        pass

    # ── 1. BUGÜNKÜ ÖZET & AKSİYONLAR ─────────────────────────────────────────
    doc.bolum("Bugünkü Durum ve Önerilen Aksiyonlar")
    doc.kutu(
        f"Piyasa rejimi: {tahsis.rejim.etiket}",
        _temiz(tahsis.rejim.aciklama, 400),
    )
    if _bt_ozet_uyari:
        doc.kutu("Model Sınırı — Önemli", _temiz(_bt_ozet_uyari, 600))
    doc.paragraf(_temiz(danisman.genel_ozet, 600))
    for n in (tahsis.profil_notlari or [])[:3]:
        doc.madde(_temiz(n, 160))

    # ── 2. ÖNERİLEN PORTFÖY DAĞILIMI ─────────────────────────────────────────
    doc.bolum("Önerilen Portföy Dağılımı")
    doc.paragraf(
        f"Toplam portföy: {toplam_eur:,.0f} EUR  ·  Yatırım vadesi: {vade}  ·  "
        f"TL maksimum pay: %{tahsis.tl_tavan_oran * 100:.0f}"
    )
    pf_rows = []
    for k in sorted(VARLIKLAR, key=lambda x: -tahsis.agirliklar.get(x, 0)):
        wgt = tahsis.agirliklar.get(k, 0)
        if wgt < 0.005:
            continue
        pf_rows.append([
            config.VARLIK_ETIKETLERI[k],
            f"%{wgt * 100:.1f}",
            f"{toplam_eur * wgt:,.0f} EUR",
        ])
    w = doc._w()
    doc.tablo(
        ["Varlık Sınıfı", "Portföyden Pay", "Tutar (EUR)"],
        pf_rows,
        col_w=[w * 0.46, w * 0.20, w * 0.34],
    )
    doc.paragraf(_temiz(tahsis.tavsiye_metni, 400))

    # ── 3. BİRLEŞİK ÖNERİLER (aksiyon listesi) ───────────────────────────────
    from rapor_ek_bolumler import birlesik_oneri_pdf_bolumu, varliklarim_pdf_bolumu

    birlesik_oneri_pdf_bolumu(
        doc,
        birlesik_oneri,
        para_birimi=para_birimi or "EUR",
        toplam_eur=toplam_eur,
        eur_try=v.eur_try or 35.0,
        makro_agirliklar=tahsis.agirliklar,
    )

    # ── 4. HİSSE & ETF YATIRIM ÖNERİLERİ ────────────────────────────────────
    if tarama and (tarama.endeksler or tarama.hisseler):
        _tarama_bolumu(doc, tarama, tahsis.rejim.etiket)

    # ── 5. VARLIKLARIM POZİSYONLARI ──────────────────────────────────────────
    varliklarim_pdf_bolumu(doc, varlik_store, snap, kullanici_portfoy)

    # ── 6. TL MEVDUAT DEĞERLENDİRMESİ ────────────────────────────────────────
    if tl_durum:
        doc.bolum("TL Mevduat Kararı")
        doc.kutu(
            tl_durum.baslik,
            f"Portföydeki pay: %{tl_durum.agirlik_pct:.1f}  ·  Maksimum tavan: %{tl_durum.tavan_pct:.0f}",
        )
        for n in tl_durum.nedenler[:6]:
            doc.madde(_temiz(n, 200))
        doc.paragraf(_temiz(f"Alternatif değerlendirme: {tl_durum.alternatif}", 220))

    if mevduat and mevduat.getiri_notu:
        profil_reel = getattr(mevduat, "profil_vade_reel", None)
        profil_eur = getattr(mevduat, "profil_vade_eur_tahmini", None)
        reel_cok_dusuk = profil_reel is not None and profil_reel < 0.5
        eur_pozitif = profil_eur is not None and profil_eur > 0
        baslik = "Getiri tanımı — önemli not"
        if reel_cok_dusuk:
            baslik = "Getiri tanımı — DİKKAT: Yerel reel getiri pratikte sıfır"
        metin = f"Yerel (TL) reel getiri ile EUR bazlı getiri farklıdır. {mevduat.getiri_notu}"
        if reel_cok_dusuk:
            metin += (
                f" Profilinizin vadesi için yerel reel getiri yalnızca "
                f"{profil_reel:+.1f} puan — pratikte enflasyona karşı sıfır koruma. "
            )
        if eur_pozitif and profil_eur is not None:
            metin += (
                f"EUR bazlı tahmin {profil_eur:+.1f} puan, ancak bu tahmin "
                "EUR/TRY kurunun vade boyunca değişmeyeceği varsayımına dayanır. "
                "Kur şok senaryosunda bu getiri negatife dönebilir."
            )
        doc.kutu(baslik, _temiz(metin, 600))
        doc.paragraf(
            f"Profil vadeniz ({mevduat.profil_vade}): "
            f"yerel reel {profil_reel:+.1f} puan  ·  "
            f"EUR bazlı tahmini {profil_eur:+.1f} puan (kur sabit varsayımı)  ·  "
            f"EUR mevduat net ~%{mevduat.eur_mevduat_net:.1f}."
        )

    if mevduat and mevduat.oranlar:
        doc.bolum("TL Mevduat Faiz Oranları")
        doc.paragraf(_temiz(mevduat.ozet, 350))
        doc.paragraf(
            '"EUR Karşılığı" sütunu, EUR/TRY kurunun vade boyunca sabit kalacağı varsayımıyla '
            "hesaplanmıştır. Kur oynaklığı bu tahmini önemli ölçüde değiştirebilir."
        )
        mev_rows = []
        for o in mevduat.oranlar:
            tag = " ✓ Profiliniz" if o.vade == mevduat.profil_vade else ""
            net_pct = (o.net_yillik or 0) * 100
            eur_tah = (
                f"{_eur_bazli_tahmini(net_pct, mevduat.enflasyon):+.1f}*"
                if o.vade.startswith("TL") else "—"
            )
            reel_flag = ""
            if (o.reel_yillik or 0) < 0.5 and o.vade.startswith("TL"):
                reel_flag = " (!)"
            mev_rows.append([
                o.vade + tag,
                f"%{o.brut_yillik * 100:.1f}",
                f"%{net_pct:.1f}",
                f"{o.reel_yillik or 0:+.1f} puan{reel_flag}",
                eur_tah,
            ])
        doc.tablo(
            ["Vade", "Brüt Faiz", "Net Faiz", "Enf. Üstü Getiri", "EUR Karşılığı (tahmini)"],
            mev_rows,
            col_w=[w * 0.26, w * 0.14, w * 0.14, w * 0.22, w * 0.24],
        )
        from rates_tr import tl_vade_sonu_hesapla, tl_vade_sonu_rapor_metni, tmsf_uyari_satirlari

        profil_o = next((o for o in mevduat.oranlar if o.vade == mevduat.profil_vade), None)
        if profil_o and v.eur_try:
            gun = profil_o.vade_gun or 365
            tl_tutar = getattr(config, "TL_MEVDUAT_TUTAR_TL", None)
            ozet = tl_vade_sonu_hesapla(
                toplam_eur=toplam_eur,
                tl_agirlik=tahsis.agirliklar.get("tl_deposit", 0),
                eur_try=v.eur_try,
                brut_yillik=profil_o.brut_yillik,
                gun=gun,
                manuel_anapara_tl=tl_mevduat_tutar_tl or tl_tutar,
            )
            if ozet:
                doc.paragraf(_temiz(tl_vade_sonu_rapor_metni(ozet), 480))
                for tmsf in tmsf_uyari_satirlari(ozet.anapara_tl):
                    doc.madde(_temiz(tmsf, 220))
                doc.madde(
                    "Vadeden önce bozmada faiz kaybı yaşanır. Acil ihtiyaç fonunuzu bu tutarın dışında tutunuz."
                )

    # ── 7. MAKRO VERİLER ──────────────────────────────────────────────────────
    doc.bolum("Makro Göstergeler")
    rezerv = (
        "Artıyor" if v.rezerv_artiyor
        else "Azalıyor" if v.rezerv_artiyor is False
        else "Bilinmiyor"
    )
    siyasi_pencere = getattr(config, "SIYASI_RISK_TARAMA_SAAT", 24)
    siyasi_metin = (
        f"{v.siyasi_risk_makale_sayisi} haber (son {siyasi_pencere}s)"
        if v.siyasi_risk_makale_sayisi is not None else "—"
    )
    savas_metin = (
        f"{v.savas_risk_makale_sayisi} haber (son 48s)"
        if v.savas_risk_makale_sayisi is not None and v.savas_risk_guvenilir is not False
        else (
            f"Güvenilmez — {v.savas_risk_makale_sayisi or 0} haber (son 48s)"
            if v.savas_risk_guvenilir is False else "—"
        )
    )
    doc.tablo(
        ["Gösterge", "Değer", "Gösterge", "Değer"],
        [
            ["EUR/TRY", _sayi(v.eur_try), "USD/TRY", _sayi(v.usd_try)],
            ["TCMB Faizi", f"%{_sayi(v.tcmb_politika_faizi, 1)}", "Fed Faizi (ABD)", f"%{_sayi(v.fed_faizi, 2)}"],
            ["Enflasyon (TR)", f"%{_sayi(snap.enflasyon_tr_yillik, 1)}", "BIST 100", _sayi(snap.bist100, 0)],
            ["Altın (USD/oz)", f"${_sayi(snap.altin_usd_oz, 0)}", "BTC (USD)", f"${_sayi(snap.btc_usd, 0)}"],
            ["Ülke riski (CDS)", f"{_sayi(v.cds_5y_bp, 0)} bp", "ABD Korku Endeksi (VIX)", _sayi(snap.vix, 1)],
            [f"Siyasi risk (son {siyasi_pencere}s)", siyasi_metin,
             "Jeopolitik risk (son 48s)", savas_metin],
            ["Döviz rezervleri", rezerv, "TL maksimum pay", f"%{tahsis.tl_tavan_oran * 100:.0f}"],
        ],
        col_w=[w * 0.32, w * 0.18, w * 0.32, w * 0.18],
    )
    doc.paragraf(
        f"Siyasi ve jeopolitik haber sayıları farklı zaman pencerelerinden (sırasıyla "
        f"son {siyasi_pencere}s ve son 48s) farklı kaynaklarla taranır; "
        "sayılar arasındaki fark bu nedenle normaldir."
    )

    if danisman.makro_baglam and danisman.makro_baglam.parcalar:
        doc.bolum("Makro Piyasa Değerlendirmesi")
        for p in danisman.makro_baglam.parcalar[:5]:
            doc.kutu(
                _temiz(p.baslik, 60),
                _temiz(f"{p.canli} — {p.beklenti}", 320),
            )

    # ── 8. VARLIK STRATEJİ NOTLARI ────────────────────────────────────────────
    doc.bolum("Varlık Bazlı Strateji Notları")
    for var in danisman.varliklar:
        if var.agirlik_pct < 0.5 and var.sinyal == "KACIN":
            continue
        doc.kutu(
            _temiz(f"{var.ad}  ·  {var.sinyal_etiket}  ·  Portföy payı: %{var.agirlik_pct:.0f}", 80),
            _temiz(var.baslik, 200),
        )
        for n in var.nedenler[:2]:
            doc.madde(_temiz(n, 160))

    # ── 9. TEKNİK EKLER ───────────────────────────────────────────────────────
    _girdi_dogrulama_bolumu(doc, snap)

    if danisman.denetim and danisman.denetim.bulgular:
        doc.bolum("Tutarlılık Kontrolleri")
        doc.paragraf(_temiz(danisman.denetim.ozet, 200))
        for b in danisman.denetim.bulgular[:5]:
            doc.madde(_temiz(f"[{b.seviye}] {b.baslik}", 120))

    if tahsis.tl_karar_adimlari:
        doc.bolum("TL Karar Adımları (Teknik Detay)")
        doc.paragraf(
            "Her satır bir indirim basamağını gösterir. 'Kapı' satırları karar motorunun "
            "çıktısı (en yüksek olası tavan). Sonraki satırlar reel getiri, rejim ve risk "
            "kısıtlamalarını uygular ve tavan daha da düşebilir. "
            "'ham': GDELT ham sayısı · 'etkin'/'kapı': duygu analizi ile ağırlıklandırılmış."
        )
        for adim in tahsis.tl_karar_adimlari:
            doc.madde(_temiz(adim, 200))

    vk = veri_kalite_olustur(snap)
    _veri_kalite_bolumu(doc, vk)

    from investor_profile import profil_mevduat_vadesi

    _, profil_vade_gun = profil_mevduat_vadesi(tahsis.profil or YatirimProfili())
    _senaryo_bolumu(doc, snap, tahsis, profil_vade_gun, tarama=tarama, birlesik_oneri=birlesik_oneri)

    _backtest_bolumu(doc, tahsis.rejim.rejim, profil, sabit_agirliklar=tahsis.agirliklar)

    doc.footer_disclaimer()
    return doc.bytes()
