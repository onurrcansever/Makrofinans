# -*- coding: utf-8 -*-
"""
Kısa WhatsApp özeti — rejim, varlık değişimi, AL hisse/ETF tek mesajda.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import config
from alerts import _oku as rejim_oku
from alerts import _yaz as rejim_yaz
from alerts import rejim_degisti_mi
from allocation_engine import tahsis_hesapla
from investor_profile import YatirimProfili
from macro_data import MacroSnapshot
from notifier import bildirim_gonder
from signal_alerts import _degisimleri_bul, _oku as sinyal_oku
from signal_alerts import _yaz as sinyal_yaz
from signal_alerts import tarama_yap
from varliklarim import yukle_store

STATE_PATH = os.getenv("OZET_ALARM_STATE_PATH", ".ozet_alarm_state.json")
VADE_UYARI_GUN = 7  # vadeye bu kadar gün kala ilk uyarı

TAHSIS_KISA = {
    "eur_cash": "EUR",
    "usd_cash": "USD",
    "tl_deposit": "TL",
    "gold": "Au",
    "silver": "Ag",
    "bist": "BIST",
    "crypto": "BTC",
}


def _profil_from_env() -> YatirimProfili:
    return YatirimProfili(
        risk=os.getenv("INVESTOR_RISK", "orta"),
        vade=os.getenv("INVESTOR_VADE", "orta"),
    )


def _ozet_oku() -> Dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _ozet_yaz(portfoy_tl: Optional[float], vade_bildirimler: Optional[Dict[str, str]] = None) -> None:
    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "portfoy_tl": portfoy_tl,
        "vade_bildirimler": vade_bildirimler or {},
    }
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _fmt_pct(x: float) -> str:
    s = f"{x:+.1f}".replace(".", ",")
    return f"{s}%"


def _fmt_tl(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


from al_bildirim import degisim_al_etiket, guncel_al_satirlar


def _tahsis_satir(tahsis) -> str:
    parcalar = []
    for k, w in sorted(tahsis.agirliklar.items(), key=lambda x: -x[1]):
        if w < 0.05:
            continue
        etiket = TAHSIS_KISA.get(k, k)
        parcalar.append(f"{etiket} %{w * 100:.0f}")
    return " · ".join(parcalar[:5]) if parcalar else "—"


def _varlik_satirlari(snap: MacroSnapshot, onceki_tl: Optional[float]) -> List[str]:
    from bildirim_ekleri import portfoy_degerle_guvenli

    store = yukle_store()
    portfoy = store.aktif()
    if not portfoy or not portfoy.pozisyonlar:
        return ["VARLIKLAR: kayıt yok"]

    try:
        deger = portfoy_degerle_guvenli(portfoy, snap, cache_salt="ozet_alarm")
    except Exception:
        n = len(portfoy.pozisyonlar)
        return [f"VARLIKLAR: {n} pozisyon (fiyat güncellenemedi)"]

    tl = deger.toplam.get("TL", 0.0)
    maliyet = deger.maliyet_toplam.get("TL", tl)
    kz = tl - maliyet
    kz_pct = (100.0 * kz / maliyet) if maliyet > 0 else 0.0

    satir = f"VARLIKLAR: {_fmt_tl(tl)} TL"
    if onceki_tl and onceki_tl > 0:
        satir += f" ({_fmt_pct(100 * (tl - onceki_tl) / onceki_tl)} önceki taramaya göre)"
    satirlar = [satir, f" K/Z: {_fmt_tl(kz)} TL ({_fmt_pct(kz_pct)})"]

    movers: List[Tuple[str, float]] = []
    for row in deger.pozisyonlar:
        g1 = row.getiriler.get("1G")
        if g1 is not None and abs(g1) >= 0.25:
            movers.append((row.pozisyon.etiket()[:14], g1))
    movers.sort(key=lambda x: -abs(x[1]))
    if movers:
        parca = ", ".join(f"{ad} {_fmt_pct(g)}" for ad, g in movers[:3])
        satirlar.append(f" Bugün: {parca}")

    return satirlar


def _guncel_al_satirlari(hisseler: list) -> List[str]:
    return guncel_al_satirlar(hisseler)


def _degisim_satirlari(olaylar: List[Tuple[str, str, Any]]) -> List[str]:
    if not olaylar:
        return []

    al_h: List[str] = []
    al_e: List[str] = []
    al_m: List[str] = []
    kaldir: List[str] = []
    sat: List[str] = []
    dikkat: List[str] = []

    for tip, _sym, h in olaylar:
        ad = degisim_al_etiket(h)
        emtia = getattr(h, "piyasa", "") == "EMTIA" or getattr(h, "varlik_turu", "") == "emtia"
        etf = getattr(h, "piyasa", "") == "ETF" or getattr(h, "varlik_turu", "") == "etf"
        if tip == "AL":
            if emtia:
                al_m.append(ad)
            elif etf:
                al_e.append(ad)
            else:
                al_h.append(ad)
        elif tip == "AL_KALDIRILDI":
            kaldir.append(ad)
        elif tip == "SAT":
            sat.append(ad)
        elif tip == "DIKKAT":
            dikkat.append(ad)

    satirlar = ["DEĞİŞİM:"]
    if al_h:
        satirlar.append(" +AL hisse: " + ", ".join(al_h))
    if al_e:
        satirlar.append(" +AL ETF: " + ", ".join(al_e))
    if al_m:
        satirlar.append(" +AL emtia: " + ", ".join(al_m))
    if kaldir:
        satirlar.append(" AL kalktı: " + ", ".join(kaldir))
    if sat:
        satirlar.append(" SAT: " + ", ".join(sat))
    if dikkat:
        satirlar.append(" DİKKAT: " + ", ".join(dikkat))
    return satirlar


def ozet_metni_olustur(
    tahsis,
    profil: YatirimProfili,
    tarama,
    olaylar: List[Tuple[str, str, Any]],
    rejim_degisti: bool,
    onceki_rejim: Optional[Dict[str, Any]],
    onceki_tl: Optional[float],
    snap: MacroSnapshot,
    vade_satirlari: Optional[List[str]] = None,
    *,
    rutin_durum: bool = False,
) -> str:
    simdi = datetime.now().strftime("%d.%m %H:%M")
    satirlar = [
        f"MAKROFINANS · {simdi}",
        profil.ozet(),
        "",
    ]
    if rutin_durum:
        satirlar.append("Durum: değişiklik yok (günlük özet)")
        satirlar.append("")

    onceki_etiket = onceki_rejim.get("rejim_etiket", "—") if onceki_rejim else "—"
    if rejim_degisti and onceki_rejim:
        satirlar.append(f"REJİM: {onceki_etiket} → {tahsis.rejim.etiket}")
    else:
        satirlar.append(f"REJİM: {tahsis.rejim.etiket}")

    satirlar.append("")
    satirlar.extend(_varlik_satirlari(snap, onceki_tl))

    # Portföy durumu — metrikler yerel; 💬 yalnızca cache (API yok)
    try:
        from bildirim_ekleri import portfoy_durum_satirlari, portfoy_pozisyon_tablo_satirlari
        pd_satir = portfoy_durum_satirlari(snap, tarama)
        if pd_satir:
            satirlar.append("")
            satirlar.extend(pd_satir)
        poz_tab = portfoy_pozisyon_tablo_satirlari(snap, tarama, profil)
        if poz_tab:
            satirlar.append("")
            satirlar.extend(poz_tab)
    except Exception:
        pass

    if vade_satirlari:
        satirlar += ["", "VADE:"]
        satirlar.extend(vade_satirlari)

    degisim = _degisim_satirlari(olaylar)
    if degisim:
        satirlar.append("")
        satirlar.extend(degisim)

    satirlar += ["", "GÜNCEL AL:"]
    satirlar.extend(_guncel_al_satirlari(tarama.hisseler))

    satirlar += ["", f"Tahsis: {_tahsis_satir(tahsis)}"]
    satirlar.append(f"TL tavan: %{tahsis.tl_tavan_oran * 100:.0f}")
    return "\n".join(satirlar)


def _vade_olaylari(onceki_bildirimler: Dict[str, str]) -> Tuple[List[str], Dict[str, str]]:
    """Vadesi yaklaşan/dolan TL mevduatlar için mesaj satırları + güncel bildirim durumu.

    Her pozisyon için iki aşama bildirilir: '7gun' (vadeye ≤7 gün) ve 'vade' (vade günü/geçti).
    Aynı aşama ikinci kez bildirilmez.
    """
    try:
        from nakit_danisman import vadeli_mevduatlar
        vadeliler = vadeli_mevduatlar(yukle_store())
    except Exception:
        return [], dict(onceki_bildirimler)

    satirlar: List[str] = []
    yeni = dict(onceki_bildirimler)
    for vb in vadeliler:
        if vb.kalan_gun > VADE_UYARI_GUN:
            continue
        asama = "vade" if vb.kalan_gun <= 0 else "7gun"
        onceki = onceki_bildirimler.get(vb.pozisyon.id)
        if onceki == "vade" or onceki == asama:
            continue
        banka = (vb.pozisyon.banka or "").strip() or "Banka"
        if vb.kalan_gun <= 0:
            satirlar.append(
                f" {banka} {_fmt_tl(vb.anapara_tl)} TL VADE DOLDU — "
                f"net ~{_fmt_tl(vb.net_tl)} TL elinizde. Karar Asistanı'nda yönlendirme planı hazır."
            )
        else:
            satirlar.append(
                f" {banka} {_fmt_tl(vb.anapara_tl)} TL — vadeye {vb.kalan_gun} gün "
                f"({vb.vade_tarihi.strftime('%d.%m')}), vade sonu net ~{_fmt_tl(vb.net_tl)} TL. "
                f"Yönlendirme için Karar Asistanı'na bakın."
            )
        yeni[vb.pozisyon.id] = asama
    return satirlar, yeni


def _portfoy_tl(snap: MacroSnapshot) -> Optional[float]:
    from bildirim_ekleri import portfoy_degerle_guvenli

    store = yukle_store()
    portfoy = store.aktif()
    if not portfoy or not portfoy.pozisyonlar:
        return None
    try:
        return portfoy_degerle_guvenli(portfoy, snap, cache_salt="ozet_alarm").toplam.get("TL")
    except Exception:
        return None


def kontrol_ozet_ve_bildir(
    snap: MacroSnapshot,
    profil: Optional[YatirimProfili] = None,
    bildir: bool = True,
    *,
    her_zaman: Optional[bool] = None,
) -> Tuple[bool, List[Tuple[str, str, Any]], bool]:
    """
    Rejim/sinyal değişince veya her_zaman=True ise özet mesaj gönderir.
    Dönüş: (gonderildi, olaylar, rejim_degisti)
    """
    if her_zaman is None:
        her_zaman = config.OZET_ALARM_HER_ZAMAN
    profil = profil or _profil_from_env()
    tahsis, tarama, profil = tarama_yap(snap, profil)

    onceki_rejim = rejim_oku()
    rejim_degisti = rejim_degisti_mi(tahsis)
    ilk_rejim = onceki_rejim is None

    profil_key = f"{profil.risk}_{profil.vade}"
    onceki_sinyal = sinyal_oku(profil_key)
    olaylar, simdi_sinyal = _degisimleri_bul(onceki_sinyal, tarama.hisseler)
    ilk_sinyal = not onceki_sinyal

    ozet_onceki = _ozet_oku()
    onceki_tl = ozet_onceki.get("portfoy_tl")
    yeni_tl = _portfoy_tl(snap)

    onceki_vade_bildirim = ozet_onceki.get("vade_bildirimler") or {}
    vade_satirlari, yeni_vade_bildirim = _vade_olaylari(onceki_vade_bildirim)

    tetik = rejim_degisti or bool(olaylar) or her_zaman
    if ilk_sinyal and not olaylar and not her_zaman:
        tetik = rejim_degisti
    if ilk_rejim and os.getenv("GITHUB_ACTIONS") and not olaylar and not her_zaman:
        tetik = False
    if vade_satirlari:
        tetik = True  # vade uyarısı tek başına mesaj tetikler

    gonderildi = False
    rutin = her_zaman and not rejim_degisti and not olaylar and not vade_satirlari
    if tetik and bildir and not (ilk_rejim and os.getenv("GITHUB_ACTIONS") and not vade_satirlari and not her_zaman):
        metin = ozet_metni_olustur(
            tahsis,
            profil,
            tarama,
            olaylar,
            rejim_degisti,
            onceki_rejim,
            onceki_tl,
            snap,
            vade_satirlari=vade_satirlari,
            rutin_durum=rutin,
        )
        gonderildi = bool(bildirim_gonder(metin))

    rejim_yaz(tahsis.rejim.rejim, tahsis)
    sinyal_yaz(profil_key, simdi_sinyal)
    # Vade bildirimi ancak mesaj gerçekten gittiyse "bildirildi" sayılır —
    # gönderim başarısızsa bir sonraki çalıştırmada yeniden denenir.
    _ozet_yaz(yeni_tl, yeni_vade_bildirim if gonderildi else onceki_vade_bildirim)

    return gonderildi, olaylar, rejim_degisti
