# GitHub + WhatsApp (ücretsiz)

Repo: [onurrcansever/Makrofinans](https://github.com/onurrcansever/Makrofinans)

## Ücret

- GitHub Free + Actions: **0 TL** (kişisel kullanımda aylık ~2.000 dk yeter)
- CallMeBot WhatsApp: **0 TL** (kişisel API)

---

## 1. WhatsApp — CallMeBot (≈2 dk)

1. [CallMeBot kayıt](https://www.callmebot.com/blog/free-api-whatsapp-messages/) adımlarını izleyin.
2. WhatsApp’tan bot numarasına kayıt mesajı gönderin → **API key** alın.
3. Telefon: ülke kodu ile, **+ olmadan** (ör. Türkiye `905xxxxxxxxx`).

Yerelde test (`.env`):

```env
BILDIRIM_KANALI=whatsapp
WHATSAPP_PHONE=905xxxxxxxxx
WHATSAPP_APIKEY=xxxx
OZET_POZISYON_TABLO=1
OZET_GOSTERIM_PB=EUR
```

```bash
python3 main.py --ozet-alarm --notify
python3 main.py --sinyal-alarm --notify
```

---

## 2. GitHub Secrets (Actions)

Repo → **Settings → Secrets and variables → Actions**

| Secret | Zorunlu | Açıklama |
|--------|---------|----------|
| `WHATSAPP_PHONE` | Evet | CallMeBot kayıtlı numara |
| `WHATSAPP_APIKEY` | Evet | CallMeBot API key |
| `VARLIKLARIM_JSON` | **Evet (tablo için)** | Base64 `.varliklarim.json` — aşağıda otomatik yükleme |
| `TEMEL_VERI_CACHE_JSON` | Hayır | Analist F/K satırları için cache |
| `PORTFOY_YORUM_CACHE_JSON` | Hayır | 💬 portföy AI yorumu için cache |
| `EVDS_API_KEY` | Önerilir | TCMB enflasyon / rezerv |
| `FRED_API_KEY` | Önerilir | Fed faizi |

`.env` dosyasını **commit etmeyin**.

---

## 3. Eksiksiz WhatsApp — portföy senkronu

GitHub Actions sunucusunda `.varliklarim.json` yoktur (gitignore). Pozisyon tablosu için Mac’teki portföyü **secret** olarak yükleyin:

### Otomatik (önerilen)

`.env` içine GitHub PAT ekleyin (`repo` + **Actions secrets** yazma izni):

```env
GITHUB_TOKEN=ghp_xxxxxxxx
GITHUB_REPO=onurrcansever/Makrofinans
```

Mac’te bir kez ve her portföy değişikliğinden sonra:

```bash
pip install pynacl
python3 scripts/portfoy_github_sync.py
# veya
./macos/portfoy_github_sync.sh
```

`macos/alarm_sync.sh` çalışırken `GITHUB_TOKEN` varsa secret’ı otomatik günceller.

### Manuel (PAT yoksa)

```bash
base64 -i .varliklarim.json | pbcopy
```

GitHub → Settings → Secrets → **New secret** → ad: `VARLIKLARIM_JSON` → yapıştır.

---

## 4. Workflow’lar

| Dosya | Ne zaman | Ne gönderir |
|-------|----------|-------------|
| `gunluk-rapor.yml` | 10/13/15/18 TR | Günlük özet + **pozisyon tablosu** + AL/SAT |
| `sinyal-alarm.yml` | Hafta içi saatlik | AL/SAT değişimi |
| `signal-engine-ci.yml` | Push/PR | Signal engine testleri |

Workflow adımları:

1. Secret’lardan `.varliklarim.json` geri yükle (`scripts/github_ci_restore.sh`)
2. Tam tarama + `portfoy_degerle`
3. WhatsApp mesajı (pozisyon tablosu dahil)

Elle test: **Actions → Makrofinans Alarmları → Run workflow**

---

## 5. Workflow dosyası push (PAT workflow scope)

Git push `workflow` scope olmadan `.github/workflows/` güncellenemez. **Çözüm:**

1. Bu repodaki güncel YAML: [`docs/ci_workflows/`](ci_workflows/)
2. GitHub → repo → ilgili workflow dosyasını aç → **Edit** → içeriği `docs/ci_workflows/gunluk-rapor.yml` ile değiştir → Commit
3. Aynı şekilde `sinyal-alarm.yml` ve `signal-engine-ci.yml` dosyalarını **Create new file** ile `.github/workflows/` altına ekle

Alternatif: PAT oluştururken **workflow** kutusunu işaretleyip `git push` yapın.

---

## 6. Profil (workflow env)

Varsayılan: `INVESTOR_RISK=orta`, `INVESTOR_VADE=kisa_6` (0–6 ay).  
Değiştirmek için workflow dosyasındaki `env:` satırlarını düzenleyin.

---

## 7. Repo gizliliği

**Settings → General → Change visibility → Private** önerilir (portföy secret’ları repoda değil, encrypted secret store’da).
