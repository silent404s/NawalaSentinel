import asyncio
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath("."))

from httpx import AsyncClient, ASGITransport
from main import app
from app.database import init_db

async def run_http_tests():
    print("==================================================================")
    print("🚀 [TEST SUITE] Customer Management HTTP & API Endpoints")
    print("==================================================================")

    await init_db()

    # Clean up test customer if exists
    from app.database import AsyncSessionLocal
    from app.models import Tenant
    from sqlalchemy.future import select

    async with AsyncSessionLocal() as session:
        stmt = select(Tenant).where(Tenant.telegram_chat_id == "-1007776665554")
        existing_t = (await session.execute(stmt)).scalar_one_or_none()
        if existing_t:
            await session.delete(existing_t)
            await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login sebagai superadmin
        print("\n1. Melakukan Login Superadmin...")
        login_res = await client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        data_login = login_res.json()
        print(f"   ✅ Login step 1 berhasil (Status: {data_login.get('status')}).")

        import pyotp
        from app.database import AsyncSessionLocal
        from app.models import User
        from sqlalchemy.future import select

        if data_login.get("status") == "REQUIRE_2FA_SETUP":
            secret = data_login["secret"]
            totp = pyotp.TOTP(secret)
            verify_res = await client.post("/api/auth/setup-2fa", data={
                "temp_token": data_login["temp_token"],
                "code": totp.now()
            })
            assert verify_res.status_code == 200, f"Setup 2FA failed: {verify_res.text}"
            print("   ✅ Setup 2FA berhasil, session cookie diterima.")
        elif data_login.get("status") == "REQUIRE_2FA_VERIFY":
            async with AsyncSessionLocal() as session:
                admin_user = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
                totp = pyotp.TOTP(admin_user.totp_secret)
                code = totp.now()

            verify_res = await client.post("/api/auth/verify-2fa", data={
                "temp_token": data_login["temp_token"],
                "code": code
            })
            assert verify_res.status_code == 200, f"2FA verify failed: {verify_res.text}"
            print("   ✅ Login 2FA berhasil, session cookie diterima.")

        # 2. Akses halaman /customers
        print("\n2. Mengakses Halaman Web /customers...")
        page_res = await client.get("/customers")
        assert page_res.status_code == 200, f"Gagal akses /customers: {page_res.status_code}"
        assert "Manajemen Pelanggan" in page_res.text, "Title tidak ditemukan di HTML"
        print("   ✅ Halaman /customers berhasil dimuat.")

        # 3. API Tambah Pelanggan (POST /api/customers)
        print("\n3. Menguji API POST /api/customers...")
        create_res = await client.post("/api/customers", data={
            "name": "Customer Test HTTP",
            "contact": "@cust_http / 081299998888",
            "telegram_chat_id": "-1007776665554",
            "package_quota": "20",
            "duration_days": "30",
            "notes": "Testing HTTP endpoint"
        })
        assert create_res.status_code == 200, f"Create customer failed: {create_res.text}"
        cust_data = create_res.json()["data"]
        cust_id = cust_data["id"]
        print(f"   ✅ Pelanggan berhasil dibuat: ID={cust_id}, Name='{cust_data['name']}'")

        # 4. API List Pelanggan (GET /api/customers)
        print("\n4. Menguji API GET /api/customers...")
        list_res = await client.get("/api/customers")
        assert list_res.status_code == 200
        customers = list_res.json()["data"]
        found = any(c["id"] == cust_id for c in customers)
        assert found, "Customer baru tidak ada di list"
        print(f"   ✅ Customer ditemukan dalam list API (Total customer: {len(customers)}).")

        # 5. API Perpanjang Sewa (POST /api/customers/{id}/renew)
        print("\n5. Menguji API POST /api/customers/{id}/renew...")
        renew_res = await client.post(f"/api/customers/{cust_id}/renew", data={"days": "30"})
        assert renew_res.status_code == 200
        print(f"   ✅ Sewa berhasil diperpanjang: {renew_res.json()['message']}")

        # 6. API Hapus Pelanggan (DELETE /api/customers/{id})
        print("\n6. Menguji API DELETE /api/customers/{id}...")
        del_res = await client.delete(f"/api/customers/{cust_id}")
        assert del_res.status_code == 200
        print(f"   ✅ Pelanggan berhasil dihapus: {del_res.json()['message']}")

    print("\n==================================================================")
    print("🎉 SEMUA PENGUJIAN HTTP & API CUSTOMER BERHASIL (100% PASS)!")
    print("==================================================================")

if __name__ == "__main__":
    asyncio.run(run_http_tests())
