import sys, os
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import asyncio
from sqlalchemy import select, delete
from app.database import AsyncSessionLocal
from app.models import Tenant, Domain
from app.telegram_bot import TelegramBotEngine

async def test_isolation():
    bot = TelegramBotEngine()
    
    async with AsyncSessionLocal() as session:
        # 1. Setup two test tenants
        # Clean up any previous test tenants
        await session.execute(delete(Domain).where(Domain.name.in_(["test-group1.com", "test-group2.com", "test-group1-replaced.com"])))
        from app.utils.timezone import now_jakarta_naive
        from datetime import timedelta
        now = now_jakarta_naive()
        t1_res = await session.execute(select(Tenant).where(Tenant.telegram_chat_id == "-100111111111"))
        t1 = t1_res.scalars().first()
        if not t1:
            t1 = Tenant(name="Test Group 1", telegram_chat_id="-100111111111", package_quota=30, is_active=True, expired_date=now + timedelta(days=30))
            session.add(t1)
            await session.flush()
        
        t2_res = await session.execute(select(Tenant).where(Tenant.telegram_chat_id == "-100222222222"))
        t2 = t2_res.scalars().first()
        if not t2:
            t2 = Tenant(name="Test Group 2", telegram_chat_id="-100222222222", package_quota=30, is_active=True, expired_date=now + timedelta(days=30))
            session.add(t2)
            await session.flush()

        # Add domain to Group 1
        d1 = Domain(name="test-group1.com", tenant_id=t1.id, user_id=1, category="Bot Input")
        # Add domain to Group 2
        d2 = Domain(name="test-group2.com", tenant_id=t2.id, user_id=1, category="Bot Input")
        session.add(d1)
        session.add(d2)
        await session.commit()
        await session.refresh(t1)
        await session.refresh(t2)
        await session.refresh(d1)
        await session.refresh(d2)

        print(f"Created Domain 1 (id={d1.id}, tenant={d1.tenant_id}) and Domain 2 (id={d2.id}, tenant={d2.tenant_id})")

    # Mock send_message to capture bot replies
    last_replies = []
    async def mock_send_message(chat_id, text, reply_to_message_id=None):
        last_replies.append({"chat_id": chat_id, "text": text})
        return True

    bot.send_message = mock_send_message

    async with AsyncSessionLocal() as session:
        t1 = (await session.execute(select(Tenant).where(Tenant.id == t1.id))).scalar_one()
        t2 = (await session.execute(select(Tenant).where(Tenant.id == t2.id))).scalar_one()

        # TEST 1: Group 1 tries to delete Group 2's domain
        print("\n--- TEST 1: Group 1 tries /del test-group2.com ---")
        last_replies.clear()
        await bot._cmd_del(session, t1, t1.telegram_chat_id, ["test-group2.com"], 101)
        reply = last_replies[-1]["text"]
        print(f"Bot reply to Group 1: {reply}")
        assert "DOMAIN TIDAK DITEMUKAN" in reply, "Group 1 must NOT be able to find Group 2's domain!"

        # Verify d2 is still in DB
        d2_check = (await session.execute(select(Domain).where(Domain.name == "test-group2.com"))).scalar_one_or_none()
        assert d2_check is not None, "Group 2's domain must still exist!"
        print("PASS: Group 1 could NOT delete Group 2's domain!")

        # TEST 2: Group 1 tries to replace Group 2's domain
        print("\n--- TEST 2: Group 1 tries /replace test-group2.com test-hack.com ---")
        last_replies.clear()
        await bot._cmd_replace(session, t1, t1.telegram_chat_id, ["test-group2.com", "test-hack.com"], 102)
        reply = last_replies[-1]["text"]
        print(f"Bot reply to Group 1: {reply}")
        assert "DOMAIN LAMA TIDAK DITEMUKAN" in reply, "Group 1 must NOT be able to find Group 2's domain for replace!"

        d2_check = (await session.execute(select(Domain).where(Domain.name == "test-group2.com"))).scalar_one_or_none()
        assert d2_check is not None, "Group 2's domain must NOT be changed!"
        print("PASS: Group 1 could NOT replace Group 2's domain!")

        # TEST 3: Group 1 runs /list
        print("\n--- TEST 3: Group 1 runs /list ---")
        last_replies.clear()
        await bot._cmd_list(session, t1, t1.telegram_chat_id, 103)
        reply = last_replies[-1]["text"]
        print(f"Bot reply to Group 1 /list:\n{reply}")
        assert "test-group1.com" in reply
        assert "test-group2.com" not in reply, "Group 1 must NOT see Group 2's domain in /list!"
        print("PASS: Group 1 only sees its own domain in /list!")

        # TEST 4: Group 2 runs /list
        print("\n--- TEST 4: Group 2 runs /list ---")
        last_replies.clear()
        await bot._cmd_list(session, t2, t2.telegram_chat_id, 104)
        reply = last_replies[-1]["text"]
        print(f"Bot reply to Group 2 /list:\n{reply}")
        assert "test-group2.com" in reply
        assert "test-group1.com" not in reply, "Group 2 must NOT see Group 1's domain in /list!"
        print("PASS: Group 2 only sees its own domain in /list!")

        # TEST 5: Group 1 deletes its own domain
        print("\n--- TEST 5: Group 1 deletes its own domain /del test-group1.com ---")
        last_replies.clear()
        await bot._cmd_del(session, t1, t1.telegram_chat_id, ["test-group1.com"], 105)
        reply = last_replies[-1]["text"]
        print(f"Bot reply to Group 1:\n{reply}")
        assert "DOMAIN BERHASIL DIHAPUS" in reply

        d1_check = (await session.execute(select(Domain).where(Domain.name == "test-group1.com"))).scalar_one_or_none()
        assert d1_check is None, "Group 1's domain should be deleted!"
        d2_check = (await session.execute(select(Domain).where(Domain.name == "test-group2.com"))).scalar_one_or_none()
        assert d2_check is not None, "Group 2's domain must still exist unharmed!"
        print("PASS: Group 1 successfully deleted its own domain, Group 2 untouched!")

        # Clean up test domain 2
        await session.delete(d2_check)
        await session.commit()

    print("\nALL MULTI-TENANT ISOLATION TESTS PASSED 100%!")

if __name__ == "__main__":
    asyncio.run(test_isolation())
