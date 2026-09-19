import hashlib
import binascii
import os
import secrets
from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import User
from sqlalchemy.future import select

# Hashing utilities using standard library hashlib (PBKDF2 HMAC SHA256)

def hash_password(password: str) -> str:
    """Hash a password for storing."""
    salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
    pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    pwdhash = binascii.hexlify(pwdhash)
    return (salt + pwdhash).decode('ascii')

def verify_password(stored_password: str, provided_password: str) -> bool:
    """Verify a stored password against one provided by user"""
    salt = stored_password[:64]
    stored_password = stored_password[64:]
    pwdhash = hashlib.pbkdf2_hmac('sha256', 
                                  provided_password.encode('utf-8'), 
                                  salt.encode('ascii'), 
                                  100000)
    pwdhash = binascii.hexlify(pwdhash).decode('ascii')
    return pwdhash == stored_password

def generate_activation_token() -> str:
    """Generate a unique activation token like NS-8F3K9A"""
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    token = ''.join(secrets.choice(chars) for _ in range(6))
    return f"NS-{token}"

# Session dependencies
async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    stmt = select(User).where(User.id == user_id, User.is_active == True)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user

async def get_current_superadmin(current_user: User = Depends(get_current_user)):
    if current_user.role != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user
