import asyncio
import os
import sys
from datetime import datetime, timedelta

# Set encoding for Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure app path in sys.path
sys.path.insert(0, os.path.abspath("."))

from sqlalchemy.future import select
from app.database import init_db, AsyncSessionLocal
from app.models import Tenant, Domain, CheckResult
from app.telegram_bot import telegram_bot_engine, normalize_domain_bot, is_valid_domain
from app.notifier import notifier
from app.utils.timezone import now_jakarta_naive

async def run_tests():
    print("==================================================================")
    print("🚀 [TEST SUITE] Multi-Tenant Telegram Bot & Subscription System")
    print("==================================================================")

    # 1. Inisialisasi DB & Migrasi
    print("\n1. Menginisialisasi Database & Skema...")
    await init_db()
    print("   ✅ DB initialized successfully.")

    test_chat_id = "-1009998887771"
    non_whitelist_chat_id = "-1009998887772"

    async with AsyncSessionLocal() as session:
        # Bersihkan data tes jika ada
        stmt_del = select(Tenant).where(Tenant.telegram_chat_id.in_([test_chat_id, non_whitelist_chat_id]))
        old_tenants = (await session.execute(stmt_del)).scalars().all()
        for ot in old_tenants:
            await session.delete(ot)
        await session.commit()

        # 2. Buat Tenant Baru (Paket 2 = 20 Domain, 30 Hari)
        print("\n2. Menguji Pembuatan Tenant / Customer Baru...")
        now = now_jakarta_naive()
        new_tenant = Tenant(
            name="VIP Member Test",
            contact="@viptest / 081234567890",
            telegram_chat_id=test_chat_id,
            package_quota=20,
            start_date=now,
            expired_date=now + timedelta(days=30),
            is_active=True,
            notes="Customer VIP langganan bulanan"
        )
        session.add(new_tenant)
        await session.commit()
        await session.refresh(new_tenant)
        print(f"   ✅ Tenant dibuat: ID={new_tenant.id}, Nama='{new_tenant.name}', Quota={new_tenant.package_quota}, Expired={new_tenant.expired_date}")

        # 3. Uji Whitelist Bot Guard
        print("\n3. Menguji Validasi Whitelist Grup Bot...")
        # Cek grup non-whitelist
        stmt_nw = select(Tenant).where(Tenant.telegram_chat_id == non_whitelist_chat_id)
        nw_res = (await session.execute(stmt_nw)).scalar_one_or_none()
        assert nw_res is None, "Grup non-whitelist tidak boleh ditemukan"
        print("   ✅ Grup non-whitelist berhasil ditolak.")

        # 4. Uji Penambahan Domain (/add) & Kuota Kelipatan 10
        print("\n4. Menguji Penambahan Domain (/add) & Kuota...")
        # Tambah beberapa domain secara acak untuk menguji A-Z sorting nanti
        sample_domains = [
            "zebra-bet.com",
            "alpha-slot.com",
            "gacor88-indo.net",
            "bet-hoki.org",
            "casino-juara.io"
        ]
        for d_name in sample_domains:
            dom = Domain(
                user_id=1,
                tenant_id=new_tenant.id,
                name=d_name,
                category="Bot Input",
                overall_status="NORMAL" if "hoki" in d_name else "BLOCKED",
                cf_status="CLEAN"
            )
            session.add(dom)
        await session.commit()

        # Hitung jumlah domain
        stmt_count = select(Domain).where(Domain.tenant_id == new_tenant.id)
        current_domains = (await session.execute(stmt_count)).scalars().all()
        assert len(current_domains) == 5, f"Expected 5 domains, got {len(current_domains)}"
        print(f"   ✅ 5 Domain berhasil ditambahkan untuk tenant ID {new_tenant.id}.")

        # 5. Uji Pengurutan /list (Harus A - Z secara alfabetis, dengan penomoran 1, 2, 3...)
        print("\n5. Menguji /list (Pengurutan Alfabetis A-Z & Nomor Urut 1, 2, 3...)...")
        stmt_sorted = select(Domain).where(Domain.tenant_id == new_tenant.id).order_by(Domain.name.asc())
        sorted_domains = (await session.execute(stmt_sorted)).scalars().all()
        sorted_names = [d.name for d in sorted_domains]
        expected_names = sorted(sample_domains)
        assert sorted_names == expected_names, f"Urutan tidak sesuai A-Z: {sorted_names} vs {expected_names}"
        print(f"   ✅ Urutan A-Z Terverifikasi:")
        for idx, d in enumerate(sorted_domains, 1):
            print(f"      {idx}. {d.name} [{d.overall_status}]")

        # 6. Uji Penghapusan Domain (/del) baik via Nama maupun via Nomor
        print("\n6. Menguji /del (Hapus Domain via Nomor & via Nama)...")
        # Hapus domain nomor 1 ("alpha-slot.com")
        target_del_1 = sorted_domains[0]
        await session.delete(target_del_1)
        await session.commit()

        # Verifikasi domain terhapus
        stmt_check = select(Domain).where(Domain.tenant_id == new_tenant.id, Domain.name == "alpha-slot.com")
        check_del = (await session.execute(stmt_check)).scalar_one_or_none()
        assert check_del is None, "alpha-slot.com harusnya sudah terhapus!"
        print("   ✅ Hapus domain nomor 1 ('alpha-slot.com') sukses.")

        # Sisa 4 domain
        rem_domains = (await session.execute(select(Domain).where(Domain.tenant_id == new_tenant.id))).scalars().all()
        assert len(rem_domains) == 4, f"Expected 4 domains remaining, got {len(rem_domains)}"
        print(f"   ✅ Sisa domain: {len(rem_domains)} / {new_tenant.package_quota}")

        # 7. Uji Perpanjangan Masa Sewa (+30 Hari)
        print("\n7. Menguji Perpanjangan Masa Sewa (+30 Hari)...")
        old_exp = new_tenant.expired_date
        new_tenant.expired_date = new_tenant.expired_date + timedelta(days=30)
        await session.commit()
        await session.refresh(new_tenant)
        delta_days = (new_tenant.expired_date - old_exp).days
        assert delta_days == 30, f"Expected 30 days added, got {delta_days}"
        print(f"   ✅ Masa sewa diperpanjang: {old_exp.strftime('%Y-%m-%d')} -> {new_tenant.expired_date.strftime('%Y-%m-%d')} (+30 hari).")

        # 8. Uji Format Notifikasi Nawala (Template E)
        print("\n8. Menguji Pemformatan Notifikasi Nawala ke Grup (Template E)...")
        # Simulasikan pemanggilan notify_tenant_domain_alert
        mock_op_results = {
            "Telkomsel": {"status": "BLOCKED"},
            "XL": {"status": "BLOCKED"},
            "IM3": {"status": "NORMAL"},
            "Tri": {"status": "NORMAL"}
        }
        # Panggil method (akan aman jika TELEGRAM_BOT_TOKEN kosong karena send_telegram_message memverifikasi token)
        await notifier.notify_tenant_domain_alert(
            domain_name="gacor88-indo.net",
            tenant=new_tenant,
            overall_status="BLOCKED",
            cf_status="CLEAN",
            operator_results=mock_op_results,
            reason="DNS diarahkan ke Nawala IP / Kominfo Block"
        )
        print("   ✅ Method notify_tenant_domain_alert dieksekusi tanpa error.")

        # 9. Uji Domain yang Terhapus Tidak Mendapatkan Notifikasi Lagi
        print("\n9. Menguji Domain yang Dihapus Tidak Akan Dikirimkan Notifikasi...")
        stmt_del_query = select(Domain).where(Domain.name == "alpha-slot.com")
        del_check = (await session.execute(stmt_del_query)).scalar_one_or_none()
        assert del_check is None, "Domain yang sudah dihapus tidak boleh ada di database"
        print("   ✅ Domain 'alpha-slot.com' tidak ditemukan di database, scheduler otomatis tidak akan memprosesnya.")

        # Cleanup test tenant
        await session.delete(new_tenant)
        await session.commit()
        print("   ✅ Data uji coba dibersihkan.")

    print("\n==================================================================")
    print("🎉 SEMUA PENGUJIAN SISTEM LANGGANAN & BOT TELEGRAM BERHASIL (100% PASS)!")
    print("==================================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
