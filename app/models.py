from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils.timezone import now_jakarta_naive

class User(Base):
    """
    Model untuk pengguna aplikasi SaaS.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    role = Column(String(50), default="USER") # SUPERADMIN or USER
    domain_quota = Column(Integer, default=10) # Kelipatan 10
    telegram_chat_id = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_jakarta_naive)

    # 2FA & Security Attributes
    totp_secret = Column(String(255), nullable=True)
    is_totp_enabled = Column(Boolean, default=False)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    backup_codes = Column(Text, nullable=True)  # JSON string berisi hash kode backup

    domains = relationship("Domain", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    login_logs = relationship("LoginLog", back_populates="user")

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "domain_quota": self.domain_quota,
            "telegram_chat_id": self.telegram_chat_id,
            "is_active": self.is_active,
            "is_totp_enabled": self.is_totp_enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class Tenant(Base):
    """
    Model pelanggan / grup langganan bot Telegram (Multi-Tenant).
    """
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True) # Nama Customer / Nama Grup
    contact = Column(String(100), nullable=True) # Kontak WA / Telegram / Sosmed
    telegram_chat_id = Column(String(100), unique=True, nullable=False, index=True) # ID Grup Telegram (-100...)
    package_quota = Column(Integer, default=10) # Kelipatan 10 (10, 20, 30, dst)
    start_date = Column(DateTime, default=now_jakarta_naive)
    expired_date = Column(DateTime, nullable=False) # Masa aktif sewa (default +30 hari)
    is_active = Column(Boolean, default=True, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now_jakarta_naive)
    updated_at = Column(DateTime, default=now_jakarta_naive, onupdate=now_jakarta_naive)

    domains = relationship("Domain", back_populates="tenant", cascade="all, delete-orphan")
    activity_logs = relationship("BotActivityLog", back_populates="tenant", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "contact": self.contact,
            "telegram_chat_id": self.telegram_chat_id,
            "package_quota": self.package_quota,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "expired_date": self.expired_date.isoformat() if self.expired_date else None,
            "is_active": self.is_active,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

class Domain(Base):
    """
    Model untuk menyimpan daftar domain dan subdomain yang dipantau.
    """
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(255), nullable=False, index=True) # e.g. domain.com or sub.domain.com
    category = Column(String(100), default="General", index=True)
    overall_status = Column(String(50), default="UNCHECKED", index=True) # UNCHECKED, NORMAL, BLOCKED, MIXED
    cf_status = Column(String(50), default="CLEAN", index=True) # CLEAN, PHISHING, UNCHECKED
    cf_reason = Column(Text, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_alerted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_jakarta_naive)

    # Relationship dengan user, tenant, hasil pengecekan per operator & log
    user = relationship("User", back_populates="domains")
    tenant = relationship("Tenant", back_populates="domains")
    results = relationship("CheckResult", back_populates="domain", cascade="all, delete-orphan")
    logs = relationship("StatusLog", back_populates="domain", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "category": self.category,
            "overall_status": self.overall_status,
            "cf_status": self.cf_status,
            "cf_reason": self.cf_reason,
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "last_alerted_at": self.last_alerted_at.isoformat() if self.last_alerted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CheckResult(Base):
    """
    Model hasil pengecekan domain per operator seluler (Telkomsel, XL, IM3, Tri).
    """
    __tablename__ = "check_results"

    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    operator = Column(String(50), nullable=False, index=True) # Telkomsel, XL, IM3, Tri
    status = Column(String(50), nullable=False, index=True) # NORMAL, BLOCKED, ERROR
    resolved_ips = Column(String(255), nullable=True) # e.g. 104.21.32.1
    block_reason = Column(Text, nullable=True) # e.g. "DNS Sinkhole IP: 180.250.247.1" or "HTTP Redirect: internetpositif.id"
    latency_ms = Column(Float, default=0.0)
    checked_at = Column(DateTime, default=now_jakarta_naive)

    domain = relationship("Domain", back_populates="results")

    def to_dict(self):
        return {
            "id": self.id,
            "domain_id": self.domain_id,
            "operator": self.operator,
            "status": self.status,
            "resolved_ips": self.resolved_ips,
            "block_reason": self.block_reason,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


class StatusLog(Base):
    """
    Model riwayat pencatatan perubahan status pemblokiran domain.
    """
    __tablename__ = "status_logs"

    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False)
    domain_name = Column(String(255), nullable=False, index=True)
    operator = Column(String(50), nullable=False, index=True)
    previous_status = Column(String(50), nullable=False)
    new_status = Column(String(50), nullable=False)
    reason = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=now_jakarta_naive, index=True)

    domain = relationship("Domain", back_populates="logs")

    def to_dict(self):
        return {
            "id": self.id,
            "domain_id": self.domain_id,
            "domain_name": self.domain_name,
            "operator": self.operator,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class AppSetting(Base):
    """
    Model penyimpanan dinamis untuk preferensi aplikasi (Telegram token, Proxy, Interval).
    """
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserSession(Base):
    """
    Model sesi login aktif per pengguna (Single Active Session per Account).
    """
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token = Column(String(128), unique=True, nullable=False, index=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    device_info = Column(String(255), nullable=True) # e.g. "Chrome 120 (Windows 10)"
    created_at = Column(DateTime, default=now_jakarta_naive)
    last_activity_at = Column(DateTime, default=now_jakarta_naive)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True, index=True)

    user = relationship("User", back_populates="sessions")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_token": self.session_token[:8] + "...",
            "ip_address": self.ip_address,
            "device_info": self.device_info,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
        }


class LoginLog(Base):
    """
    Model riwayat aktivitas login dan otentikasi (Audit Log).
    """
    __tablename__ = "login_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username = Column(String(100), nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True) # LOGIN_SUCCESS, LOGIN_FAILED, 2FA_FAILED, LOGOUT, SESSIONS_REVOKED, PASSWORD_CHANGED, 2FA_RESET
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    device_info = Column(String(255), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now_jakarta_naive, index=True)

    user = relationship("User", back_populates="login_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "event_type": self.event_type,
            "ip_address": self.ip_address,
            "device_info": self.device_info,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BotActivityLog(Base):
    """
    Model riwayat audit log aktivitas pengguna pada bot Telegram.
    Mencatat username, user ID, chat ID, perintah, dan detail aksi (tambah apa, hapus apa, ganti apa, dll).
    """
    __tablename__ = "bot_activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    telegram_chat_id = Column(String(100), nullable=False, index=True) # ID grup
    telegram_user_id = Column(String(100), nullable=False, index=True) # ID user Telegram
    telegram_username = Column(String(100), nullable=True, index=True) # @username
    full_name = Column(String(200), nullable=True) # Nama lengkap user di Telegram
    command = Column(String(50), nullable=False, index=True) # /add, /del, /replace, dll
    details = Column(Text, nullable=False) # Ringkasan aksi
    raw_message = Column(Text, nullable=True) # Pesan lengkap yang dikirim
    status = Column(String(20), default="SUCCESS", index=True) # SUCCESS, FAILED, REJECTED
    created_at = Column(DateTime, default=now_jakarta_naive, index=True)

    tenant = relationship("Tenant", back_populates="activity_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "telegram_chat_id": self.telegram_chat_id,
            "telegram_user_id": self.telegram_user_id,
            "telegram_username": self.telegram_username,
            "full_name": self.full_name,
            "command": self.command,
            "details": self.details,
            "raw_message": self.raw_message,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

