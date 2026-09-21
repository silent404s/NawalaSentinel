import asyncio
import sys
import os

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import AsyncSessionLocal, init_db
from app.models import Tenant, Domain, BotActivityLog
from app.telegram_bot import telegram_bot_engine
from sqlalchemy.future import select
from sqlalchemy import desc

async def test_bot_activity_logging():
    print("=== TEST: BOT ACTIVITY LOGGING & AUDIT TRAIL ===")
    await init_db()

    async with AsyncSessionLocal() as session:
        # Check or create a test tenant
        stmt = select(Tenant).where(Tenant.telegram_chat_id == "-1001234567890")
        tenant = (await session.execute(stmt)).scalar_one_or_none()
        if not tenant:
            from datetime import datetime, timedelta
            tenant = Tenant(
                name="Grup Uji Coba Audit",
                telegram_chat_id="-1001234567890",
                package_quota=10,
                start_date=datetime.now(),
                expired_date=datetime.now() + timedelta(days=30),
                is_active=True
            )
            session.add(tenant)
            await session.commit()
            await session.refresh(tenant)
            print(f"Created test tenant: {tenant.name} ({tenant.telegram_chat_id})")
        else:
            print(f"Using existing test tenant: {tenant.name} ({tenant.telegram_chat_id})")

        # Mock user info
        mock_user = {
            "id": 987654321,
            "username": "tester_pro",
            "first_name": "Budi",
            "last_name": "Santoso"
        }

        # 1. Test _cmd_add
        print("\n--> Testing _cmd_add activity logging...")
        await telegram_bot_engine._cmd_add(
            session=session,
            tenant=tenant,
            chat_id=tenant.telegram_chat_id,
            args=["testauditsatu.com", "testauditdua.com"],
            message_id=101,
            from_user=mock_user,
            raw_text="/add testauditsatu.com testauditdua.com"
        )

        # 2. Test _cmd_list
        print("\n--> Testing _cmd_list activity logging...")
        await telegram_bot_engine._cmd_list(
            session=session,
            tenant=tenant,
            chat_id=tenant.telegram_chat_id,
            message_id=102,
            from_user=mock_user,
            raw_text="/list"
        )

        # 3. Test _cmd_replace
        print("\n--> Testing _cmd_replace activity logging...")
        await telegram_bot_engine._cmd_replace(
            session=session,
            tenant=tenant,
            chat_id=tenant.telegram_chat_id,
            args=["testauditsatu.com", "testauditsatubaru.com"],
            message_id=103,
            from_user=mock_user,
            raw_text="/replace testauditsatu.com testauditsatubaru.com"
        )

        # 4. Test _cmd_del
        print("\n--> Testing _cmd_del activity logging...")
        await telegram_bot_engine._cmd_del(
            session=session,
            tenant=tenant,
            chat_id=tenant.telegram_chat_id,
            args=["testauditsatubaru.com", "testauditdua.com"],
            message_id=104,
            from_user=mock_user,
            raw_text="/del testauditsatubaru.com testauditdua.com"
        )

        # Verify logs in DB
        print("\n--> Querying BotActivityLog from database...")
        stmt_logs = (
            select(BotActivityLog)
            .where(BotActivityLog.telegram_chat_id == tenant.telegram_chat_id)
            .order_by(desc(BotActivityLog.created_at))
            .limit(10)
        )
        logs = (await session.execute(stmt_logs)).scalars().all()

        print(f"Found {len(logs)} activity logs for chat {tenant.telegram_chat_id}:")
        for l in logs:
            safe_detail = l.details.encode("ascii", "replace").decode("ascii")
            print(f"[{l.created_at.strftime('%H:%M:%S')}] @{l.telegram_username} (ID: {l.telegram_user_id}) -> {l.command} | {safe_detail} | Status: {l.status}")

        assert len(logs) >= 4, "Expected at least 4 logs"
        commands_logged = [l.command for l in logs]
        assert "/del" in commands_logged
        assert "/replace" in commands_logged
        assert "/list" in commands_logged
        assert "/add" in commands_logged

        print("\n[SUCCESS] All bot commands logged correctly with username, user ID, details, and status!")

if __name__ == "__main__":
    asyncio.run(test_bot_activity_logging())
