import io
import csv
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.future import select
from sqlalchemy import func, delete, desc, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Domain, CheckResult, StatusLog, AppSetting, User, UserSession, LoginLog, Tenant, BotActivityLog
from app.config import settings
from app.auth import (
    get_current_user,
    get_current_user_optional,
    verify_password,
    generate_totp_secret,
    get_totp_uri,
    generate_qr_code_svg,
    verify_totp_code,
    generate_backup_codes,
    verify_and_consume_backup_code,
    generate_temp_token,
    verify_temp_token,
    is_user_locked,
    record_login_failure,
    record_login_success,
    create_user_session,
    invalidate_all_user_sessions,
    get_client_ip,
    parse_device_info,
)
from app.checker import checker_engine
from app.notifier import notifier, TelegramNotifier
from app.scheduler import run_full_domain_scan, get_next_run_time_seconds, reschedule_job
from app.utils.timezone import format_wib, format_time_wib, now_jakarta_naive
from app.updater import system_updater

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["wib_datetime"] = format_wib
templates.env.filters["wib_time"] = format_time_wib


# Helper untuk normalisasi domain name / URL
def normalize_domain(domain_str: str) -> str:
    domain_str = domain_str.strip().lower()
    if domain_str.startswith("http://"):
        domain_str = domain_str[7:]
    elif domain_str.startswith("https://"):
        domain_str = domain_str[8:]
    # Hapus trailing slash saja, pertahankan path (misal: vpngwnlog.com/login)
    domain_str = domain_str.rstrip("/")
    return domain_str.strip()


# ==========================================
# WEB DASHBOARD UI ROUTES (Jinja2 Templates)
# ==========================================

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Halaman Login & Verifikasi 2FA.
    """
    user = await get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "app_name": settings.APP_NAME,
        }
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Halaman Utama Web Dashboard Monitoring.
    """
    # Stats
    total_domains = (await db.execute(select(func.count(Domain.id)))).scalar_one()
    normal_count = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "NORMAL"))).scalar_one()
    blocked_count = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "BLOCKED"))).scalar_one()
    phishing_count = (await db.execute(select(func.count(Domain.id)).where(Domain.cf_status == "PHISHING"))).scalar_one()
    mixed_count = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "MIXED"))).scalar_one()
    unchecked_count = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "UNCHECKED"))).scalar_one()
    block_ratio = round((blocked_count / total_domains * 100), 1) if total_domains > 0 else 0.0

    # Per-operator Blocked Stats
    op_blocked = {}
    for op in ["Telkomsel", "XL", "IM3", "Tri"]:
        count = (await db.execute(
            select(func.count(CheckResult.id))
            .where(CheckResult.operator == op, CheckResult.status == "BLOCKED")
        )).scalar_one()
        op_blocked[op] = count

    # Domains sorted A-Z (All domains for all-in-one Dashboard)
    domains_result = await db.execute(
        select(Domain).options(selectinload(Domain.tenant)).order_by(Domain.name.asc())
    )
    domains = domains_result.scalars().all()

    # Operator check results for dashboard preview
    domain_ids = [d.id for d in domains]
    op_results_map = {}
    if domain_ids:
        res_stmt = select(CheckResult).where(CheckResult.domain_id.in_(domain_ids))
        res = await db.execute(res_stmt)
        for r in res.scalars().all():
            if r.domain_id not in op_results_map:
                op_results_map[r.domain_id] = {}
            op_results_map[r.domain_id][r.operator] = r

    # Recent Status Logs
    logs_result = await db.execute(
        select(StatusLog).order_by(desc(StatusLog.timestamp)).limit(10)
    )
    recent_logs = logs_result.scalars().all()

    # Unique categories and domain counts
    cat_stmt = select(Domain.category, func.count(Domain.id)).group_by(Domain.category).order_by(Domain.category.asc())
    cat_res = await db.execute(cat_stmt)
    categories = [{"name": row[0] or "General", "count": row[1]} for row in cat_res.all()]

    next_check_seconds = get_next_run_time_seconds()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current_user": current_user,
            "active_page": "dashboard",
            "stats": {
                "total": total_domains,
                "normal": normal_count,
                "blocked": blocked_count,
                "phishing": phishing_count,
                "mixed": mixed_count,
                "unchecked": unchecked_count,
                "block_ratio": block_ratio,
                "op_blocked": op_blocked,
            },
            "domains": domains,
            "categories": categories,
            "op_results_map": op_results_map,
            "recent_logs": recent_logs,
            "next_check_seconds": next_check_seconds,
            "check_interval_minutes": settings.CHECK_INTERVAL_MINUTES,
            "app_name": settings.APP_NAME,
        }
    )



@router.get("/domains")
async def domains_page(request: Request, current_user: User = Depends(get_current_user)):
    """
    Halaman Kelola Domain disatukan langsung ke Dashboard utama (All-in-One).
    """
    return RedirectResponse(url="/", status_code=302)


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Halaman Riwayat Log: Log Aktivitas Bot Telegram & Riwayat Perubahan Status Operator ISP.
    """
    # 1. Ambil 200 log aktivitas bot Telegram terbaru (Audit Trail)
    stmt_bot = (
        select(BotActivityLog)
        .options(selectinload(BotActivityLog.tenant))
        .order_by(desc(BotActivityLog.created_at))
        .limit(200)
    )
    res_bot = await db.execute(stmt_bot)
    bot_logs = res_bot.scalars().all()

    # Hitung ringkasan aktivitas bot
    total_bot_logs = len(bot_logs)
    count_add = sum(1 for b in bot_logs if b.command == "/add")
    count_del = sum(1 for b in bot_logs if b.command == "/del")
    count_replace = sum(1 for b in bot_logs if b.command == "/replace")

    # 2. Ambil 100 log perubahan status operator ISP
    stmt_status = select(StatusLog).order_by(desc(StatusLog.timestamp)).limit(100)
    res_status = await db.execute(stmt_status)
    status_logs = res_status.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            "current_user": current_user,
            "active_page": "logs",
            "bot_logs": bot_logs,
            "total_bot_logs": total_bot_logs,
            "count_add": count_add,
            "count_del": count_del,
            "count_replace": count_replace,
            "logs": status_logs,
            "app_name": settings.APP_NAME,
        }
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Halaman Pengaturan Bot Telegram, Interval, Proxy, Pembaruan Sistem, & Keamanan 2FA / Sesi.
    """
    version_info = await system_updater.get_version_info()

    # Ambil sesi aktif pengguna saat ini
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    active_session = None
    if token:
        sess_stmt = select(UserSession).where(UserSession.session_token == token, UserSession.is_active == True)
        active_session = (await db.execute(sess_stmt)).scalar_one_or_none()

    # Ambil 15 riwayat aktivitas login terbaru
    if current_user.role == "SUPERADMIN":
        log_stmt = select(LoginLog).order_by(desc(LoginLog.created_at)).limit(15)
    else:
        log_stmt = select(LoginLog).where(LoginLog.user_id == current_user.id).order_by(desc(LoginLog.created_at)).limit(15)
    recent_login_logs = (await db.execute(log_stmt)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "current_user": current_user,
            "active_session": active_session,
            "recent_login_logs": recent_login_logs,
            "active_page": "settings",
            "settings": settings,
            "version_info": version_info,
            "app_name": settings.APP_NAME,
        }
    )


@router.get("/docs", response_class=HTMLResponse)
@router.get("/panduan", response_class=HTMLResponse)
async def docs_page(request: Request, current_user: User = Depends(get_current_user)):
    """
    Halaman Dokumentasi, Cara Kerja Sistem, & Tutorial Lengkap.
    """
    return templates.TemplateResponse(
        request=request,
        name="docs.html",
        context={
            "current_user": current_user,
            "active_page": "docs",
            "settings": settings,
            "app_name": settings.APP_NAME,
        }
    )


@router.get("/api/system/version")
async def api_system_version():
    """
    Mengambil status versi git saat ini.
    """
    return await system_updater.get_version_info()


@router.post("/api/system/update")
async def api_system_update(branch: Optional[str] = Form(None), current_user: User = Depends(get_current_user)):
    """
    Menjalankan proses update otomatis aman (Safe Zero-Downtime Pipeline) langsung dari GitHub.
    """
    if current_user.role != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Akses ditolak. Hanya Superadmin yang dapat memperbarui sistem.")
    res = await system_updater.execute_safe_update(branch=branch or "main")
    return JSONResponse(res)



# ==========================================
# REST API ENDPOINTS
# ==========================================

@router.post("/api/auth/login")
@router.post("/api/login")
async def api_auth_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember_me: bool = Form(False),
    db: AsyncSession = Depends(get_db)
):
    """
    Tahap 1 Login: Verifikasi Username, Password, dan Status Lockout.
    Mengembalikan instruksi REQUIRE_2FA_SETUP atau REQUIRE_2FA_VERIFY.
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    stmt = select(User).where(User.username == username)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        await record_login_failure(db, None, username, ip, ua, "Username tidak terdaftar", is_2fa=False)
        return JSONResponse({"status": "error", "message": "Username atau Password salah!"}, status_code=401)

    # Cek apakah akun sedang dalam status lockout sementara
    is_locked, remaining_seconds = is_user_locked(user)
    if is_locked:
        minutes = int((remaining_seconds + 59) // 60)
        return JSONResponse(
            {"status": "error", "message": f"Akun terkunci sementara akibat terlalu banyak percobaan gagal. Silakan coba lagi dalam {minutes} menit ({remaining_seconds} detik)."},
            status_code=429
        )

    # Verifikasi Password
    if not verify_password(user.password, password):
        await record_login_failure(db, user, username, ip, ua, "Password salah", is_2fa=False)
        return JSONResponse({"status": "error", "message": "Username atau Password salah!"}, status_code=401)

    if not user.is_active:
        return JSONResponse({"status": "error", "message": "Akun Anda telah dinonaktifkan. Hubungi Administrator."}, status_code=403)

    temp_token = generate_temp_token(user.id)

    # Kasus A: Pengguna belum mengaktifkan 2FA (Setup Wajib Pertama Kali)
    if not user.is_totp_enabled or not user.totp_secret:
        secret = generate_totp_secret()
        user.totp_secret = secret
        uri = get_totp_uri(user.username, secret)
        qr_svg = generate_qr_code_svg(uri)
        plain_codes, hashed_codes_json = generate_backup_codes(8)
        user.backup_codes = hashed_codes_json
        await db.commit()

        return JSONResponse({
            "status": "REQUIRE_2FA_SETUP",
            "message": "Silakan konfigurasikan Google Authenticator dan simpan kode cadangan Anda.",
            "temp_token": temp_token,
            "secret": secret,
            "qr_svg": qr_svg,
            "backup_codes": plain_codes
        })

    # Kasus B: Pengguna sudah mengaktifkan 2FA -> minta 6-digit TOTP
    return JSONResponse({
        "status": "REQUIRE_2FA_VERIFY",
        "message": "Masukkan 6-digit kode dari Google Authenticator Anda.",
        "temp_token": temp_token
    })


@router.post("/api/auth/setup-2fa")
async def api_auth_setup_2fa(
    request: Request,
    temp_token: str = Form(...),
    code: str = Form(...),
    remember_me: bool = Form(False),
    db: AsyncSession = Depends(get_db)
):
    """
    Konfirmasi Setup 2FA Pertama Kali: Verifikasi kode TOTP awal dan aktifkan 2FA secara permanen.
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    user_id = verify_temp_token(temp_token)
    if not user_id:
        return JSONResponse({"status": "error", "message": "Sesi verifikasi telah kedaluwarsa. Silakan login kembali."}, status_code=400)

    stmt = select(User).where(User.id == user_id, User.is_active == True)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user or not user.totp_secret:
        return JSONResponse({"status": "error", "message": "Data pengguna tidak valid."}, status_code=400)

    if not verify_totp_code(user.totp_secret, code):
        await record_login_failure(db, user, user.username, ip, ua, "Kode 2FA setup tidak cocok", is_2fa=True)
        return JSONResponse({"status": "error", "message": "Kode 2FA salah atau jam di perangkat Anda belum sinkron."}, status_code=400)

    # Aktifkan 2FA
    user.is_totp_enabled = True

    # Buat single session (otomatis menonaktifkan sesi lama)
    session = await create_user_session(db, user, request, remember_me=remember_me)
    await record_login_success(db, user, ip, ua)

    response = JSONResponse({"status": "success", "message": "2FA berhasil diaktifkan! Login sukses."})
    max_age = 7 * 86400 if remember_me else settings.SESSION_MAX_LIFETIME_HOURS * 3600
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session.session_token,
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG,
        max_age=max_age
    )
    return response


@router.post("/api/auth/verify-2fa")
async def api_auth_verify_2fa(
    request: Request,
    temp_token: str = Form(...),
    code: str = Form(...),
    is_backup: bool = Form(False),
    remember_me: bool = Form(False),
    db: AsyncSession = Depends(get_db)
):
    """
    Tahap 2 Login: Verifikasi 6-Digit TOTP Google Authenticator atau Kode Cadangan (Backup Code).
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    user_id = verify_temp_token(temp_token)
    if not user_id:
        return JSONResponse({"status": "error", "message": "Sesi verifikasi telah kedaluwarsa. Silakan login kembali."}, status_code=400)

    stmt = select(User).where(User.id == user_id, User.is_active == True)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        return JSONResponse({"status": "error", "message": "Pengguna tidak ditemukan."}, status_code=400)

    # Cek lockout
    is_locked, remaining_seconds = is_user_locked(user)
    if is_locked:
        minutes = int((remaining_seconds + 59) // 60)
        return JSONResponse(
            {"status": "error", "message": f"Akun terkunci. Coba lagi dalam {minutes} menit ({remaining_seconds} detik)."},
            status_code=429
        )

    # Verifikasi OTP atau Backup Code
    if is_backup:
        is_valid = verify_and_consume_backup_code(user, code)
        fail_msg = "Kode cadangan salah atau sudah pernah digunakan!"
    else:
        is_valid = verify_totp_code(user.totp_secret or "", code)
        fail_msg = "Kode 2FA salah! Pastikan jam di ponsel Anda akurat."

    if not is_valid:
        await record_login_failure(db, user, user.username, ip, ua, fail_msg, is_2fa=True)
        return JSONResponse({"status": "error", "message": fail_msg}, status_code=400)

    # Buat single session (otomatis mengakhiri sesi lain akun ini)
    session = await create_user_session(db, user, request, remember_me=remember_me)
    await record_login_success(db, user, ip, ua)

    response = JSONResponse({"status": "success", "message": "Login berhasil!"})
    max_age = 7 * 86400 if remember_me else settings.SESSION_MAX_LIFETIME_HOURS * 3600
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session.session_token,
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG,
        max_age=max_age
    )
    return response


@router.post("/api/auth/logout")
@router.get("/logout")
async def api_auth_logout(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Logout: Memutus sesi aktif di database, mencatat audit log, dan menghapus cookie.
    """
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    if token:
        stmt = select(UserSession).where(UserSession.session_token == token)
        res = await db.execute(stmt)
        sess = res.scalar_one_or_none()
        if sess:
            sess.is_active = False
            log = LoginLog(
                user_id=sess.user_id,
                event_type="LOGOUT",
                ip_address=ip,
                user_agent=ua,
                device_info=sess.device_info,
                reason="Pengguna melakukan logout normal",
                created_at=now_jakarta_naive()
            )
            db.add(log)
            await db.commit()

    response = RedirectResponse(url="/login?logged_out=1", status_code=302)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return response


@router.post("/api/auth/logout-all")
async def api_auth_logout_all(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Logout Semua Sesi: Memutus seluruh sesi aktif akun ini di seluruh perangkat/browser.
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    await invalidate_all_user_sessions(db, current_user.id, reason="Logout Semua Sesi via Pengaturan")

    log = LoginLog(
        user_id=current_user.id,
        username=current_user.username,
        event_type="SESSIONS_REVOKED",
        ip_address=ip,
        user_agent=ua,
        device_info=parse_device_info(ua),
        reason="Pengguna memutus seluruh sesi aktif di semua perangkat",
        created_at=now_jakarta_naive()
    )
    db.add(log)
    await db.commit()

    response = JSONResponse({"status": "success", "message": "Seluruh sesi aktif akun Anda telah diakhiri. Silakan login kembali."})
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return response


@router.post("/api/auth/reset-2fa")
async def api_auth_reset_2fa(
    request: Request,
    current_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reset 2FA: Menghapus konfigurasi 2FA yang ada dan memutus seluruh sesi aktif (memerlukan password).
    """
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")

    if not verify_password(current_user.password, current_password):
        return JSONResponse({"status": "error", "message": "Password saat ini salah! Reset 2FA dibatalkan."}, status_code=400)

    # Invalidate 2FA
    current_user.is_totp_enabled = False
    current_user.totp_secret = None
    current_user.backup_codes = None

    # Invalidate all sessions
    await invalidate_all_user_sessions(db, current_user.id, reason="Reset 2FA")

    log = LoginLog(
        user_id=current_user.id,
        username=current_user.username,
        event_type="2FA_RESET",
        ip_address=ip,
        user_agent=ua,
        device_info=parse_device_info(ua),
        reason="Pengguna mereset konfigurasi Google Authenticator 2FA",
        created_at=now_jakarta_naive()
    )
    db.add(log)
    await db.commit()

    response = JSONResponse({"status": "success", "message": "2FA berhasil direset. Silakan login kembali untuk konfigurasi ulang."})
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return response


@router.get("/api/auth/login-history")
async def api_auth_login_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mengambil riwayat log aktivitas login pengguna (Audit Log).
    """
    if current_user.role == "SUPERADMIN":
        stmt = select(LoginLog).order_by(desc(LoginLog.created_at)).limit(25)
    else:
        stmt = select(LoginLog).where(LoginLog.user_id == current_user.id).order_by(desc(LoginLog.created_at)).limit(25)

    res = await db.execute(stmt)
    logs = res.scalars().all()
    return JSONResponse({"status": "success", "logs": [l.to_dict() for l in logs]})


@router.get("/api/auth/active-session")
async def api_auth_active_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mengambil informasi sesi aktif saat ini.
    """
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    sess_info = None
    if token:
        stmt = select(UserSession).where(UserSession.session_token == token, UserSession.is_active == True)
        sess = (await db.execute(stmt)).scalar_one_or_none()
        if sess:
            sess_info = sess.to_dict()
    return JSONResponse({"status": "success", "session": sess_info})


@router.get("/api/version")
async def api_version():
    """
    Endpoint pengecekan status & versi sistem backend.
    """
    return JSONResponse({
        "app": settings.APP_NAME,
        "version": "2.0.0",
        "status": "online"
    })

@router.get("/api/stats")
async def api_stats(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    API statistik live.
    """
    total = (await db.execute(select(func.count(Domain.id)))).scalar_one()
    normal = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "NORMAL"))).scalar_one()
    blocked = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "BLOCKED"))).scalar_one()
    phishing = (await db.execute(select(func.count(Domain.id)).where(Domain.cf_status == "PHISHING"))).scalar_one()
    mixed = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "MIXED"))).scalar_one()

    return {
        "total": total,
        "normal": normal,
        "blocked": blocked,
        "phishing": phishing,
        "mixed": mixed,
        "next_check_seconds": get_next_run_time_seconds(),
        "interval_minutes": settings.CHECK_INTERVAL_MINUTES,
    }



@router.post("/api/domains/add")
async def api_add_domains(raw_domains: str = Form(...), category: str = Form("General"), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Penambahan domain langsung dari dashboard admin dinonaktifkan karena sistem murni untuk pelanggan.
    """
    return JSONResponse(
        {
            "status": "error", 
            "message": "Penambahan domain langsung dari dashboard admin dinonaktifkan. Sistem ini murni untuk pelanggan (domain didaftarkan oleh masing-masing grup pelanggan via /add di bot Telegram)."
        }, 
        status_code=403
    )


@router.post("/api/domains/import")
async def api_import_domains(file: UploadFile = File(...), category: str = Form("General"), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Import domain langsung dari dashboard admin dinonaktifkan karena sistem murni untuk pelanggan.
    """
    return JSONResponse(
        {
            "status": "error", 
            "message": "Import domain langsung dari dashboard admin dinonaktifkan. Sistem ini murni untuk pelanggan (domain didaftarkan oleh masing-masing grup pelanggan via /add di bot Telegram)."
        }, 
        status_code=403
    )


@router.post("/api/domains/{domain_id}/delete")
async def api_delete_domain(domain_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Hapus domain spesifik dari database.
    """
    stmt = select(Domain).where(Domain.id == domain_id)
    res = await db.execute(stmt)
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Domain tidak ditemukan")
    if d.tenant_id is not None:
        raise HTTPException(
            status_code=403, 
            detail="Domain ini milik grup pelanggan (tenant). Hanya anggota grup yang dapat menghapus domain ini melalui bot Telegram (/del atau /replace)."
        )
    if current_user.role != "SUPERADMIN" and d.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Akses ditolak")

    await db.execute(delete(Domain).where(Domain.id == domain_id))
    await db.commit()
    return JSONResponse({"status": "success", "message": "Domain berhasil dihapus"})


@router.post("/api/domains/clear-all")
async def api_clear_all_domains(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Hapus seluruh domain non-tenant (hanya milik admin / umum), riwayat log, dan hasil pengecekan dari database.
    Domain milik grup pelanggan (tenant) di Telegram dilindungi dan tidak akan dihapus.
    """
    if current_user.role == "SUPERADMIN":
        admin_domains_stmt = select(Domain.id).where(Domain.tenant_id.is_(None))
        admin_domain_ids = [row[0] for row in (await db.execute(admin_domains_stmt)).all()]
        if admin_domain_ids:
            await db.execute(delete(CheckResult).where(CheckResult.domain_id.in_(admin_domain_ids)))
            await db.execute(delete(StatusLog).where(StatusLog.domain_id.in_(admin_domain_ids)))
            await db.execute(delete(Domain).where(Domain.id.in_(admin_domain_ids)))
    else:
        user_domains_stmt = select(Domain.id).where(Domain.user_id == current_user.id, Domain.tenant_id.is_(None))
        user_domain_ids = [row[0] for row in (await db.execute(user_domains_stmt)).all()]
        if user_domain_ids:
            await db.execute(delete(CheckResult).where(CheckResult.domain_id.in_(user_domain_ids)))
            await db.execute(delete(StatusLog).where(StatusLog.domain_id.in_(user_domain_ids)))
            await db.execute(delete(Domain).where(Domain.id.in_(user_domain_ids)))

    await db.commit()
    return JSONResponse({"status": "success", "message": "Seluruh domain non-tenant dan riwayat pemantauan berhasil dihapus!"})


@router.post("/api/domains/{domain_id}/category")
async def api_update_domain_category(
    domain_id: int,
    category: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Ubah nama kategori untuk satu domain spesifik.
    """
    stmt = select(Domain).where(Domain.id == domain_id)
    res = await db.execute(stmt)
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Domain tidak ditemukan")
    if d.tenant_id is not None:
        raise HTTPException(
            status_code=403, 
            detail="Domain ini milik grup pelanggan (tenant). Kategori domain tenant tidak dapat diubah dari dashboard."
        )
    if current_user.role != "SUPERADMIN" and d.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Akses ditolak")

    cat_clean = category.strip() or "General"
    d.category = cat_clean
    await db.commit()
    return JSONResponse({
        "status": "success",
        "message": f"Kategori domain '{d.name}' berhasil diubah ke '{cat_clean}'.",
        "domain_id": domain_id,
        "category": cat_clean
    })


@router.post("/api/categories/rename")
async def api_rename_category(
    old_category: str = Form(...),
    new_category: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Ubah / rename nama kategori secara massal pada semua domain non-tenant.
    """
    old_cat = old_category.strip()
    new_cat = new_category.strip()
    if not old_cat or not new_cat:
        return JSONResponse({"status": "error", "message": "Nama kategori lama dan baru harus diisi!"}, status_code=400)

    # Lindungi domain milik tenant agar tidak ikut ter-rename
    stmt = update(Domain).where(Domain.category == old_cat, Domain.tenant_id.is_(None))
    if current_user.role != "SUPERADMIN":
        stmt = stmt.where(Domain.user_id == current_user.id)
    stmt = stmt.values(category=new_cat)
    res = await db.execute(stmt)
    await db.commit()
    updated_count = res.rowcount

    return JSONResponse({
        "status": "success",
        "message": f"Berhasil mengubah nama kategori '{old_cat}' menjadi '{new_cat}' pada {updated_count} domain.",
        "updated": updated_count,
        "old_category": old_cat,
        "new_category": new_cat
    })


@router.get("/api/categories")
async def api_get_categories(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Mendapatkan daftar seluruh kategori dan jumlah domain di dalamnya.
    """
    cat_stmt = select(Domain.category, func.count(Domain.id)).group_by(Domain.category).order_by(Domain.category.asc())
    cat_res = await db.execute(cat_stmt)
    categories = [{"name": row[0] or "General", "count": row[1]} for row in cat_res.all()]
    return JSONResponse({"status": "success", "categories": categories})


@router.post("/api/check-now")
async def api_check_now(current_user: User = Depends(get_current_user)):
    """
    Pemicu manual untuk pengecekan langsung seluruh domain di latar belakang.
    """
    import asyncio
    asyncio.create_task(run_full_domain_scan())
    return JSONResponse({"status": "success", "message": "Pengecekan massal telah dimulai di latar belakang!"})


@router.post("/api/check-domain/{domain_id}")
async def api_check_single_domain(domain_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Pengecekan manual instan untuk 1 domain spesifik.
    """
    stmt = select(Domain).where(Domain.id == domain_id)
    res = await db.execute(stmt)
    domain_obj = res.scalar_one_or_none()

    if not domain_obj:
        raise HTTPException(status_code=404, detail="Domain tidak ditemukan")

    # Jalankan pengecekan 4 operator & Cloudflare
    check_res = await checker_engine.check_domain_all_operators(domain_obj.name)
    
    # Simpan hasil
    domain_obj.overall_status = check_res["overall_status"]
    domain_obj.cf_status = check_res.get("cf_status", "CLEAN")
    domain_obj.cf_reason = check_res.get("cf_reason", "")
    domain_obj.last_checked_at = now_jakarta_naive()

    # Update CheckResult per operator
    for op_name, op_res in check_res["operator_results"].items():
        existing_stmt = select(CheckResult).where(CheckResult.domain_id == domain_id, CheckResult.operator == op_name)
        existing_res = await db.execute(existing_stmt)
        existing_obj = existing_res.scalar_one_or_none()

        if existing_obj:
            existing_obj.status = op_res["status"]
            existing_obj.resolved_ips = op_res["resolved_ips"]
            existing_obj.block_reason = op_res["block_reason"]
            existing_obj.latency_ms = op_res["latency_ms"]
            existing_obj.checked_at = now_jakarta_naive()
        else:
            new_res = CheckResult(
                domain_id=domain_id,
                operator=op_name,
                status=op_res["status"],
                resolved_ips=op_res["resolved_ips"],
                block_reason=op_res["block_reason"],
                latency_ms=op_res["latency_ms"],
                checked_at=now_jakarta_naive()
            )
            db.add(new_res)

    await db.commit()
    return JSONResponse({"status": "success", "data": check_res})


@router.get("/api/export")
async def api_export_csv(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Ekspor laporan hasil pengecekan seluruh domain dalam format CSV.
    """
    stmt = select(Domain)
    res = await db.execute(stmt)
    domains = res.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header CSV
    writer.writerow([
        "ID", "Domain Name", "Category", "Overall Status",
        "Telkomsel Status", "Telkomsel Reason",
        "XL Status", "XL Reason",
        "IM3 Status", "IM3 Reason",
        "Tri Status", "Tri Reason",
        "Last Checked At"
    ])

    for d in domains:
        # Ambil operator check results
        res_stmt = select(CheckResult).where(CheckResult.domain_id == d.id)
        op_res = await db.execute(res_stmt)
        results = op_res.scalars().all()
        op_map = {r.operator: r.status for r in results}
        reason_map = {r.operator: (r.block_reason or "") for r in results}

        writer.writerow([
            d.id,
            d.name,
            d.category,
            d.overall_status,
            op_map.get("Telkomsel", "UNCHECKED"),
            reason_map.get("Telkomsel", "-"),
            op_map.get("XL", "UNCHECKED"),
            reason_map.get("XL", "-"),
            op_map.get("IM3", "UNCHECKED"),
            reason_map.get("IM3", "-"),
            op_map.get("Tri", "UNCHECKED"),
            reason_map.get("Tri", "-"),
            d.last_checked_at.strftime("%Y-%m-%d %H:%M:%S") if d.last_checked_at else "Never"
        ])

    output.seek(0)
    filename = f"nawala_domain_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/api/settings/update")
async def api_update_settings(
    telegram_token: str = Form(""),
    telegram_chat_id: str = Form(""),
    telegram_enabled: bool = Form(False),
    check_interval: int = Form(5),
    chunk_size: int = Form(2000),
    concurrent_checks: int = Form(30),
    chunk_delay: float = Form(5.0),
    local_test_mode: bool = Form(False),
    telkomsel_proxy: str = Form(""),
    xl_proxy: str = Form(""),
    im3_proxy: str = Form(""),
    tri_proxy: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update konfigurasi aplikasi (Telegram, Scheduler, Concurrency, Proxy) dan simpan permanen ke DB.
    """
    if current_user.role != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Hanya Superadmin yang dapat mengubah pengaturan.")
    settings.TELEGRAM_BOT_TOKEN = telegram_token.strip()
    settings.TELEGRAM_CHAT_ID = telegram_chat_id.strip()
    settings.TELEGRAM_ALERTS_ENABLED = telegram_enabled
    settings.CHECK_INTERVAL_MINUTES = max(1, check_interval)
    settings.CHUNK_SIZE = max(10, chunk_size)
    settings.CONCURRENT_CHECKS = max(5, min(150, concurrent_checks))
    settings.CHUNK_DELAY_SECONDS = max(0.0, chunk_delay)
    settings.LOCAL_TEST_MODE = False

    settings.OPERATOR_PROXIES["Telkomsel"] = telkomsel_proxy.strip()
    settings.OPERATOR_PROXIES["XL"] = xl_proxy.strip()
    settings.OPERATOR_PROXIES["IM3"] = im3_proxy.strip()
    settings.OPERATOR_PROXIES["Tri"] = tri_proxy.strip()

    # Update checker concurrency
    checker_engine.update_concurrency(settings.CONCURRENT_CHECKS)

    # Re-init notifier
    notifier.bot_token = settings.TELEGRAM_BOT_TOKEN
    notifier.chat_id = settings.TELEGRAM_CHAT_ID

    # Dynamic scheduler update
    reschedule_job(settings.CHECK_INTERVAL_MINUTES)

    # Persist settings ke database AppSetting
    settings_data = {
        "TELEGRAM_BOT_TOKEN": settings.TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": settings.TELEGRAM_CHAT_ID,
        "TELEGRAM_ALERTS_ENABLED": str(settings.TELEGRAM_ALERTS_ENABLED),
        "CHECK_INTERVAL_MINUTES": str(settings.CHECK_INTERVAL_MINUTES),
        "CHUNK_SIZE": str(settings.CHUNK_SIZE),
        "CONCURRENT_CHECKS": str(settings.CONCURRENT_CHECKS),
        "CHUNK_DELAY_SECONDS": str(settings.CHUNK_DELAY_SECONDS),
        "LOCAL_TEST_MODE": str(settings.LOCAL_TEST_MODE),
        "TELKOMSEL_PROXY": settings.OPERATOR_PROXIES["Telkomsel"],
        "XL_PROXY": settings.OPERATOR_PROXIES["XL"],
        "IM3_PROXY": settings.OPERATOR_PROXIES["IM3"],
        "TRI_PROXY": settings.OPERATOR_PROXIES["Tri"],
    }

    for key, val in settings_data.items():
        stmt = select(AppSetting).where(AppSetting.key == key)
        res = await db.execute(stmt)
        setting_row = res.scalar_one_or_none()
        if setting_row:
            setting_row.value = val
        else:
            db.add(AppSetting(key=key, value=val))

    await db.commit()

    return JSONResponse({"status": "success", "message": "Pengaturan berhasil diperbarui dan disimpan secara permanen!"})


@router.post("/api/settings/test-telegram")
async def api_test_telegram(
    telegram_token: Optional[str] = Form(None),
    telegram_chat_id: Optional[str] = Form(None)
):
    """
    Uji coba koneksi Telegram:
    - Jika hanya ada Bot Token: verifikasi via API getMe Telegram.
    - Jika ada Chat ID: kirim pesan uji coba ke chat ID tersebut.
    """
    token = (telegram_token or settings.TELEGRAM_BOT_TOKEN or "").strip()
    chat_id = (telegram_chat_id or settings.TELEGRAM_CHAT_ID or "").strip()

    if not token:
        return JSONResponse({"status": "error", "message": "Telegram Bot Token wajib diisi terlebih dahulu!"}, status_code=400)

    # 1. Cek validitas Bot Token via getMe
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            if res.status_code != 200:
                return JSONResponse({
                    "status": "error",
                    "message": "Token Bot tidak valid! Periksa kembali token yang diberikan oleh @BotFather."
                }, status_code=400)
            bot_info = res.json().get("result", {})
            bot_name = bot_info.get("first_name", "Bot")
            bot_username = bot_info.get("username", "")
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Gagal menghubungi server Telegram: {e}"
        }, status_code=500)

    # 2. Jika ada Chat ID, coba kirim pesan tes ke Chat ID tersebut
    if chat_id:
        test_notifier = TelegramNotifier(bot_token=token, chat_id=chat_id)
        msg_sent = await test_notifier.send_test_alert()
        if msg_sent:
            return JSONResponse({
                "status": "success",
                "message": f"Koneksi sukses! Bot @{bot_username} berhasil mengirim pesan tes ke Chat ID {chat_id}."
            })
        else:
            return JSONResponse({
                "status": "error",
                "message": f"Bot @{bot_username} valid, namun gagal mengirim pesan ke Chat ID {chat_id}. Pastikan bot sudah dimasukkan ke chat/grup tersebut."
            }, status_code=400)

    # 3. Jika Chat ID kosong (hanya Bot Token)
    return JSONResponse({
        "status": "success",
        "message": f"Koneksi sukses! Bot Telegram valid & terhubung sebagai @{bot_username} ({bot_name})."
    })


@router.get("/api/logout")
@router.post("/api/logout")
async def api_logout(request: Request):
    """
    Logout dan bersihkan sesi pengguna.
    """
    request.session.clear()
    return JSONResponse({"status": "success", "message": "Berhasil logout!"})


# ==========================================
# CUSTOMER / TENANT MANAGEMENT (Multi-Tenant)
# ==========================================

@router.get("/customers", response_class=HTMLResponse)
async def customers_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Halaman Manajemen Pelanggan / Whitelist Grup Telegram Bot.
    """
    stmt = select(Tenant).order_by(Tenant.id.desc())
    res = await db.execute(stmt)
    tenants = res.scalars().all()

    now = now_jakarta_naive()
    tenant_list = []
    total_quota = 0
    active_count = 0
    expired_count = 0

    for t in tenants:
        # Hitung jumlah domain
        domain_count_stmt = select(func.count(Domain.id)).where(Domain.tenant_id == t.id)
        d_count = (await db.execute(domain_count_stmt)).scalar_one()

        remaining_days = max(0, (t.expired_date.date() - now.date()).days) if t.expired_date else 0
        is_expired = (t.expired_date and t.expired_date < now) or (not t.is_active)

        if is_expired:
            expired_count += 1
        else:
            active_count += 1

        total_quota += t.package_quota

        t_dict = t.to_dict()
        t_dict["domain_count"] = d_count
        t_dict["remaining_days"] = remaining_days
        t_dict["is_expired"] = is_expired
        tenant_list.append(t_dict)

    return templates.TemplateResponse(
        request=request,
        name="customers.html",
        context={
            "app_name": settings.APP_NAME,
            "current_user": current_user,
            "tenants": tenant_list,
            "total_tenants": len(tenant_list),
            "active_count": active_count,
            "expired_count": expired_count,
            "total_quota": total_quota,
        }
    )


@router.get("/api/customers")
async def api_get_customers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    API: Mendapatkan daftar seluruh customer / tenant beserta status kuota & masa aktif.
    """
    stmt = select(Tenant).order_by(Tenant.id.desc())
    res = await db.execute(stmt)
    tenants = res.scalars().all()

    now = now_jakarta_naive()
    results = []
    for t in tenants:
        domain_count_stmt = select(func.count(Domain.id)).where(Domain.tenant_id == t.id)
        d_count = (await db.execute(domain_count_stmt)).scalar_one()

        remaining_days = max(0, (t.expired_date.date() - now.date()).days) if t.expired_date else 0
        is_expired = (t.expired_date and t.expired_date < now) or (not t.is_active)

        t_data = t.to_dict()
        t_data["domain_count"] = d_count
        t_data["remaining_days"] = remaining_days
        t_data["is_expired"] = is_expired
        results.append(t_data)

    return JSONResponse({"status": "success", "data": results})


@router.post("/api/customers")
async def api_create_customer(
    name: str = Form(...),
    contact: Optional[str] = Form(None),
    telegram_chat_id: str = Form(...),
    package_quota: int = Form(10),
    duration_days: int = Form(30),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    API: Mendaftarkan pelanggan/grup baru (Whitelist Grup Bot Telegram).
    """
    name = name.strip()
    telegram_chat_id = telegram_chat_id.strip()

    if not name or not telegram_chat_id:
        return JSONResponse({"status": "error", "message": "Nama dan ID Grup Telegram wajib diisi!"}, status_code=400)

    # Validasi kuota kelipatan 10
    if package_quota < 10:
        package_quota = 10

    # Cek duplikasi telegram_chat_id
    stmt = select(Tenant).where(Tenant.telegram_chat_id == telegram_chat_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return JSONResponse({
            "status": "error",
            "message": f"ID Grup Telegram {telegram_chat_id} sudah terdaftar atas nama '{existing.name}'!"
        }, status_code=400)

    now = now_jakarta_naive()
    expired_date = now + timedelta(days=duration_days)

    new_tenant = Tenant(
        name=name,
        contact=contact.strip() if contact else None,
        telegram_chat_id=telegram_chat_id,
        package_quota=package_quota,
        start_date=now,
        expired_date=expired_date,
        is_active=True,
        notes=notes.strip() if notes else None
    )
    db.add(new_tenant)
    await db.commit()
    await db.refresh(new_tenant)

    return JSONResponse({
        "status": "success",
        "message": f"Pelanggan '{new_tenant.name}' berhasil didaftarkan! ID Grup: {new_tenant.telegram_chat_id} telah di-whitelist.",
        "data": new_tenant.to_dict()
    })


@router.put("/api/customers/{customer_id}")
async def api_update_customer(
    customer_id: int,
    name: str = Form(...),
    contact: Optional[str] = Form(None),
    telegram_chat_id: str = Form(...),
    package_quota: int = Form(10),
    is_active: bool = Form(True),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    API: Memperbarui data pelanggan/grup.
    """
    tenant = await db.get(Tenant, customer_id)
    if not tenant:
        return JSONResponse({"status": "error", "message": "Pelanggan tidak ditemukan!"}, status_code=404)

    # Cek jika chat_id diubah dan bentrok dengan tenant lain
    telegram_chat_id = telegram_chat_id.strip()
    if telegram_chat_id != tenant.telegram_chat_id:
        stmt = select(Tenant).where(Tenant.telegram_chat_id == telegram_chat_id, Tenant.id != customer_id)
        dup = (await db.execute(stmt)).scalar_one_or_none()
        if dup:
            return JSONResponse({"status": "error", "message": f"ID Grup {telegram_chat_id} sudah digunakan pelanggan lain!"}, status_code=400)

    tenant.name = name.strip()
    tenant.contact = contact.strip() if contact else None
    tenant.telegram_chat_id = telegram_chat_id
    tenant.package_quota = max(10, package_quota)
    tenant.is_active = is_active
    tenant.notes = notes.strip() if notes else None
    tenant.updated_at = now_jakarta_naive()

    await db.commit()
    return JSONResponse({"status": "success", "message": f"Data pelanggan '{tenant.name}' berhasil diperbarui!"})


@router.post("/api/customers/{customer_id}/renew")
async def api_renew_customer(
    customer_id: int,
    days: int = Form(30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    API: Memperpanjang masa sewa bot pelanggan (+30 hari atau sesuai input).
    """
    tenant = await db.get(Tenant, customer_id)
    if not tenant:
        return JSONResponse({"status": "error", "message": "Pelanggan tidak ditemukan!"}, status_code=404)

    now = now_jakarta_naive()
    # Jika sudah expired, hitung mulai dari sekarang. Jika masih aktif, tambahkan ke expired_date saat ini.
    if tenant.expired_date and tenant.expired_date > now:
        tenant.expired_date = tenant.expired_date + timedelta(days=days)
    else:
        tenant.expired_date = now + timedelta(days=days)

    tenant.is_active = True
    tenant.updated_at = now
    await db.commit()

    exp_str = tenant.expired_date.strftime("%d %b %Y")
    return JSONResponse({
        "status": "success",
        "message": f"Masa sewa untuk '{tenant.name}' berhasil diperpanjang {days} hari (s/d {exp_str})!"
    })


@router.delete("/api/customers/{customer_id}")
async def api_delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    API: Menghapus pelanggan/grup dan seluruh daftar domain miliknya.
    """
    tenant = await db.get(Tenant, customer_id)
    if not tenant:
        return JSONResponse({"status": "error", "message": "Pelanggan tidak ditemukan!"}, status_code=404)

    tenant_name = tenant.name
    await db.delete(tenant)
    await db.commit()

    return JSONResponse({"status": "success", "message": f"Pelanggan '{tenant_name}' beserta domain miliknya berhasil dihapus!"})


@router.get("/api/customers/{customer_id}/domains")
async def api_get_customer_domains(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    API: Mendapatkan daftar domain milik customer/grup tertentu.
    """
    tenant = await db.get(Tenant, customer_id)
    if not tenant:
        return JSONResponse({"status": "error", "message": "Pelanggan tidak ditemukan!"}, status_code=404)

    stmt = select(Domain).where(Domain.tenant_id == customer_id).order_by(Domain.name.asc())
    res = await db.execute(stmt)
    domains = res.scalars().all()

    return JSONResponse({
        "status": "success",
        "tenant": tenant.to_dict(),
        "domains": [d.to_dict() for d in domains]
    })
