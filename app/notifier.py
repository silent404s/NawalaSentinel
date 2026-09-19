import httpx
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from app.config import settings

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
        if not self.bot_token or not target_chat_id:
            logger.warning("Telegram Bot Token atau Chat ID belum dikonfigurasi.")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
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

    async def notify_status_change(self, domain_name: str, operator: str, old_status: str, new_status: str, reason: str, ips: str = "", chat_id: Optional[str] = None):
        """
        Mengirim notifikasi otomatis saat domain berubah dari NORMAL -> BLOCKED atau sebaliknya.
        """
        is_blocked = (new_status == "BLOCKED")
        
        emoji = "🚨" if is_blocked else "✅"
        header_title = "ALERT: DOMAIN TERBLOKIR!" if is_blocked else "UPDATE: DOMAIN KEMBALI NORMAL"
        status_color = "<b>TERBLOKIR (BLOCKED)</b>" if is_blocked else "<b>AKTIF (NORMAL)</b>"
        
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S WIB")

        message = (
            f"{emoji} <b>{header_title}</b> {emoji}\n\n"
            f"🌐 <b>Domain:</b> <code>{domain_name}</code>\n"
            f"📱 <b>Operator:</b> {operator}\n"
            f"🔄 <b>Status Sebelumnya:</b> {old_status}\n"
            f"⚠️ <b>Status Baru:</b> {status_color}\n"
            f"🔍 <b>Keterangan:</b> {reason}\n"
        )
        
        if ips:
            message += f"📌 <b>IP Terdeteksi:</b> <code>{ips}</code>\n"
            
        message += f"\n⏰ <i>Waktu Deteksi: {timestamp_str}</i>"

        # 1. Kirim Notifikasi Telegram jika diaktifkan
        if settings.TELEGRAM_ALERTS_ENABLED and chat_id:
            await self.send_telegram_message(message, chat_id=chat_id)

        # 2. Kirim Webhook (jika dikonfigurasi)
        if settings.WEBHOOK_ALERTS_ENABLED and settings.WEBHOOK_URL:
            await self.send_webhook_alert({
                "event": "domain_status_changed",
                "domain": domain_name,
                "operator": operator,
                "old_status": old_status,
                "new_status": new_status,
                "reason": reason,
                "ips": ips,
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
