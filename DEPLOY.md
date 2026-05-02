# Deploy ke GitHub Pages dengan Auto-Scrape

Site live di `https://<username>.github.io/<repo-name>/` dan auto-refresh tiap hari jam 05:00 WIB.

## 1. Push ke GitHub

```bash
cd chess-calendar
git init
git add .
git commit -m "init: chess calendar"
git branch -M main

# Bikin repo kosong dulu di github.com (jangan tick "Add README"),
# lalu copy URL-nya:
git remote add origin https://github.com/<username>/<repo-name>.git
git push -u origin main
```

## 2. Enable GitHub Pages

1. Buka repo di GitHub → **Settings** → **Pages** (sidebar kiri)
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/ (root)`
4. **Save**

Tunggu ~1 menit, site live di `https://<username>.github.io/<repo-name>/`.

## 3. Beri permission ke Actions buat commit

Workflow butuh push balik ke repo. Default-nya kadang read-only.

1. Repo → **Settings** → **Actions** → **General** (sidebar kiri)
2. Scroll ke **Workflow permissions**
3. Pilih **Read and write permissions**
4. **Save**

## 4. Tes workflow (opsional, biar nggak nunggu cron)

1. Repo → **Actions** tab
2. Pilih **Daily Tournament Scrape**
3. Klik **Run workflow** → **Run workflow** (hijau)
4. Tunggu ~3–5 menit. Liat log-nya. Kalau hijau, beres.

Setelah itu workflow jalan otomatis tiap hari jam **22:00 UTC = 05:00 WIB (besok pagi)**.

## 5. Custom domain (opsional)

Kalau punya domain (misal `catur.azka.id`):

1. Settings → Pages → **Custom domain** → masukin domain → Save
2. DNS provider, tambah CNAME record:
   ```
   catur  CNAME  <username>.github.io
   ```
3. Tunggu propagasi (~10 menit). HTTPS otomatis aktif.

## Troubleshooting

| Masalah | Fix |
|---|---|
| Workflow gagal di step `Commit & push` | Belum aktifin "Read and write permissions" (step 3) |
| Site 404 | Pages belum di-enable (step 2), atau branch salah |
| Scrape fail karena chess-results.com timeout | Re-run workflow manual. Data lama tetap aman, belum di-overwrite |
| Cron telat 10–15 menit | Normal — GitHub Actions free tier shared queue |
| Mau ganti jadwal | Edit `cron: '0 22 * * *'` di `.github/workflows/scrape.yml`. Format: `menit jam * * *` (UTC) |

## Cost

**Gratis selamanya**. GitHub Actions gratis untuk public repo (unlimited menit).
GitHub Pages gratis untuk public repo (100 GB bandwidth/bulan).
