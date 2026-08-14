# GBP Verification Monitor — Panduan Utama Project (Monorepo)

Project ini berisi solusi pemantauan status verifikasi **Google Business Profile (GBP)** di seluruh jaringan outlet/kios FIFGROUP. Toolset ini membantu memetakan lokasi, mendeteksi masalah koordinat, dan mencocokkan (rekonsiliasi) data internal perusahaan dengan data aktual di Google Maps.

Repository ini bertipe monorepo yang memuat **dua arsitektur alternatif**:
1. **Opsi A: Django Web Dashboard (`gbp_monitor/`)** — Aplikasi web lengkap dengan UI modern (Tailwind CSS), visualisasi peta interaktif, manajemen status, dan integrasi database awan **Supabase PostgreSQL**.
2. **Opsi B: Standalone Scripts & Streamlit Dashboard (Root Directory)** — Skrip otomasi CLI ringan berbasis scheduler lokal dan dashboard interaktif **Streamlit** menggunakan database **SQLite**.

---

## 🗺️ Gambaran Umum Arsitektur & Struktur File

```text
gmb_otomasi/ (Root)
│
├── gbp_monitor/               ← [OPSI A] FOLDER UTAMA DJANGO WEB DASHBOARD (Direkomendasikan)
│   ├── manage.py              
│   ├── gbp/                   ← Django App (Models, Views, Tailwind templates)
│   │   ├── services/          ← Logika bisnis utama (Reconciliation, API, Export)
│   │   └── management/        ← Command otomasi Django (fetch_gbp_status, run_gbp_pipeline)
│   └── gbp_monitor/           ← Konfigurasi setting Django (terintegrasi Supabase)
│
├── fetch_status.py            ← [OPSI B] CLI untuk fetch GBP API → simpan ke SQLite/CSV
├── update_database.py         ← [OPSI B] CLI lookup/update data internal dengan hasil fetch
├── scheduler.py               ← [OPSI B] Scheduler berkala untuk fetch_status & update_database
├── dashboard.py               ← [OPSI B] Dashboard interaktif berbasis Streamlit
├── history_db.py              ← [OPSI B] Utilitas SQLite lokal (gbp_history.db)
│
├── credentials.json           ← OAuth 2.0 Credentials dari Google Cloud Console (Dibuat Manual)
├── token.json                 ← Google API Access Token (Terbuat otomatis setelah Login pertama)
└── requirements.txt           ← Library Python untuk script root (Opsi B)
```

---

## 🔐 KONFIGURASI GOOGLE BUSINESS PROFILE API (Wajib untuk Opsi A & B)

Kedua opsi membutuhkan otorisasi ke Google API. Ikuti langkah berikut untuk menyiapkannya:

### 1. Buat Google Cloud Project
1. Buka [Google Cloud Console](https://console.cloud.google.com).
2. Klik **"New Project"** → beri nama (contoh: `gbp-fifgroup-monitor`).
3. Pilih project tersebut.

### 2. Aktifkan API yang Dibutuhkan
Buka **APIs & Services → Library**, cari dan aktifkan ketiga API berikut:
* `Business Profile Account Management API`
* `My Business Business Information API`
* `My Business Verifications API`

> ⚠️ **PENTING:** Business Profile API adalah *Restricted API*. Akun Anda harus mendapatkan persetujuan akses (approval) dari Google agar bisa menarik data production. 
> Ajukan akses di: [Google Developers GBP Prereqs](https://developers.google.com/my-business/content/prereqs). Proses persetujuan memakan waktu **3–7 hari kerja**.

### 3. Buat OAuth 2.0 Client ID
1. Buka **APIs & Services → OAuth consent screen**.
2. Set tipe ke **External** (jika untuk testing/akun non-organisasi) atau **Internal** (jika menggunakan Google Workspace perusahaan).
3. Lengkapi data wajib, pastikan masukkan email Anda pada bagian **Test Users** agar bisa login saat masa pengembangan.
4. Buka **APIs & Services → Credentials** → Klik **"Create Credentials"** → **"OAuth 2.0 Client ID"**.
5. Pilih Application Type: **Desktop App**.
6. Klik **Download JSON**, ganti nama file tersebut menjadi **`credentials.json`**.
7. Salin file `credentials.json` ke folder root (untuk Opsi B) dan/atau folder `gbp_monitor/data/` (untuk Opsi A).

---

## 🚀 OPSI A: DJANGO WEB DASHBOARD (`gbp_monitor`)
Aplikasi web berbasis Django 4.x yang terhubung ke cloud database Supabase.

### Fitur Utama Opsi A:
* **UI/UX Premium**: Dibangun dengan Tailwind CSS, responsif, dan dinamis.
* **Database Persisten**: Menggunakan PostgreSQL (Supabase) via `dj-database-url` sehingga riwayat run tersimpan aman di cloud.
* **Visualisasi Kaya**: Chart tren verifikasi (Chart.js), pemetaan koordinat (Folium Map), dan kartu rangkuman risiko.
* **UI Update Status**: Lakukan tarik data API dan pencocokan CSV langsung dari browser.

### Cara Menjalankan Opsi A:
1. Masuk ke direktori:
   ```bash
   cd gbp_monitor
   ```
2. Buat virtual environment & aktifkan:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```
3. Install dependensi Python & Node.js:
   ```bash
   pip install -r requirements.txt
   npm install
   ```
4. Salin `.env.example` ke `.env` dan konfigurasikan database Supabase serta file path Google credential Anda.
5. Jalankan autentikasi pertama kali:
   ```bash
   python manage.py fetch_gbp_status
   ```
   *(Browser akan terbuka untuk meminta izin akun Google Anda. Setelah selesai, file `token.json` akan dibuat otomatis di folder `data/`)*
6. Build Tailwind CSS & Jalankan migrasi:
   ```bash
   npm run build:css
   python manage.py migrate
   ```
7. Jalankan Server:
   ```bash
   python manage.py runserver
   ```
   Akses di [http://localhost:8000](http://localhost:8000).

---

## ⚡ OPSI B: STANDALONE SCRIPTS & STREAMLIT DASHBOARD (Root)
Solusi otomasi lokal berbasis skrip CLI Python dan visualisasi antarmuka Streamlit.

### Fitur Utama Opsi B:
* **Ringan**: Cocok dipasang di server lokal atau komputer scheduler tanpa server web penuh.
* **Otomasi CLI**: Skrip bisa dijadwalkan langsung lewat Windows Task Scheduler atau Linux Cron.
* **Streamlit UI**: Visualisasi cepat menggunakan dashboard streamlit.

### Cara Menjalankan Opsi B:
1. Aktifkan virtual environment di root direktori.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Letakkan `credentials.json` hasil langkah setup Google API di root direktori.
4. Jalankan fetch status perdana (dan OAuth login):
   ```bash
   python fetch_status.py
   ```
   *(Setelah login sukses di browser, file `token.json` otomatis terbuat di root)*
5. Jalankan update database (lookup data hasil fetch ke database internal Anda):
   ```bash
   python update_database.py --gbp-file gbp_status_YYYYMMDD.csv --db-file database_kios.csv --mode csv --db-key-col kode_kios
   ```
6. Jalankan Dashboard Streamlit:
   ```bash
   streamlit run dashboard.py
   ```
7. Untuk menjalankan berkala (background task):
   ```bash
   python scheduler.py --schedule 08:00
   ```

---

## 🧠 LOGIKA BISNIS UTAMA (BUSINESS LOGIC)

### 1. Penentuan Status Verifikasi (Prioritas Atas ke Bawah)
Sistem (baik di Opsi A maupun Opsi B) mengklasifikasikan status verifikasi Google ke dalam 4 kategori berdasarkan data API:
1. **`Suspended`**: Metadata lokasi menunjukkan `isSuspended`, `suspended`, atau `isDisabled` bernilai `True` (Toko ditangguhkan oleh Google).
2. **`Duplicate`**: Lokasi terdeteksi sebagai `duplicateLocation` pada respons metadata Google.
3. **`Verified`**: Lokasi terverifikasi penuh dan akun Anda memegang akses kepemilikan (`hasVoiceOfMerchant = True`).
4. **`Need Verification` / `Unverified`**: Lokasi terdaftar namun belum terverifikasi oleh akun Anda.

### 2. Status Evaluasi Koordinat (`Coord Status`)
Sistem mengevaluasi kualitas data Latitude dan Longitude yang dikembalikan dari API Google Maps:
* **`OK`**: Koordinat berhasil di-parsing dengan benar dan berada di dalam rentang bumi yang valid (Latitude -90 s/d 90, Longitude -180 s/d 180).
* **`MISSING`**: Lokasi tidak memiliki koordinat sama sekali di Google.
* **`PARSE_ERROR`**: Koordinat ada di API tetapi format angkanya rusak (misal salah ketik tanda baca).
* **`OUT_OF_RANGE`**: Koordinat terbaca tetapi nilainya di luar batas koordinat peta dunia.

### 3. Alur Rekonsiliasi (Pencocokan)
Rekonsiliasi membandingkan **Master Data Kios** dengan data **GBP API**:
* Pencocokan dilakukan menggunakan kunci unik (`store_code` di GBP vs `kode_kios`/`kode_outlet` di database internal).
* Jika kode identik, sistem memperbarui status verifikasi internal mengikuti status aktual Google.
* Jika kode kosong atau kode ganda (duplicate identifier di data Anda), sistem akan menandai baris tersebut sebagai `Manual Review` atau `Invalid` agar tidak merusak database.

### 4. Penyimpanan Data (Storage & Database)
Data history untuk chart dan fitur dashboard disimpan menggunakan sistem database rasional via **Django ORM** (pada Opsi A).
* **Database Default**: Secara default (saat pengembangan/development), sistem menggunakan **SQLite** (tersimpan di file `gbp_monitor/db.sqlite3`). File ini menyimpan seluruh history fetching data API dan Master Data Anda.
* **Database Production**: Untuk skala produksi, aplikasi ini sudah dikonfigurasi untuk terhubung langsung ke **Supabase (PostgreSQL)** cukup dengan mengubah `DATABASE_URL` di dalam file `.env`.
* **Struktur Penyimpanan Utama**:
  1. `MasterLocation`: Menyimpan tabel data master outlet Anda (Area, Network, Alamat, dll).
  2. `FetchRun`: Menyimpan history waktu setiap kali Anda menarik data dari Google.
  3. `LocationSnapshot`: Menyimpan setiap baris data lokasi spesifik pada waktu/run tertentu (berisi Status, Latitude, Longitude, dsb).

### 5. Pemetaan & Filter Ganda (Dual-Filter Map View)
Sistem memiliki modul Peta Interaktif (*Map View*) yang dirender menggunakan library *Folium* secara dinamis, dilengkapi dengan filter eksklusif:
* **Mode Status**: Menampilkan penyebaran lokasi dan filter checkbox murni berdasarkan status verifikasi Google (Verified, Need Verification, Suspended, dll).
* **Mode Jenis Network**: Menampilkan penyebaran lokasi dengan pewarnaan dan filter checkbox berdasarkan jenis/kategori infrastruktur jaringan operasional (Cabang, Pos, Kios/Subkios, Lainnya).
* Sistem melakukan pencarian silang otomatis (lookup) dari data Google API terhadap *Master Data* untuk mengetahui *Network* masing-masing lokasi.
* Filter UI dirancang eksklusif, artinya jika pengguna sedang berada di Mode Status, sistem secara cerdas hanya akan menerapkan filter status (mengabaikan input filter tipe network), dan sebaliknya.

---

## 🛠️ TROUBLESHOOTING UMUM

| Gejala/Error | Penyebab | Solusi |
|---|---|---|
| `403 ACCESS_DENIED` | Akun Google Anda belum terdaftar sebagai admin di GBP, atau akses restricted API belum disetujui Google. | Daftarkan email ke test users OAuth consent screen, atau tunggu persetujuan dari Google Developers. |
| `Token expired / Invalid Grant` | Token OAuth di `token.json` kedaluwarsa atau di-revoke oleh Google Cloud Console. | Hapus file `token.json` lalu jalankan kembali skrip fetch untuk memicu login browser ulang. |
| `store_code tidak cocok` | Kode kios di database internal berbeda dengan "Shop Code" di dashboard Google Business Profile. | Samakan "Shop Code / Store Code" di portal Google Business Profile Manager dengan kode outlet di sistem internal Anda. |
| `ModuleNotFoundError` | Ada modul Python yang belum terpasang di Virtual Environment yang aktif. | Pastikan virtual environment telah aktif (`.venv`) dan jalankan kembali `pip install -r requirements.txt`. |

---
*FIFGROUP Google Business Profile Automation Toolset. Pastikan keamanan kredensial dengan tidak mengunggah file `.env`, `credentials.json`, atau `token.json` ke publik.*
