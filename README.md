# 🛡️ NawalaSentinel — Multi-Operator Domain Block Monitor

**NawalaSentinel** adalah sistem backend lengkap dan antarmuka web modern untuk pemantauan otomatis status pemblokiran domain (Nawala / DNS Blocking / Internet Positif) pada **ratusan domain dan subdomain** secara paralel di 4 jaringan operator seluler utama Indonesia: **Telkomsel, XL Axiata, Tri (3), dan IM3 Indosat**.

---

## ✨ Fitur Utama NawalaSentinel

1. **Multi-Operator Real-Time Checking**:
   - Pengecekan terpisah untuk tiap operator seluler (**Telkomsel, XL, IM3, Tri**).
   - Mengombinasikan kueri DNS A/AAAA langsung ke resolver DNS operator (deteksi IP Sinkhole) dan inspeksi HTTP/HTTPS (deteksi redirect & signature halaman blokir).

2. **Performa Tinggi & Asinkron (AsyncIO + dnspython)**:
   - Didesain dengan `asyncio`, `dnspython` async resolver, dan `httpx`.
   - Menggunakan `asyncio.Semaphore` untuk menangani ratusan domain sekaligus secara paralel dalam hitungan detik.

3. **Background Scheduler Otomatis**:
   - `APScheduler` berjalan secara otomatis di background setiap **5 menit** untuk mengecek seluruh domain terdaftar.
   - Mengidentifikasi transisi perubahan status (`NORMAL` ↔ `BLOCKED`).

4. **Sistem Notifikasi Telegram & Webhook Real-Time**:
   - Integrasi Bot Telegram otomatis yang akan mengabarkan secara *real-time* dengan format pesan HTML jika ada domain yang statusnya berubah menjadi **Terblokir** atau kembali **Normal**.
   - Mendukung Generic Webhook (Discord / Slack / Custom API).

5. **Antarmuka Web Dashboard Modern (Glassmorphism Dark Mode)**:
   - Dashboard visual statistik (Kartu counter Total, Normal, Terblokir, Mixed).
   - Fitur **Import Massal** file `.txt` / `.csv` atau paste teks massal.
   - Fitur **Ekspor Laporan** hasil pengecekan dalam format `.csv`.
   - Tombol **Cek Massal Sekarang** untuk eksekusi instant manual.
   - Pengaturan Bot Telegram, Interval Scheduler, dan Proxy per operator.

---

## 🏗️ Struktur Proyek (`NawalaSentinel/`)

```
NawalaSentinel/
├── app/
│   ├── __init__.py
│   ├── config.py              # Konfigurasi aplikasi & .env loader
│   ├── database.py            # SQLite Async Engine SQLAlchemy & session
│   ├── models.py              # Schema ORM (Domain, CheckResult, StatusLog)
│   ├── checker.py             # Engine async kueri DNS & HTTP per operator
│   ├── scheduler.py           # Background APScheduler 5 menit
│   ├── notifier.py            # Bot Telegram & Webhook alert engine
│   ├── routes.py              # Endpoint FastAPI (UI & REST API)
│   ├── static/                # Asset CSS Dark-mode Glassmorphism & JS
│   │   ├── css/style.css
│   │   └── js/main.js
│   └── templates/             # Jinja2 HTML Templates (index, domains, logs, settings)
│       ├── base.html
│       ├── index.html
│       ├── domains.html
│       ├── logs.html
│       └── settings.html
├── data/                      # Direktori SQLite Database (nawalasentinel.db)
├── main.py                    # Entry point uvicorn server
├── requirements.txt           # File dependensi Python
├── .env.example               # Template environment variables
└── README.md                  # Panduan penggunaan
```

---

## 🚀 Panduan Instalasi & Penggunaan

### 1. Masuk ke Folder Project
```bash
cd "c:/Users/skylark/Downloads/SEO Automation Tools/NawalaSentinel"
```

### 2. Instal Dependensi Python
```bash
pip install -r requirements.txt
```

### 3. Konfigurasi Environment Variables (`.env`)
```bash
cp .env.example .env
```

### 4. Jalankan Server Application
```bash
python main.py
```

Buka browser dan akses **Web Dashboard NawalaSentinel**:
👉 **`http://localhost:8000`**

---

## 🌐 Panduan Deployment di aaPanel (Linux VPS)

### Metode 1: Menggunakan aaPanel Python Project Manager
1. Buka **aaPanel** > **App Store** > Pasang **Python Project Manager**.
2. Masuk ke **Python Project Manager** > Tab **Version management** > Pasang **Python 3.10+**.
3. Di tab **Python project**, klik **Add Project**:
   - **Project Name**: `nawalasentinel`
   - **Path**: Pilih direktori tempat clone repo (misal: `/www/wwwroot/nawalasentinel`)
   - **Python Version**: Pilih Python 3.10 / 3.11
   - **Framework**: `FastAPI` / `python`
   - **Startup file/folder**: `main.py`
   - **Run with**: `gunicorn` atau `uvicorn` (`main:app --host 127.0.0.1 --port 8000 --workers 1`)
   - **Bind Domain**: Masukkan domain / subdomain Anda (aaPanel akan otomatis membuat Nginx Reverse Proxy).
4. Buat file `.env` dari template:
   ```bash
   cp .env.example .env
   ```
5. Buat akun admin default:
   ```bash
   python seed_admin.py
   ```
6. Klik **Start** project di Python Manager.

---

### Metode 2: Clone via Terminal VPS & Systemd Service
1. **Clone Repository di VPS**:
   ```bash
   cd /www/wwwroot
   git clone https://github.com/silent404s/NawalaSentinel.git nawalasentinel
   cd nawalasentinel
   ```
2. **Buat Virtual Environment & Install Dependencies**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Setup Konfigurasi & Admin**:
   ```bash
   cp .env.example .env
   python seed_admin.py
   ```
4. **Jalankan Uvicorn / Gunicorn**:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
5. **Konfigurasi Reverse Proxy Nginx di aaPanel**:
   - Tambahkan Website di aaPanel dengan domain Anda.
   - Buka Website Setting > **Reverse Proxy** > **Add reverse proxy**.
   - Target URL: `http://127.0.0.1:8000`

