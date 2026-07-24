# Modulfinans yayın

## Canlı URL’ler

- Uygulama (Render / asıl Streamlit): https://modulfinans.onrender.com
- Netlify kapı (yönlendirir): https://modulfinans.netlify.app → Render
- Custom domain: https://makro.modulcheck.com
- Hedef domain: https://www.makro.modulcheck.com (DNS → Render)

## Mimari

- **Uygulama:** Render Web Service `modulfinans` — Streamlit (`app.py`)
- **DNS:** Netlify zone `modulcheck.com` — CNAME → `modulfinans.onrender.com`
- **Netlify proje:** [Modulfinans](https://app.netlify.com/projects/modulfinans) (placeholder + DNS yüzeyi)
- **Neon:** kullanılmıyor

## Render

Blueprint: [`render.yaml`](../render.yaml)

```bash
streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
```

## DNS kayıtları

| Tip   | Host        | Değer                       |
|-------|-------------|-----------------------------|
| CNAME | `makro`     | `modulfinans.onrender.com`  |
| CNAME | `www.makro` | `modulfinans.onrender.com`  |
