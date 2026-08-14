# GBP Monitor — Dashboard Monitoring Status Verifikasi GBP

Dashboard internal FIFGROUP untuk memonitor status verifikasi Google Business Profile (GBP) di seluruh jaringan outlet.

## Tech Stack

| Layer | Teknologi |
|-------|-----------|
| Backend | Django 4.x |
| Frontend | Django Templates + Tailwind CSS |
| Database | Supabase PostgreSQL (via `dj-database-url`) |
| GBP API | Google Business Profile API (server-side) |
| Visualisasi | Chart.js, Folium |

---

## Setup

### 1. Clone & Virtual Environment

```bash
git clone <repo-url>
cd gbp_monitor
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Konfigurasi Environment

Salin `.env.example` ke `.env` dan isi nilainya:

```bash
cp .env.example .env
```

Edit `.env`:

```env
SECRET_KEY=buat-secret-key-panjang-dan-aman
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Supabase PostgreSQL (dari Settings > Database > URI di Supabase Dashboard)
DATABASE_URL=postgresql://postgres:<password>@<host>:5432/postgres

# Path Google OAuth credentials
GBP_CREDENTIALS_PATH=data/credentials.json
GBP_TOKEN_PATH=data/token.json
GBP_DEFAULT_ACCOUNT_ID=
```

> ⚠️ **Jangan commit file `.env` ke repository!**

### 4. Setup Google API Credentials

1. Letakkan `credentials.json` di folder `data/`
2. Jalankan autentikasi Google OAuth pertama kali:

```bash
python manage.py fetch_gbp_status
```

Ini akan membuka browser untuk login Google dan menyimpan `data/token.json`.

### 5. Setup Tailwind CSS

```bash
# Install Node dependencies
npm install

# Build CSS (production)
npm run build:css

# Atau watch mode saat development
npm run dev:css
```

> ℹ️ File `output.css` harus ada sebelum server dijalankan. Jalankan `npm run build:css` minimal sekali.

### 6. Migrasi Database ke Supabase

Pastikan `DATABASE_URL` sudah diisi di `.env`, lalu:

```bash
python manage.py migrate
```

Ini akan membuat semua tabel di Supabase PostgreSQL.

### 7. Jalankan Server

```bash
python manage.py runserver
```

Buka: [http://localhost:8000](http://localhost:8000)

---

## Struktur Database (Supabase)

| Tabel | Deskripsi |
|-------|-----------|
| `gbp_fetchrun` | Metadata setiap fetch GBP API |
| `gbp_locationsnapshot` | Status lokasi per run |
| `gbp_masterlocation` | Data master outlet/network |
| `gbp_reconciliationjob` | Metadata proses pencocokan |
| `gbp_reconciliationresult` | Detail hasil pencocokan |

---

## Management Commands

### Fetch Status GBP dari API

```bash
python manage.py fetch_gbp_status
```

Mengambil data terbaru dari Google Business Profile API dan menyimpan ke Supabase.

### Import Master Data dari CSV

```bash
python manage.py import_master_locations --file path/to/master.csv
```

CSV minimal memiliki kolom:
- `store_code` (atau `kode_kios`, `kode_outlet`)
- `location_name` (atau `location_id`, `branch_id`)
- `business_name` (atau `nama_bisnis`)
- `network_name` (atau `network`)
- `account_name`
- `verification_status` (atau `status`)
- `area` (atau `wilayah`, `region`)
- `network` (atau `jenis_network`, `tipe_network` - Contoh: Cabang, Pos, Kios, Subkios)

Opsi tambahan:
```bash
# Preview tanpa menyimpan
python manage.py import_master_locations --file master.csv --dry-run

# Hapus semua data sebelum import
python manage.py import_master_locations --file master.csv --clear
```

### Import Data Legacy dari SQLite

```bash
python manage.py import_legacy_sqlite --db-file gbp_history.db
```

### Jalankan Pipeline Lengkap

```bash
python manage.py run_gbp_pipeline
```

Cocok dijalankan via **Task Scheduler Windows** atau **cron**.

---

## Fitur Utama

### Overview
- Summary cards: Total Network, Verified, Duplicate, Suspended, Need Verification, Unverified
- Line chart Peningkatan Jumlah Verifikasi (Time Series)
- Kartu Status yang Membutuhkan Perhatian (Risk/Attention Summary)
- Tabel Top 10 Area & Bottom 10 Area (berdasarkan verification rate)
- Tabel Status Verifikasi Berdasarkan Jenis Network (Cabang, Pos, dll)
- Riwayat semua run

### Data Table
- Search by nama bisnis / store code
- Filter by status (Verified/Duplicate/Suspended/Unverified)
- Sort by kolom
- Pagination
- Export CSV dan Excel
- Link ke detail lokasi dan Google Maps

### Map View
- Peta interaktif (Folium) dengan marker berwarna per status
- Filter status
- Tabel lokasi dengan koordinat bermasalah
- **3 Mode Tampilan:**
  - **Berdasarkan Status** — Marker berwarna sesuai status verifikasi (Verified, Duplicate, Suspended, Need Verification)
  - **Berdasarkan Jenis Network** — Marker berwarna sesuai tipe network (Cabang, Pos, Kios/Subkios, Lainnya)
  - **Branch Coverage Mode** — Visualisasi coverage cabang terhadap Pos, Kios, dan Subkios

### Branch Coverage Mode

Mode ini menampilkan coverage setiap cabang terhadap network di bawahnya (Pos, Kios, Subkios).

**Logic Coverage:**
- Coverage ditentukan berdasarkan **3 angka pertama** dari `store_code` (prefix)
- Jika cabang dan Pos/Kios/Subkios memiliki prefix yang sama, mereka berada dalam satu coverage group
- Contoh: Cabang `101001` meng-cover Pos `101101` dan Kios `101201` karena prefix sama: `101`
- Jenis network (Cabang/Pos/Kios/Subkios) dibedakan dari kolom `NETWORK` di master data (bukan dari store code)

**Visual Coverage:**
- Setiap cabang diberi warna overlay yang berbeda
- Jika coverage group memiliki ≥3 titik koordinat → polygon convex hull
- Jika coverage group hanya memiliki 1–2 titik → circle buffer (radius 3km)
- **Penting:** Area coverage adalah estimasi visual berdasarkan titik network, bukan batas wilayah administratif resmi

**Fitur:**
- Summary cards: Total Cabang, Pos, Kios, Subkios, Average Coverage
- Dropdown pilih cabang → tampilkan child markers dan detail panel
- Detail panel: jumlah network per jenis, status verifikasi, tabel network ter-cover
- Warning untuk: duplicate branch prefix, unmapped network, invalid store code

**URL Parameter:**
```
/map/?mode=coverage                        # Semua cabang
/map/?mode=coverage&branch_prefix=101      # Detail cabang dengan prefix 101
```

**Service:**
- Logic grouping berada di `gbp/services/map_coverage_service.py`
- Tidak ada field baru `category` — menggunakan kolom `network` dari `MasterLocation`


### Update Status Verifikasi
- Ambil data terbaru dari GBP API
- Bandingkan dengan master data (CSV upload atau path)
- Tampilkan network yang berubah status
- Tabel lengkap hasil pencocokan
- Download hasil pencocokan (CSV)
- Hasil tersimpan di database Supabase (persistent)

---

## Keamanan

- Jangan commit `.env`, `token.json`, `credentials.json`
- Google OAuth hanya berjalan di server-side Django
- Supabase connection string hanya ada di `.env`
- SSL aktif otomatis untuk koneksi PostgreSQL

---

## Development Workflow

```bash
# Terminal 1: Django server
python manage.py runserver

# Terminal 2: Tailwind watch
npm run dev:css
```

---

## Struktur Project

```
gbp_monitor/
├── manage.py
├── requirements.txt
├── package.json
├── tailwind.config.js
├── .env.example
│
├── gbp_monitor/
│   ├── settings.py        ← Konfigurasi (django-environ + dj-database-url)
│   └── urls.py
│
├── gbp/
│   ├── models.py          ← FetchRun, LocationSnapshot, MasterLocation, ReconciliationJob, ReconciliationResult
│   ├── views.py           ← Clean views, delegasi ke services
│   ├── urls.py
│   ├── forms.py
│   │
│   ├── services/
│   │   ├── gbp_api.py
│   │   ├── status_parser.py
│   │   ├── history_service.py
│   │   ├── reconciliation_service.py  ← Simpan ke Supabase
│   │   ├── export_service.py
│   │   ├── dashboard_service.py       ← Agregasi dashboard (Master + Snapshot)
│   │   ├── master_update_service.py   ← Import CSV → MasterLocation
│   │   └── map_coverage_service.py    ← Branch Coverage Mode logic
│   │
│   ├── management/commands/
│   │   ├── fetch_gbp_status.py
│   │   ├── import_legacy_sqlite.py
│   │   ├── run_gbp_pipeline.py
│   │   └── import_master_locations.py ← Baru
│   │
│   ├── templates/gbp/
│   │   ├── base.html          ← Tailwind layout
│   │   ├── overview.html
│   │   ├── data_table.html
│   │   ├── map_view.html
│   │   ├── update_status.html
│   │   ├── location_detail.html
│   │   └── components/
│   │
│   └── static/gbp/
│       ├── css/input.css      ← Tailwind source
│       └── js/main.js
│
└── data/
    ├── credentials.json   ← JANGAN COMMIT
    └── token.json         ← JANGAN COMMIT
```
