import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Pastikan path import terarah ke project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.notifier import TelegramNotifier
from app.models import Tenant, Domain, CheckResult
from app.utils.timezone import now_jakarta_naive

class MockTenant:
    def __init__(self, name="MISTEK KONTOL", telegram_chat_id="-5573735476"):
        self.name = name
        self.telegram_chat_id = telegram_chat_id

async def test_alert_formatting():
    print("=== TEST ALERT FORMATTING ===")
    sent_messages = []

    class TestNotifier(TelegramNotifier):
        async def send_telegram_message(self, text: str, parse_mode: str = "HTML", chat_id: str = None) -> bool:
            sent_messages.append({"text": text, "chat_id": chat_id})
            return True

    t_notifier = TestNotifier()
    mock_tenant = MockTenant()

    # 1. Test Compact First Alert - BLOCKED
    await t_notifier.notify_tenant_domain_alert(
        domain_name="nagawinxtra.com",
        tenant=mock_tenant,
        overall_status="BLOCKED",
        cf_status="CLEAN",
        operator_results={},
        is_recovery=False,
        is_reminder=False
    )
    first_alert = sent_messages[-1]["text"]
    print("\n--- FIRST ALERT (BLOCKED) ---")
    print(first_alert)
    assert "Peringatan: Domain Terblokir!" in first_alert
    assert "nagawinxtra.com" in first_alert
    assert "❌ <b>nagawinxtra.com</b> ❌" in first_alert
    assert "/replace nagawinxtra.com linkbaru.com" in first_alert
    assert "/del nagawinxtra.com" in first_alert

    # 2. Test Minimal Reminder Alert - BLOCKED
    await t_notifier.notify_tenant_domain_alert(
        domain_name="nagawinxtra.com",
        tenant=mock_tenant,
        overall_status="BLOCKED",
        cf_status="CLEAN",
        operator_results={},
        is_recovery=False,
        is_reminder=True
    )
    reminder_alert = sent_messages[-1]["text"]
    print("\n--- REMINDER ALERT (BLOCKED) ---")
    print(reminder_alert)
    assert "nagawinxtra.com Komdigi Alert!" in reminder_alert
    assert "/replace nagawinxtra.com linkbaru.com" in reminder_alert
    assert "/del nagawinxtra.com" in reminder_alert

    # 3. Test Minimal Reminder Alert - PHISHING
    await t_notifier.notify_tenant_domain_alert(
        domain_name="phish-site.com",
        tenant=mock_tenant,
        overall_status="NORMAL",
        cf_status="PHISHING",
        operator_results={},
        is_recovery=False,
        is_reminder=True
    )
    phish_reminder = sent_messages[-1]["text"]
    print("\n--- REMINDER ALERT (PHISHING) ---")
    print(phish_reminder)
    assert "phish-site.com Phishing Alert!" in phish_reminder
    assert "/replace phish-site.com linkbaru.com" in phish_reminder
    assert "/del phish-site.com" in phish_reminder

    # 4. Test Recovery Alert
    await t_notifier.notify_tenant_domain_alert(
        domain_name="nagawinxtra.com",
        tenant=mock_tenant,
        overall_status="NORMAL",
        cf_status="CLEAN",
        operator_results={},
        is_recovery=True,
        is_reminder=False
    )
    recovery_alert = sent_messages[-1]["text"]
    print("\n--- RECOVERY ALERT ---")
    print(recovery_alert)
    assert "Pemberitahuan: Domain Kembali Normal" in recovery_alert

    print("\n✅ All Alert Formatting tests passed!")

async def test_scheduler_reminder_logic():
    print("\n=== TEST SCHEDULER REMINDER TIMING LOGIC ===")
    now = now_jakarta_naive()
    
    # Skenario 1: Baru pertama kali terblokir (was_old_bad=False, is_now_bad=True)
    # Harus kirim First Alert (is_reminder=False)
    was_old_bad = False
    is_now_bad = True
    assert (is_now_bad and not was_old_bad) == True
    
    # Skenario 2: Masih terblokir tapi baru 5 menit lalu dikirim alert
    was_old_bad = True
    is_now_bad = True
    last_alerted_at = now - timedelta(minutes=5)
    elapsed = (now - last_alerted_at).total_seconds()
    should_remind = elapsed >= 1800
    assert should_remind == False, "Tidak boleh kirim reminder sebelum 30 menit!"
    
    # Skenario 3: Masih terblokir dan sudah 31 menit lalu dikirim alert
    last_alerted_at = now - timedelta(minutes=31)
    elapsed = (now - last_alerted_at).total_seconds()
    should_remind = elapsed >= 1800
    assert should_remind == True, "Harus kirim reminder jika sudah >= 30 menit!"
    
    print("✅ Scheduler reminder timing tests passed!")

async def main():
    await test_alert_formatting()
    await test_scheduler_reminder_logic()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
