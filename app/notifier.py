import html
import httpx
import logging
from typing import Dict, Any, Optional

from app.config import settings
from app.utils.timezone import now_jakarta

logger = logging.getLogger("nawala_notifier")

class TelegramNotifier:
    """
    Sistem Alerting & Notifikasi Telegram / Webhook Real-Time
    untuk Perubahan Status Pemblokiran Domain.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID

    async def send_telegram_message(self, text: str, parse_mode: str = "HTML", chat_id: Optional[str] = None) -> bool:
        """
        Kirim pesan ke Telegram Chat / Channel menggunakan Bot API.
        """
        target_chat_id = chat_id or self.chat_id
        token = self.bot_token or settings.TELEGRAM_BOT_TOKEN
        if not token or not target_chat_id:
            logger.warning("Telegram Bot Token atau Chat ID belum dikonfigurasi.")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    logger.info("Notifikasi Telegram berhasil dikirim.")
                    return True
                else:
                    logger.error(f"Gagal mengirim notifikasi Telegram: {response.text}")
                    return False
            except Exception as e:
                logger.error(f"Error saat menghubungi Telegram API: {e}")
                return False

    async def notify_status_change(self, domain_name: str, operator: str, old_status: str, new_status: str, reason: str, ips: str = "", cf_status: str = "CLEAN", chat_id: Optional[str] = None):
        """
        Mengirim notifikasi otomatis saat domain berubah dari NORMAL -> BLOCKED atau sebaliknya.
        """
        if new_status == "BLOCKED":
            emoji = "🚨"
            header_title = "ALERT: DOMAIN TERBLOKIR NAWALA!"
            status_color = "<b>TERBLOKIR (BLOCKED)</b>"
        else:
            emoji = "✅"
            header_title = "UPDATE: DOMAIN KEMBALI NORMAL"
            status_color = "<b>AKTIF (NORMAL)</b>"
        
        timestamp_str = now_jakarta().strftime("%Y-%m-%d %H:%M:%S WIB")

        safe_domain = html.escape(domain_name)
        safe_operator = html.escape(operator)
        safe_reason = html.escape(reason)
        safe_ips = html.escape(ips)

        message = (
            f"{emoji} <b>{header_title}</b> {emoji}\n\n"
            f"🌐 <b>Domain:</b> <code>{safe_domain}</code>\n"
            f"📱 <b>Operator:</b> {safe_operator}\n"
            f"🔄 <b>Status ISP:</b> {old_status} -> {status_color}\n"
        )

        if cf_status == "PHISHING":
            message += f"🛡️ <b>Status Cloudflare:</b> ⚠️ <b>SUSPECTED PHISHING</b>\n"
            if new_status == "BLOCKED":
                message += f"🚨 <b>PERHATIAN GANDA:</b> Domain ini terblokir Nawala ISP SEKALIGUS terkena Suspected Phishing di Cloudflare!\n"

        message += f"🔍 <b>Keterangan:</b> {safe_reason}\n"
        
        if safe_ips:
            message += f"📌 <b>IP Terdeteksi:</b> <code>{safe_ips}</code>\n"
            
        message += f"\n⏰ <i>Waktu Deteksi: {timestamp_str}</i>"

        # 1. Kirim Notifikasi Telegram jika diaktifkan
        target_chat = chat_id or self.chat_id
        if settings.TELEGRAM_ALERTS_ENABLED and target_chat:
            await self.send_telegram_message(message, chat_id=target_chat)

        # 2. Kirim Webhook (jika dikonfigurasi)
        if settings.WEBHOOK_ALERTS_ENABLED and settings.WEBHOOK_URL:
            await self.send_webhook_alert({
                "event": "domain_status_changed",
                "domain": domain_name,
                "operator": operator,
                "old_status": old_status,
                "new_status": new_status,
                "cf_status": cf_status,
                "reason": reason,
                "ips": ips,
                "timestamp": timestamp_str
            })

    async def notify_cloudflare_status(self, domain_name: str, cf_status: str, cf_reason: str, isp_status: str = "NORMAL", chat_id: Optional[str] = None):
        """
        Mengirim notifikasi otomatis saat status Cloudflare berubah (terkena Suspected Phishing atau pulih).
        """
        if cf_status == "PHISHING":
            emoji = "⚠️"
            header_title = "ALERT: CLOUDFLARE SUSPECTED PHISHING!"
            cf_text = "<b>SUSPECTED PHISHING</b>"
        else:
            emoji = "✅"
            header_title = "UPDATE: CLOUDFLARE STATUS AMAN (CLEAN)"
            cf_text = "<b>CLEAN / NORMAL</b>"

        timestamp_str = now_jakarta().strftime("%Y-%m-%d %H:%M:%S WIB")

        safe_domain = html.escape(domain_name)
        safe_reason = html.escape(cf_reason)

        message = (
            f"{emoji} <b>{header_title}</b> {emoji}\n\n"
            f"🌐 <b>Domain:</b> <code>{safe_domain}</code>\n"
            f"🛡️ <b>Status Cloudflare:</b> {cf_text}\n"
            f"📱 <b>Status Nawala ISP:</b> <b>{isp_status}</b>\n"
            f"🔍 <b>Keterangan:</b> {safe_reason}\n"
        )
        if cf_status == "PHISHING" and isp_status in ("BLOCKED", "MIXED"):
            message += f"🚨 <b>PERHATIAN GANDA:</b> Domain ini terblokir Nawala ISP ({isp_status}) SEKALIGUS terkena Suspected Phishing di Cloudflare!\n"

        message += f"\n⏰ <i>Waktu Deteksi: {timestamp_str}</i>"

        target_chat = chat_id or self.chat_id
        if settings.TELEGRAM_ALERTS_ENABLED and target_chat:
            await self.send_telegram_message(message, chat_id=target_chat)

        if settings.WEBHOOK_ALERTS_ENABLED and settings.WEBHOOK_URL:
            await self.send_webhook_alert({
                "event": "cloudflare_status_changed",
                "domain": domain_name,
                "cf_status": cf_status,
                "isp_status": isp_status,
                "reason": cf_reason,
                "timestamp": timestamp_str
            })

    async def send_webhook_alert(self, payload: Dict[str, Any]) -> bool:
        """
        Kirim notifikasi ke generic HTTP Webhook (Slack, Discord, Custom API).
        """
        if not settings.WEBHOOK_URL:
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(settings.WEBHOOK_URL, json=payload)
                return response.status_code in (200, 201, 202, 204)
            except Exception as e:
                logger.error(f"Error mengirim Webhook alert: {e}")
                return False

    async def notify_tenant_domain_alert(
        self,
        domain_name: str,
        tenant: Any,
        overall_status: str,
        cf_status: str,
        operator_results: Optional[Dict[str, Any]] = None,
        reason: str = "Terdeteksi pemblokiran DNS / Sinkhole",
        is_recovery: bool = False,
        is_reminder: bool = False
    ):
        """
        Mengirim notifikasi khusus ke grup pelanggan / tenant:
        - is_recovery=True: Notifikasi domain kembali normal
        - is_reminder=True: Peringatan kedua dst. yang super simpel & ringkas agar tidak memenuhi layar
        - is_reminder=False: Peringatan pertama yang jelas, padat, dan disertai rekomendasi /replace & /del
        """
        if not tenant or not tenant.telegram_chat_id:
            return

        chat_id = tenant.telegram_chat_id
        tenant_name = tenant.name if hasattr(tenant, "name") else "Grup"
        safe_domain = html.escape(domain_name)
        safe_tenant = html.escape(tenant_name)
        timestamp_str = now_jakarta().strftime("%d %b %Y %H:%M WIB")

        # 1. NOTIFIKASI DOMAIN KEMBALI NORMAL
        if is_recovery:
            message = (
                "✅ <b>Pemberitahuan: Domain Kembali Normal</b>\n\n"
                f"🌐 Domain: <code>{safe_domain}</code>\n"
                f"📊 Status: <b>NORMAL / CLEAN</b>\n"
                f"🏷️ Grup: <b>{safe_tenant}</b>\n"
                f"⏰ Waktu: {timestamp_str}\n\n"
                "Domain sudah dapat diakses normal kembali di seluruh jaringan ISP."
            )
            await self.send_telegram_message(message, chat_id=chat_id)
            return

        # 2. PERINGATAN KEDUA & SETERUSNYA (REMINDER ALERT - SUPER SIMPEL)
        if is_reminder:
            if cf_status == "PHISHING" and overall_status in ("BLOCKED", "MIXED"):
                header = f"❌ <b>{safe_domain} Komdigi & Phishing Alert!</b> ❌"
            elif cf_status == "PHISHING":
                header = f"⚠️ <b>{safe_domain} Phishing Alert!</b> ⚠️"
            else:
                header = f"❌ <b>{safe_domain} Komdigi Alert!</b> ❌"

            message = (
                f"{header}\n\n"
                f"⏰ Pengecekan: {timestamp_str}\n\n"
                f"⚡ Ganti: <code>/replace {safe_domain} linkbaru.com</code>\n"
                f"🗑️ Hapus: <code>/del {safe_domain}</code>"
            )
            await self.send_telegram_message(message, chat_id=chat_id)
            return

        # 3. PERINGATAN PERTAMA (FIRST ALERT - ULTRA RINGKAS)
        if cf_status == "PHISHING" and overall_status in ("BLOCKED", "MIXED"):
            header = "🚨 <b>Peringatan: Nawala & Phishing!</b>"
        elif cf_status == "PHISHING":
            header = "⚠️ <b>Peringatan: Cloudflare Phishing!</b>"
        else:
            header = "🔴 <b>Peringatan: Domain Terblokir!</b>"

        message = (
            f"{header}\n\n"
            f"❌ <b>{safe_domain}</b> ❌\n\n"
            f"💡 <b>Rekomendasi Tindakan:</b>\n"
            f"• Ganti: <code>/replace {safe_domain} linkbaru.com</code>\n"
            f"• Hapus: <code>/del {safe_domain}</code>"
        )

        await self.send_telegram_message(message, chat_id=chat_id)

    async def send_test_alert(self) -> bool:
        """
        Fungsi uji coba pengiriman notifikasi Telegram.
        """
        test_message = (
            "🔔 <b>[TEST] Notifikasi NawalaSentinel Radar Alert</b>\n\n"
            "Sistem notifikasi NawalaSentinel berhasil terhubung dan siap memberikan peringatan real-time saat status domain terblokir di ISP Indonesia!"
        )
        return await self.send_telegram_message(test_message)


# Global Instance
notifier = TelegramNotifier()
