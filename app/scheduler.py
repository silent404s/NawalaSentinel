import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload


from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Domain, CheckResult, StatusLog
from app.checker import checker_engine
from app.notifier import notifier
from app.utils.timezone import now_jakarta_naive

logger = logging.getLogger("nawala_scheduler")

scheduler = AsyncIOScheduler()
is_scanning = False
scan_lock = asyncio.Lock()

async def run_full_domain_scan():
    """
    Background Task: Pengecekan massal otomatis seluruh domain setiap 5 menit.
    Mendukung Sesi Chunking (misal: 2.000 domain per sub-batch) agar beban server & DNS konstan.
    """
    global is_scanning
    if is_scanning:
        logger.warning("⚠️ [SCHEDULER] Siklus pemindaian domain sedang berjalan, melewati pemicu ini.")
        return

    async with scan_lock:
        is_scanning = True
        logger.info("⚡ [SCHEDULER] Memulai siklus pengecekan otomatis seluruh domain...")

        async with AsyncSessionLocal() as session:
            try:
                # 1. Ambil seluruh domain beserta relasi user & tenant dari database
                stmt = select(Domain).options(joinedload(Domain.user), joinedload(Domain.tenant))
                result = await session.execute(stmt)
                domains = result.scalars().all()

                if not domains:
                    logger.info("ℹ️ Belum ada domain yang terdaftar di database.")
                    return

                name_to_domains = {}
                for d in domains:
                    if d.name not in name_to_domains:
                        name_to_domains[d.name] = []
                    name_to_domains[d.name].append(d)

                domain_names = list(name_to_domains.keys())
                total_domains = len(domain_names)

                chunk_size = settings.CHUNK_SIZE
                chunks = [domain_names[i:i + chunk_size] for i in range(0, total_domains, chunk_size)]
                total_chunks = len(chunks)

                logger.info(f"📊 [CHUNKED SCAN] Total {total_domains} domain dibagi menjadi {total_chunks} sesi/batch (Ukuran: {chunk_size} domain/batch).")

                # 2. Jalankan per sesi/chunk
                for chunk_idx, chunk_domains in enumerate(chunks, 1):
                    logger.info(f"🚀 Memproses Sesi {chunk_idx}/{total_chunks} ({len(chunk_domains)} domain)...")

                    batch_results = await checker_engine.check_batch_domains(chunk_domains)

                    # Batch pre-fetch CheckResult untuk semua domain di chunk ini (mencegah N+1 query)
                    chunk_domain_ids = [d.id for name in chunk_domains for d in name_to_domains.get(name, [])]
                    existing_results_map = {}
                    if chunk_domain_ids:
                        existing_stmt = select(CheckResult).where(CheckResult.domain_id.in_(chunk_domain_ids))
                        existing_res = await session.execute(existing_stmt)
                        for r in existing_res.scalars().all():
                            if r.domain_id not in existing_results_map:
                                existing_results_map[r.domain_id] = {}
                            existing_results_map[r.domain_id][r.operator] = r

                    # 3. Proses hasil pengecekan per domain & operator
                    for domain_data in batch_results:
                        domain_name = domain_data["domain"]
                        new_overall_status = domain_data["overall_status"]
                        raw_new_cf = domain_data.get("cf_status", "CLEAN")
                        new_cf_status = "CLEAN" if raw_new_cf == "NORMAL" else raw_new_cf
                        new_cf_reason = domain_data.get("cf_reason", "")
                        operator_results = domain_data["operator_results"]

                        target_domains = name_to_domains.get(domain_name, [])
                        if not target_domains:
                            continue

                        for domain_obj in target_domains:
                            raw_old_cf = domain_obj.cf_status or "CLEAN"
                            old_cf_status = "CLEAN" if raw_old_cf == "NORMAL" else raw_old_cf
                            old_overall_status = domain_obj.overall_status or "UNCHECKED"

                            # Cek apakah terjadi perubahan status Cloudflare (untuk pengguna personal/non-tenant)
                            if old_cf_status != new_cf_status and old_cf_status != "UNCHECKED":
                                logger.warning(f"⚠️ Perubahan Status Cloudflare {domain_name}: {old_cf_status} -> {new_cf_status}")
                                if not (domain_obj.tenant and domain_obj.tenant.is_active):
                                    await notifier.notify_cloudflare_status(
                                        domain_name=domain_name,
                                        cf_status=new_cf_status,
                                        cf_reason=new_cf_reason,
                                        isp_status=new_overall_status,
                                        chat_id=domain_obj.user.telegram_chat_id if domain_obj.user else None
                                    )

                            existing_results = existing_results_map.get(domain_obj.id, {})

                            # Update status per operator & catat StatusLog
                            for operator_name, op_res in operator_results.items():
                                old_op_status = existing_results[operator_name].status if operator_name in existing_results else "UNCHECKED"
                                new_op_status = op_res["status"]
                                block_reason = op_res["block_reason"]
                                resolved_ips = op_res["resolved_ips"]
                                latency_ms = op_res["latency_ms"]

                                # Cek apakah terjadi perubahan status untuk operator ini
                                if old_op_status != new_op_status and old_op_status != "UNCHECKED":
                                    logger.warning(f"🚨 Perubahan Status Domain {domain_name} ({operator_name}): {old_op_status} -> {new_op_status}")
                                    
                                    # Catat ke StatusLog
                                    log_entry = StatusLog(
                                        domain_id=domain_obj.id,
                                        domain_name=domain_name,
                                        operator=operator_name,
                                        previous_status=old_op_status,
                                        new_status=new_op_status,
                                        reason=block_reason,
                                        timestamp=now_jakarta_naive()
                                    )
                                    session.add(log_entry)

                                    # Kirim Notifikasi untuk pengguna personal / non-tenant
                                    if not (domain_obj.tenant and domain_obj.tenant.is_active):
                                        await notifier.notify_status_change(
                                            domain_name=domain_name,
                                            operator=operator_name,
                                            old_status=old_op_status,
                                            new_status=new_op_status,
                                            reason=block_reason,
                                            ips=resolved_ips,
                                            cf_status=new_cf_status,
                                            chat_id=domain_obj.user.telegram_chat_id if domain_obj.user else None
                                        )

                                # Simpan/Update CheckResult
                                if operator_name in existing_results:
                                    check_res_obj = existing_results[operator_name]
                                    check_res_obj.status = new_op_status
                                    check_res_obj.resolved_ips = resolved_ips
                                    check_res_obj.block_reason = block_reason
                                    check_res_obj.latency_ms = latency_ms
                                    check_res_obj.checked_at = now_jakarta_naive()
                                else:
                                    new_res_obj = CheckResult(
                                        domain_id=domain_obj.id,
                                        operator=operator_name,
                                        status=new_op_status,
                                        resolved_ips=resolved_ips,
                                        block_reason=block_reason,
                                        latency_ms=latency_ms,
                                        checked_at=now_jakarta_naive()
                                    )
                                    session.add(new_res_obj)

                            # SISTEM NOTIFIKASI TENANT (Grup Pelanggan):
                            # Peringatan Pertama, Peringatan Berkala (Reminder), & Notifikasi Pemulihan
                            if domain_obj.tenant and domain_obj.tenant.is_active:
                                is_now_bad = (new_overall_status in ("BLOCKED", "MIXED") or new_cf_status == "PHISHING")
                                was_old_bad = (old_overall_status in ("BLOCKED", "MIXED") or old_cf_status == "PHISHING")
                                now_dt = now_jakarta_naive()

                                # 1. Pemulihan (Recovery)
                                if not is_now_bad and was_old_bad:
                                    await notifier.notify_tenant_domain_alert(
                                        domain_name=domain_name,
                                        tenant=domain_obj.tenant,
                                        overall_status=new_overall_status,
                                        cf_status=new_cf_status,
                                        operator_results=operator_results,
                                        reason="Domain kembali normal",
                                        is_recovery=True
                                    )
                                    domain_obj.last_alerted_at = None

                                # 2. Baru Terblokir / Phishing (Peringatan Pertama)
                                elif is_now_bad and not was_old_bad:
                                    await notifier.notify_tenant_domain_alert(
                                        domain_name=domain_name,
                                        tenant=domain_obj.tenant,
                                        overall_status=new_overall_status,
                                        cf_status=new_cf_status,
                                        operator_results=operator_results,
                                        reason=new_cf_reason if new_cf_status == "PHISHING" else "Terdeteksi pemblokiran ISP Nawala",
                                        is_recovery=False,
                                        is_reminder=False
                                    )
                                    domain_obj.last_alerted_at = now_dt

                                # 3. Masih Terblokir & Belum Dihapus (Peringatan Kedua & Seterusnya - Reminder)
                                elif is_now_bad and was_old_bad:
                                    should_remind = False
                                    if domain_obj.last_alerted_at is None:
                                        should_remind = True
                                    else:
                                        elapsed = (now_dt - domain_obj.last_alerted_at).total_seconds()
                                        # Kirim peringatan ulang pada setiap siklus pengecekan berikutnya (minimal 3-4 menit)
                                        min_reminder_interval = max(180, (settings.CHECK_INTERVAL_MINUTES * 60) - 60)
                                        if elapsed >= min_reminder_interval:
                                            should_remind = True

                                    if should_remind:
                                        await notifier.notify_tenant_domain_alert(
                                            domain_name=domain_name,
                                            tenant=domain_obj.tenant,
                                            overall_status=new_overall_status,
                                            cf_status=new_cf_status,
                                            operator_results=operator_results,
                                            reason=new_cf_reason if new_cf_status == "PHISHING" else "Domain masih terblokir dan belum dihapus",
                                            is_recovery=False,
                                            is_reminder=True
                                        )
                                        domain_obj.last_alerted_at = now_dt

                            # Update Domain Overall Status, CF Status, & Timestamp
                            domain_obj.overall_status = new_overall_status
                            domain_obj.cf_status = new_cf_status
                            domain_obj.cf_reason = new_cf_reason
                            domain_obj.last_checked_at = now_jakarta_naive()

                    await session.commit()
                    logger.info(f"✅ Sesi {chunk_idx}/{total_chunks} selesai & commit ke DB.")

                    # Jeda jeda antar sesi jika ada sesi berikutnya
                    if chunk_idx < total_chunks and settings.CHUNK_DELAY_SECONDS > 0:
                        logger.info(f"⏳ Jeda {settings.CHUNK_DELAY_SECONDS} detik sebelum sesi berikutnya...")
                        await asyncio.sleep(settings.CHUNK_DELAY_SECONDS)

                logger.info("🎉 [SCHEDULER] Seluruh sesi batch pengecekan domain selesai!")

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ [SCHEDULER] Gagal menjalankan background scan: {e}")
            finally:
                is_scanning = False


def start_scheduler():
    """
    Menjalankan scheduler otomatis dengan interval waktu yang dikonfigurasi.
    Serta langsung memicu siklus pengecekan awal saat aplikasi mulai berjalan.
    """
    interval_mins = settings.CHECK_INTERVAL_MINUTES
    scheduler.add_job(
        run_full_domain_scan,
        'interval',
        minutes=interval_mins,
        id='nawala_domain_scan_job',
        replace_existing=True,
        next_run_time=datetime.now()
    )
    scheduler.start()
    logger.info(f"🚀 Background Scheduler aktif! Pengecekan otomatis berjalan setiap {interval_mins} menit sekali.")

def reschedule_job(new_interval_minutes: int):
    """
    Memperbarui interval waktu eksekusi scheduler secara dinamis tanpa restart server.
    """
    settings.CHECK_INTERVAL_MINUTES = new_interval_minutes
    if scheduler.running:
        try:
            scheduler.reschedule_job(
                job_id='nawala_domain_scan_job',
                trigger='interval',
                minutes=new_interval_minutes
            )
            logger.info(f"🔄 Scheduler berhasil diperbarui ke interval {new_interval_minutes} menit.")
        except Exception as e:
            logger.error(f"Gagal memperbarui interval scheduler: {e}")

def stop_scheduler():
    """
    Menghentikan scheduler.
    """
    if scheduler.running:
        scheduler.shutdown()
        logger.info("🛑 Background Scheduler dihentikan.")

def get_next_run_time_seconds() -> int:
    """
    Mengembalikan sisa waktu (dalam detik) sampai eksekusi job berikutnya.
    """
    try:
        job = scheduler.get_job('nawala_domain_scan_job')
        if job and job.next_run_time:
            now = datetime.now(job.next_run_time.tzinfo)
            delta = (job.next_run_time - now).total_seconds()
            return max(0, int(delta))
    except Exception:
        pass
    return settings.CHECK_INTERVAL_MINUTES * 60

