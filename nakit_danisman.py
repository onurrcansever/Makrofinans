# -*- coding: utf-8 -*-
"""
Nakit Danışmanı — "elime yeni para geçti, neye ne kadar ekleyeyim?" ve
"mevduat vadem bitince nereye yönlendireyim?" sorularına rakamsal plan üretir.

Dağıtım kuralı (basit ve denetlenebilir):
1. Mevcut portföyün fiili ağırlıkları hesaplanır (varlık sınıfı bazında, TL).
2. Hedef ağırlıklar tahsis motorundan gelir (rejim + profil + TL tavanı dahil).
3. Yeni para, hedef−fiili açığı en büyük sınıflara orantılı dağıtılır.
4. Açıklar kapandıktan sonra kalan, hedef ağırlıklara göre bölünür.
5. KIRINTI_ESIK_TL altındaki satırlar en büyük kaleme eklenir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import config
from macro_data import MacroSnapshot
from varliklarim import VarlikPortfoy, VarlikPozisyon, VarlikStore

KIRINTI_ESIK_TL = 5_000.0

# Varlıklarım pozisyon türü → tahsis sınıfı
TUR_SINIF = {
    "tl_mevduat": "tl_deposit",
    "nakit_tl": "tl_deposit",
    "tefas": "tl_deposit",     # TEFAS TL enstrümanı — kur riski TL tarafında
    "nakit_eur": "eur_cash",
    "nakit_usd": "usd_cash",
    "altin": "gold",
    "gumus": "silver",
    "kripto": "crypto",
    # hisse/etf sembole göre çözülür (_pozisyon_sinifi)
}


def _pozisyon_sinifi(p: VarlikPozisyon) -> str:
    if p.tur in TUR_SINIF:
        return TUR_SINIF[p.tur]
    if p.tur == "hisse":
        return "bist" if p.sembol.upper().endswith(".IS") else "usd_cash"
    if p.tur == "etf":
        return "eur_cash"  # UCITS ETF'ler FX dilimi içinde değerlendirilir
    return "eur_cash"


@dataclass
class PlanSatiri:
    sinif: str
    etiket: str
    tutar_tl: float
    oran_pct: float          # yeni paranın yüzdesi
    mevcut_pct: float        # işlem öncesi fiili ağırlık
    hedef_pct: float         # hedef ağırlık
    arac: str = ""           # somut araç önerisi
    gerekce: str = ""


@dataclass
class NakitPlani:
    girilen_tutar: float
    para_birimi: str
    tutar_tl: float
    mevcut_toplam_tl: float
    yeni_toplam_tl: float
    rejim_etiket: str
    satirlar: List[PlanSatiri] = field(default_factory=list)
    notlar: List[str] = field(default_factory=list)


@dataclass
class VadeBilgisi:
    pozisyon: VarlikPozisyon
    vade_tarihi: date
    kalan_gun: int
    anapara_tl: float
    net_tl: float            # vade sonu net (anapara + faiz − stopaj)
    brut_faiz_tl: float
    stopaj_tl: float


def _tl_cevir(tutar: float, pb: str, eur_try: float, usd_try: float) -> float:
    if pb == "TL":
        return tutar
    if pb == "EUR":
        return tutar * eur_try
    if pb == "USD":
        return tutar * usd_try
    return tutar


def _fiili_dagilim_tl(
    portfoy: Optional[VarlikPortfoy],
    snap: MacroSnapshot,
    *,
    haric_pozisyon_id: str = "",
) -> Dict[str, float]:
    """Sınıf bazında mevcut TL değerleri. haric_pozisyon_id vade dolan mevduatı dışarıda tutar."""
    dagilim = {k: 0.0 for k in config.VARLIK_ETIKETLERI}
    if not portfoy or not portfoy.pozisyonlar:
        return dagilim

    from varlik_fiyat import _pb_cevir, portfoy_degerle

    eur_try = snap.veri.eur_try or 35.0
    usd_try = snap.veri.usd_try or eur_try * 1.08
    try:
        deger = portfoy_degerle(portfoy, snap, cache_salt="nakit_danisman")
    except Exception:
        # Fiyat çekilemezse maliyet bazlı yaklaşık dağılım
        for p in portfoy.pozisyonlar:
            if p.id == haric_pozisyon_id:
                continue
            sinif = _pozisyon_sinifi(p)
            dagilim[sinif] = dagilim.get(sinif, 0.0) + _tl_cevir(
                p.maliyet_toplam(), p.para_birimi or "TL", eur_try, usd_try
            )
        return dagilim

    for pd_ in deger.pozisyonlar:
        p = pd_.pozisyon
        if p.id == haric_pozisyon_id:
            continue
        sinif = _pozisyon_sinifi(p)
        tl = _pb_cevir(pd_.guncel_deger, pd_.para or "TL", "TL", eur_try, usd_try)
        dagilim[sinif] = dagilim.get(sinif, 0.0) + tl
    return dagilim


def _arac_onerisi(
    sinif: str,
    tarama: Any = None,
    mevduat_ozet: Any = None,
) -> str:
    """Sınıf için somut araç — AL sinyalli hisse/ETF, güncel mevduat oranı vb."""
    if sinif == "tl_deposit":
        if mevduat_ozet is not None and getattr(mevduat_ozet, "profil_vade_net", 0):
            vade = getattr(mevduat_ozet, "profil_vade", "") or "profil vadesi"
            return f"TL vadeli mevduat — {vade} net %{mevduat_ozet.profil_vade_net:.1f} (Yapı Kredi canlı)"
        return "TL vadeli mevduat (güncel banka oranını kontrol edin)"
    if sinif == "gold":
        return "Gram altın / bankada vadesiz altın hesabı"
    if sinif == "silver":
        return "Gram gümüş / gümüş hesabı"
    if sinif == "crypto":
        return "BTC (yalnızca ayrılan pay kadar)"
    if sinif == "usd_cash":
        return "USD nakit / USD mevduat"

    if sinif in ("eur_cash", "bist") and tarama is not None:
        hisseler = getattr(tarama, "hisseler", None) or []
        uygun = [
            h for h in hisseler
            if getattr(h, "alim_uygun", "") == "UYGUN" and getattr(h, "fiyat", None)
        ]
        if sinif == "eur_cash":
            etfler = sorted(
                [h for h in uygun if getattr(h, "piyasa", "") == "ETF"],
                key=lambda x: -(x.skor or 0),
            )
            if etfler:
                adlar = ", ".join(
                    (h.revolut_ticker or h.sembol.split(".")[0]) for h in etfler[:2]
                )
                return f"EUR nakit — bir bölümü AL sinyalli ETF: {adlar}"
        if sinif == "bist":
            bist = sorted(
                [h for h in uygun if getattr(h, "piyasa", "") == "BIST"],
                key=lambda x: -(x.skor or 0),
            )
            if bist:
                adlar = ", ".join(h.sembol.replace(".IS", "") for h in bist[:3])
                return f"AL sinyalli BIST: {adlar}"
            return "BIST — şu an AL sinyali yok, endeks fonu veya bekleme"
    if sinif == "eur_cash":
        return "EUR nakit / EUR mevduat"
    if sinif == "bist":
        return "BIST hisse/endeks fonu"
    return config.VARLIK_ETIKETLERI.get(sinif, sinif)


def yeni_para_plani(
    tutar: float,
    para_birimi: str,
    snap: MacroSnapshot,
    tahsis: Any,
    *,
    varlik_store: Optional[VarlikStore] = None,
    tarama: Any = None,
    mevduat_ozet: Any = None,
    haric_pozisyon_id: str = "",
) -> Optional[NakitPlani]:
    """Yeni parayı hedef tahsise göre sınıflara böler. Dönüş None = geçersiz girdi."""
    if tutar <= 0:
        return None

    eur_try = snap.veri.eur_try or 35.0
    usd_try = snap.veri.usd_try or eur_try * 1.08
    tutar_tl = _tl_cevir(float(tutar), para_birimi, eur_try, usd_try)

    portfoy = varlik_store.aktif() if varlik_store else None
    fiili = _fiili_dagilim_tl(portfoy, snap, haric_pozisyon_id=haric_pozisyon_id)
    mevcut_toplam = sum(fiili.values())
    yeni_toplam = mevcut_toplam + tutar_tl

    hedef: Dict[str, float] = dict(tahsis.agirliklar or {})
    toplam_w = sum(hedef.values())
    if toplam_w <= 0:
        return None
    hedef = {k: w / toplam_w for k, w in hedef.items()}

    # 1) Açıklar: hedef tutar − fiili tutar (yalnızca pozitif)
    acik = {
        k: max(0.0, hedef.get(k, 0.0) * yeni_toplam - fiili.get(k, 0.0))
        for k in hedef
    }
    toplam_acik = sum(acik.values())

    dagitim: Dict[str, float] = {k: 0.0 for k in hedef}
    if toplam_acik >= tutar_tl and toplam_acik > 0:
        for k in hedef:
            dagitim[k] = tutar_tl * acik[k] / toplam_acik
    else:
        # Açıkları tamamen kapat, kalanı hedef ağırlıkla böl
        for k in hedef:
            dagitim[k] = acik[k]
        kalan = tutar_tl - toplam_acik
        if kalan > 0:
            for k in hedef:
                dagitim[k] += kalan * hedef[k]

    # 2) TL tavanı güvenliği: fiili + yeni TL, tavanı aşmasın
    tavan = float(getattr(tahsis, "tl_tavan_oran", 1.0) or 1.0)
    tl_izin = max(0.0, tavan * yeni_toplam - fiili.get("tl_deposit", 0.0))
    fazla_tl = dagitim.get("tl_deposit", 0.0) - tl_izin
    if fazla_tl > 0:
        dagitim["tl_deposit"] = tl_izin
        # Fazlayı TL dışındaki hedef ağırlıklara orantılı dağıt
        digerler = {k: hedef[k] for k in hedef if k != "tl_deposit"}
        dw = sum(digerler.values())
        if dw > 0:
            for k in digerler:
                dagitim[k] += fazla_tl * digerler[k] / dw

    # 3) Kırıntı birleştirme
    kucukler = [k for k, v in dagitim.items() if 0 < v < KIRINTI_ESIK_TL]
    if kucukler and any(v >= KIRINTI_ESIK_TL for v in dagitim.values()):
        en_buyuk = max(dagitim, key=lambda k: dagitim[k])
        for k in kucukler:
            if k != en_buyuk:
                dagitim[en_buyuk] += dagitim[k]
                dagitim[k] = 0.0

    satirlar: List[PlanSatiri] = []
    for k, v in sorted(dagitim.items(), key=lambda x: -x[1]):
        if v <= 0:
            continue
        mevcut_pct = 100.0 * fiili.get(k, 0.0) / mevcut_toplam if mevcut_toplam > 0 else 0.0
        hedef_pct = 100.0 * hedef.get(k, 0.0)
        if mevcut_toplam > 0:
            gerekce = f"Hedef %{hedef_pct:.0f}, mevcut %{mevcut_pct:.0f} — açık kapatılıyor"
        else:
            gerekce = f"Hedef ağırlık %{hedef_pct:.0f} (rejim: {tahsis.rejim.etiket})"
        satirlar.append(PlanSatiri(
            sinif=k,
            etiket=config.VARLIK_ETIKETLERI.get(k, k),
            tutar_tl=round(v, 0),
            oran_pct=round(100.0 * v / tutar_tl, 1),
            mevcut_pct=round(mevcut_pct, 1),
            hedef_pct=round(hedef_pct, 1),
            arac=_arac_onerisi(k, tarama=tarama, mevduat_ozet=mevduat_ozet),
            gerekce=gerekce,
        ))

    notlar = [
        f"Plan bugünkü rejime göre hesaplandı: {tahsis.rejim.etiket}. "
        "Rejim değişirse öneri de değişir — WhatsApp alarmı sizi uyarır.",
    ]
    if mevcut_toplam <= 0:
        notlar.append("Varlıklarım boş — dağılım doğrudan hedef ağırlıklarla yapıldı.")
    tl_sonrasi = (fiili.get("tl_deposit", 0.0) + dagitim.get("tl_deposit", 0.0)) / yeni_toplam if yeni_toplam > 0 else 0
    if tavan < 1.0 and tl_sonrasi >= tavan - 0.005:
        notlar.append(f"TL payı 4 kapı tavanında (%{tavan * 100:.0f}) — daha fazla TL önerilmez.")

    return NakitPlani(
        girilen_tutar=float(tutar),
        para_birimi=para_birimi,
        tutar_tl=round(tutar_tl, 0),
        mevcut_toplam_tl=round(mevcut_toplam, 0),
        yeni_toplam_tl=round(yeni_toplam, 0),
        rejim_etiket=tahsis.rejim.etiket,
        satirlar=satirlar,
        notlar=notlar,
    )


# ------------------------------------------------------------------
# Vade sonu takibi
# ------------------------------------------------------------------

def vade_bilgisi(p: VarlikPozisyon, bugun: Optional[date] = None) -> Optional[VadeBilgisi]:
    """tl_mevduat pozisyonu için vade tarihi + vade sonu net tutar. None = vade bilgisi yok."""
    if p.tur != "tl_mevduat" or p.vade_gun <= 0 or not p.alim_tarihi:
        return None
    try:
        alim = datetime.fromisoformat(p.alim_tarihi).date()
    except ValueError:
        return None

    bugun = bugun or date.today()
    vade_t = alim + timedelta(days=int(p.vade_gun))
    anapara = p.miktar if p.miktar > 0 else p.maliyet_toplam()
    if anapara <= 0:
        return None

    from yapikredi_rates import stopaj_orani

    brut_yillik = p.brut_faiz / 100.0 if p.brut_faiz > 1 else p.brut_faiz
    brut_faiz_tl = anapara * brut_yillik * (p.vade_gun / 365.0)
    stopaj = stopaj_orani(int(p.vade_gun), "TL")
    stopaj_tl = brut_faiz_tl * stopaj
    return VadeBilgisi(
        pozisyon=p,
        vade_tarihi=vade_t,
        kalan_gun=(vade_t - bugun).days,
        anapara_tl=anapara,
        net_tl=anapara + brut_faiz_tl - stopaj_tl,
        brut_faiz_tl=brut_faiz_tl,
        stopaj_tl=stopaj_tl,
    )


def vadeli_mevduatlar(store: Optional[VarlikStore], bugun: Optional[date] = None) -> List[VadeBilgisi]:
    """Tüm portföylerdeki vadeli TL mevduatlar — kalan güne göre sıralı.

    Vade takibi aktif portföyle sınırlı değildir; hangi portföyde olursa
    olsun dolacak mevduat kaçırılmamalıdır.
    """
    if not store:
        return []
    out = []
    for portfoy in store.portfoyler:
        for p in portfoy.pozisyonlar:
            vb = vade_bilgisi(p, bugun)
            if vb is not None:
                out.append(vb)
    out.sort(key=lambda v: v.kalan_gun)
    return out


def vade_sonu_plani(
    vb: VadeBilgisi,
    snap: MacroSnapshot,
    tahsis: Any,
    *,
    varlik_store: Optional[VarlikStore] = None,
    tarama: Any = None,
    mevduat_ozet: Any = None,
) -> Optional[NakitPlani]:
    """Vade sonunda eline geçecek net tutar için yönlendirme planı.

    Dolan mevduat fiili dağılımdan çıkarılır — para artık 'nakit' sayılır.
    """
    plan = yeni_para_plani(
        vb.net_tl,
        "TL",
        snap,
        tahsis,
        varlik_store=varlik_store,
        tarama=tarama,
        mevduat_ozet=mevduat_ozet,
        haric_pozisyon_id=vb.pozisyon.id,
    )
    if plan is not None:
        plan.notlar.insert(
            0,
            f"{vb.vade_tarihi.strftime('%d.%m.%Y')} vadesinde net ~{vb.net_tl:,.0f} TL "
            f"(anapara {vb.anapara_tl:,.0f} + faiz {vb.brut_faiz_tl:,.0f} − stopaj {vb.stopaj_tl:,.0f}). "
            "Plan bugünkü rejime göredir; vade günü güncel rejimle yeniden hesaplayın.",
        )
    return plan
