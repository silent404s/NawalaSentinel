import asyncio
from app.database import AsyncSessionLocal, init_db
from app.models import User
from app.auth import hash_password
from sqlalchemy.future import select

async def seed_superadmin():
    await init_db()
    async with AsyncSessionLocal() as session:
        stmt = select(User).where(User.username == "admin")
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            print("Creating superadmin 'admin' / 'admin123' ...")
            new_admin = User(
                username="admin",
                password=hash_password("admin123"),
                role="SUPERADMIN",
                domain_quota=9999,
                is_active=True
            )
            session.add(new_admin)
            await session.commit()
            print("Superadmin created!")
        else:
            print("Superadmin already exists.")

if __name__ == "__main__":
    asyncio.run(seed_superadmin())
