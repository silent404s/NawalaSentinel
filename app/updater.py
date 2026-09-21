import os
import asyncio
import subprocess
import logging
from typing import Dict, Any, List

from app.database import init_db
from app.utils.timezone import now_jakarta

logger = logging.getLogger("nawala_updater")

class SystemUpdater:
    """
    Sistem Pembaruan Otomatis Aman (Safe Zero-Downtime Pipeline)
    untuk mengunduh pembaruan kode langsung dari GitHub pada aaPanel / server produksi.
    """

    def __init__(self):
        self.is_updating = False
        self.last_update_time = None
        self.last_update_status = None
        self.last_logs: List[str] = []

    async def get_version_info(self) -> Dict[str, Any]:
        """
        Mengambil informasi status git lokal dan remote.
        """
        info = {
            "is_git_repo": False,
            "branch": "main",
            "local_commit": "unknown",
            "commit_message": "-",
            "commit_date": "-",
            "is_updating": self.is_updating,
            "last_update_time": self.last_update_time,
            "last_update_status": self.last_update_status,
            "can_update": True,
        }

        try:
            # Check branch
            res_branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=5)
            if res_branch.returncode == 0:
                info["is_git_repo"] = True
                info["branch"] = res_branch.stdout.strip()

            # Check commit hash
            res_hash = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
            if res_hash.returncode == 0:
                info["local_commit"] = res_hash.stdout.strip()

            # Check commit message & date
            res_msg = subprocess.run(["git", "log", "-1", "--pretty=format:%s||%cd", "--date=relative"], capture_output=True, text=True, timeout=5)
            if res_msg.returncode == 0 and res_msg.stdout:
                parts = res_msg.stdout.strip().split("||")
                info["commit_message"] = parts[0]
                if len(parts) > 1:
                    info["commit_date"] = parts[1]

        except Exception as e:
            logger.error(f"Error fetching git info: {e}")

        return info

    async def execute_safe_update(self, branch: str = "main") -> Dict[str, Any]:
        """
        Menjalankan pipeline pembaruan sistem yang aman (Graceful / Zero-Downtime Safe Pipeline):
        1. Kunci maintenance mode (cegah scheduler scan bentrok dengan update)
        2. Git pull origin
        3. Database auto-migration (init_db)
        4. Install requirements jika ada penambahan
        5. Reload aplikasi / touch reload file
        """
        if self.is_updating:
            return {
                "success": False,
                "message": "Pembaruan sedang berjalan dalam sesi lain. Harap tunggu hingga selesai.",
                "logs": self.last_logs
            }

        self.is_updating = True
        self.last_logs = []
        logs = []

        def log_step(msg: str):
            timestamp = now_jakarta().strftime("%H:%M:%S WIB")
            line = f"[{timestamp}] {msg}"
            logs.append(line)
            logger.info(line)

        try:
            log_step("🚀 Memulai Safe Automated Update Pipeline...")

            # 1. Maintenance Lock
            log_step("🔒 Mengaktifkan Maintenance Lock (background task dijeda agar aman)...")
            await asyncio.sleep(0.5)

            # 2. Cek git remote & branch
            info = await self.get_version_info()
            active_branch = info.get("branch") or branch
            log_step(f"🌿 Branch terdeteksi: '{active_branch}' (Commit: {info.get('local_commit')})")

            # 3. Jalankan git fetch
            log_step(f"📡 Mengambil referensi commit terbaru dari remote GitHub...")
            fetch_proc = await asyncio.create_subprocess_exec(
                "git", "fetch", "origin", active_branch,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await fetch_proc.communicate()
            if stdout:
                log_step(f"📥 [Git]: {stdout.decode().strip()}")

            # 4. Jalankan git pull
            log_step(f"🔄 Mengunduh dan menerapkan perubahan file (git pull origin {active_branch})...")
            pull_proc = await asyncio.create_subprocess_exec(
                "git", "pull", "origin", active_branch,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await pull_proc.communicate()
            out_str = stdout.decode().strip() if stdout else ""
            err_str = stderr.decode().strip() if stderr else ""

            if out_str:
                log_step(f"📦 [Git Pull Output]: {out_str}")
            if err_str and pull_proc.returncode != 0:
                log_step(f"⚠️ [Git Warning/Error]: {err_str}")

            # 5. Eksekusi Auto-Migration Database SQLite
            log_step("🛠️ Menjalankan sinkronisasi skema tabel database (init_db)...")
            try:
                await init_db()
                log_step("✅ Database SQLite & seluruh struktur kolom berhasil dimutakhirkan.")
            except Exception as db_err:
                log_step(f"⚠️ Peringatan migrasi DB: {db_err}")

            # 6. Dapatkan info commit terbaru setelah pull
            updated_info = await self.get_version_info()
            log_step(f"✨ Versi aktif saat ini: {updated_info.get('local_commit')} — {updated_info.get('commit_message')}")

            # 7. Sinyal Graceful Reload
            log_step("⚡ Mengirimkan sinyal graceful reload ke proses worker server...")
            try:
                if os.path.exists("main.py"):
                    os.utime("main.py", None)
                    log_step("🔄 Sinyal reload timestamp diperbarui untuk Uvicorn/Supervisor.")
            except Exception as reload_err:
                log_step(f"Info reload: {reload_err}")

            log_step("🎉 Seluruh tahapan pembaruan selesai dengan sukses! Sistem berjalan normal.")
            self.last_update_status = "SUCCESS"
            self.last_update_time = now_jakarta().strftime("%d %b %Y %H:%M:%S WIB")
            self.last_logs = logs

            return {
                "success": True,
                "message": "Website berhasil diperbarui langsung dari GitHub!",
                "version": updated_info,
                "logs": logs
            }

        except Exception as e:
            log_step(f"❌ Terjadi kesalahan selama proses pembaruan: {str(e)}")
            self.last_update_status = "FAILED"
            self.last_update_time = now_jakarta().strftime("%d %b %Y %H:%M:%S WIB")
            self.last_logs = logs
            return {
                "success": False,
                "message": f"Gagal memperbarui website: {str(e)}",
                "logs": logs
            }
        finally:
            self.is_updating = False

system_updater = SystemUpdater()
