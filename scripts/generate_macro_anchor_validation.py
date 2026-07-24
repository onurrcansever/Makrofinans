# -*- coding: utf-8 -*-
"""
Makro Çıpa Doğrulaması — Brent / DXY / ABD tahvil getirisi
==========================================================
Amaç: Bu çıpaları karar motoruna bağlamadan ÖNCE, "sezgiyle eşik koyma" yerine
tarihsel veriyle iki şeyi kanıtlamak:

  A) ÖNGÖRÜCÜ DEĞER — Çıpa "stresi" (petrol↑ + DXY↑ + ABD faizi↑) ileriye dönük
     risk-varlık getirisini (USD bazlı BIST) ve TL değer kaybını gerçekten
     öngörüyor mu? Eşikler ELLE değil, verinin kantillerinden (33/66) türetilir.
     Spearman sıra-korelasyonu + tercile kova ortalamalarıyla ölçülür.

  B) REEL GETİRİ OKUMASI — Motor reel getiriyi `reel = tcmb − enflasyon` (basit
     çıkarma) ile okuyor. Bunun Fisher-tam (`(1+i)/(1+π)−1`) karşılığına göre
     sapmasını ve petrol→TR enflasyonu gecikmeli ilişkisini ölçer.

Çıktı: signal_engine/reports/macro_anchor_validation.{json,md} + stdout özet.
Ağ: yfinance (aylık) + TÜFE (EVDS varsa gerçek, yoksa yaklaşık). Kesin performans
iddiası değildir; yön/kalibrasyon kanıtıdır (mevcut backtest.py ile aynı çekince).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import MAKRO_TABLO, _yf_aylik  # noqa: E402
from enflasyon_kaynak import _tufe_evds_uret, tufe_endeks_serisi  # noqa: E402

RAPOR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signal_engine", "reports")

TICKERLAR = {
    "brent": "BZ=F",
    "dxy": "DX-Y.NYB",
    "abd_10y": "^TNX",
    "bist": "XU100.IS",
    "usdtry": "USDTRY=X",
}


def _seri_indeks(aylar: int) -> pd.DataFrame:
    """Aylık kapanış paneli — hepsi ay-sonu (ME) hizalı tek DataFrame."""
    kolonlar = {}
    for ad, tk in TICKERLAR.items():
        s = _yf_aylik(tk, aylar)
        if s is None or s.empty:
            print(f"[UYARI] {ad} ({tk}) boş döndü.")
            continue
        s.index = pd.to_datetime(s.index).tz_localize(None)
        kolonlar[ad] = s
    if not kolonlar:
        return pd.DataFrame()
    df = pd.DataFrame(kolonlar).sort_index()
    return df


def _z(s: pd.Series) -> pd.Series:
    std = s.std()
    if std is None or std == 0 or np.isnan(std):
        return s * 0.0
    return (s - s.mean()) / std


def _spearman(a: pd.Series, b: pd.Series) -> Optional[float]:
    """Spearman = sıraların (rank) Pearson korelasyonu — scipy gerekmez."""
    d = pd.concat([a, b], axis=1).dropna()
    if len(d) < 6:
        return None
    r = d.iloc[:, 0].rank().corr(d.iloc[:, 1].rank(), method="pearson")
    return None if pd.isna(r) else round(float(r), 3)


@dataclass
class ValidationRapor:
    generated_at: str
    veri_penceresi: Dict[str, object]
    kaynaklar: Dict[str, str]
    A_ongorucu_deger: Dict[str, object] = field(default_factory=dict)
    B_reel_getiri: Dict[str, object] = field(default_factory=dict)
    C_rejim_etki: Dict[str, object] = field(default_factory=dict)
    verdict: List[str] = field(default_factory=list)
    notlar: List[str] = field(default_factory=list)


def bolum_a_ongorucu(df: pd.DataFrame) -> Dict[str, object]:
    """Çıpa stresi ileri BIST(USD) getirisi ve TL değer kaybını öngörüyor mu?"""
    out: Dict[str, object] = {}
    if df.empty or "bist" not in df or "usdtry" not in df:
        out["hata"] = "Yetersiz fiyat verisi."
        return out

    bist_usd = df["bist"] / df["usdtry"]

    # Çıpa stresi bileşeni — 3 aylık değişimlerin z-skoru ortalaması (veri-güdümlü;
    # elle eşik yok). Yükseliş = rüzgâra karşı olduğu için hepsi pozitif katkı.
    parcalar = []
    for ad in ("brent", "dxy", "abd_10y"):
        if ad in df:
            deg3 = df[ad].pct_change(3)
            parcalar.append(_z(deg3))
    if not parcalar:
        out["hata"] = "Çıpa serileri yok."
        return out
    stres = pd.concat(parcalar, axis=1).mean(axis=1)
    stres.name = "stres"

    # İleriye dönük getiriler (lookahead YOK: t'deki stres → t+1/t+3 getiri)
    ileri_bist_1a = bist_usd.shift(-1) / bist_usd - 1.0
    ileri_bist_3a = bist_usd.shift(-3) / bist_usd - 1.0
    ileri_usdtry_3a = df["usdtry"].shift(-3) / df["usdtry"] - 1.0  # + = TL değer kaybı

    out["spearman"] = {
        "stres_vs_bist_usd_ileri_1a": _spearman(stres, ileri_bist_1a),
        "stres_vs_bist_usd_ileri_3a": _spearman(stres, ileri_bist_3a),
        "stres_vs_usdtry_ileri_3a": _spearman(stres, ileri_usdtry_3a),
    }

    # Tercile kovaları — kesimler VERİDEN (33/66 kantil), elle değil.
    gecerli = stres.dropna()
    q33, q66 = gecerli.quantile(1 / 3), gecerli.quantile(2 / 3)
    out["esik_veriden"] = {"q33": round(float(q33), 3), "q66": round(float(q66), 3)}

    def _kova(x: float) -> str:
        if x <= q33:
            return "düşük stres"
        if x >= q66:
            return "yüksek stres"
        return "orta stres"

    kova = stres.apply(lambda x: _kova(x) if pd.notna(x) else np.nan)
    tab = pd.DataFrame({
        "kova": kova,
        "bist_usd_ileri_3a": ileri_bist_3a,
        "usdtry_ileri_3a": ileri_usdtry_3a,
    }).dropna(subset=["kova"])

    tercile = []
    for ad in ("düşük stres", "orta stres", "yüksek stres"):
        alt = tab[tab["kova"] == ad]
        if alt.empty:
            continue
        tercile.append({
            "kova": ad,
            "n": int(len(alt)),
            "bist_usd_ileri_3a_ort_pct": round(float(alt["bist_usd_ileri_3a"].mean() * 100), 2),
            "usdtry_ileri_3a_ort_pct": round(float(alt["usdtry_ileri_3a"].mean() * 100), 2),
        })
    out["tercile"] = tercile
    return out


def bolum_b_reel(aylar: int) -> Dict[str, object]:
    """Reel getiri okuması doğru mu? Fisher sapması + petrol→enflasyon gecikmesi."""
    out: Dict[str, object] = {}

    # --- Fisher analizi: motorun basit (tcmb-enflasyon) vs tam formül ---
    ornekler = []
    hatalar = []
    for ay, m in sorted(MAKRO_TABLO.items()):
        tcmb, enf = m["tcmb"], m["enflasyon"]
        basit = tcmb - enf
        tam = ((1 + tcmb / 100) / (1 + enf / 100) - 1) * 100
        fark = basit - tam
        hatalar.append(abs(fark))
        ornekler.append({
            "ay": ay, "tcmb": tcmb, "enflasyon": enf,
            "basit_reel_pp": round(basit, 2),
            "fisher_tam_reel_pp": round(tam, 2),
            "sapma_pp": round(fark, 2),
        })
    out["fisher_analizi"] = {
        "aciklama": "Motor reel=tcmb−enflasyon (basit). Yüksek enflasyonda Fisher-tam üstünde kalır.",
        "ort_mutlak_sapma_pp": round(float(np.mean(hatalar)), 2) if hatalar else None,
        "max_sapma_pp": round(float(np.max(hatalar)), 2) if hatalar else None,
        "ornekler": ornekler,
    }

    # --- Petrol → TR enflasyonu gecikmeli ilişki ---
    # Backtest tek-atış olduğu için non-blocking `tufe_endeks_serisi` cold cache'te
    # None→sentetik döner. EVDS'i DOĞRUDAN (bloklayan) çek; yoksa sentetiğe düş.
    try:
        bugun = datetime.now()
        bas = f"{bugun.year - (aylar // 12) - 1}-01"
        bit = f"{bugun.year}-{bugun.month:02d}"
        seri_cpi = _tufe_evds_uret()
        if seri_cpi:
            cpi_kaynak = "TÜİK/EVDS (TP.FG.J01, doğrudan çekim)"
        else:
            seri_cpi, cpi_kaynak = tufe_endeks_serisi(bas, bit)
    except Exception as e:
        seri_cpi, cpi_kaynak = {}, f"alınamadı ({e})"
    out["cpi_kaynak"] = cpi_kaynak

    if seri_cpi and len(seri_cpi) >= 18:
        cpi = pd.Series(
            {pd.Period(k, freq="M").to_timestamp("M"): v for k, v in seri_cpi.items()}
        ).sort_index()
        cpi_yoy = cpi / cpi.shift(12) - 1.0
        brent = _yf_aylik("BZ=F", aylar)
        if brent is not None and not brent.empty:
            brent.index = pd.to_datetime(brent.index).tz_localize(None)
            brent_yoy = brent / brent.shift(12) - 1.0
            # Aynı ay-sonu ızgarasına hizala
            brent_yoy_m = brent_yoy.resample("ME").last()
            lag_corr = {}
            for k in (0, 3, 6):
                lag_corr[f"lag_{k}a"] = _spearman(brent_yoy_m.shift(k), cpi_yoy)
            out["petrol_enflasyon_gecikme_corr"] = {
                "aciklama": "Brent YoY (k ay önce) vs TÜFE YoY — pozitif & artan = petrol öncü.",
                "spearman": lag_corr,
            }
        else:
            out["petrol_enflasyon_gecikme_corr"] = {"hata": "Brent verisi yok."}
    else:
        out["petrol_enflasyon_gecikme_corr"] = {
            "hata": f"Aylık TÜFE serisi yetersiz (kaynak: {cpi_kaynak}). "
                    "Gerçek EVDS anahtarı yoksa sentetik seri lead-lag için düzdür."
        }
    return out


def _reel_kova_skoru(reel: float) -> int:
    """regime_hysteresis kovaları: reel>3 → +25, reel>0 → +12, aksi → −20."""
    if reel > 3:
        return 25
    if reel > 0:
        return 12
    return -20


def bolum_c_rejim_etki() -> Dict[str, object]:
    """Fisher-tam reel geçişinin rejim SKORLAMASINA etkisi (basit vs Fisher).

    reel>0 kapısı işaret-değişmez (matematiksel) → TL_FIRSAT kapısı flip etmez;
    yalnızca büyüklük kovaları (reel>3) kayabilir. Bunu MAKRO_TABLO ayları
    üzerinde ölçer."""
    from reel_hesap import reel_getiri
    satir = []
    kova_degisen = 0
    isaret_degisen = 0
    for ay, m in sorted(MAKRO_TABLO.items()):
        tcmb, enf = m["tcmb"], m["enflasyon"]
        basit = tcmb - enf
        fisher = reel_getiri(tcmb, enf)
        ks, kf = _reel_kova_skoru(basit), _reel_kova_skoru(fisher)
        if ks != kf:
            kova_degisen += 1
        if (basit > 0) != (fisher > 0):
            isaret_degisen += 1
        satir.append({
            "ay": ay,
            "basit_reel_pp": round(basit, 2),
            "fisher_reel_pp": round(fisher, 2),
            "basit_kova_skor": ks,
            "fisher_kova_skor": kf,
            "skor_delta": kf - ks,
        })
    return {
        "aciklama": "Rejim skoru reel kova katkısı: basit vs Fisher (regime_hysteresis kuralı).",
        "ay_sayisi": len(satir),
        "kova_degisen_ay": kova_degisen,
        "isaret_degisen_ay": isaret_degisen,
        "tl_firsat_kapisi_flip": isaret_degisen,  # reel>0 kapısı bunlarda değişir
        "detay": satir,
    }


def _verdict(a: Dict, b: Dict) -> List[str]:
    v = []
    sp = a.get("spearman", {}) if isinstance(a, dict) else {}
    r3 = sp.get("stres_vs_bist_usd_ileri_3a")
    ru = sp.get("stres_vs_usdtry_ileri_3a")
    terc = a.get("tercile", []) if isinstance(a, dict) else []
    if r3 is not None:
        if r3 <= -0.2:
            v.append(f"A: Çıpa stresi ileri BIST(USD) getirisiyle NEGATİF ilişkili (ρ={r3}) — "
                     "yüksek stres → düşük getiri. Risk-varlık ağırlığını kısmak için VERİYLE desteklenir.")
        elif r3 >= 0.2:
            v.append(f"A: Beklenenin AKSİNE pozitif ilişki (ρ={r3}) — bu pencerede çıpa stresi "
                     "risk-varlıkta düşüş öngörmüyor. Karara bağlamak ACELE olur.")
        else:
            v.append(f"A: İlişki zayıf (ρ={r3}) — tek başına çıpa stresi güçlü öngörücü değil.")
    if ru is not None:
        yon = "TL değer kaybını öngörüyor" if ru >= 0.2 else ("ilişki zayıf" if abs(ru) < 0.2 else "ters yönlü")
        v.append(f"A: Stres → 3a USD/TL ρ={ru} ({yon}).")
    if len(terc) >= 2:
        dus = next((t for t in terc if t["kova"] == "düşük stres"), None)
        yuk = next((t for t in terc if t["kova"] == "yüksek stres"), None)
        if dus and yuk:
            v.append(f"A: Düşük-stres aylar ort. BIST(USD) 3a %{dus['bist_usd_ileri_3a_ort_pct']:+.1f} vs "
                     f"yüksek-stres %{yuk['bist_usd_ileri_3a_ort_pct']:+.1f} — fark kovadan görülür.")
    fa = b.get("fisher_analizi", {}) if isinstance(b, dict) else {}
    if fa.get("ort_mutlak_sapma_pp") is not None:
        s = fa["ort_mutlak_sapma_pp"]
        if s >= 1.0:
            v.append(f"B: Reel getiri BASİT formülle Fisher-tam'dan ort. {s} pp iyimser okunuyor — "
                     "yüksek enflasyonda `(1+i)/(1+π)−1` kullanılmalı (kalibrasyon gerekçesi).")
        else:
            v.append(f"B: Basit reel formül sapması küçük (ort. {s} pp) — mevcut okuma yeterince doğru.")
    lc = b.get("petrol_enflasyon_gecikme_corr", {}) if isinstance(b, dict) else {}
    spc = lc.get("spearman", {}) if isinstance(lc, dict) else {}
    if spc:
        v.append(f"B: Petrol→TÜFE gecikme korelasyonu {spc} — artan lag'de yükseliyorsa petrol öncü göstergedir.")
    elif lc.get("hata"):
        v.append(f"B: Petrol→enflasyon ilişkisi ölçülemedi ({lc['hata']}).")
    return v


def main():
    aylar = int(os.environ.get("ANCHOR_AYLAR", "60"))
    print(f"[macro_anchor_validation] {aylar} aylık pencere çekiliyor...")
    df = _seri_indeks(aylar)
    if df.empty:
        print("[HATA] Fiyat verisi alınamadı.")
        return 1

    a = bolum_a_ongorucu(df)
    b = bolum_b_reel(aylar)
    c = bolum_c_rejim_etki()
    rapor = ValidationRapor(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        veri_penceresi={
            "aylar": int(len(df)),
            "baslangic": str(df.index.min().date()),
            "bitis": str(df.index.max().date()),
        },
        kaynaklar={
            "fiyat": "yfinance (aylık kapanış)",
            "cpi": b.get("cpi_kaynak", "—"),
            "makro_tablo": "backtest.MAKRO_TABLO (CDS/enflasyon/tcmb yaklaşık, real curated)",
        },
        A_ongorucu_deger=a,
        B_reel_getiri=b,
        C_rejim_etki=c,
        notlar=[
            "Eşikler veri kantillerinden (33/66) türetildi — elle/sezgiyle konmadı.",
            "Lookahead yok: t'deki çıpa → t+1/t+3 getiri.",
            "CDS/enflasyon yaklaşık; kesin performans değil, yön/kalibrasyon kanıtı.",
        ],
    )
    rapor.verdict = _verdict(a, b)
    if c:
        rapor.verdict.append(
            f"C: Fisher geçişi rejim reel kovasını {c['kova_degisen_ay']}/{c['ay_sayisi']} ayda "
            f"değiştiriyor; TL_FIRSAT (reel>0) kapısı {c['tl_firsat_kapisi_flip']} ayda flip eder "
            "(işaret-değişmez → beklenen 0). Etki büyüklük eşiklerinde, sınırlı ve öngörülebilir."
        )

    os.makedirs(RAPOR_DIR, exist_ok=True)
    json_yol = os.path.join(RAPOR_DIR, "macro_anchor_validation.json")
    with open(json_yol, "w", encoding="utf-8") as f:
        json.dump(asdict(rapor), f, ensure_ascii=False, indent=2)

    md = _md(rapor)
    md_yol = os.path.join(RAPOR_DIR, "macro_anchor_validation.md")
    with open(md_yol, "w", encoding="utf-8") as f:
        f.write(md)

    print("\n" + md)
    print(f"\n[yazıldı] {json_yol}\n[yazıldı] {md_yol}")
    return 0


def _md(r: ValidationRapor) -> str:
    L = ["# Makro Çıpa Doğrulaması", "",
         f"- Üretim: {r.generated_at}",
         f"- Pencere: {r.veri_penceresi['baslangic']} → {r.veri_penceresi['bitis']} ({r.veri_penceresi['aylar']} ay)",
         f"- CPI kaynağı: {r.kaynaklar.get('cpi')}", ""]
    L.append("## Karar / Kanıt Özeti")
    for v in r.verdict:
        L.append(f"- {v}")
    L.append("")
    L.append("## A) Öngörücü Değer — Çıpa Stresi → İleri Getiri")
    sp = r.A_ongorucu_deger.get("spearman", {})
    if sp:
        L.append("| İlişki | Spearman ρ |")
        L.append("|---|---|")
        for k, val in sp.items():
            L.append(f"| {k} | {val} |")
    terc = r.A_ongorucu_deger.get("tercile", [])
    if terc:
        L.append("")
        L.append("| Kova | n | BIST(USD) ileri 3a ort % | USD/TL ileri 3a ort % |")
        L.append("|---|---|---|---|")
        for t in terc:
            L.append(f"| {t['kova']} | {t['n']} | {t['bist_usd_ileri_3a_ort_pct']:+.2f} | {t['usdtry_ileri_3a_ort_pct']:+.2f} |")
    ev = r.A_ongorucu_deger.get("esik_veriden")
    if ev:
        L.append("")
        L.append(f"Veri-güdümlü stres kesimleri: q33={ev['q33']}, q66={ev['q66']}")
    L.append("")
    L.append("## B) Reel Getiri Okuması")
    fa = r.B_reel_getiri.get("fisher_analizi", {})
    if fa:
        L.append(f"- {fa.get('aciklama','')}")
        L.append(f"- Ort. mutlak sapma: **{fa.get('ort_mutlak_sapma_pp')} pp**, max: {fa.get('max_sapma_pp')} pp")
        L.append("")
        L.append("| Ay | TCMB | Enflasyon | Basit reel pp | Fisher-tam pp | Sapma pp |")
        L.append("|---|---|---|---|---|---|")
        for o in fa.get("ornekler", []):
            L.append(f"| {o['ay']} | {o['tcmb']} | {o['enflasyon']} | {o['basit_reel_pp']:+.2f} | {o['fisher_tam_reel_pp']:+.2f} | {o['sapma_pp']:+.2f} |")
    lc = r.B_reel_getiri.get("petrol_enflasyon_gecikme_corr", {})
    if lc.get("spearman"):
        L.append("")
        L.append(f"- Petrol→TÜFE gecikme (Spearman): {lc['spearman']}")
    elif lc.get("hata"):
        L.append("")
        L.append(f"- Petrol→enflasyon: {lc['hata']}")
    c = r.C_rejim_etki
    if c:
        L.append("")
        L.append("## C) Fisher Geçişinin Rejim Kararlarına Etkisi")
        L.append(f"- {c.get('aciklama','')}")
        L.append(f"- Reel kova değişen ay: **{c.get('kova_degisen_ay')}/{c.get('ay_sayisi')}**; "
                 f"TL_FIRSAT (reel>0) kapısı flip: **{c.get('tl_firsat_kapisi_flip')}** (işaret-değişmez → 0 beklenir)")
        L.append("")
        L.append("| Ay | Basit reel pp | Fisher reel pp | Basit kova | Fisher kova | Skor Δ |")
        L.append("|---|---|---|---|---|---|")
        for o in c.get("detay", []):
            L.append(f"| {o['ay']} | {o['basit_reel_pp']:+.2f} | {o['fisher_reel_pp']:+.2f} | "
                     f"{o['basit_kova_skor']:+d} | {o['fisher_kova_skor']:+d} | {o['skor_delta']:+d} |")
    L.append("")
    L.append("## Notlar")
    for n in r.notlar:
        L.append(f"- {n}")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
