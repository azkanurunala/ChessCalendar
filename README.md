# Catur.ID — Kalender Turnamen Catur Indonesia

Aplikasi kalender turnamen catur Indonesia dengan fokus pada **Jabodetabek + Bandung**, plus event nasional di luar wilayah tersebut. Data di-scrape otomatis dari chess-results.com dan PB PERCASI, hanya menampilkan turnamen ≥ hari ini sampai 1 tahun ke depan (no backdates).

## Fitur

- **Dual view**: Daftar (chronological) + Kalender (month grid)
- **Smart filters**: Wilayah (Jabodetabek/Bandung/All), kota, format (Standard/Rapid/Blitz), FIDE-rated only
- **Search**: Cari berdasarkan nama, kota, organizer
- **ICS export**: Tambah turnamen ke Google Calendar / Apple Calendar / Outlook 1 klik
- **Auto-filter no-backdate**: Hanya menampilkan turnamen yang masih akan datang
- **Cosmic dark glassmorphism**: Royal gold + deep purple + electric cyan
- **Mobile responsive**: Bottom-sheet modal di mobile, centered modal di desktop

## File Structure

```
chess-calendar/
├── index.html              # Aplikasi web utama (single-file SPA)
├── tournaments.json        # Data turnamen (di-embed ke index.html via build.py)
├── scrape_tournaments.py   # Python scraper — refresh dari chess-results.com
├── build.py                # Rebuild index.html setelah scraping
└── README.md               # File ini
```

## Quick Start

### 1. Buka aplikasi

Cukup buka `index.html` di browser — tidak perlu server. Data sudah di-embed.

### 2. Refresh data

```bash
# Install dependencies
pip install requests beautifulsoup4 lxml

# Scrape data terbaru dari chess-results.com (cepat, listing only)
python scrape_tournaments.py

# Atau scrape dengan detail (akurat dates, ~2s per turnamen, lambat tapi lengkap)
python scrape_tournaments.py --with-details

# Rebuild index.html dengan data baru
python build.py
```

### 3. Deploy (opsional)

Karena `index.html` adalah single-file SPA, tinggal upload ke:
- GitHub Pages (gratis)
- Vercel / Netlify (gratis)
- Cloudflare Pages (gratis)
- Atau hosting statis apa pun

## Workflow Refresh Berkala

Untuk update data otomatis (mis. setiap minggu), pakai cron:

```bash
# crontab -e — refresh tiap Senin pagi 06:00 WIB
0 6 * * 1 cd /path/to/chess-calendar && python scrape_tournaments.py --with-details && python build.py
```

Atau pakai GitHub Actions untuk auto-rebuild + deploy ke Pages.

## Sumber Data

| Sumber | URL | Cakupan |
|---|---|---|
| chess-results.com | `https://chess-results.com/fed.aspx?lan=1&fed=INA` | Primary — semua FIDE Swiss-Manager events |
| PB PERCASI | `https://www.pb-percasi.com/` | Annual major events (Indonesian GM, Kejurnas, Pertamina GM, Ramadhan Cup) |
| ChessPrime | `https://chessprime.com/tournaments/countries/ina/` | Cross-reference dates |
| Festival Catur ID | `https://festival.catur.id/` | Event nasional khusus |

## Tournament Schema

```typescript
interface Tournament {
  id: string;              // e.g. "tnr1402189" (chess-results id) or "annual-igmt-2027"
  name: string;            // "Indonesian GM Tournament 2026"
  startDate: string;       // ISO date "2026-02-15"
  endDate: string;         // ISO date "2026-02-25"
  city: string;            // "Bandung"
  venue: string;           // "Hotel Mewangi Bandung"
  region: string;          // "Jawa Barat" | "DKI Jakarta" | "Banten"
  type: "Standard" | "Rapid" | "Blitz";
  category: string;        // "Open" | "U-12" | "Pelajar" | "Wanita" | "Junior" | ...
  isFIDE: boolean;         // FIDE-rated?
  isJabodetabek: boolean;  // Auto-classified
  isBandung: boolean;      // Auto-classified
  organizer: string;       // "PB PERCASI"
  sourceUrl: string;       // Link ke chess-results.com page
}
```

## Customization

### Ubah default region filter
Di `index.html`, cari:
```js
regionFilter: 'jabodetabek-bandung', // default
```
Ubah ke `'all'`, `'jabodetabek'`, atau `'bandung'`.

### Tambah kota Jabodetabek/Bandung
Di `scrape_tournaments.py`:
```python
JABODETABEK_CITIES = {
    "jakarta", "bogor", ...  # tambahkan di sini
}
```

### Tambah event manual
Edit `scrape_tournaments.py` → fungsi `annual_recurring_events()`.

## Limitations

- Chess-results.com listing tidak selalu menampilkan tanggal di halaman index — script perlu fetch detail page dengan flag `--with-details` untuk dates akurat (lambat).
- Banyak event lokal kecil tidak terdaftar di chess-results.com (cuma diumumkan via Instagram/WA).
- Jadwal nasional tahunan (Kejurnas, Pertamina GM, dll.) di-hardcode di scraper berdasarkan pola historis — perlu cek manual setiap awal tahun.

## Stack

- **Frontend**: Single-file HTML + Tailwind CSS + Alpine.js + GSAP
- **Scraper**: Python 3.10+ + requests + BeautifulSoup
- **Design**: Cosmic dark glassmorphism (Bebas Neue + IBM Plex Sans + Cormorant Garamond)
- **No backend** — semuanya static

## License

Open data, open source. Built dengan ♛ untuk komunitas catur Indonesia.
