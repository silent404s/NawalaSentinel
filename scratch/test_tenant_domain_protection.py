import sys, os
sys.path.insert(0, os.path.abspath("."))
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Domain, User, Tenant
from main import app

async def test_protection():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Domain).where(Domain.tenant_id.is_not(None)))
        tenant_domains = res.scalars().all()
        
        # If no tenant domains currently, create one for tenant 1
        if not tenant_domains:
            # Check tenant 1 exists
            t_res = await db.execute(select(Tenant))
            tenant = t_res.scalars().first()
            if not tenant:
                tenant = Tenant(name="Test Group", telegram_chat_id="-123456", package_quota=30, is_active=True)
                db.add(tenant)
                await db.flush()
            
            # Check user
            u_res = await db.execute(select(User))
            user = u_res.scalars().first()
            
            new_domain = Domain(
                name="nagawinplay.com",
                user_id=user.id,
                tenant_id=tenant.id,
                category="Bot Input",
                overall_status="BLOCKED",
                cf_status="CLEAN"
            )
            db.add(new_domain)
            await db.commit()
            await db.refresh(new_domain)
            tenant_domains = [new_domain]
        
        target_domain = tenant_domains[0]
        domain_id = target_domain.id
        print(f"Testing with tenant domain: id={domain_id}, name={target_domain.name}, tenant_id={target_domain.tenant_id}")

        # Get superadmin user for auth
        user_res = await db.execute(select(User).where(User.role == "SUPERADMIN"))
        admin = user_res.scalars().first()
        assert admin is not None, "Admin user must exist"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        from app.models import UserSession
        from app.config import settings
        from app.utils.timezone import now_jakarta_naive
        import secrets
        from datetime import timedelta
        session_token = secrets.token_hex(32)
        async with AsyncSessionLocal() as db:
            sess = UserSession(
                user_id=admin.id,
                session_token=session_token,
                ip_address="127.0.0.1",
                user_agent="TestBot",
                expires_at=now_jakarta_naive() + timedelta(days=1),
                last_activity_at=now_jakarta_naive(),
                is_active=True
            )
            db.add(sess)
            await db.commit()

        cookies = {settings.SESSION_COOKIE_NAME: session_token}

        # 1. Test DELETE /api/domains/{id}/delete on tenant domain -> Must be 403 Forbidden
        del_resp = await client.post(f"/api/domains/{domain_id}/delete", cookies=cookies)
        print(f"DELETE status code: {del_resp.status_code}, body: {del_resp.json()}")
        assert del_resp.status_code == 403, f"Expected 403, got {del_resp.status_code}"
        assert "milik grup pelanggan" in del_resp.json()["detail"]

        # 2. Test POST /api/domains/{id}/category on tenant domain -> Must be 403 Forbidden
        cat_resp = await client.post(f"/api/domains/{domain_id}/category", data={"category": "HackedCat"}, cookies=cookies)
        print(f"CATEGORY status code: {cat_resp.status_code}, body: {cat_resp.json()}")
        assert cat_resp.status_code == 403, f"Expected 403, got {cat_resp.status_code}"
        assert "milik grup pelanggan" in cat_resp.json()["detail"]

        # 3. Test GET / (Dashboard) to verify rendered HTML
        dash_resp = await client.get("/", cookies=cookies)
        assert dash_resp.status_code == 200
        html = dash_resp.text
        # Verify lock badge for tenant domain
        assert "tenant-managed" in html
        assert "Hanya dapat dihapus/diedit oleh anggota grup" in html
        print("Dashboard HTML verified: lock badge and disabled delete button present!")

        print("\nALL PROTECTIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_protection())
