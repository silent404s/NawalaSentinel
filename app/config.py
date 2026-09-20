import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

class Settings:
    """
    Konfigurasi Aplikasi NawalaSentinel - Domain Block Monitor
    """
    APP_NAME: str = os.getenv("APP_NAME", "NawalaSentinel — Multi-Operator Domain Block Monitor")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("true", "1", "t")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "nawalasentinel-secret-key-3908420934")
    
    # Mode Pengujian Lokal / Simulasi (Memungkinkan pengujian seluruh status di localhost tanpa modem 4G fisik)
    LOCAL_TEST_MODE: bool = os.getenv("LOCAL_TEST_MODE", "False").lower() in ("true", "1", "t")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/nawalasentinel.db")

    # Scheduler & Parallel Concurrency
    CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "5"))
    CONCURRENT_CHECKS: int = int(os.getenv("CONCURRENT_CHECKS", "30"))
    
    # Chunked Batching (Sesi Pembagian Pengecekan per Batch)
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "2000")) # Contoh 2.000 domain per sesi
    CHUNK_DELAY_SECONDS: float = float(os.getenv("CHUNK_DELAY_SECONDS", "5.0")) # Jeda jeda antar sesi dalam detik

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_ALERTS_ENABLED: bool = os.getenv("TELEGRAM_ALERTS_ENABLED", "False").lower() in ("true", "1", "t")
    
    # Generic Webhook
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_ALERTS_ENABLED: bool = os.getenv("WEBHOOK_ALERTS_ENABLED", "False").lower() in ("true", "1", "t")
    
    # Operator DNS Server List
    OPERATOR_DNS = {
        "Telkomsel": [ip.strip() for ip in os.getenv("TELKOMSEL_DNS", "180.250.192.9,180.250.192.10").split(",") if ip.strip()],
        "XL": [ip.strip() for ip in os.getenv("XL_DNS", "202.152.165.9,202.152.165.10").split(",") if ip.strip()],
        "IM3": [ip.strip() for ip in os.getenv("IM3_DNS", "202.155.0.10,202.155.0.15").split(",") if ip.strip()],
        "Tri": [ip.strip() for ip in os.getenv("TRI_DNS", "114.121.17.2,114.121.17.3").split(",") if ip.strip()],
    }
    
    # Operator Proxies (Opsional)
    OPERATOR_PROXIES = {
        "Telkomsel": os.getenv("TELKOMSEL_PROXY", ""),
        "XL": os.getenv("XL_PROXY", ""),
        "IM3": os.getenv("IM3_PROXY", ""),
        "Tri": os.getenv("TRI_PROXY", ""),
    }

    # Public/Fallback DNS Resolver (Google / Cloudflare)
    PUBLIC_DNS = ["1.1.1.1", "8.8.8.8"]

    # Daftar IP Sinkhole / Blocked Response yang umum digunakan ISP Indonesia
    KNOWN_SINKHOLE_IPS = [
        "180.250.247.",  # Telkomsel Nawala/TrustPositif Sinkhole
        "180.250.",      # Telkomsel Range
        "180.240.",      # Telkom Range
        "118.98.",       # Telkomsel Sinkhole Range
        "202.152.165.",  # XL Block Sinkhole
        "112.215.",      # XL Sinkhole Range
        "36.86.",        # Indosat Ooredoo / IM3 Sinkhole Range
        "114.4.",        # Indosat Sinkhole Range
        "114.5.",        # Indosat Sinkhole Range
        "202.155.",      # Indosat DNS/Proxy Range
        "103.19.",       # Moratel / Smartfren Range
        "103.247.",      # Smartfren Sinkhole Range
        "180.131.",      # DNS Nawala Sinkhole IP Range
        "10.11.",        # Private ISP Sinkhole
        "10.19.",        # Private ISP Sinkhole
        "127.0.0.1",     # Loopback sinkhole
        "0.0.0.0",       # Null sinkhole
    ]

    # Signature Kata Kunci Blockpage Internet Positif pada HTTP HTML / Headers
    BLOCKPAGE_SIGNATURES = [
        "internetpositif",
        "internet positif",
        "internetpositif.id",
        "trustpositif",
        "trust positif",
        "trustpositif.komdigi.go.id",
        "pos-blokir",
        "siteblocked",
        "mercusuar",
        "uzone.id",
        "internetsehat",
        "nawala",
        "request rejected",
        "the requested url was rejected",
    ]

    # Signature Khusus Cloudflare & Browser Anti-Phishing Warnings
    PHISHING_SIGNATURES = [
        "suspected phishing",
        "reported for potential phishing",
        "phishing is when a site attempts to steal sensitive information",
        "deceptive site ahead",
        "the site ahead contains harmful programs",
        "peringatan: terindikasi phishing",
    ]

settings = Settings()
