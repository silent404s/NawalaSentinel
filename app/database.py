import os
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import settings

# Pastikan folder data/ ada
os.makedirs("data", exist_ok=True)

# Async Engine SQLAlchemy untuk SQLite
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

# Aktifkan Foreign Keys di SQLite
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        pass

# Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class untuk ORM Models
Base = declarative_base()

async def get_db():
    """
    Dependency generator untuk mendapatkan session database async per request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    """
    Inisialisasi tabel database saat aplikasi dimulai, jalankan auto-migration jika ada kolom baru,
    serta auto-seed superadmin default.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # Migrasi otomatis untuk SQLite (jika kolom user_id belum ada pada tabel domains)
        def migrate_sqlite_columns(sync_conn):
            cursor = sync_conn.connection.cursor()
            cursor.execute("PRAGMA table_info(domains)")
            columns = [row[1] for row in cursor.fetchall()]
            if "user_id" not in columns:
                cursor.execute("ALTER TABLE domains ADD COLUMN user_id INTEGER DEFAULT 1")
                cursor.execute("UPDATE domains SET user_id = 1 WHERE user_id IS NULL")
            if "cf_status" not in columns:
                cursor.execute("ALTER TABLE domains ADD COLUMN cf_status VARCHAR(50) DEFAULT 'CLEAN'")
                cursor.execute("UPDATE domains SET cf_status = 'CLEAN' WHERE cf_status IS NULL")
            if "cf_reason" not in columns:
                cursor.execute("ALTER TABLE domains ADD COLUMN cf_reason TEXT")

            if "tenant_id" not in columns:
                cursor.execute("ALTER TABLE domains ADD COLUMN tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE")
            if "last_alerted_at" not in columns:
                cursor.execute("ALTER TABLE domains ADD COLUMN last_alerted_at DATETIME")

            # Update index agar name tidak unik global melainkan unik per tenant
            cursor.execute("DROP INDEX IF EXISTS ix_domains_name")
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_domains_name ON domains (name)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_domains_tenant_name ON domains (tenant_id, name)")

            # Migrasi kolom tabel users (2FA, Lockout, Backup Codes)
            cursor.execute("PRAGMA table_info(users)")
            user_cols = [row[1] for row in cursor.fetchall()]
            if "totp_secret" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN totp_secret VARCHAR(255)")
            if "is_totp_enabled" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN is_totp_enabled BOOLEAN DEFAULT 0")
            if "failed_login_attempts" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0")
            if "locked_until" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN locked_until DATETIME")
            if "backup_codes" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN backup_codes TEXT")

            sync_conn.connection.commit()

        await conn.run_sync(migrate_sqlite_columns)

    # Auto-seed Superadmin default jika belum ada user
    async with AsyncSessionLocal() as session:
        from app.models import User
        from app.auth import hash_password
        from sqlalchemy.future import select

        stmt = select(User).limit(1)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            new_admin = User(
                username="admin",
                password=hash_password("admin123"),
                role="SUPERADMIN",
                domain_quota=99999,
                is_active=True
            )
            session.add(new_admin)
            await session.commit()

    # Muat preferensi dari AppSetting jika tersimpan di DB
    async with AsyncSessionLocal() as session:
        from app.models import AppSetting
        from app.notifier import notifier
        from app.checker import checker_engine
        from sqlalchemy.future import select

        res = await session.execute(select(AppSetting))
        for row in res.scalars().all():
            if row.key == "TELEGRAM_BOT_TOKEN" and row.value:
                settings.TELEGRAM_BOT_TOKEN = row.value
                notifier.bot_token = row.value
            elif row.key == "TELEGRAM_CHAT_ID" and row.value:
                settings.TELEGRAM_CHAT_ID = row.value
                notifier.chat_id = row.value
            elif row.key == "TELEGRAM_ALERTS_ENABLED":
                settings.TELEGRAM_ALERTS_ENABLED = (row.value.lower() in ("true", "1", "t"))
            elif row.key == "CHECK_INTERVAL_MINUTES" and row.value:
                settings.CHECK_INTERVAL_MINUTES = int(row.value)
            elif row.key == "CHUNK_SIZE" and row.value:
                settings.CHUNK_SIZE = int(row.value)
            elif row.key == "CONCURRENT_CHECKS" and row.value:
                settings.CONCURRENT_CHECKS = int(row.value)
                checker_engine.update_concurrency(settings.CONCURRENT_CHECKS)
            elif row.key == "CHUNK_DELAY_SECONDS" and row.value:
                settings.CHUNK_DELAY_SECONDS = float(row.value)
            elif row.key == "LOCAL_TEST_MODE":
                settings.LOCAL_TEST_MODE = (row.value.lower() in ("true", "1", "t"))
            elif row.key == "TELKOMSEL_PROXY":
                settings.OPERATOR_PROXIES["Telkomsel"] = row.value or ""
            elif row.key == "XL_PROXY":
                settings.OPERATOR_PROXIES["XL"] = row.value or ""
            elif row.key == "IM3_PROXY":
                settings.OPERATOR_PROXIES["IM3"] = row.value or ""
            elif row.key == "TRI_PROXY":
                settings.OPERATOR_PROXIES["Tri"] = row.value or ""

