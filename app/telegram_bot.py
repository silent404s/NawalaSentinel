import asyncio
import html
import logging
import random
import re
from typing import Optional, List, Dict, Any

import httpx
from sqlalchemy.future import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Tenant, Domain, CheckResult, BotActivityLog
from app.checker import checker_engine
from app.utils.timezone import now_jakarta_naive

logger = logging.getLogger("telegram_bot")

def normalize_domain_bot(domain_str: str) -> str:
    """
    Normalisasi domain name dari pesan chat bot.
    """
    domain_str = domain_str.strip().lower()
    if domain_str.startswith("http://"):
        domain_str = domain_str[7:]
    elif domain_str.startswith("https://"):
        domain_str = domain_str[8:]
    domain_str = domain_str.rstrip("/")
    return domain_str.strip()

def is_valid_domain(domain_str: str) -> bool:
    """
    Validasi format domain dasar.
    """
    if not domain_str or " " in domain_str:
        return False
    # Cek minimal ada titik dan panjang wajar
    domain_part = domain_str.split("/")[0]
    return "." in domain_part and len(domain_part) >= 3


class TelegramBotEngine:
    """
    Engine Bot Telegram Interaktif & Multi-Tenant:
    - Long-polling listener untuk menerima perintah grup (/add, /del, /list, /cek, /status, /help, /info).
    - Verifikasi Whitelist ID Grup & Pengecekan Hak Akses Admin Bot.
    - Isolasi data domain per customer/tenant.
    - Notifikasi peringatan Nawala & Cloudflare khusus grup pemilik domain.
    """

    def __init__(self):
        self.is_running = False
        self._polling_task: Optional[asyncio.Task] = None
        self.bot_id: Optional[int] = None
        self.bot_username: Optional[str] = None
        self.last_update_id: int = 0

    async def start(self):
        """
        Memulai background task long polling bot Telegram.
        """
        if self.is_running:
            return

        self.is_running = True
        self._polling_task = asyncio.create_task(self._poll_loop())
        logger.info("🤖 [TELEGRAM BOT] Interactive Multi-Tenant Bot Engine dimulai.")

    async def stop(self):
        """
        Menghentikan background task long polling bot Telegram.
        """
        self.is_running = False
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
        logger.info("🛑 [TELEGRAM BOT] Bot Engine dihentikan.")

    async def _fetch_bot_info(self, client: httpx.AsyncClient, token: str) -> bool:
        """
        Mengambil informasi bot (id dan username) dari Telegram getMe API.
        """
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            res = await client.get(url, timeout=10.0)
            if res.status_code == 200:
                data = res.json().get("result", {})
                self.bot_id = data.get("id")
                self.bot_username = data.get("username")
                logger.info(f"🤖 [TELEGRAM BOT] Berhasil terhubung sebagai @{self.bot_username} (ID: {self.bot_id})")
                return True
            else:
                logger.warning(f"⚠️ [TELEGRAM BOT] Gagal getMe: {res.text}")
                return False
        except Exception as e:
            logger.error(f"❌ [TELEGRAM BOT] Error fetch bot info: {e}")
            return False

    async def is_bot_admin(self, client: httpx.AsyncClient, token: str, chat_id: str) -> bool:
        """
        Memeriksa apakah bot memiliki hak akses Administrator di grup tersebut.
        Mengecek via getChatMember dan getChatAdministrators.
        """
        if not self.bot_id:
            await self._fetch_bot_info(client, token)
            if not self.bot_id:
                # Jika gagal ambil bot_id, default True agar tidak memblokir operasional
                return True

        # 1. Cek via getChatMember
        url = f"https://api.telegram.org/bot{token}/getChatMember"
        try:
            res = await client.get(url, params={"chat_id": chat_id, "user_id": self.bot_id}, timeout=10.0)
            if res.status_code == 200:
                data = res.json().get("result", {})
                status = data.get("status", "")
                if status in ("administrator", "creator"):
                    return True

            # 2. Fallback: periksa via getChatAdministrators
            url_admins = f"https://api.telegram.org/bot{token}/getChatAdministrators"
            res_admins = await client.get(url_admins, params={"chat_id": chat_id}, timeout=10.0)
            if res_admins.status_code == 200:
                admins = res_admins.json().get("result", [])
                for adm in admins:
                    user = adm.get("user", {})
                    if user.get("id") == self.bot_id:
                        return True

            return False
        except Exception as e:
            logger.error(f"❌ [TELEGRAM BOT] Error cek status admin bot di chat {chat_id}: {e}")
            # Jika terjadi gangguan koneksi sementara ke API pengecekan, izinkan agar user tidak terblokir
            return True

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        reply_to_message_id: Optional[int] = None
    ) -> bool:
        """
        Kirim pesan ke Telegram Chat/Grup.
        """
        token = settings.TELEGRAM_BOT_TOKEN
        if not token or not chat_id:
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post(url, json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.error(f"❌ [TELEGRAM BOT] Gagal mengirim pesan ke {chat_id}: {e}")
            return False

    async def _poll_loop(self):
        """
        Loop asynchronous long-polling untuk menerima updates.
        """
        logger.info("🔄 [TELEGRAM BOT] Polling loop aktif...")

        while self.is_running:
            token = settings.TELEGRAM_BOT_TOKEN
            if not token:
                # Token belum diset di pengaturan, tunggu 10 detik lalu cek kembali
                await asyncio.sleep(10.0)
                continue

            try:
                async with httpx.AsyncClient(timeout=35.0) as client:
                    # Ambil bot info jika belum ada
                    if not self.bot_id:
                        ok = await self._fetch_bot_info(client, token)
                        if not ok:
                            await asyncio.sleep(10.0)
                            continue

                    # Long polling getUpdates
                    url = f"https://api.telegram.org/bot{token}/getUpdates"
                    params = {
                        "offset": self.last_update_id + 1,
                        "timeout": 20,
                        "allowed_updates": ["message"]
                    }

                    response = await client.get(url, params=params)
                    if response.status_code == 200:
                        data = response.json()
                        updates = data.get("result", [])
                        for update in updates:
                            self.last_update_id = update["update_id"]
                            if "message" in update:
                                # Proses pesan secara asynchronous agar tidak memblokir loop
                                asyncio.create_task(self._handle_incoming_message(client, token, update["message"]))
                    elif response.status_code in (401, 404):
                        logger.warning(f"⚠️ [TELEGRAM BOT] Token tidak valid ({response.status_code}). Menunggu...")
                        await asyncio.sleep(15.0)
                    else:
                        await asyncio.sleep(5.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"ℹ️ [TELEGRAM BOT] Polling notice: {e}")
                await asyncio.sleep(3.0)

    async def _log_activity(
        self,
        session,
        tenant: Optional[Tenant],
        chat_id: str,
        from_user: dict,
        command: str,
        details: str,
        raw_message: str,
        status: str = "SUCCESS"
    ):
        """
        Mencatat audit log aktivitas setiap pengguna bot ke tabel bot_activity_logs.
        """
        try:
            user_id = str(from_user.get("id", "")) if from_user else ""
            username = from_user.get("username") if from_user else None
            first_name = from_user.get("first_name", "") if from_user else ""
            last_name = from_user.get("last_name", "") if from_user else ""
            full_name = f"{first_name} {last_name}".strip() or None
            clean_username = username.lstrip("@") if username else None

            log_entry = BotActivityLog(
                tenant_id=tenant.id if tenant else None,
                telegram_chat_id=str(chat_id),
                telegram_user_id=user_id,
                telegram_username=clean_username,
                full_name=full_name,
                command=command,
                details=details,
                raw_message=raw_message,
                status=status,
                created_at=now_jakarta_naive()
            )
            session.add(log_entry)
            await session.commit()
        except Exception as e:
            logger.error(f"❌ [TELEGRAM BOT] Error mencatat audit log: {e}")

    async def _handle_incoming_message(self, client: httpx.AsyncClient, token: str, message: dict):
        """
        Memproses pesan Telegram yang masuk: validasi grup, status admin, dan eksekusi command.
        """
        text = message.get("text", "").strip()
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        message_id = message.get("message_id")
        from_user = message.get("from", {})

        if not text or not chat_id:
            return

        # Hanya respon pesan yang diawali "/"
        if not text.startswith("/"):
            return

        parts = text.split()
        raw_cmd = parts[0]
        args = parts[1:]

        # Normalisasi command: hilangkan nama bot (misal: /add@MyBot -> /add)
        cmd = raw_cmd.split("@")[0].lower()

        # Daftar command yang didukung
        supported_commands = ("/add", "/del", "/replace", "/list", "/cek", "/status", "/help", "/info", "/start", "/katakatahariini", "/kata")
        if cmd not in supported_commands:
            return

        logger.info(f"📨 [TELEGRAM BOT] Menerima command '{cmd}' dari chat_id={chat_id} (user={from_user.get('username')}, id={from_user.get('id')})")

        async with AsyncSessionLocal() as session:
            # 1. CEK WHITELIST GRUP
            stmt = select(Tenant).where(Tenant.telegram_chat_id == chat_id)
            res = await session.execute(stmt)
            tenant = res.scalar_one_or_none()

            if not tenant:
                # Grup Belum Terdaftar / Whitelist (Template F.1)
                reply = (
                    "⛔ <b>AKSES DITOLAK</b>\n\n"
                    "Grup ini belum terdaftar dalam sistem langganan bot.\n"
                    f"ID Grup: <code>{chat_id}</code>\n\n"
                    "Silakan hubungi Admin untuk mendaftarkan grup Anda dan mengaktifkan bot."
                )
                await self._log_activity(session, None, chat_id, from_user, cmd, "Akses ditolak: Grup belum terdaftar di whitelist", text, status="REJECTED")
                await self.send_message(chat_id, reply, reply_to_message_id=message_id)
                return

            # 2. CEK BOT HARUS MENJADI ADMIN DI GRUP (Template F.2)
            # Catatan: jika chat adalah private chat ('private'), tidak perlu cek admin grup
            chat_type = chat.get("type", "")
            if chat_type in ("group", "supergroup"):
                is_admin = await self.is_bot_admin(client, token, chat_id)
                if not is_admin:
                    reply = (
                        "⚠️ <b>PERINGATAN: BOT HARUS MENJADI ADMIN</b>\n\n"
                        "Untuk dapat memantau dan mengirimkan notifikasi radar pemantauan dengan lancar, "
                        "bot ini <b>WAJIB</b> dijadikan sebagai <b>Administrator</b> di grup ini.\n\n"
                        "Silakan ubah hak akses bot menjadi Admin lalu coba kembali."
                    )
                    await self._log_activity(session, tenant, chat_id, from_user, cmd, "Peringatan: Bot belum dijadikan admin di grup", text, status="REJECTED")
                    await self.send_message(chat_id, reply, reply_to_message_id=message_id)
                    return

            # 3. CEK MASA SEWA / EXPIRED (Template F.3)
            now = now_jakarta_naive()
            if not tenant.is_active or (tenant.expired_date and tenant.expired_date < now):
                exp_str = tenant.expired_date.strftime("%d %b %Y") if tenant.expired_date else "Habis"
                reply = (
                    "⏳ <b>MASA SEWA TELAH HABIS</b>\n\n"
                    f"Masa aktif langganan bot untuk grup ini telah berakhir pada <b>{exp_str}</b>.\n"
                    "Fitur monitoring dan perintah bot dinonaktifkan sementara.\n\n"
                    "Silakan hubungi Admin untuk melakukan perpanjangan masa sewa."
                )
                await self._log_activity(session, tenant, chat_id, from_user, cmd, "Akses ditolak: Masa sewa grup telah habis", text, status="REJECTED")
                await self.send_message(chat_id, reply, reply_to_message_id=message_id)
                return

            # 4. EKSEKUSI COMMAND
            if cmd == "/list":
                await self._cmd_list(session, tenant, chat_id, message_id, from_user, text)
            elif cmd == "/add":
                await self._cmd_add(session, tenant, chat_id, args, message_id, from_user, text)
            elif cmd == "/del":
                await self._cmd_del(session, tenant, chat_id, args, message_id, from_user, text)
            elif cmd == "/replace":
                await self._cmd_replace(session, tenant, chat_id, args, message_id, from_user, text)
            elif cmd == "/cek":
                await self._cmd_cek(session, tenant, chat_id, args, message_id, from_user, text)
            elif cmd == "/status":
                await self._cmd_status(session, tenant, chat_id, message_id, from_user, text)
            elif cmd in ("/help", "/start"):
                await self._cmd_help(session, tenant, chat_id, message_id, from_user, text)
            elif cmd == "/info":
                await self._cmd_info(session, tenant, chat_id, message_id, from_user, text)
            elif cmd in ("/katakatahariini", "/kata"):
                await self._cmd_katakatahariini(session, tenant, chat_id, message_id, from_user, text)

    # -------------------------------------------------------------
    # COMMAND HANDLERS
    # -------------------------------------------------------------

    async def _cmd_list(self, session, tenant: Tenant, chat_id: str, message_id: int, from_user: dict = None, raw_text: str = ""):
        """
        Handler perintah /list:
        Menampilkan daftar domain diurutkan alfabetis A-Z dengan penomoran urut 1, 2, 3...
        """
        stmt = (
            select(Domain)
            .where(Domain.tenant_id == tenant.id)
            .order_by(Domain.name.asc())
        )
        res = await session.execute(stmt)
        domains = res.scalars().all()

        total_domains = len(domains)
        quota = tenant.package_quota
        packet_no = max(1, quota // 10)

        now = now_jakarta_naive()
        remaining_days = max(0, (tenant.expired_date.date() - now.date()).days) if tenant.expired_date else 0
        exp_date_str = tenant.expired_date.strftime("%d %b %Y") if tenant.expired_date else "-"

        header = (
            f"📋 <b>DAFTAR DOMAIN MONITORING</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Grup: <b>{html.escape(tenant.name)}</b>\n"
            f"Paket: Paket {packet_no} ({quota} Domain)\n"
            f"Kuota Terpakai: <b>{total_domains} / {quota} Domain</b>\n"
            f"Masa Aktif: s/d {exp_date_str} ({remaining_days} hari lagi)\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        if not domains:
            body = "<i>(Belum ada domain yang didaftarkan pada grup ini)</i>\n\n"
        else:
            lines = []
            for idx, d in enumerate(domains, 1):
                safe_name = html.escape(d.name)
                # Status icon saja tanpa teks didalam []
                is_blocked = d.overall_status in ("BLOCKED", "MIXED")
                is_phishing = d.cf_status == "PHISHING"

                if is_phishing and is_blocked:
                    icon = "🟡🔴"
                elif is_phishing:
                    icon = "🟡"
                elif d.overall_status == "BLOCKED":
                    icon = "🔴"
                elif d.overall_status == "MIXED":
                    icon = "🟡"
                elif d.overall_status == "NORMAL":
                    icon = "🟢"
                else:
                    icon = "⚪"

                lines.append(f"{idx}. {icon} <code>{safe_name}</code>")
            body = "\n".join(lines) + "\n\n"

        footer = (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <b>Tips:</b>\n"
            f"• Tambah: <code>/add &lt;domain&gt;</code>\n"
            f"• Ganti: <code>/replace &lt;lama/nomor&gt; &lt;baru&gt;</code>\n"
            f"• Hapus: <code>/del &lt;nomor atau domain&gt;</code>\n"
            f"• Cek status: <code>/status</code>"
        )

        await self.send_message(chat_id, header + body + footer, reply_to_message_id=message_id)
        await self._log_activity(
            session, tenant, chat_id, from_user, "/list",
            f"Melihat daftar monitoring ({total_domains}/{quota} domain)",
            raw_text, status="SUCCESS"
        )

    async def _cmd_add(self, session, tenant: Tenant, chat_id: str, args: List[str], message_id: int, from_user: dict = None, raw_text: str = ""):
        """
        Handler perintah /add <domain> [domain2] [domain3] ...:
        Mendukung penambahan 1 domain atau banyak domain sekaligus (Bulk Add).
        """
        if not args:
            reply = (
                "❌ <b>FORMAT PERINTAH SALAH</b>\n\n"
                "Gunakan format:\n"
                "<code>/add &lt;nama_domain&gt;</code>\n\n"
                "Atau input banyak domain sekaligus (Bulk Add):\n"
                "<code>/add domain1.com domain2.com domain3.com</code>\n"
                "atau pisahkan dengan baris baru (enter)."
            )
            await self._log_activity(session, tenant, chat_id, from_user, "/add", "Format salah: Argumen kosong", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Ekstrak seluruh token domain (pisahkan spasi, koma, titik koma, dan enter)
        raw_token_text = " ".join(args)
        tokens = re.split(r'[\s,;]+', raw_token_text)

        # Bersihkan & buang duplikat dalam input sendiri
        seen = set()
        candidate_domains = []
        for token in tokens:
            cleaned = normalize_domain_bot(token)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                candidate_domains.append(cleaned)

        if not candidate_domains:
            reply = "❌ Tidak ada domain valid yang terdeteksi dalam perintah."
            await self._log_activity(session, tenant, chat_id, from_user, "/add", "Format salah: Tidak ada domain valid", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Ambil daftar domain yang sudah ada di tenant ini
        stmt_existing = select(Domain.name).where(Domain.tenant_id == tenant.id)
        existing_names = set((await session.execute(stmt_existing)).scalars().all())
        current_count = len(existing_names)
        available_quota = max(0, tenant.package_quota - current_count)

        # Cek jika kuota sudah penuh dari awal
        if available_quota <= 0:
            packet_no = max(1, tenant.package_quota // 10)
            reply = (
                "⚠️ <b>KUOTA PAKET TELAH PENUH!</b>\n\n"
                f"Grup Anda menggunakan <b>Paket {packet_no}</b> (Maksimal {tenant.package_quota} Domain).\n"
                f"Saat ini sudah terdaftar: <b>{current_count} / {tenant.package_quota} Domain</b>.\n\n"
                "Silakan hapus domain yang tidak aktif dengan perintah:\n"
                "<code>/del &lt;domain atau nomor&gt;</code>\n"
                "atau hubungi Admin untuk upgrade paket kuota."
            )
            await self._log_activity(session, tenant, chat_id, from_user, "/add", f"Gagal tambah domain: Kuota grup penuh ({current_count}/{tenant.package_quota})", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Klasifikasikan input domain
        to_add = []
        duplicates = []
        invalids = []
        quota_exceeded = []

        for d in candidate_domains:
            if not is_valid_domain(d):
                invalids.append(d)
            elif d in existing_names:
                duplicates.append(d)
            elif len(to_add) >= available_quota:
                quota_exceeded.append(d)
            else:
                to_add.append(d)

        # Jika tidak ada yang bisa ditambahkan
        if not to_add:
            if duplicates and not invalids and not quota_exceeded:
                reply = (
                    "ℹ️ <b>DOMAIN SUDAH TERDAFTAR</b>\n\n"
                    "Seluruh domain yang Anda masukkan sudah ada dalam daftar pemantauan grup ini.\n"
                    "Ketik <code>/list</code> untuk melihat daftar lengkap."
                )
            else:
                reply = "❌ <b>TIDAK ADA DOMAIN YANG BERHASIL DITAMBAHKAN</b>\n\n"
                if duplicates:
                    reply += f"• Duplikat (Sudah ada): {len(duplicates)} domain\n"
                if invalids:
                    reply += f"• Format tidak valid: {len(invalids)} domain\n"
                if quota_exceeded:
                    reply += f"• Melebihi kuota paket: {len(quota_exceeded)} domain\n"
            await self._log_activity(session, tenant, chat_id, from_user, "/add", f"Gagal tambah domain (Duplikat: {len(duplicates)}, Salah: {len(invalids)}, Kuota: {len(quota_exceeded)})", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Simpan domain yang lolos ke database
        added_objs = []
        for d in to_add:
            new_dom = Domain(
                user_id=1,
                tenant_id=tenant.id,
                name=d,
                category="Bot Input",
                overall_status="UNCHECKED",
                cf_status="CLEAN"
            )
            session.add(new_dom)
            added_objs.append(new_dom)

        await session.commit()
        for dom in added_objs:
            await session.refresh(dom)

        new_total = current_count + len(to_add)

        # Log activity
        added_str = ", ".join(to_add)
        extra = []
        if duplicates:
            extra.append(f"Duplikat: {', '.join(duplicates)}")
        if quota_exceeded:
            extra.append(f"Melebihi kuota: {', '.join(quota_exceeded)}")
        if invalids:
            extra.append(f"Salah format: {', '.join(invalids)}")
        detail_msg = f"Menambahkan {len(to_add)} domain: {added_str}"
        if extra:
            detail_msg += f" | ({'; '.join(extra)})"
        await self._log_activity(session, tenant, chat_id, from_user, "/add", detail_msg, raw_text, status="SUCCESS")

        # Jika hanya 1 domain yang di-input dan berhasil
        if len(candidate_domains) == 1 and len(to_add) == 1:
            reply = (
                "✅ <b>DOMAIN BERHASIL DITAMBAHKAN</b>\n\n"
                f"🌐 Domain: <code>{html.escape(to_add[0])}</code>\n"
                f"🏷️ Kategori: Bot Input\n"
                f"📊 Kuota Grup: <b>{new_total} / {tenant.package_quota} Domain</b>\n\n"
                "Domain langsung didaftarkan ke radar pemantauan 24/7. "
                "Anda akan menerima notifikasi otomatis jika terdeteksi blokir Nawala atau Cloudflare Phishing."
            )
        else:
            # Respon Bulk Add
            reply = (
                f"✅ <b>{len(to_add)} DOMAIN BERHASIL DITAMBAHKAN (BULK ADD)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Kuota Grup: <b>{new_total} / {tenant.package_quota} Domain</b>\n\n"
                "<b>Daftar Domain Ditambahkan:</b>\n"
            )
            for idx, d in enumerate(to_add, 1):
                reply += f"{idx}. <code>{html.escape(d)}</code>\n"

            if duplicates or quota_exceeded or invalids:
                reply += "\n━━━━━━━━━━━━━━━━━━━━\n<b>Keterangan Tambahan:</b>\n"
                if duplicates:
                    reply += f"• ℹ️ Sudah terdaftar (dilewati): {len(duplicates)} domain\n"
                if quota_exceeded:
                    reply += f"• ⚠️ Melebihi batas kuota (dilewati): {len(quota_exceeded)} domain\n"
                if invalids:
                    reply += f"• ❌ Format salah (dilewati): {len(invalids)} domain\n"

        await self.send_message(chat_id, reply, reply_to_message_id=message_id)

        # Trigger background check untuk domain-domain baru ini
        for dom in added_objs:
            asyncio.create_task(self._quick_check_domain(dom.id, dom.name, tenant))

    async def _cmd_del(self, session, tenant: Tenant, chat_id: str, args: List[str], message_id: int, from_user: dict = None, raw_text: str = ""):
        """
        Handler perintah /del <domain_atau_nomor> [domain2] [nomor2] ...:
        Mendukung penghapusan 1 atau banyak domain sekaligus (Bulk Delete).
        """
        if not args:
            reply = (
                "❌ <b>FORMAT PERINTAH SALAH</b>\n\n"
                "Gunakan format:\n"
                "<code>/del &lt;nama_domain atau nomor&gt;</code>\n\n"
                "Contoh:\n"
                "<code>/del slotgacor88.com</code>\n"
                "atau hapus banyak sekaligus (Bulk Delete):\n"
                "<code>/del 1 2 3</code> atau <code>/del domain1.com domain2.com</code>"
            )
            await self._log_activity(session, tenant, chat_id, from_user, "/del", "Format salah: Argumen kosong", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Ambil seluruh domain grup terurut alfabetis A-Z
        stmt_all = (
            select(Domain)
            .where(Domain.tenant_id == tenant.id)
            .order_by(Domain.name.asc())
        )
        all_domains = (await session.execute(stmt_all)).scalars().all()
        name_to_domain = {d.name: d for d in all_domains}

        # Ekstrak seluruh argumen
        raw_arg_text = " ".join(args)
        tokens = re.split(r'[\s,;]+', raw_arg_text)

        deleted_domains = []
        not_found = []

        for token in tokens:
            token = token.strip()
            if not token:
                continue

            target = None
            if token.isdigit():
                idx = int(token) - 1
                if 0 <= idx < len(all_domains):
                    target = all_domains[idx]
            else:
                norm_d = normalize_domain_bot(token)
                target = name_to_domain.get(norm_d)

            if target and target not in deleted_domains:
                deleted_domains.append(target)
            elif not target:
                not_found.append(token)

        if not deleted_domains:
            reply = (
                "❌ <b>DOMAIN TIDAK DITEMUKAN</b>\n\n"
                f"Domain atau nomor urut yang Anda masukkan tidak terdaftar di grup ini.\n"
                "Ketik <code>/list</code> untuk memeriksa daftar domain Anda."
            )
            await self._log_activity(session, tenant, chat_id, from_user, "/del", f"Gagal hapus: Domain tidak ditemukan ({', '.join(tokens[:5])})", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Hapus domain dari database
        del_names = [d.name for d in deleted_domains]
        for d in deleted_domains:
            await session.delete(d)
        await session.commit()

        remaining_count = max(0, len(all_domains) - len(deleted_domains))

        # Log activity
        del_str = ", ".join(del_names)
        del_detail = f"Menghapus {len(del_names)} domain: {del_str}"
        if not_found:
            del_detail += f" | (Tidak ditemukan: {', '.join(not_found)})"
        await self._log_activity(session, tenant, chat_id, from_user, "/del", del_detail, raw_text, status="SUCCESS")

        if len(deleted_domains) == 1:
            d_name = deleted_domains[0].name
            reply = (
                "🗑️ <b>DOMAIN BERHASIL DIHAPUS</b>\n\n"
                f"Domain <code>{html.escape(d_name)}</code> telah dihapus dari daftar monitoring grup ini.\n"
                f"📊 Sisa Kuota: <b>{remaining_count} / {tenant.package_quota} Domain</b>.\n\n"
                "Sistem tidak akan lagi mengirimkan notifikasi apapun terkait domain tersebut ke grup ini."
            )
        else:
            reply = (
                f"🗑️ <b>{len(deleted_domains)} DOMAIN BERHASIL DIHAPUS (BULK DELETE)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Sisa Kuota: <b>{remaining_count} / {tenant.package_quota} Domain</b>\n\n"
                "<b>Domain yang Dihapus:</b>\n"
            )
            for idx, d in enumerate(deleted_domains, 1):
                reply += f"{idx}. <code>{html.escape(d.name)}</code>\n"

            if not_found:
                reply += f"\n• ℹ️ Tidak ditemukan (dilewati): {', '.join(not_found)}\n"

            reply += "\nSistem tidak akan lagi mengirimkan notifikasi apapun terkait domain tersebut ke grup ini."

        await self.send_message(chat_id, reply, reply_to_message_id=message_id)

    async def _cmd_replace(self, session, tenant: Tenant, chat_id: str, args: List[str], message_id: int, from_user: dict = None, raw_text: str = ""):
        """
        Handler perintah /replace <old_domain_or_number> <new_domain>:
        Mengganti domain terblokir dengan link domain baru secara langsung.
        """
        if len(args) < 2:
            reply = (
                "❌ <b>FORMAT PERINTAH SALAH</b>\n\n"
                "Gunakan format:\n"
                "<code>/replace &lt;domain_lama/nomor&gt; &lt;domain_baru&gt;</code>\n\n"
                "Contoh:\n"
                "<code>/replace nagawinxtra.com linkbaru.com</code>\n"
                "atau menggunakan nomor urut dari /list:\n"
                "<code>/replace 1 linkbaru.com</code>"
            )
            await self._log_activity(session, tenant, chat_id, from_user, "/replace", "Format salah: Membutuhkan domain lama & baru", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        old_arg = args[0].strip()
        new_arg = args[1].strip()

        # Ambil seluruh domain grup terurut alfabetis A-Z
        stmt_all = (
            select(Domain)
            .where(Domain.tenant_id == tenant.id)
            .order_by(Domain.name.asc())
        )
        all_domains = (await session.execute(stmt_all)).scalars().all()
        name_to_domain = {d.name: d for d in all_domains}

        # Cari target domain lama
        target_domain = None
        if old_arg.isdigit():
            idx = int(old_arg) - 1
            if 0 <= idx < len(all_domains):
                target_domain = all_domains[idx]
        else:
            norm_old = normalize_domain_bot(old_arg)
            target_domain = name_to_domain.get(norm_old)

        if not target_domain:
            reply = (
                "❌ <b>DOMAIN LAMA TIDAK DITEMUKAN</b>\n\n"
                f"Domain atau nomor urut <code>{html.escape(old_arg)}</code> tidak terdaftar di grup ini.\n"
                "Ketik <code>/list</code> untuk memeriksa daftar domain Anda."
            )
            await self._log_activity(session, tenant, chat_id, from_user, "/replace", f"Gagal: Domain lama '{old_arg}' tidak ditemukan", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Validasi domain baru
        new_domain = normalize_domain_bot(new_arg)
        if not is_valid_domain(new_domain):
            reply = (
                "❌ <b>FORMAT DOMAIN BARU TIDAK VALID</b>\n\n"
                f"Nama domain <code>{html.escape(new_arg)}</code> tidak valid. "
                "Pastikan format penulisan domain benar (contoh: <code>linkbaru.com</code>)."
            )
            await self._log_activity(session, tenant, chat_id, from_user, "/replace", f"Gagal: Format domain baru '{new_arg}' tidak valid", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Cek apakah domain baru sudah ada di grup ini
        if new_domain in name_to_domain:
            reply = (
                "⚠️ <b>DOMAIN BARU SUDAH TERDAFTAR</b>\n\n"
                f"Domain <code>{html.escape(new_domain)}</code> sudah ada dalam daftar pemantauan grup ini."
            )
            await self._log_activity(session, tenant, chat_id, from_user, "/replace", f"Gagal: Domain baru '{new_domain}' sudah terdaftar di grup", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Lakukan pergantian domain
        old_name = target_domain.name
        target_domain.name = new_domain
        target_domain.overall_status = "UNCHECKED"
        target_domain.cf_status = "CLEAN"
        target_domain.cf_reason = None
        target_domain.last_checked_at = None
        target_domain.last_alerted_at = None

        # Hapus riwayat CheckResult lama
        stmt_del_cr = select(CheckResult).where(CheckResult.domain_id == target_domain.id)
        cr_res = await session.execute(stmt_del_cr)
        for cr in cr_res.scalars().all():
            await session.delete(cr)

        await session.commit()
        await session.refresh(target_domain)

        await self._log_activity(session, tenant, chat_id, from_user, "/replace", f"Mengganti domain: '{old_name}' ➔ '{new_domain}'", raw_text, status="SUCCESS")

        reply = (
            "🔄 <b>DOMAIN BERHASIL DIGANTI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔴 Domain Lama: <code>{html.escape(old_name)}</code>\n"
            f"🟢 Domain Baru: <code>{html.escape(new_domain)}</code>\n"
            f"🏷️ Kategori: {html.escape(target_domain.category or 'General')}\n\n"
            "Domain baru langsung didaftarkan ke radar pemantauan 24/7 dan sedang dicek statusnya..."
        )
        await self.send_message(chat_id, reply, reply_to_message_id=message_id)

        # Trigger pengecekan langsung untuk domain baru
        asyncio.create_task(self._quick_check_domain(target_domain.id, new_domain, tenant))

    async def _cmd_cek(self, session, tenant: Tenant, chat_id: str, args: List[str], message_id: int, from_user: dict = None, raw_text: str = ""):
        """
        Handler perintah /cek <domain>:
        Cek instan status Nawala & Cloudflare saat itu juga tanpa perlu disimpan ke list.
        """
        if not args:
            reply = (
                "❌ <b>FORMAT PERINTAH SALAH</b>\n\n"
                "Gunakan format:\n"
                "<code>/cek &lt;nama_domain&gt;</code>\n\n"
                "Contoh:\n"
                "<code>/cek slotgacor88.com</code>"
            )
            await self._log_activity(session, tenant, chat_id, from_user, "/cek", "Format salah: Argumen domain kosong", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        domain_name = normalize_domain_bot(args[0])
        if not is_valid_domain(domain_name):
            reply = "❌ Format domain tidak valid."
            await self._log_activity(session, tenant, chat_id, from_user, "/cek", f"Gagal: Format domain '{domain_name}' tidak valid", raw_text, status="FAILED")
            await self.send_message(chat_id, reply, reply_to_message_id=message_id)
            return

        # Beri pesan awal sedang memeriksa
        wait_msg = f"🔍 Sedang memeriksa status <code>{html.escape(domain_name)}</code> di 4 operator & Cloudflare..."
        await self.send_message(chat_id, wait_msg, reply_to_message_id=message_id)

        # Jalankan cek batch 1 domain
        res_list = await checker_engine.check_batch_domains([domain_name])
        if not res_list:
            await self._log_activity(session, tenant, chat_id, from_user, "/cek", f"Gagal periksa domain '{domain_name}': Engine error", raw_text, status="FAILED")
            await self.send_message(chat_id, "❌ Terjadi kesalahan saat memeriksa domain.", reply_to_message_id=message_id)
            return

        data = res_list[0]
        overall = data.get("overall_status", "NORMAL")
        cf_raw = data.get("cf_status", "CLEAN")
        cf_status = "CLEAN" if cf_raw == "NORMAL" else cf_raw
        op_results = data.get("operator_results", {})

        await self._log_activity(session, tenant, chat_id, from_user, "/cek", f"Cek domain '{domain_name}' ➔ Status: {overall}, CF: {cf_status}", raw_text, status="SUCCESS")

        def op_badge(st: str) -> str:
            if st == "BLOCKED":
                return "🔴 TERBLOKIR"
            elif st == "NORMAL":
                return "🟢 NORMAL"
            return "⚪ ERROR / UNKNOWN"

        tsel_st = op_badge(op_results.get("Telkomsel", {}).get("status", "NORMAL"))
        xl_st = op_badge(op_results.get("XL", {}).get("status", "NORMAL"))
        im3_st = op_badge(op_results.get("IM3", {}).get("status", "NORMAL"))
        tri_st = op_badge(op_results.get("Tri", {}).get("status", "NORMAL"))

        cf_tag = "⚠️ <b>SUSPECTED PHISHING</b>" if cf_status == "PHISHING" else "🟢 <b>AMAN (Clean)</b>"

        # Evaluasi status keseluruhan dengan memperhitungkan Cloudflare Phishing
        if cf_status == "PHISHING" and overall in ("BLOCKED", "MIXED"):
            overall_tag = "🚨 <b>TERBLOKIR NAWALA & CLOUDFLARE PHISHING!</b>"
            warning_banner = (
                "\n⚠️ <b>PERINGATAN GANDA:</b>\n"
                "Domain ini terblokir Nawala ISP sekaligus terkena Suspected Phishing di Cloudflare!\n"
                "Pengunjung/pemain akan terhalang oleh layar peringatan merah.\n"
            )
        elif cf_status == "PHISHING":
            overall_tag = "⚠️ <b>TERDETEKSI CLOUDFLARE PHISHING!</b>"
            warning_banner = (
                "\n⚠️ <b>PERINGATAN KEAMANAN:</b>\n"
                "Domain ini terdeteksi <b>Suspected Phishing</b> oleh sistem Cloudflare!\n"
                "Pengunjung yang membuka link ini akan melihat layar merah peringatan keamanan.\n"
            )
        elif overall == "BLOCKED":
            overall_tag = "🔴 <b>TERBLOKIR NAWALA</b>"
            warning_banner = (
                "\n🔴 <b>PERINGATAN PEMBLOKIRAN:</b>\n"
                "Domain ini terblokir oleh Nawala / Kominfo di jaringan operator Indonesia.\n"
            )
        elif overall == "MIXED":
            overall_tag = "🟡 <b>SEBAGIAN TERBLOKIR ISP</b>"
            warning_banner = (
                "\n🟡 <b>PERINGATAN:</b>\n"
                "Domain ini terblokir di sebagian operator seluler Indonesia.\n"
            )
        else:
            overall_tag = "🟢 <b>AMAN / NORMAL</b>"
            warning_banner = ""

        reply = (
            f"🔍 <b>HASIL PENGECEKAN INSTAN</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 Domain: <code>{html.escape(domain_name)}</code>\n"
            f"📊 Status Keseluruhan: {overall_tag}\n\n"
            f"📱 <b>Status Operator ISP:</b>\n"
            f"• Telkomsel: {tsel_st}\n"
            f"• XL Axiata: {xl_st}\n"
            f"• Indosat (IM3): {im3_st}\n"
            f"• Tri (3): {tri_st}\n\n"
            f"🛡️ <b>Status Cloudflare:</b> {cf_tag}\n"
            f"{warning_banner}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 Ketik <code>/add {html.escape(domain_name)}</code> untuk memasukkannya ke radar pemantauan 24/7."
        )
        await self.send_message(chat_id, reply, reply_to_message_id=message_id)

    async def _cmd_status(self, session, tenant: Tenant, chat_id: str, message_id: int, from_user: dict = None, raw_text: str = ""):
        """
        Handler perintah /status:
        Ringkasan performa grup, kuota, dan masa sewa.
        """
        stmt = select(Domain).where(Domain.tenant_id == tenant.id)
        domains = (await session.execute(stmt)).scalars().all()

        total = len(domains)
        normal_count = sum(1 for d in domains if d.overall_status == "NORMAL" and d.cf_status != "PHISHING")
        blocked_count = sum(1 for d in domains if d.overall_status in ("BLOCKED", "MIXED"))
        phishing_count = sum(1 for d in domains if d.cf_status == "PHISHING")

        now = now_jakarta_naive()
        remaining_days = max(0, (tenant.expired_date.date() - now.date()).days) if tenant.expired_date else 0
        exp_date_str = tenant.expired_date.strftime("%d %b %Y") if tenant.expired_date else "-"
        packet_no = max(1, tenant.package_quota // 10)

        reply = (
            f"📊 <b>STATUS & PERFORMA MONITORING</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ Grup: <b>{html.escape(tenant.name)}</b>\n"
            f"📦 Paket: <b>Paket {packet_no} ({tenant.package_quota} Domain)</b>\n"
            f"📈 Penggunaan Kuota: <b>{total} / {tenant.package_quota} Domain</b>\n\n"
            f"🟢 Domain Aman (Normal): <b>{normal_count}</b>\n"
            f"🔴 Domain Terblokir Nawala: <b>{blocked_count}</b>\n"
            f"🟡 Cloudflare Phishing: <b>{phishing_count}</b>\n\n"
            f"⏳ Masa Aktif: s/d <b>{exp_date_str}</b> ({remaining_days} hari lagi)\n"
            f"🤖 Status Bot: 🟢 <b>Aktif & Terlindungi</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Ketik <code>/list</code> untuk melihat daftar lengkap domain."
        )
        await self._log_activity(session, tenant, chat_id, from_user, "/status", f"Melihat status grup (Total: {total}, Normal: {normal_count}, Terblokir: {blocked_count}, Phishing: {phishing_count})", raw_text, status="SUCCESS")
        await self.send_message(chat_id, reply, reply_to_message_id=message_id)

    async def _cmd_help(self, session, tenant: Tenant, chat_id: str, message_id: int, from_user: dict = None, raw_text: str = ""):
        """
        Handler perintah /help:
        Daftar panduan lengkap perintah bot.
        """
        reply = (
            "📖 <b>PANDUAN PENGGUNAAN BOT NAWALA SENTINEL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Berikut perintah yang dapat Anda gunakan di grup ini:\n\n"
            "• <code>/list</code> : Melihat daftar domain & status monitoring (A - Z)\n"
            "• <code>/add &lt;domain1&gt; [domain2] ...</code> : Menambahkan satu atau banyak domain (Bulk Add)\n"
            "• <code>/replace &lt;domain_lama/nomor&gt; &lt;domain_baru&gt;</code> : Mengganti domain lama dengan baru\n"
            "• <code>/del &lt;domain/nomor&gt; ...</code> : Menghapus satu atau banyak domain (Bulk Delete)\n"
            "• <code>/cek &lt;domain&gt;</code> : Cek status Nawala & Cloudflare secara instan\n"
            "• <code>/status</code> : Ringkasan performa domain & sisa masa sewa bot\n"
            "• <code>/info</code> : Informasi paket sewa & kontak Admin perpanjangan\n"
            "• <code>/katakatahariini</code> : Kata-kata lucu & penghibur hari ini 🎭\n"
            "• <code>/help</code> : Menampilkan pesan bantuan ini\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ <i>Sistem memantau 4 operator (Telkomsel, XL, IM3, Tri) dan Cloudflare Phishing secara nonstop 24/7.</i>"
        )
        await self._log_activity(session, tenant, chat_id, from_user, "/help", "Melihat panduan bantuan bot", raw_text, status="SUCCESS")
        await self.send_message(chat_id, reply, reply_to_message_id=message_id)

    async def _cmd_info(self, session, tenant: Tenant, chat_id: str, message_id: int, from_user: dict = None, raw_text: str = ""):
        """
        Handler perintah /info:
        Informasi kepemilikan paket dan perpanjangan sewa.
        """
        now = now_jakarta_naive()
        remaining_days = max(0, (tenant.expired_date.date() - now.date()).days) if tenant.expired_date else 0
        exp_date_str = tenant.expired_date.strftime("%d %b %Y") if tenant.expired_date else "-"
        packet_no = max(1, tenant.package_quota // 10)

        reply = (
            "ℹ️ <b>INFORMASI LANGGANAN BOT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Pelanggan: <b>{html.escape(tenant.name)}</b>\n"
            f"📱 Kontak Terdaftar: {html.escape(tenant.contact or '-')}\n"
            f"🆔 ID Grup: <code>{tenant.telegram_chat_id}</code>\n"
            f"📦 Paket: <b>Paket {packet_no} ({tenant.package_quota} Domain)</b>\n"
            f"📅 Tanggal Mulai: {tenant.start_date.strftime('%d %b %Y') if tenant.start_date else '-'}\n"
            f"⏳ Masa Berakhir: <b>{exp_date_str}</b> ({remaining_days} hari lagi)\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💬 <b>Perpanjangan / Upgrade Kuota:</b>\n"
            f"Silakan hubungi Admin melalui kontak resmi untuk melakukan perpanjangan masa sewa."
        )
        await self._log_activity(session, tenant, chat_id, from_user, "/info", f"Melihat info langganan (Paket {packet_no}, Masa aktif s/d {exp_date_str})", raw_text, status="SUCCESS")
        await self.send_message(chat_id, reply, reply_to_message_id=message_id)

    async def _cmd_katakatahariini(self, session, tenant: Tenant, chat_id: str, message_id: int, from_user: dict = None, raw_text: str = ""):
        """
        Handler perintah /katakatahariini:
        Menampilkan kata-kata lucu, kocak, dan menghibur untuk anggota grup.
        """
        quotes = [
            "Kerja keraslah sampai tetangga mengira kamu pelihara tuyul, bukan malah kerja keras sampai kamu yang jadi tuyulnya. 🗿",
            "Jangan pernah menyerah! Kalau capek ya tidur, bukan malah depresi mikirin cicilan. 🛌",
            "Uang bukan segalanya, tapi kalau nggak ada uang, segalanya berasa nggak ada apa-apanya. 💸",
            "Hidup itu seperti naik sepeda. Supaya tetap seimbang, ya jangan lupa ngegas... tapi kalau ada jurang ya ngerem, jangan bablas! 🚲",
            "Semua orang punya masalah, yang membedakan cuma ada yang update status sama yang diam-diam ngopi sambil overthinking. ☕",
            "Harta, tahta, tapi kok masih rebahan terus ya? Bangun woi, mimpi jadi sultan tapi tidur 14 jam sehari! 👑",
            "Jangan bangga dipanggil 'sayang', kelinci di pasar malam juga dipanggil sayang pas mau dibeli. 🐰",
            "Rezeki itu sudah ada yang ngatur. Kalau rezekimu belum kelihatan, mungkin kamu belum ngikutin petunjuk arahnya. 🗺️",
            "Secangkir kopi di pagi hari mengajarkan kita bahwa hidup ini pahit, tapi kalau ditambah gula ya manis... kalau kebanyakan gula ya kena diabetes. ☕",
            "Masa depan itu misteri, masa lalu itu kenangan, dan hari ini adalah kesempatan... kesempatan buat tidur siang lagi. 😴",
            "Kalau ada orang yang bilang kamu jelek, jangan sedih. Belum tentu dia salah kok. 😂",
            "Jangan suka mengulur waktu, karena waktu tidak bisa melar seperti karet kolor. 🩳",
            "Kegagalan adalah keberhasilan yang tertunda... tapi kalau gagal terus, ya mungkin memang bukan bakatmu di situ, coba jualan seblak aja. 🍜",
            "Pekerjaan seberat apapun akan terasa ringan, jika tidak dikerjakan sama sekali. 🧠",
            "Sahabat sejati adalah mereka yang tahu kamu rada gila, tapi tetap bangga jalan bareng kamu di tempat umum. 🤝",
            "Jangan berharap hidup ini mudah, berharaplah kamu punya uang banyak biar masalahnya bisa diselesaikan pakai duit. 💳",
            "Di balik pria yang sukses, ada wanita hebat di belakangnya. Di balik pria yang bangkrut, ada diskon checkout Shopee 12.12. 🛍️",
            "Gaji itu seperti mantan, cuma numpang lewat beberapa hari terus ngilang tanpa jejak. 📉",
            "Hidup itu sebentar, yang lama itu nunggu balasan chat dari dia yang kamu suka. 📱",
            "Tuhan tidak akan memberi cobaan di luar batas kemampuan hamba-Nya... tapi kadang kita sendiri yang hobi nambah-nambahin masalah. 🤦‍♂️",
            "Tetaplah bernapas, karena kalau kamu berhenti bernapas, nanti keluarga kamu yang repot nyiapin tenda kuning. ⛺",
            "Rumput tetangga memang selalu lebih hijau, tapi tagihan listrik tetangga siapa yang tahu? Jangan suka banding-bandingin! 🌾",
            "Kalau kamu merasa tidak berguna di dunia ini, ingatlah bahwa pohon butuh karbon dioksida dari napasmu. Jadi tetaplah bernapas! 🌳",
            "Jangan takut mencoba hal baru, takutlah kalau saldo ATM kamu tiba-tiba tinggal 12 ribu pas tanggal tua. 🏧",
            "Hidup ini penuh kejutan. Baru mau semangat kerja, eh udah jam pulang kantor. ⏰",
            "Jika rencanamu gagal, santai saja. Alfabet masih punya 25 huruf lainnya dari B sampai Z. 🔤",
            "Cinta itu buta, tapi tetangga sebelah matanya tajem banget kalau lihat kamu bawa gebetan baru ke rumah. 👀",
            "Jangan pernah lupa bersyukur hari ini, minimal kamu masih bisa scroll Telegram sambil ketawa sendirian kayak orang gila. 🤣",
            "Setiap hari adalah lembaran baru, tapi kok ceritanya bolak-balik rebahan lagi rebahan lagi. 📖",
            "Kunci sukses adalah konsistensi... konsisten mengeluh tapi besoknya tetap berangkat kerja juga. 💼",
            "Jangan stres karena pekerjaan, ingatlah bahwa kantor bisa mencari penggantimu dalam 3 hari, tapi keluarga tidak akan pernah bisa menggantikanmu. Jadi santai saja! 🛋️",
            "Hati-hati di jalan, karena kalau di hati aku, kamu udah ada yang punya. 💔",
            "Bekerjalah seperti tuyul: nggak kelihatan, nggak banyak omong, tapi uangnya banyak! 👻"
        ]
        quote = random.choice(quotes)
        reply = (
            "🎭 <b>KATA-KATA HARI INI</b> 🎭\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<i>\"{quote}\"</i>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Ketik <code>/katakatahariini</code> lagi kalau butuh asupan tawa berikutnya!</i>"
        )
        await self._log_activity(session, tenant, chat_id, from_user, "/katakatahariini", "Melihat kata-kata hari ini", raw_text, status="SUCCESS")
        await self.send_message(chat_id, reply, reply_to_message_id=message_id)

    async def _quick_check_domain(self, domain_id: int, domain_name: str, tenant: Tenant):
        """
        Background task: melakukan pengecekan awal saat domain baru di-add.
        """
        try:
            results = await checker_engine.check_batch_domains([domain_name])
            if not results:
                return

            res_data = results[0]
            overall = res_data.get("overall_status", "NORMAL")
            cf_raw = res_data.get("cf_status", "CLEAN")
            cf_status = "CLEAN" if cf_raw == "NORMAL" else cf_raw
            cf_reason = res_data.get("cf_reason", "")
            op_results = res_data.get("operator_results", {})

            async with AsyncSessionLocal() as session:
                d = await session.get(Domain, domain_id)
                if not d:
                    return

                d.overall_status = overall
                d.cf_status = cf_status
                d.cf_reason = cf_reason
                d.last_checked_at = now_jakarta_naive()

                for op_name, op_val in op_results.items():
                    cr = CheckResult(
                        domain_id=d.id,
                        operator=op_name,
                        status=op_val["status"],
                        resolved_ips=op_val["resolved_ips"],
                        block_reason=op_val["block_reason"],
                        latency_ms=op_val["latency_ms"],
                        checked_at=now_jakarta_naive()
                    )
                    session.add(cr)

                await session.commit()

            # Jika ternyata domain yang baru di-add langsung terdeteksi BLOCKED atau PHISHING, kirim alert
            if overall in ("BLOCKED", "MIXED") or cf_status == "PHISHING":
                from app.notifier import notifier
                await notifier.notify_tenant_domain_alert(
                    domain_name=domain_name,
                    tenant=tenant,
                    overall_status=overall,
                    cf_status=cf_status,
                    operator_results=op_results,
                    reason="Terdeteksi saat pendaftaran awal domain",
                    is_recovery=False,
                    is_reminder=False
                )
                async with AsyncSessionLocal() as session:
                    d = await session.get(Domain, domain_id)
                    if d:
                        d.last_alerted_at = now_jakarta_naive()
                        await session.commit()

        except Exception as e:
            logger.error(f"❌ [TELEGRAM BOT] Error quick check domain {domain_name}: {e}")


# Global instance
telegram_bot_engine = TelegramBotEngine()
