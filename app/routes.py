import io
import csv
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.future import select
from sqlalchemy import func, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Domain, CheckResult, StatusLog, AppSetting, User
from app.config import settings
from app.auth import get_current_user, verify_password
from app.checker import checker_engine
from app.notifier import notifier
from app.scheduler import run_full_domain_scan, get_next_run_time_seconds, reschedule_job
from app.utils.timezone import format_wib, format_time_wib, now_jakarta_naive
from app.updater import system_updater

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["wib_datetime"] = format_wib
templates.env.filters["wib_time"] = format_time_wib


# Helper untuk normalisasi domain name
def normalize_domain(domain_str: str) -> str:
    domain_str = domain_str.strip().lower()
    if domain_str.startswith("http://"):
        domain_str = domain_str[7:]
    elif domain_str.startswith("https://"):
        domain_str = domain_str[8:]
    if "/" in domain_str:
        domain_str = domain_str.split("/")[0]
    return domain_str.strip()


# ==========================================
# WEB DASHBOARD UI ROUTES (Jinja2 Templates)
# ==========================================

@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
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

    # Recent Domains
    domains_result = await db.execute(
        select(Domain).order_by(desc(Domain.last_checked_at)).limit(50)
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

    next_check_seconds = get_next_run_time_seconds()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
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
            "op_results_map": op_results_map,
            "recent_logs": recent_logs,
            "next_check_seconds": next_check_seconds,
            "check_interval_minutes": settings.CHECK_INTERVAL_MINUTES,
            "app_name": settings.APP_NAME,
        }
    )



@router.get("/domains", response_class=HTMLResponse)
async def domains_page(request: Request, q: Optional[str] = None, status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """
    Halaman Kelola & Pemantauan Daftar Domain/Subdomain.
    """
    total_domains = (await db.execute(select(func.count(Domain.id)))).scalar_one()
    normal_count = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "NORMAL"))).scalar_one()
    blocked_count = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "BLOCKED"))).scalar_one()
    phishing_count = (await db.execute(select(func.count(Domain.id)).where(Domain.cf_status == "PHISHING"))).scalar_one()
    mixed_count = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "MIXED"))).scalar_one()
    unchecked_count = (await db.execute(select(func.count(Domain.id)).where(Domain.overall_status == "UNCHECKED"))).scalar_one()
    block_ratio = round((blocked_count / total_domains * 100), 1) if total_domains > 0 else 0.0

    query = select(Domain)
    if q:
        query = query.where(Domain.name.ilike(f"%{q.strip()}%"))
    if status and status != "ALL":
        if status == "PHISHING":
            query = query.where(Domain.cf_status == "PHISHING")
        else:
            query = query.where(Domain.overall_status == status)

    query = query.order_by(desc(Domain.created_at))
    result = await db.execute(query)
    domains = result.scalars().all()

    # Domain ID -> Dict operator check results
    domain_ids = [d.id for d in domains]
    op_results_map = {}
    if domain_ids:
        res_stmt = select(CheckResult).where(CheckResult.domain_id.in_(domain_ids))
        res = await db.execute(res_stmt)
        for r in res.scalars().all():
            if r.domain_id not in op_results_map:
                op_results_map[r.domain_id] = {}
            op_results_map[r.domain_id][r.operator] = r

    return templates.TemplateResponse(
        request=request,
        name="domains.html",
        context={
            "active_page": "domains",
            "stats": {
                "total": total_domains,
                "normal": normal_count,
                "blocked": blocked_count,
                "phishing": phishing_count,
                "mixed": mixed_count,
                "unchecked": unchecked_count,
                "block_ratio": block_ratio,
            },
            "domains": domains,
            "op_results_map": op_results_map,
            "next_check_seconds": get_next_run_time_seconds(),
            "check_interval_minutes": settings.CHECK_INTERVAL_MINUTES,
            "q": q or "",
            "status": status or "ALL",
            "app_name": settings.APP_NAME,
        }
    )


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Halaman Riwayat Perubahan Status Pemblokiran Domain.
    """
    stmt = select(StatusLog).order_by(desc(StatusLog.timestamp)).limit(100)
    result = await db.execute(stmt)
    logs = result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            "active_page": "logs",
            "logs": logs,
            "app_name": settings.APP_NAME,
        }
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """
    Halaman Pengaturan Bot Telegram, Interval, Proxy, & Pembaruan Sistem.
    """
    version_info = await system_updater.get_version_info()
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "active_page": "settings",
            "settings": settings,
            "version_info": version_info,
            "app_name": settings.APP_NAME,
        }
    )


@router.get("/docs", response_class=HTMLResponse)
@router.get("/panduan", response_class=HTMLResponse)
async def docs_page(request: Request):
    """
    Halaman Dokumentasi, Cara Kerja Sistem, & Tutorial Lengkap.
    """
    return templates.TemplateResponse(
        request=request,
        name="docs.html",
        context={
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

@router.post("/api/login")
async def api_login(request: Request, username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    """
    Endpoint otentikasi login.
    """
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(user.password, password):
        return JSONResponse(
            {"status": "error", "message": "Username atau Password salah!"},
            status_code=401
        )
    
    if not user.is_active:
        return JSONResponse(
            {"status": "error", "message": "Akun Anda telah dinonaktifkan!"},
            status_code=403
        )

    # Set Session
    request.session["user_id"] = user.id

    return JSONResponse({
        "status": "success",
        "message": "Login berhasil!",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "domain_quota": user.domain_quota
        }
    })


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
async def api_stats(db: AsyncSession = Depends(get_db)):
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
    Menambahkan domain atau subdomain baru (massal via text).
    """
    lines = raw_domains.strip().splitlines()
    valid_lines = [normalize_domain(l) for l in lines if normalize_domain(l) and "." in normalize_domain(l)]
    
    # Validation Quota
    stmt_count = select(func.count(Domain.id)).where(Domain.user_id == current_user.id)
    current_count = (await db.execute(stmt_count)).scalar_one()
    
    if current_count + len(valid_lines) > current_user.domain_quota:
        return JSONResponse(
            {"status": "error", "message": f"Kuota melebihi batas! Sisa kuota: {current_user.domain_quota - current_count}, Domain dimasukkan: {len(valid_lines)}"}, 
            status_code=400
        )

    added_count = 0
    skipped_count = 0

    for line in lines:
        cleaned = normalize_domain(line)
        if not cleaned or "." not in cleaned:
            continue

        # Cek apakah domain sudah terdaftar di sistem
        stmt = select(Domain).where(Domain.name == cleaned)
        res = await db.execute(stmt)
        if res.scalar_one_or_none():
            skipped_count += 1
            continue

        new_domain = Domain(name=cleaned, category=category, overall_status="UNCHECKED", user_id=current_user.id)
        db.add(new_domain)
        added_count += 1

    await db.commit()

    if added_count == 0 and skipped_count > 0:
        msg = f"Domain sudah terdaftar sebelumnya ({skipped_count} duplikat dilewati)."
        status_type = "info"
    elif added_count > 0 and skipped_count > 0:
        msg = f"Berhasil menambahkan {added_count} domain baru ({skipped_count} duplikat dilewati)."
        status_type = "success"
    elif added_count > 0:
        msg = f"Berhasil menambahkan {added_count} domain baru!"
        status_type = "success"
    else:
        msg = "Tidak ada domain valid yang dapat ditambahkan."
        status_type = "warning"

    return JSONResponse({"status": status_type, "message": msg, "added": added_count, "skipped": skipped_count})


@router.post("/api/domains/import")
async def api_import_domains(file: UploadFile = File(...), category: str = Form("General"), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Import massal domain melalui unggah file TXT/CSV.
    """
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")

    lines = text.splitlines()
    valid_lines = []
    for line in lines:
        parts = line.split(",")
        domain_raw = parts[0] if parts else line
        cleaned = normalize_domain(domain_raw)
        if cleaned and "." in cleaned and " " not in cleaned:
            valid_lines.append(cleaned)

    # Validation Quota
    stmt_count = select(func.count(Domain.id)).where(Domain.user_id == current_user.id)
    current_count = (await db.execute(stmt_count)).scalar_one()

    if current_count + len(valid_lines) > current_user.domain_quota:
        return JSONResponse(
            {"status": "error", "message": f"Kuota melebihi batas! Sisa kuota: {current_user.domain_quota - current_count}, Domain di-import: {len(valid_lines)}"}, 
            status_code=400
        )

    added_count = 0
    skipped_count = 0

    lines = text.splitlines()
    for line in lines:
        # Jika CSV, ambil kolom pertama atau baris terpisah
        parts = line.split(",")
        domain_raw = parts[0] if parts else line
        cleaned = normalize_domain(domain_raw)

        if not cleaned or "." not in cleaned or " " in cleaned:
            continue

        # Cek apakah domain sudah terdaftar di sistem
        stmt = select(Domain).where(Domain.name == cleaned)
        res = await db.execute(stmt)
        if res.scalar_one_or_none():
            skipped_count += 1
            continue

        new_domain = Domain(name=cleaned, category=category, overall_status="UNCHECKED", user_id=current_user.id)
        db.add(new_domain)
        added_count += 1

    await db.commit()

    if added_count == 0 and skipped_count > 0:
        msg = f"Semua domain dalam file ({skipped_count} domain) sudah terdaftar sebelumnya."
        status_type = "info"
    elif added_count > 0 and skipped_count > 0:
        msg = f"Berhasil mengimpor {added_count} domain baru ({skipped_count} duplikat dilewati)."
        status_type = "success"
    elif added_count > 0:
        msg = f"Berhasil mengimpor {added_count} domain baru!"
        status_type = "success"
    else:
        msg = "File tidak memuat domain yang valid."
        status_type = "warning"

    return JSONResponse({"status": status_type, "message": msg, "added": added_count, "skipped": skipped_count})


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
    if current_user.role != "SUPERADMIN" and d.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Akses ditolak")

    await db.execute(delete(Domain).where(Domain.id == domain_id))
    await db.commit()
    return JSONResponse({"status": "success", "message": "Domain berhasil dihapus"})


@router.post("/api/domains/clear-all")
async def api_clear_all_domains(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Hapus seluruh domain, riwayat log, dan hasil pengecekan dari database.
    """
    if current_user.role == "SUPERADMIN":
        await db.execute(delete(CheckResult))
        await db.execute(delete(StatusLog))
        await db.execute(delete(Domain))
    else:
        user_domains_stmt = select(Domain.id).where(Domain.user_id == current_user.id)
        user_domain_ids = [row[0] for row in (await db.execute(user_domains_stmt)).all()]
        if user_domain_ids:
            await db.execute(delete(CheckResult).where(CheckResult.domain_id.in_(user_domain_ids)))
            await db.execute(delete(StatusLog).where(StatusLog.domain_id.in_(user_domain_ids)))
            await db.execute(delete(Domain).where(Domain.id.in_(user_domain_ids)))

    await db.commit()
    return JSONResponse({"status": "success", "message": "Seluruh domain dan riwayat pemantauan berhasil dihapus!"})


@router.post("/api/check-now")
async def api_check_now():
    """
    Pemicu manual untuk pengecekan langsung seluruh domain di latar belakang.
    """
    import asyncio
    asyncio.create_task(run_full_domain_scan())
    return JSONResponse({"status": "success", "message": "Pengecekan massal telah dimulai di latar belakang!"})


@router.post("/api/check-domain/{domain_id}")
async def api_check_single_domain(domain_id: int, db: AsyncSession = Depends(get_db)):
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
async def api_export_csv(db: AsyncSession = Depends(get_db)):
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
    local_test_mode: bool = Form(False),
    telkomsel_proxy: str = Form(""),
    xl_proxy: str = Form(""),
    im3_proxy: str = Form(""),
    tri_proxy: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update konfigurasi aplikasi (Telegram, Scheduler, Proxy) dan simpan permanen ke DB.
    """
    if current_user.role != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Hanya Superadmin yang dapat mengubah pengaturan.")
    settings.TELEGRAM_BOT_TOKEN = telegram_token.strip()
    settings.TELEGRAM_CHAT_ID = telegram_chat_id.strip()
    settings.TELEGRAM_ALERTS_ENABLED = telegram_enabled
    settings.CHECK_INTERVAL_MINUTES = max(1, check_interval)
    settings.LOCAL_TEST_MODE = False

    settings.OPERATOR_PROXIES["Telkomsel"] = telkomsel_proxy.strip()
    settings.OPERATOR_PROXIES["XL"] = xl_proxy.strip()
    settings.OPERATOR_PROXIES["IM3"] = im3_proxy.strip()
    settings.OPERATOR_PROXIES["Tri"] = tri_proxy.strip()

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
    Uji coba notifikasi Telegram.
    """
    test_notifier = TelegramNotifier(
        bot_token=telegram_token or settings.TELEGRAM_BOT_TOKEN,
        chat_id=telegram_chat_id or settings.TELEGRAM_CHAT_ID
    )
    success = await test_notifier.send_test_alert()
    
    if success:
        return JSONResponse({"status": "success", "message": "Pesan tes berhasil dikirim ke Telegram!"})
    else:
        return JSONResponse({"status": "error", "message": "Gagal mengirim pesan tes. Periksa Bot Token & Chat ID!"}, status_code=400)


@router.get("/api/logout")
@router.post("/api/logout")
async def api_logout(request: Request):
    """
    Logout dan bersihkan sesi pengguna.
    """
    request.session.clear()
    return JSONResponse({"status": "success", "message": "Berhasil logout!"})
