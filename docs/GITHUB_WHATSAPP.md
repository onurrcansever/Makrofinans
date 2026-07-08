# GitHub + WhatsApp (ücretsiz)

Repo: [onurrcansever/Makrofinans](https://github.com/onurrcansever/Makrofinans)

## Ücret

- GitHub Free + Actions: **0 TL** (kişisel kullanımda aylık ~2.000 dk yeter)
- CallMeBot WhatsApp: **0 TL** (kişisel API)

## 1. WhatsApp — CallMeBot (≈2 dk)

1. [CallMeBot kayıt](https://www.callmebot.com/blog/free-api-whatsapp-messages/) adımlarını izleyin.
2. WhatsApp’tan bot numarasına kayıt mesajı gönderin → **API key** alın.
3. Telefon: ülke kodu ile, **+ olmadan** (ör. Türkiye `905xxxxxxxxx`).

Yerelde test (`.env`):

```env
BILDIRIM_KANALI=whatsapp
WHATSAPP_PHONE=905xxxxxxxxx
WHATSAPP_APIKEY=xxxx
```

```bash
python3 main.py --alert-only
python3 main.py --sinyal-alarm --notify
```

## 2. GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Zorunlu | Açıklama |
|--------|---------|----------|
| `WHATSAPP_PHONE` | Evet | CallMeBot kayıtlı numara |
| `WHATSAPP_APIKEY` | Evet | CallMeBot API key |
| `EVDS_API_KEY` | Önerilir | TCMB enflasyon / rezerv |
| `FRED_API_KEY` | Önerilir | Fed faizi |

`.env` dosyasını **commit etmeyin**.

## 3. Repo gizliliği

**Settings → General → Change visibility → Private** önerilir.

## 4. Workflow

`.github/workflows/gunluk-rapor.yml`:

- Günde 2 kez (09:00 ve 17:00 TR)
- Rejim değişince WhatsApp
- Hisse AL/SAT/DİKKAT değişince WhatsApp
- İlk çalışmada spam yok (durum dosyası cache’lenir)

Elle test: **Actions → Makrofinans Alarmları → Run workflow**

## 5. Profil (workflow env)

Varsayılan: `INVESTOR_RISK=orta`, `INVESTOR_VADE=kisa_6` (0–6 ay).  
Değiştirmek için workflow dosyasındaki `env:` satırlarını düzenleyin.
