import uvicorn
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


from app.config import settings
from app.database import init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.routes import router

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Inisialisasi aplikasi: buat tabel DB & aktifkan background scheduler.
    """
    logger.info("🚀 Menginisialisasi Database SQLite & Tabel...")
    await init_db()

    logger.info("⚡ Mengaktifkan APScheduler Background Task (5 Menit)...")
    start_scheduler()

    yield

    logger.info("🛑 Menghentikan scheduler dan mematikan aplikasi...")
    stop_scheduler()

# Inisialisasi FastAPI App
app = FastAPI(
    title=settings.APP_NAME,
    description="Sistem Pemantauan Status Pemblokiran Domain Nawala & Internet Positif di Operator Telkomsel, XL, Tri, & IM3",
    version="1.0.0",
    lifespan=lifespan
)

# Add Session Middleware
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY if hasattr(settings, "SECRET_KEY") else "super-secret-key-change-me")

# Mount Folder Asset Statis (CSS, JS)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Mount Routes
app.include_router(router)

if __name__ == "__main__":
    print(f"================================================================")
    print(f"🛡️  {settings.APP_NAME} Starting...")
    print(f"🌐  Web Dashboard Server: http://{settings.HOST}:{settings.PORT}")
    print(f"================================================================")
    
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
