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
from backtest import backtest_calistir, backtest_metrikleri
from alim_uygunluk import alim_aksiyon_hucre

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


def _uygun_tablo_hucre(h) -> str:
    return alim_aksiyon_hucre(h)


def _hisse_sirala(hisseler: list) -> list:
    return sorted(
        hisseler,
        key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor),
    )


def _skor_sirala(hisseler: list) -> list:
    return sorted(hisseler, key=lambda h: -h.skor)


def _uygunluk_ozet_metin(tarama: TaramaSonucu) -> str:
    say = {"UYGUN": 0, "SINIRLI": 0, "UYGUN_DEGIL": 0, "IZLE": 0}
    for h in tarama.hisseler or []:
        k = getattr(h, "alim_uygun", "IZLE")
        say[k] = say.get(k, 0) + 1
    return (
        f"AL: {say['UYGUN']} · DİKKAT: {say['SINIRLI']} · "
        f"ALMA: {say['UYGUN_DEGIL']} · BEKLE: {say['IZLE']}"
    )


def _hisse_detay_madde(h) -> str:
    rsi_txt = f"{h.rsi:.0f}" if h.rsi is not None else "—"
    ek = ""
    if getattr(h, "alim_uygun_not", ""):
        ek += f" [{_temiz(h.alim_uygun_not, 70)}]"
    if getattr(h, "trend_notu", "") and h.trend_notu not in ("", "Trend filtresi OK"):
        ek += f" Trend: {_temiz(h.trend_notu, 55)}."
    if getattr(h, "faktor_notu", "") and h.faktor_notu not in ("", "Faktör nötr"):
        ek += f" Faktör: {_temiz(h.faktor_notu, 50)}."
    if getattr(h, "profil_notu", "") and h.profil_notu != "Profil uyumlu":
        ek += f" Profil: {_temiz(h.profil_notu, 50)}."
    if getattr(h, "rejim_notu", "") and h.rejim_notu != "Rejim uyumlu":
        ek += f" Rejim: {_temiz(h.rejim_notu, 50)}."
    if getattr(h, "haber_notu", ""):
        ek += f" Haber: {_temiz(h.haber_notu, 45)}."
    peer = getattr(h, "peer_yuzdelik", None)
    endeks = getattr(h, "endeks_gore", None)
    z52 = getattr(h, "zirve_52h_pct", None)
    z52_txt = f"{z52:.0f}" if z52 is not None else "—"
    if peer is not None or endeks is not None:
        if peer is not None:
            ek += f" Peer %{peer:.0f}"
        if endeks is not None:
            ek += f" · Endeks {endeks:+.0f}pp 3A"
    return _temiz(
        f"{_uygun_tablo_hucre(h)} · {h.ad} ({h.sembol}) · "
        f"{SINYAL_ETIKET.get(h.sinyal, h.sinyal)} · RSI {rsi_txt} · skor {h.skor:.0f} · "
        f"1A {_pct(h.degisim_1ay)} · 3A {_pct(getattr(h, 'degisim_3ay', None))} · "
        f"52H %{z52_txt} · SMA200 {_sayi(getattr(h, 'sma200', None), 0)}{ek}",
        220,
    )


def _hisse_ozet_satir(
    h,
    *,
    detayli: bool = False,
    ilk_sutun: str = "uygunluk",
    sira: int = 0,
) -> List[str]:
    peer = getattr(h, "peer_yuzdelik", None)
    endeks = getattr(h, "endeks_gore", None)
    if ilk_sutun == "sira":
        col0 = f"#{sira}"
    else:
        col0 = _uygun_tablo_hucre(h)
    row = [
        col0,
        h.sembol,
        _temiz(h.ad, 12 if detayli else 10),
        h.piyasa,
        _temiz(SINYAL_ETIKET.get(h.sinyal, h.sinyal), 10),
        _sayi(h.skor, 0),
        _pct(h.degisim_1ay, 0),
        _pct(getattr(h, "degisim_3ay", None), 0),
        _sayi(h.rsi, 0) if h.rsi is not None else "—",
        _sayi(getattr(h, "zirve_52h_pct", None), 0) if getattr(h, "zirve_52h_pct", None) else "—",
        _sayi(peer, 0) if peer is not None else "—",
        f"{endeks:+.0f}" if endeks is not None else "—",
        _sayi(getattr(h, "sma200", None), 0) if getattr(h, "sma200", None) else "—",
    ]
    if detayli:
        row.append(_temiz(getattr(h, "alim_uygun_not", "") or getattr(h, "trend_notu", ""), 22))
    return row


def _tablo_hisse_ozet(
    doc: "RaporPDF",
    hisseler: list,
    *,
    detayli: bool = False,
    font: float = 5.5,
    ilk_sutun: str = "uygunluk",
) -> None:
    if not hisseler:
        return
    w = doc._w()
    ilk_baslik = "Skor Sırası" if ilk_sutun == "sira" else "Karar"
    baslik = [
        ilk_baslik, "Sembol", "Hisse", "Piyasa", "Sinyal", "Skor",
        "1A", "3A", "RSI", "52H", "Peer", "End.", "SMA200",
    ]
    cols = [0.10, 0.07, 0.11, 0.06, 0.09, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.07]
    if ilk_sutun == "sira":
        cols[0] = 0.07
        cols[2] += 0.03
    if detayli:
        baslik.append("Not")
        cols = [c * 0.88 for c in cols] + [0.20]
    rows = [
        _hisse_ozet_satir(h, detayli=detayli, ilk_sutun=ilk_sutun, sira=i + 1)
        for i, h in enumerate(hisseler)
    ]
    doc.tablo(baslik, rows, font_boyut=font, satir_yuk=3.6, col_w=[w * c for c in cols])


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


def _backtest_bolumu(doc: "RaporPDF", rejim: str, ay: int = 12) -> None:
    try:
        satirlar = backtest_calistir(ay)
        met = backtest_metrikleri(satirlar, rejim)
    except Exception:
        return
    if not met:
        return
    doc.bolum("Backtest & Model İstikrarı")
    sharpe = f"{met.sharpe_yillik:.2f}" if met.sharpe_yillik is not None else "—"
    doc.kutu(
        f"Son {ay} ay simülasyon · Sharpe {sharpe}",
        _temiz(
            f"Toplam getiri {met.toplam_getiri_pct:+.1f}% · Max drawdown {met.max_drawdown_pct:.1f}% · "
            f"Volatilite (yıllık) {met.volatilite_yillik_pct:.1f}% · "
            f"Rejim değişimi {met.rejim_degisim_sayisi} · "
            f"En sık rejim: {met.en_sik_rejim.replace('_', ' ')}",
            350,
        ),
    )
    if met.model_drift and met.drift_mesaji:
        doc.madde(_temiz(met.drift_mesaji, 160))
    elif rejim:
        doc.madde(
            _temiz(
                f"Mevcut rejim ({rejim}) backtest döneminde "
                f"%{met.mevcut_rejim_oran_pct:.0f} süre görüldü — drift yok.",
                160,
            )
        )
    for n in met.notlar[:3]:
        doc.madde(_temiz(n, 160))
    if satirlar:
        w = doc._w()
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
        doc.tablo(
            ["Ay", "Rejim", "EUR/TRY", "Altın", "TL", "BIST"],
            rows,
            font_boyut=7,
            satir_yuk=4,
            col_w=[w * 0.12, w * 0.30, w * 0.14, w * 0.14, w * 0.14, w * 0.16],
        )


def _tarama_bolumu(doc: "RaporPDF", tarama: TaramaSonucu, rejim_etiket: str) -> None:
    doc.bolum("Hisse & Endeks Taraması")
    profil_oz = getattr(tarama, "profil_ozet", "") or ""
    if profil_oz:
        doc.kutu("Yatırımcı profili (tarama filtresi)", profil_oz)
        for n in (getattr(tarama, "profil_notlari", None) or [])[:5]:
            doc.madde(_temiz(n, 160))

    doc.kutu("Alım uygunluk özeti", _uygunluk_ozet_metin(tarama))
    doc.paragraf(
        "Karar: AL = al · DİKKAT = küçük pay/uyarı · ALMA = alma · BEKLE = izle. "
        f"Yahoo (gecikmeli) · RSI + SMA20/50/200 · Rejim: {rejim_etiket}. "
        f"{getattr(tarama, 'tarama_ozet', '') or ''} "
        "Katmanlar: teknik → trend (1A/SMA200) → rejim → profil → faktör/peer → haber. "
        "Yatırım tavsiyesi değildir."
    )
    for u in (tarama.uyarilar or [])[:3]:
        doc.madde(_temiz(u, 140))

    if tarama.endeksler:
        doc.paragraf("Endeksler — BIST 100 · NASDAQ · S&P 500")
        w = doc._w()
        endeks_rows = []
        for e in tarama.endeksler:
            fiyat = _sayi(e.fiyat, 0 if (e.fiyat or 0) >= 100 else 2)
            endeks_rows.append([
                _temiz(e.ad, 22),
                fiyat,
                _pct(e.degisim_1g),
                _pct(e.degisim_1ay),
                _pct(e.degisim_3ay),
                _sayi(e.rsi, 0) if e.rsi is not None else "—",
                _temiz(SINYAL_ETIKET.get(e.sinyal, e.sinyal), 14),
                _sayi(e.skor, 0),
            ])
        doc.tablo(
            ["Endeks", "Fiyat", "1G", "1A", "3A", "RSI", "Sinyal", "Skor"],
            endeks_rows,
            font_boyut=7.5,
            satir_yuk=4,
            col_w=[w * 0.22, w * 0.12, w * 0.08, w * 0.08, w * 0.08, w * 0.08, w * 0.22, w * 0.12],
        )

    uygun_list = _hisse_sirala([h for h in (tarama.hisseler or []) if getattr(h, "alim_uygun", "") == "UYGUN"])
    if uygun_list:
        doc.paragraf(f"AL — {len(uygun_list)} varlık")
        _tablo_hisse_ozet(doc, uygun_list, detayli=True, font=5.5)
        for h in uygun_list[:8]:
            doc.madde(_hisse_detay_madde(h))

    sinirli_list = _hisse_sirala([h for h in (tarama.hisseler or []) if getattr(h, "alim_uygun", "") == "SINIRLI"])
    if sinirli_list:
        doc.paragraf(f"DİKKAT — sınırlı uygun — {len(sinirli_list)} varlık (küçük pay veya bekle)")
        _tablo_hisse_ozet(doc, sinirli_list[:15], detayli=True, font=5.5)
        for h in sinirli_list[:6]:
            doc.madde(_hisse_detay_madde(h))

    if tarama.alim_firsatlari:
        doc.paragraf(f"Alım adayları (profil filtreli) — {len(tarama.alim_firsatlari)} varlık")
        _tablo_hisse_ozet(doc, _hisse_sirala(tarama.alim_firsatlari[:20]), detayli=True, font=5.5)
        for h in tarama.alim_firsatlari[:8]:
            doc.madde(_hisse_detay_madde(h))
    else:
        doc.paragraf(
            "Profil filtreli alım adayı yok — BEKLE veya makro tahsis (mevduat/altın/EUR) öncelikli."
        )

    etf_firsat = getattr(tarama, "etf_firsatlari", None) or []
    if etf_firsat:
        doc.paragraf(f"Revolut ETF adayları — {len(etf_firsat)} fon (UCITS · skor ≥55)")
        etf_rows = []
        for h in _hisse_sirala(etf_firsat[:12]):
            rt = getattr(h, "revolut_ticker", "") or h.sembol.split(".")[0]
            etf_rows.append([
                _uygun_tablo_hucre(h),
                rt,
                _temiz(h.ad, 18),
                _temiz(SINYAL_ETIKET.get(h.sinyal, h.sinyal), 10),
                _sayi(h.skor, 0),
                _pct(h.degisim_1ay, 0),
                _sayi(h.rsi, 0) if h.rsi is not None else "—",
                _sayi(getattr(h, "zirve_52h_pct", None), 0) if getattr(h, "zirve_52h_pct", None) else "—",
                _temiz(getattr(h, "isin", "") or "—", 14),
                _temiz(getattr(h, "alim_uygun_not", ""), 20),
            ])
        w = doc._w()
        doc.tablo(
            ["Karar", "Revolut", "ETF", "Sinyal", "Skor", "1A", "RSI", "52H", "ISIN", "Not"],
            etf_rows,
            font_boyut=5.5,
            satir_yuk=3.6,
            col_w=[w * x for x in (0.10, 0.07, 0.18, 0.09, 0.05, 0.06, 0.05, 0.05, 0.15, 0.20)],
        )
        for h in etf_firsat[:6]:
            doc.madde(_hisse_detay_madde(h))

    onemli = _hisse_sirala([
        h for h in (tarama.hisseler or [])
        if getattr(h, "alim_uygun", "") in ("UYGUN", "SINIRLI")
        or h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM")
    ])[:35]
    if onemli:
        doc.paragraf(f"Teknik özet — öncelikli {len(onemli)} varlık (skor sıralı, bilgi amaçlı)")
        _tablo_hisse_ozet(doc, onemli, detayli=False, font=5.2, ilk_sutun="sira")

    if tarama.hisseler:
        doc.paragraf(
            "Piyasa bazında öne çıkanlar — bilgi amaçlı en yüksek skorlu 6 varlık; "
            "alım kararı için yalnızca üstteki Alım uygunluk bölümüne bakın."
        )
        for piyasa in ("BIST", "SP500", "NASDAQ", "ETF"):
            grup = _skor_sirala([
                h for h in tarama.hisseler
                if h.piyasa == piyasa and h.sinyal not in ("ASIRI_ALIM", "UZAK_DUR", "VERI_YOK")
            ])[:6]
            if not grup:
                continue
            doc.paragraf(f"{piyasa} — top 6 (skor sıralı)")
            _tablo_hisse_ozet(doc, grup, detayli=True, font=5.2, ilk_sutun="sira")


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
        self.pdf.rect(0, 0, 210, 26, "F")
        self.pdf.set_text_color(255, 255, 255)
        self.pdf.set_xy(self._kenar, 9)
        self.pdf.set_font("TR", "B", 17)
        self.pdf.cell(
            self._w(), 7, "Anlık Durum Yatırım Raporu",
            new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT,
        )
        self._sol()
        self.pdf.set_x(self._kenar)
        self.pdf.set_font("TR", "", 9.5)
        self.pdf.cell(
            self._w(), 5, "Makro Portföy Asistanı · Haber Araştırma & Strateji Özeti",
            new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT,
        )
        self.pdf.ln(5)
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.set_font("TR", "", 8)
        self.paragraf(f"Rapor: {now}  ·  Veri: {veri}  ·  Mod: {snap.veri_kaynak.upper()}")
        self.paragraf(f"Profil: {profil.ozet()}")
        self.pdf.ln(1)

    def bolum(self, baslik: str) -> None:
        self._sayfa_yeterli(14)
        self.pdf.ln(2)
        self._sol()
        self.pdf.set_font("TR", "B", 11.5)
        self.pdf.set_text_color(0, 51, 102)
        self.pdf.cell(self._w(), 6, baslik, new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT)
        self.pdf.set_draw_color(0, 51, 102)
        y = self.pdf.get_y()
        self.pdf.line(self.pdf.l_margin, y, self.pdf.w - self.pdf.r_margin, y)
        self.pdf.ln(2)
        self.pdf.set_text_color(0, 0, 0)

    def paragraf(self, metin: str) -> None:
        self._yaz(self._w(), 4.5, metin, boyut=9)

    def madde(self, metin: str) -> None:
        self._yaz(self._w(), 4.2, "• " + _temiz(metin), boyut=8.5)

    def kutu(self, baslik: str, metin: str) -> None:
        self._sayfa_yeterli(16)
        w = self._w()
        self.pdf.set_fill_color(240, 244, 248)
        self._sol()
        self.pdf.set_font("TR", "B", 9)
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.multi_cell(
            w, 4.8, _temiz(baslik), fill=True, align=self._Align.L,
            new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT,
        )
        self._sol()
        self.pdf.set_font("TR", "", 8.5)
        self.pdf.multi_cell(
            w, 4.2, _temiz(metin), fill=True, align=self._Align.L,
            new_x=self._XPos.LMARGIN, new_y=self._YPos.NEXT,
        )
        self.pdf.ln(1.5)

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
        self._sayfa_yeterli(14)
        self.pdf.ln(2)
        self.pdf.set_font("TR", "", 7)
        self.pdf.set_text_color(100, 100, 100)
        self._sol()
        self.pdf.multi_cell(
            self._w(), 3.5,
            "Yasal uyarı: Bu rapor otomatik üretilmiş karar-destek belgesidir; yatırım tavsiyesi değildir. "
            "Nihai karar yatırımcıya aittir. © Makro Portföy Asistanı",
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
) -> bytes:
    toplam_eur = toplam_eur or config.TOPLAM_EUR
    v = snap.veri
    vade = VADE_SECENEKLERI.get(profil.vade, profil.vade)
    doc = RaporPDF()
    doc.antet(profil, snap)

    doc.bolum("Yönetici Özeti")
    doc.kutu(
        f"Makro rejim: {tahsis.rejim.etiket}",
        tahsis.rejim.aciklama,
    )
    doc.paragraf(_temiz(danisman.genel_ozet, 700))
    for n in (tahsis.profil_notlari or [])[:3]:
        doc.madde(_temiz(n, 160))

    doc.bolum("Piyasa Verileri")
    rezerv = (
        "Artıyor" if v.rezerv_artiyor
        else "Azalıyor" if v.rezerv_artiyor is False
        else "Bilinmiyor (×0,85)"
    )
    siyasi_metin = (
        f"{v.siyasi_risk_makale_sayisi} haber (ağırlıksız)"
        if v.siyasi_risk_makale_sayisi is not None else "—"
    )
    savas_metin = (
        f"{v.savas_risk_makale_sayisi} haber"
        if v.savas_risk_makale_sayisi is not None and v.savas_risk_guvenilir is not False
        else (
            f"Tarama güvensiz ({v.savas_risk_makale_sayisi or 0})"
            if v.savas_risk_guvenilir is False
            else "—"
        )
    )
    w = doc._w()
    doc.tablo(
        ["Gösterge", "Değer", "Gösterge", "Değer"],
        [
            ["EUR/TRY", _sayi(v.eur_try), "USD/TRY", _sayi(v.usd_try)],
            ["CDS 5Y", f"{_sayi(v.cds_5y_bp, 0)} bp", "VIX", _sayi(snap.vix, 1)],
            ["TCMB faizi", f"%{_sayi(v.tcmb_politika_faizi, 1)}", "Enflasyon TR", f"%{_sayi(snap.enflasyon_tr_yillik, 1)}"],
            ["Fed faizi", f"%{_sayi(v.fed_faizi, 2)}", "Altın/oz", f"${_sayi(snap.altin_usd_oz, 0)}"],
            ["BIST 100", _sayi(snap.bist100, 0), "BTC", f"${_sayi(snap.btc_usd, 0)}"],
            ["Siyasi risk", siyasi_metin, "Jeopolitik", savas_metin],
            ["Rezerv (Kapı 4)", rezerv, "TL tavan", f"%{tahsis.tl_tavan_oran * 100:.0f}"],
        ],
        col_w=[w * 0.28, w * 0.22, w * 0.28, w * 0.22],
    )

    vk = veri_kalite_olustur(snap)
    _veri_kalite_bolumu(doc, vk)

    if tahsis.tl_karar_adimlari:
        doc.bolum("4 Kapı Özeti (TL tavan)")
        for adim in tahsis.tl_karar_adimlari[:6]:
            doc.madde(_temiz(adim, 160))

    if tl_durum:
        doc.bolum("TL Mevduat Kararı")
        doc.kutu(
            tl_durum.baslik,
            f"Portföy payı %{tl_durum.agirlik_pct:.1f} · 4 kapı tavanı %{tl_durum.tavan_pct:.0f}",
        )
        for n in tl_durum.nedenler[:6]:
            doc.madde(_temiz(n, 200))
        doc.paragraf(_temiz(f"Alternatif: {tl_durum.alternatif}", 220))

    if mevduat and mevduat.getiri_notu:
        doc.bolum("Getiri Tanımı (önemli)")
        doc.kutu(
            "Yerel reel ≠ EUR bazlı getiri",
            mevduat.getiri_notu,
        )
        doc.paragraf(
            f"Profil vadeniz ({mevduat.profil_vade}): yerel reel "
            f"{mevduat.profil_vade_reel:+.1f} pp · EUR bazlı tahmini "
            f"{mevduat.profil_vade_eur_tahmini:+.1f} pp · EUR mevduat net "
            f"~%{mevduat.eur_mevduat_net:.1f}."
        )

    doc.bolum("Önerilen Portföy Dağılımı")
    doc.paragraf(
        f"Toplam {toplam_eur:,.0f} EUR · Vade: {vade} · TL tavan: %{tahsis.tl_tavan_oran * 100:.0f}"
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
            f"{tahsis.skorlar.get(k, 0):.0f}",
        ])
    doc.tablo(
        ["Varlık", "Ağırlık", "Tutar", "Skor"],
        pf_rows,
        col_w=[doc._w() * 0.38, doc._w() * 0.14, doc._w() * 0.30, doc._w() * 0.18],
    )
    doc.paragraf(_temiz(tahsis.tavsiye_metni, 400))

    if danisman.makro_baglam and danisman.makro_baglam.parcalar:
        doc.bolum("Canlı Makro Değerlendirme")
        for p in danisman.makro_baglam.parcalar[:5]:
            doc.kutu(
                _temiz(p.baslik, 60),
                _temiz(f"{p.canli} — {p.beklenti}", 320),
            )

    if mevduat and mevduat.oranlar:
        doc.bolum("TL Mevduat Faizleri")
        doc.paragraf(_temiz(mevduat.ozet, 350))
        mev_rows = []
        for o in mevduat.oranlar:
            tag = " ✓" if o.vade == mevduat.profil_vade else ""
            net_pct = (o.net_yillik or 0) * 100
            eur_tah = (
                f"{_eur_bazli_tahmini(net_pct, mevduat.enflasyon):+.1f}"
                if o.vade.startswith("TL") else "—"
            )
            mev_rows.append([
                o.vade + tag,
                f"%{o.brut_yillik * 100:.1f}",
                f"%{net_pct:.1f}",
                f"{o.reel_yillik or 0:+.1f}",
                eur_tah,
            ])
        doc.tablo(
            ["Vade", "Brüt", "Net", "Yerel reel", "EUR tah."],
            mev_rows,
            col_w=[doc._w() * 0.28, doc._w() * 0.14, doc._w() * 0.14, doc._w() * 0.22, doc._w() * 0.22],
        )

    if tarama and (tarama.endeksler or tarama.hisseler):
        _tarama_bolumu(doc, tarama, tahsis.rejim.etiket)

    _backtest_bolumu(doc, tahsis.rejim.rejim)

    doc.bolum("Varlık Bazlı Strateji Notları")
    for var in danisman.varliklar:
        if var.agirlik_pct < 0.5 and var.sinyal == "KACIN":
            continue
        doc.kutu(
            _temiz(f"{var.ad} · {var.sinyal_etiket} · %{var.agirlik_pct:.0f}", 70),
            _temiz(var.baslik, 160),
        )
        for n in var.nedenler[:2]:
            doc.madde(_temiz(n, 140))

    if danisman.denetim and danisman.denetim.bulgular:
        doc.bolum("Denetim Uyarıları")
        doc.paragraf(_temiz(danisman.denetim.ozet, 200))
        for b in danisman.denetim.bulgular[:5]:
            doc.madde(_temiz(f"[{b.seviye}] {b.baslik}", 120))

    doc.footer_disclaimer()
    return doc.bytes()
