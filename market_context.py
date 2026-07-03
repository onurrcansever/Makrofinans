# -*- coding: utf-8 -*-
"""
Canlı Makro Bağlam Motoru
=========================
Fed, CDS, altın ve TL için güncel veri + trend + ileriye dönük kural tabanlı yorum.
Gerçek LLM değil; tüm iddialar sayısal veriye dayanır.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Tuple

from allocation_engine import TahsisSonucu
from investor_profile import (
    VADE_SECENEKLERI,
    YatirimProfili,
    profil_mevduat_vadesi,
    vade_cok_kisa_mi,
    vade_kisa_mi,
)
from macro_data import MacroSnapshot

_CACHE: dict = {"ts": 0.0, "yf": {}}
_CACHE_TTL = 3600

CDS_BANTLAR = [
    (200, "Çok düşük", "Türkiye için nadir; güçlü güven ortamı."),
    (280, "Normal", "Tipik band; TL ve yerel varlıklar için tolere edilebilir risk."),
    (350, "Yüksek", "Stres sinyali; kur oynaklığı artabilir."),
    (450, "Kritik", "Kriz eşiği; TL ve BIST agresif azaltılır."),
    (9999, "Aşırı", "Acil koruma modu."),
]

FOMC_2026 = [
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 5, 6), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 11, 4), date(2026, 12, 16),
]

TCMB_PPK_2026 = [
    date(2026, 1, 23), date(2026, 3, 19), date(2026, 4, 24), date(2026, 6, 19),
    date(2026, 7, 24), date(2026, 8, 21), date(2026, 9, 18), date(2026, 10, 23),
    date(2026, 11, 20), date(2026, 12, 18),
]


@dataclass
class BaglamParcasi:
    baslik: str
    canli: str
    konum: str
    trend: str
    beklenti: str
    kaynak: str
    ok: str = "→"


@dataclass
class MakroBaglam:
    parcalar: List[BaglamParcasi] = field(default_factory=list)
    guncelleme: str = ""


def _yf_trend(ticker: str, gun: int = 63) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    simdi = time.time()
    if simdi - _CACHE["ts"] < _CACHE_TTL and ticker in _CACHE["yf"]:
        return _CACHE["yf"][ticker]
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="6mo", auto_adjust=True)
        if h.empty:
            return None, None, None
        guncel = float(h["Close"].iloc[-1])
        once = float(h["Close"].iloc[-gun]) if len(h) > gun else float(h["Close"].iloc[0])
        sonuc = (guncel, once, guncel - once)
        _CACHE["yf"][ticker] = sonuc
        _CACHE["ts"] = simdi
        return sonuc
    except Exception:
        return None, None, None


def _yf_aralik(ticker: str, period: str = "1y") -> Tuple[Optional[float], Optional[float], Optional[float]]:
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if h.empty:
            return None, None, None
        return float(h["Close"].iloc[-1]), float(h["Close"].max()), float(h["Close"].min())
    except Exception:
        return None, None, None


def _sonraki_tarih(takvim: List[date]) -> Tuple[date, int]:
    bugun = date.today()
    sonraki = min(d for d in takvim if d >= bugun)
    return sonraki, (sonraki - bugun).days


def _cds_konum(bp: float) -> Tuple[str, str, str]:
    onceki = 150
    for esik, etiket, aciklama in CDS_BANTLAR:
        if bp < esik:
            aralik = f"{onceki}–{esik} bp ({etiket})"
            kalan = esik - bp
            konum = (
                f"**{bp:.0f} bp** — {etiket} bölgede. "
                f"Bir üst stres eşiğine (**{esik} bp**) ~**{kalan:.0f} bp** mesafe var."
            )
            return aralik, konum, aciklama
        onceki = esik
    return ">450 bp", f"**{bp:.0f} bp** — kritik bölge.", "Acil risk azaltımı."


def _eurtry_vol_kisa() -> Tuple[Optional[float], str]:
    try:
        from macro_auto import _eurtry_volatilite
        vol = _eurtry_volatilite(90)
        if vol is not None:
            return vol * 100, f"Son 90 gün yıllıklandırılmış vol **%{vol*100:.1f}**"
    except Exception:
        pass
    return None, "Kur volatilitesi hesaplanamadı."


def _kisa_vade_beklenti(
    snap: MacroSnapshot,
    ykb_profil: Optional[float],
    siyasi: int,
    vade: str,
    profil_vade_etiket: str,
) -> str:
    vol, vol_metin = _eurtry_vol_kisa()
    sonraki, gun = _sonraki_tarih(TCMB_PPK_2026)
    vol_uyari = ""
    if vol and vol > 25:
        vol_uyari = f" Kur oynaklığı yüksek (**%{vol:.1f}**) — kısa ufuk için EUR/USD mevduat öncelikli olabilir."
    elif vol and vol < 18:
        vol_uyari = f" Kur volatilitesi görece sakin (**%{vol:.1f}**) — kısa TL mevduat penceresi açık."
    faiz_notu = ""
    if ykb_profil:
        faiz_notu = f" Yapı Kredi **{profil_vade_etiket} %{ykb_profil:.1f}** brüt — profil vadenize uygun tenör."
    vade_metin = VADE_SECENEKLERI.get(vade, vade)
    return (
        f"**{vade_metin}:** Kararınızı **banka faizi, kur hareketi ve bir sonraki TCMB toplantısı** "
        f"({sonraki.strftime('%d.%m.%Y')}, {gun} gün) belirler.{faiz_notu} "
        f"{vol_metin}.{vol_uyari} "
        f"Siyasi haber yoğunluğu: **{siyasi}** (48 saat)."
    )


def _cds_beklenti_vade(vade: str, cds: float) -> str:
    if vade_cok_kisa_mi(vade):
        ufuk = "0–3 ay" if vade == "kisa_3" else "0–6 ay"
        return (
            f"CDS 5Y (**{cds:.0f} bp**) uzun vadeli ülke risk primidir; **{ufuk}** kararınızda "
            f"doğrudan kullanılmaz — referans olarak tutulur. Kısa vadede **kur volatilitesi, "
            f"banka mevduat faizi ve TCMB PPK** daha belirleyicidir. "
            f"CDS **280 bp** üzerinde EM stres sinyali güçlenir."
        )
    if vade == "kisa":
        return (
            f"CDS 5Y (**{cds:.0f} bp**) uzun vadeli ülke risk primidir; **0–12 ay** kararınızda "
            f"ikincil referans. Kısa vadede **kur volatilitesi, 3–6 ay mevduat faizi ve TCMB PPK** "
            f"daha belirleyicidir. CDS **280 bp** üzerinde EM stres sinyali güçlenir."
        )
    if vade == "uzun":
        return (
            f"CDS **{cds:.0f} bp** — 3+ yıl ufku için ülke riski doğrudan geçerli. "
            f"**280 bp** üzeri EM stres, **350 bp** üzeri ciddi kur baskısı sinyali."
        )
    return (
        f"CDS **{cds:.0f} bp** — 1–3 yıl ufku için orta vadeli ülke riski göstergesi. "
        f"**280 bp** üzerine çıkarsa sistem **EM stres** rejimine geçer."
    )


def _fed_beklenti(irx_chg: Optional[float], tnx_chg: Optional[float], fed: float) -> str:
    if irx_chg is None:
        return (
            f"Fed fon faizi **%{fed:.2f}** seviyesinde. "
            "Piyasa beklentisi için tahvil eğrisi verisi şu an sınırlı."
        )
    if tnx_chg is not None and tnx_chg < -0.15 and irx_chg <= 0:
        yon = "gevşeme (faiz indirimi)"
    elif irx_chg > 0.15:
        yon = "sıkılaşma veya bekle-gör"
    else:
        yon = "mevcut seviyede kalma (pause)"

    sonraki, gun = _sonraki_tarih(FOMC_2026)
    return (
        f"Piyasa sinyali: **{yon}** eğilimi. "
        f"10Y tahvil son 3 ay **{tnx_chg:+.2f} pp**, kısa faiz **{irx_chg:+.2f} pp** değişti. "
        f"Sonraki FOMC: **{sonraki.strftime('%d.%m.%Y')}** ({gun} gün) — karar o tarihte netleşir."
    )


def _altin_beklenti(fiyat: float, yuksek: float, dusuk: float, deg3m: Optional[float]) -> str:
    if not yuksek or not dusuk or yuksek <= dusuk:
        return "Teknik bant verisi yok — makro koruma gerekçesi öncelikli."
    band = yuksek - dusuk
    konum_pct = (fiyat - dusuk) / band * 100
    if konum_pct > 85:
        konum = "52 hafta bandının **üst %15'inde** — kısa vadede kar satışı normal."
    elif konum_pct < 25:
        konum = "52 hafta bandının **alt çeyreğinde** — toparlanma potansiyeli."
    else:
        konum = f"52 hafta bandının **%{konum_pct:.0f}** noktasında — orta bölge."

    trend = ""
    if deg3m is not None:
        if deg3m > 5:
            trend = f" Son 3 ay **+{deg3m:.1f}%** yükseliş; momentum güçlü."
        elif deg3m < -5:
            trend = f" Son 3 ay **{deg3m:.1f}%** düşüş; kademeli alım düşünülebilir."
        else:
            trend = f" Son 3 ay yatay (**{deg3m:+.1f}%**)."

    return konum + trend + " Fed ve reel faiz beklentisi altın talebini belirler."


def _tl_beklenti(snap: MacroSnapshot, tahsis: TahsisSonucu, ykb_3ay: Optional[float]) -> str:
    tcmb = snap.veri.tcmb_politika_faizi or 37
    enf = snap.enflasyon_tr_yillik or 35
    reel = tcmb - enf
    cds = snap.veri.cds_5y_bp or 265
    sonraki, gun = _sonraki_tarih(TCMB_PPK_2026)

    if tahsis.rejim.rejim != "TL_FIRSAT":
        return (
            f"Mevcut rejim **{tahsis.rejim.etiket}** — TL fırsat koşulları tam sağlanmıyor. "
            f"Reel faiz ~**{reel:+.1f} pp**, CDS **{cds:.0f} bp**."
        )

    if reel <= 0:
        return (
            "Reel faiz negatif — TL mevduat **enflasyonu yenemiyor**. "
            "Enflasyon verisi veya TCMB kararı değişene kadar caziyet sınırlı."
        )

    vade_notu = ""
    if ykb_3ay and ykb_3ay > 35:
        vade_notu = (
            f" Yapı Kredi 3 ay brüt **%{ykb_3ay:.1f}** — kısa vade reel getiri güçlü; "
            "**3–6 ay** pencere mantıklı."
        )
    elif ykb_3ay:
        vade_notu = f" Banka 3 ay faizi **%{ykb_3ay:.1f}** — orta vade tercih edin."

    return (
        f"TL fırsat rejimi aktif: reel faiz **+{reel:.1f} pp**, CDS **{cds:.0f} bp** (<280). "
        f"**Ne zamana kadar?** CDS 280 bp'yi aşana, reel faiz sıfırın altına inene veya "
        f"siyasi risk artana kadar — pratikte **{sonraki.strftime('%d.%m')} TCMB PPK**'ye "
        f"({gun} gün) kadar izleyin.{vade_notu}"
    )


def makro_baglam_olustur(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    kaynak_haritasi: Optional[dict] = None,
    profil: Optional[YatirimProfili] = None,
) -> MakroBaglam:
    kh = kaynak_haritasi or snap.kaynak_haritasi or {}
    profil = profil or tahsis.profil or YatirimProfili()
    vade = profil.vade
    profil_vade_etiket, _ = profil_mevduat_vadesi(profil)
    parcalar: List[BaglamParcasi] = []

    ykb_3ay = ykb_6ay = ykb_1y = None
    try:
        from yapikredi_rates import yapikredi_tl_faizleri
        ykb = yapikredi_tl_faizleri()
        if ykb:
            ykb_3ay, ykb_6ay, ykb_1y = ykb.tl_3ay_brut, ykb.tl_6ay_brut, ykb.tl_1y_brut
    except Exception:
        pass
    ykb_profil = {"TL 3 ay": ykb_3ay, "TL 6 ay": ykb_6ay, "TL 1 yıl": ykb_1y}.get(profil_vade_etiket)

    siyasi = snap.veri.siyasi_risk_makale_sayisi or 5
    savas = snap.veri.savas_risk_makale_sayisi or 0
    savas_guven = snap.veri.savas_risk_guvenilir
    savas_kaynak = kh.get("savas_risk", "GDELT")

    savas_ok = "↗" if savas >= 8 else ("→" if savas >= 4 else "↘")
    if savas_guven is False:
        savas_ok = "?"
    parcalar.append(BaglamParcasi(
        baslik="Jeopolitik / savaş riski",
        canli=(
            f"Son 48 saat: **{savas}** haber (Hürmüz, İran, enerji)"
            if savas_guven is not False
            else f"Tarama **güvenilir değil** (ham sayı: {savas}) — manuel teyit şart"
        ),
        konum=(
            "Google News TR + GDELT; Türkçe finans siteleri (Dünya, Mynet vb.) dahil. "
            "Haber **sayısı** — şiddet ağırlığı yok."
        ),
        trend=(
            f"Siyasi iç risk (CHP vb.): **{siyasi}** haber — ayrı indeks."
        ),
        beklenti=(
            "Orta Doğu gerilimi (İran-İsrail, Hürmüz) kur, petrol ve CDS kanallarını etkiler; "
            "haber akışını izleyin."
            if savas_guven is not False and savas >= 4
            else (
                "Jeopolitik tarama boş veya erişilemedi — 'düşük risk' **varsaymayın**; "
                "bugünkü Türkçe finans haberlerini manuel kontrol edin."
                if savas_guven is False
                else "Jeopolitik tansiyon düşük sayılıyor; yine de tranşlı girin."
            )
        ),
        kaynak=savas_kaynak,
        ok=savas_ok,
    ))

    fed = snap.veri.fed_faizi or 4.0
    irx, _, irx_chg = _yf_trend("^IRX")
    tnx, _, tnx_chg = _yf_trend("^TNX")
    fed_kaynak = kh.get("fed_faizi", "Canlı / proxy")
    if irx_chg is not None and irx_chg > 0.1:
        ok = "↗"
    elif irx_chg is not None and irx_chg < -0.1:
        ok = "↘"
    else:
        ok = "→"
    parcalar.append(BaglamParcasi(
        baslik="Fed & USD",
        canli=f"Fed fon ~**%{fed:.2f}** · 10Y tahvil ~**%{tnx:.2f}**" if tnx else f"Fed fon ~**%{fed:.2f}**",
        konum="ABD faizleri global USD mevduat ve dolar talebini belirler.",
        trend=(
            f"Son 3 ay: kısa vade **{irx_chg:+.2f} pp**, 10Y **{tnx_chg:+.2f} pp**"
            if irx_chg is not None and tnx_chg is not None
            else "Trend verisi sınırlı."
        ),
        beklenti=_fed_beklenti(irx_chg, tnx_chg, fed),
        kaynak=f"{fed_kaynak} · Yahoo ^IRX/^TNX",
        ok=ok,
    ))

    cds = float(snap.veri.cds_5y_bp or 265)
    aralik, konum, aciklama = _cds_konum(cds)
    cds_ok = "→" if cds < 280 else ("↗" if cds < 350 else "↑")
    cds_baslik = (
        "CDS 5Y (referans — yapısal risk)"
        if vade_kisa_mi(vade)
        else "Türkiye CDS (5Y)"
    )
    cds_konum = (
        f"{konum} *Kısa vade profilinizde birincil gösterge değil; kur volatilitesi ve banka faizi öncelikli.*"
        if vade_kisa_mi(vade)
        else konum
    )
    parcalar.append(BaglamParcasi(
        baslik=cds_baslik,
        canli=f"**{cds:.0f} bp**",
        konum=cds_konum,
        trend=f"Bant: {aralik}. {aciklama}",
        beklenti=_cds_beklenti_vade(vade, cds),
        kaynak=kh.get("cds", "Otomatik"),
        ok=cds_ok,
    ))

    if vade_kisa_mi(vade):
        vol, vol_metin = _eurtry_vol_kisa()
        vol_ok = "↗" if vol and vol > 22 else ("→" if vol and vol > 15 else "↘")
        parcalar.insert(0, BaglamParcasi(
            baslik=f"Profil vadeniz — {VADE_SECENEKLERI.get(vade, vade)}",
            canli=(
                f"**{profil_vade_etiket}** brüt **%{ykb_profil:.1f}** · EUR/TRY **{snap.veri.eur_try:.2f}**"
                if ykb_profil and snap.veri.eur_try
                else f"Profil: **{profil_vade_etiket}** · EUR/TRY **{snap.veri.eur_try or '—'}**"
            ),
            konum=vol_metin,
            trend=(
                f"Yapı Kredi canlı faiz · {vol_metin}" if ykb_profil else "Banka faizi bekleniyor."
            ),
            beklenti=_kisa_vade_beklenti(snap, ykb_profil, siyasi, vade, profil_vade_etiket),
            kaynak=kh.get("tl_mevduat", "Yapı Kredi") + " · Frankfurter",
            ok=vol_ok,
        ))

    altin = snap.altin_usd_oz
    guncel, yuksek, dusuk = _yf_aralik("GC=F")
    fiyat = altin or guncel
    deg3m = None
    if fiyat:
        try:
            import yfinance as yf
            h = yf.Ticker("GC=F").history(period="4mo")
            if len(h) > 20:
                eski = float(h["Close"].iloc[0])
                deg3m = (fiyat - eski) / eski * 100
        except Exception:
            pass
    if deg3m is not None and deg3m > 1:
        alt_ok = "↗"
    elif deg3m is not None and deg3m < -1:
        alt_ok = "↘"
    else:
        alt_ok = "→"
    parcalar.append(BaglamParcasi(
        baslik="Altın (spot)",
        canli=f"**${fiyat:,.0f}/oz**" if fiyat else "—",
        konum=(
            f"52 hafta: **${dusuk:,.0f}** – **${yuksek:,.0f}**"
            if yuksek and dusuk else "Bant hesaplanamadı."
        ),
        trend=f"3 aylık değişim: **{deg3m:+.1f}%**" if deg3m is not None else "Trend: —",
        beklenti=_altin_beklenti(fiyat or 0, yuksek or 0, dusuk or 0, deg3m),
        kaynak=kh.get("altin", "Yahoo GC=F"),
        ok=alt_ok,
    ))

    tcmb = snap.veri.tcmb_politika_faizi or 37
    enf = snap.enflasyon_tr_yillik or 35
    reel = tcmb - enf
    tl_ok = "↗" if reel > 1 else ("→" if reel > 0 else "↘")
    tl_trend = (
        f"Profil vadeniz **{profil_vade_etiket}** brüt **%{ykb_profil:.1f}** (canlı)"
        if ykb_profil
        else (
            f"Yapı Kredi 3ay **%{ykb_3ay:.1f}** brüt (canlı)" if ykb_3ay
            else "Banka faizi: canlı veri bekleniyor."
        )
    )
    parcalar.append(BaglamParcasi(
        baslik=f"TL mevduat & getiri tanımı ({profil_vade_etiket})",
        canli=(
            f"Net **%{ykb_profil:.1f}** brüt (canlı) · yerel reel **{reel:+.1f} pp** "
            f"(TL enflasyonu − net)"
            if ykb_profil
            else f"TCMB **%{tcmb:.0f}** · enflasyon ~**%{enf:.0f}** → yerel reel **{reel:+.1f} pp**"
        ),
        konum=(
            "**Yerel reel** TL satın alma gücünü ölçer; **EUR bazlı getiri** kur hareketine bağlıdır — "
            "aynı şey değildir."
        ),
        trend=tl_trend,
        beklenti=_tl_beklenti(snap, tahsis, ykb_3ay),
        kaynak=kh.get("tl_mevduat", "Yapı Kredi + TCMB"),
        ok=tl_ok,
    ))

    return MakroBaglam(
        parcalar=parcalar,
        guncelleme=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
