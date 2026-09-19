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

logger = logging.getLogger("nawala_scheduler")

scheduler = AsyncIOScheduler()

async def run_full_domain_scan():
    """
    Background Task: Pengecekan massal otomatis seluruh domain setiap 5 menit.
    Mendukung Sesi Chunking (misal: 2.000 domain per sub-batch) agar beban server & DNS konstan.
    """
    logger.info("⚡ [SCHEDULER] Memulai siklus pengecekan otomatis seluruh domain...")

    async with AsyncSessionLocal() as session:
        try:
            # 1. Ambil seluruh domain beserta relasi user dari database
            stmt = select(Domain).options(joinedload(Domain.user))
            result = await session.execute(stmt)
            domains = result.scalars().all()

            if not domains:
                logger.info("ℹ️ Belum ada domain yang terdaftar di database.")
                return

            domain_map = {d.name: d for d in domains}
            domain_names = list(domain_map.keys())
            total_domains = len(domain_names)

            chunk_size = settings.CHUNK_SIZE
            chunks = [domain_names[i:i + chunk_size] for i in range(0, total_domains, chunk_size)]
            total_chunks = len(chunks)

            logger.info(f"📊 [CHUNKED SCAN] Total {total_domains} domain dibagi menjadi {total_chunks} sesi/batch (Ukuran: {chunk_size} domain/batch).")

            # 2. Jalankan per sesi/chunk
            for chunk_idx, chunk_domains in enumerate(chunks, 1):
                logger.info(f"🚀 Memproses Sesi {chunk_idx}/{total_chunks} ({len(chunk_domains)} domain)...")

                batch_results = await checker_engine.check_batch_domains(chunk_domains)

                # 3. Proses hasil pengecekan per domain & operator
                for domain_data in batch_results:
                    domain_name = domain_data["domain"]
                    new_overall_status = domain_data["overall_status"]
                    operator_results = domain_data["operator_results"]

                    domain_obj = domain_map.get(domain_name)
                    if not domain_obj:
                        continue

                    # Ambil hasil pengecekan lama per operator
                    existing_results_stmt = select(CheckResult).where(CheckResult.domain_id == domain_obj.id)
                    existing_results_res = await session.execute(existing_results_stmt)
                    existing_results = {r.operator: r for r in existing_results_res.scalars().all()}

                    # Update status per operator
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
                                timestamp=datetime.utcnow()
                            )
                            session.add(log_entry)

                            # Kirim Notifikasi Telegram / Webhook jika berubah menjadi BLOCKED atau pulih ke NORMAL
                            await notifier.notify_status_change(
                                domain_name=domain_name,
                                operator=operator_name,
                                old_status=old_op_status,
                                new_status=new_op_status,
                                reason=block_reason,
                                ips=resolved_ips,
                                chat_id=domain_obj.user.telegram_chat_id if domain_obj.user else None
                            )

                        # Simpan/Update CheckResult
                        if operator_name in existing_results:
                            check_res_obj = existing_results[operator_name]
                            check_res_obj.status = new_op_status
                            check_res_obj.resolved_ips = resolved_ips
                            check_res_obj.block_reason = block_reason
                            check_res_obj.latency_ms = latency_ms
                            check_res_obj.checked_at = datetime.utcnow()
                        else:
                            new_res_obj = CheckResult(
                                domain_id=domain_obj.id,
                                operator=operator_name,
                                status=new_op_status,
                                resolved_ips=resolved_ips,
                                block_reason=block_reason,
                                latency_ms=latency_ms,
                                checked_at=datetime.utcnow()
                            )
                            session.add(new_res_obj)

                    # Update Domain Overall Status & Timestamp
                    domain_obj.overall_status = new_overall_status
                    domain_obj.last_checked_at = datetime.utcnow()

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


def start_scheduler():
    """
    Menjalankan scheduler otomatis dengan interval waktu yang dikonfigurasi.
    """
    interval_mins = settings.CHECK_INTERVAL_MINUTES
    scheduler.add_job(
        run_full_domain_scan,
        'interval',
        minutes=interval_mins,
        id='nawala_domain_scan_job',
        replace_existing=True
    )
    scheduler.start()
    logger.info(f"🚀 Background Scheduler aktif! Pengecekan otomatis berjalan setiap {interval_mins} menit sekali.")

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

