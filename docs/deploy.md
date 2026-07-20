# Modulfinans yayın

## Mimari

- **Uygulama:** Render Web Service (`modulfinans`) — Streamlit (`app.py`)
- **Domain / DNS:** Netlify zone `modulcheck.com` → `www.makro.modulcheck.com` CNAME → Render
- **Neon:** kullanılmıyor (state yerel JSON; çok kullanıcılı DB yok)

## Render

Blueprint: depodaki [`render.yaml`](../render.yaml).

Start:

```bash
streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
```

Secret env (Render Dashboard → Environment): `GROQ_API_KEY`, `FRED_API_KEY`, `EVDS_API_KEY`, isteğe bağlı Telegram/WhatsApp.

## Netlify

Proje: [Modulfinans](https://app.netlify.com/projects/modulfinans) — DNS yüzeyi; Streamlit Netlify’da çalışmaz.

DNS (zone `modulcheck.com`):

| Tip   | Host       | Değer                      |
|-------|------------|----------------------------|
| CNAME | `www.makro`| `<servis>.onrender.com`    |

Custom domain Render tarafında da eklenir (SSL).

## Yerel

Masaüstü app `.streamlit/config.toml` ile `127.0.0.1:8502` kullanmaya devam eder; Render CLI flag’leri bunu override eder.
