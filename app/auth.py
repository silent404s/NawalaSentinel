import hashlib
import binascii
import os
import secrets
import json
import logging
from datetime import timedelta
from typing import Optional, List, Tuple

import pyotp
import qrcode
import qrcode.image.svg
from io import BytesIO

from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from app.database import get_db
from app.models import User, UserSession, LoginLog
from app.config import settings
from app.utils.timezone import now_jakarta_naive

logger = logging.getLogger("auth")

# ==========================================
# PASSWORD HASHING UTILITIES (PBKDF2 SHA256)
# ==========================================

def hash_password(password: str) -> str:
    """Hash password menggunakan PBKDF2 HMAC SHA256 dengan salt 60-byte & 100.000 iterasi."""
    salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
    pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    pwdhash = binascii.hexlify(pwdhash)
    return (salt + pwdhash).decode('ascii')


def verify_password(stored_password: str, provided_password: str) -> bool:
    """Verifikasi password terhadap hash tersimpan."""
    try:
        salt = stored_password[:64]
        stored_hash = stored_password[64:]
        pwdhash = hashlib.pbkdf2_hmac(
            'sha256', 
            provided_password.encode('utf-8'), 
            salt.encode('ascii'), 
            100000
        )
        pwdhash = binascii.hexlify(pwdhash).decode('ascii')
        return secrets.compare_digest(pwdhash, stored_hash)
    except Exception:
        return False


def generate_activation_token() -> str:
    """Generate token aktivasi unik seperti NS-8F3K9A."""
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    token = ''.join(secrets.choice(chars) for _ in range(6))
    return f"NS-{token}"


# ==========================================
# 2FA / TOTP & BACKUP CODES UTILITIES
# ==========================================

def generate_totp_secret() -> str:
    """Menghasilkan base32 secret key acak untuk Google Authenticator."""
    return pyotp.random_base32()


def get_totp_uri(username: str, secret: str) -> str:
    """Mendapatkan URI provisioning otpauth:// untuk QR code."""
    issuer = settings.APP_NAME.split("—")[0].strip() if "—" in settings.APP_NAME else "NawalaSentinel"
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def generate_qr_code_svg(uri: str) -> str:
    """Menghasilkan gambar QR code dalam format SVG XML string murni."""
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(uri, image_factory=factory, box_size=8, border=2)
    stream = BytesIO()
    img.save(stream)
    return stream.getvalue().decode("utf-8")


def verify_totp_code(secret: str, code: str) -> bool:
    """
    Verifikasi kode 6-digit TOTP Google Authenticator.
    Menggunakan valid_window=1 (mengizinkan jeda waktu +/- 30 detik untuk kompensasi clock drift).
    """
    if not secret or not code:
        return False
    clean_code = code.strip().replace(" ", "").replace("-", "")
    if len(clean_code) != 6 or not clean_code.isdigit():
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(clean_code, valid_window=1)


def generate_backup_codes(count: int = 8) -> Tuple[List[str], str]:
    """
    Menghasilkan daftar kode backup satu kali pakai (One-Time Recovery Codes).
    Return: (plain_codes: List[str], hashed_codes_json: str)
    Format: 'XXXX-XXXX'
    """
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    plain_codes = []
    hashed_codes = []

    for _ in range(count):
        part1 = ''.join(secrets.choice(chars) for _ in range(4))
        part2 = ''.join(secrets.choice(chars) for _ in range(4))
        code = f"{part1}-{part2}"
        plain_codes.append(code)

        # Hash code dengan SHA256 sebelum disimpan ke DB
        code_hash = hashlib.sha256(code.replace("-", "").upper().encode("utf-8")).hexdigest()
        hashed_codes.append(code_hash)

    return plain_codes, json.dumps(hashed_codes)


def verify_and_consume_backup_code(user: User, code: str) -> bool:
    """
    Verifikasi kode cadangan dan hapus kode yang sudah dipakai dari daftar user.
    """
    if not user.backup_codes or not code:
        return False

    clean_code = code.strip().replace("-", "").replace(" ", "").upper()
    code_hash = hashlib.sha256(clean_code.encode("utf-8")).hexdigest()

    try:
        current_hashes = json.loads(user.backup_codes)
        if not isinstance(current_hashes, list):
            return False

        if code_hash in current_hashes:
            # Hapus hash yang cocok (single-use)
            current_hashes.remove(code_hash)
            user.backup_codes = json.dumps(current_hashes)
            return True
    except Exception as e:
        logger.error(f"Error parsing backup codes for user {user.username}: {e}")

    return False


from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

def generate_temp_token(user_id: int) -> str:
    """Generate signed temporary token for 2FA verification step (valid 5 minutes)."""
    s = URLSafeTimedSerializer(settings.SECRET_KEY)
    return s.dumps({"user_id": user_id}, salt="2fa-auth")


def verify_temp_token(token: str, max_age: int = 300) -> Optional[int]:
    """Verify signed temporary token and return user_id if valid and not expired."""
    s = URLSafeTimedSerializer(settings.SECRET_KEY)
    try:
        data = s.loads(token, salt="2fa-auth", max_age=max_age)
        return data.get("user_id")
    except (SignatureExpired, BadSignature):
        return None


# ==========================================
# DEVICE & CLIENT INFO HELPERS
# ==========================================

def get_client_ip(request: Request) -> str:
    """Mengekstrak IP address asli klien, mendukung reverse proxy/Cloudflare."""
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    x_forwarded = request.headers.get("x-forwarded-for")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()

    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def parse_device_info(user_agent: str) -> str:
    """
    Parsing sederhana & akurat untuk ringkasan Browser & OS dari User-Agent.
    Contoh output: "Chrome 120 (Windows 10)" atau "Safari (iOS)"
    """
    if not user_agent:
        return "Unknown Device"

    ua = user_agent.lower()

    # Deteksi Browser
    browser = "Browser Lain"
    if "edg/" in ua:
        browser = "Microsoft Edge"
    elif "opr/" in ua or "opera" in ua:
        browser = "Opera"
    elif "chrome/" in ua and "chromium" not in ua:
        browser = "Google Chrome"
    elif "firefox/" in ua:
        browser = "Mozilla Firefox"
    elif "safari/" in ua and "chrome" not in ua:
        browser = "Apple Safari"

    # Deteksi OS
    os_name = "Unknown OS"
    if "windows nt 10.0" in ua:
        os_name = "Windows 10/11"
    elif "windows nt 6.3" in ua:
        os_name = "Windows 8.1"
    elif "windows nt 6.1" in ua:
        os_name = "Windows 7"
    elif "windows" in ua:
        os_name = "Windows"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua or "ipod" in ua:
        os_name = "iOS"
    elif "macintosh" in ua or "mac os x" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"

    return f"{browser} ({os_name})"


# ==========================================
# BRUTE FORCE & LOCKOUT MANAGEMENT
# ==========================================

def is_user_locked(user: User) -> Tuple[bool, int]:
    """
    Cek apakah akun pengguna sedang dalam status terkunci sementara (Lockout).
    Return: (is_locked: bool, remaining_seconds: int)
    """
    if user.locked_until:
        now = now_jakarta_naive()
        if user.locked_until > now:
            remaining = int((user.locked_until - now).total_seconds())
            return True, max(1, remaining)
        else:
            # Masa lockout sudah habis, reset otomatis
            user.locked_until = None
            user.failed_login_attempts = 0
    return False, 0


async def record_login_failure(
    db: AsyncSession,
    user: Optional[User],
    username: str,
    ip: str,
    user_agent: str,
    reason: str,
    is_2fa: bool = False
):
    """
    Mencatat percobaan login / 2FA gagal, menambah counter lockout, dan menyimpan audit log.
    """
    event_type = "2FA_FAILED" if is_2fa else "LOGIN_FAILED"
    device_info = parse_device_info(user_agent)

    if user:
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.locked_until = now_jakarta_naive() + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
            reason = f"{reason} - Akun dikunci sementara selama {settings.LOCKOUT_DURATION_MINUTES} menit karena {user.failed_login_attempts} kali gagal berturut-turut."
            logger.warning(f"🚨 Akun {username} dikunci sementara akibat berulang kali gagal login dari IP {ip}.")

    log = LoginLog(
        user_id=user.id if user else None,
        username=username,
        event_type=event_type,
        ip_address=ip,
        user_agent=user_agent,
        device_info=device_info,
        reason=reason,
        created_at=now_jakarta_naive()
    )
    db.add(log)
    await db.commit()


async def record_login_success(
    db: AsyncSession,
    user: User,
    ip: str,
    user_agent: str
):
    """
    Mereset counter kegagalan dan mencatat event LOGIN_SUCCESS ke tabel audit log.
    """
    user.failed_login_attempts = 0
    user.locked_until = None

    device_info = parse_device_info(user_agent)
    log = LoginLog(
        user_id=user.id,
        username=user.username,
        event_type="LOGIN_SUCCESS",
        ip_address=ip,
        user_agent=user_agent,
        device_info=device_info,
        reason="Login berhasil dengan verifikasi 2FA",
        created_at=now_jakarta_naive()
    )
    db.add(log)
    await db.commit()


# ==========================================
# SINGLE ACTIVE SESSION MANAGEMENT
# ==========================================

async def create_user_session(
    db: AsyncSession,
    user: User,
    request: Request,
    remember_me: bool = False
) -> UserSession:
    """
    Membuat sesi login aktif baru untuk pengguna.
    PRINSIP UTAMA: 1 Akun = 1 Sesi Aktif.
    Seluruh sesi aktif sebelumnya milik akun ini akan otomatis di-nonaktifkan (is_active = False).
    """
    # 1. Nonaktifkan seluruh sesi aktif sebelumnya
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.is_active == True)
        .values(is_active=False)
    )

    # 2. Buat session token baru yang aman & unik
    session_token = secrets.token_urlsafe(48)
    now = now_jakarta_naive()
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")
    device_info = parse_device_info(ua)

    if remember_me:
        expires_at = now + timedelta(days=7)
    else:
        expires_at = now + timedelta(hours=settings.SESSION_MAX_LIFETIME_HOURS)

    new_session = UserSession(
        user_id=user.id,
        session_token=session_token,
        ip_address=ip,
        user_agent=ua,
        device_info=device_info,
        created_at=now,
        last_activity_at=now,
        expires_at=expires_at,
        is_active=True
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    logger.info(f"✅ Sesi baru dibuat untuk user {user.username} (Token: {session_token[:8]}...) dari {ip} [{device_info}]")
    return new_session


async def invalidate_all_user_sessions(db: AsyncSession, user_id: int, reason: str = "Logout Semua Sesi"):
    """
    Memutus seluruh sesi aktif untuk akun tertentu (Logout Semua Sesi / Perubahan Keamanan).
    """
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.is_active == True)
        .values(is_active=False)
    )
    await db.commit()
    logger.info(f"🚪 Seluruh sesi untuk user ID {user_id} telah di-invalidate ({reason}).")


async def get_user_from_session_token(db: AsyncSession, token: str) -> Optional[Tuple[User, UserSession]]:
    """
    Mencari dan memvalidasi sesi aktif berdasarkan session_token.
    Memeriksa:
    1. is_active == True
    2. expires_at > now
    3. Idle Timeout (selisih last_activity_at)
    Jika valid, memperbarui last_activity_at.
    """
    if not token:
        return None

    stmt = select(UserSession).where(UserSession.session_token == token, UserSession.is_active == True)
    res = await db.execute(stmt)
    session_obj = res.scalar_one_or_none()

    if not session_obj:
        return None

    now = now_jakarta_naive()

    # Cek masa kedaluwarsa absolut (24 jam / 7 hari)
    if session_obj.expires_at and session_obj.expires_at <= now:
        session_obj.is_active = False
        await db.commit()
        return None

    # Cek batas waktu idle / inaktivitas (default: 60 menit)
    if session_obj.last_activity_at:
        idle_seconds = (now - session_obj.last_activity_at).total_seconds()
        if idle_seconds > (settings.SESSION_IDLE_TIMEOUT_MINUTES * 60):
            session_obj.is_active = False
            await db.commit()
            logger.info(f"⌛ Sesi {token[:8]}... berakhir karena idle {int(idle_seconds/60)} menit.")
            return None

    # Sesi valid: perbarui last_activity_at
    session_obj.last_activity_at = now
    await db.commit()

    # Ambil user terkait
    user_stmt = select(User).where(User.id == session_obj.user_id, User.is_active == True)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()

    if not user:
        session_obj.is_active = False
        await db.commit()
        return None

    return user, session_obj


# ==========================================
# FASTAPI DEPENDENCIES
# ==========================================

async def get_current_user_optional(request: Request, db: AsyncSession = Depends(get_db)) -> Optional[User]:
    """Mengambil user saat ini jika ada sesi valid, tanpa memicu error 401."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        # Cek Authorization Header (Bearer token)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        result = await get_user_from_session_token(db, token)
        if result:
            return result[0]
    return None


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """
    Dependency wajib autentikasi untuk Dashboard & API.
    Memeriksa session_token dari cookie HttpOnly.
    TIDAK ADA bypass otomatis di DEBUG mode.
    """
    user = await get_current_user_optional(request, db)
    if user:
        return user

    # Jika request meminta HTML (browser browsing), tandai detail khusus agar dapat di-redirect ke /login
    accept_header = request.headers.get("accept", "")
    if "text/html" in accept_header:
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED_HTML")

    raise HTTPException(status_code=401, detail="Not authenticated. Please login.")


async def get_current_superadmin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency wajib otorisasi role SUPERADMIN."""
    if current_user.role != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Akses ditolak. Memerlukan hak akses Superadmin.")
    return current_user
