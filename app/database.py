import os
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
    Inisialisasi tabel database saat aplikasi dimulai.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
