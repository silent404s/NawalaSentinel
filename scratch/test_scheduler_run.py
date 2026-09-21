import asyncio
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import init_db, AsyncSessionLocal
from app.models import Tenant, Domain
from app.scheduler import run_full_domain_scan
from app.notifier import TelegramNotifier

async def test_scheduler():
    print("=== TESTING run_full_domain_scan() ===")
    await init_db()

    sent_alerts = []
    class MockNotifier(TelegramNotifier):
        async def send_telegram_message(self, text: str, parse_mode: str = "HTML", chat_id: str = None) -> bool:
            print(f"[MOCK NOTIFIER] chat_id={chat_id}\n{text}\n")
            sent_alerts.append({"chat_id": chat_id, "text": text})
            return True

    import app.scheduler
    import app.notifier
    app.scheduler.notifier = MockNotifier()

    print("Running run_full_domain_scan()...")
    try:
        await run_full_domain_scan()
        print(f"run_full_domain_scan() completed successfully! Sent alerts count: {len(sent_alerts)}")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_scheduler())
