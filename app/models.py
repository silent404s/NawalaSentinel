from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, Boolean, Index
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

    domains = relationship("Domain", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "domain_quota": self.domain_quota,
            "telegram_chat_id": self.telegram_chat_id,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class Domain(Base):
    """
    Model untuk menyimpan daftar domain dan subdomain yang dipantau.
    """
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), unique=True, nullable=False, index=True) # e.g. domain.com or sub.domain.com
    category = Column(String(100), default="General", index=True)
    overall_status = Column(String(50), default="UNCHECKED", index=True) # UNCHECKED, NORMAL, BLOCKED, MIXED
    cf_status = Column(String(50), default="CLEAN", index=True) # CLEAN, PHISHING, UNCHECKED
    cf_reason = Column(Text, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_jakarta_naive)

    # Relationship dengan hasil pengecekan per operator & log
    user = relationship("User", back_populates="domains")
    results = relationship("CheckResult", back_populates="domain", cascade="all, delete-orphan")
    logs = relationship("StatusLog", back_populates="domain", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "category": self.category,
            "overall_status": self.overall_status,
            "cf_status": self.cf_status,
            "cf_reason": self.cf_reason,
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
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
