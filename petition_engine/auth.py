"""
auth.py — Avukat kimlik doğrulama servisi
JWT token üretimi, avukat kaydı ve giriş endpoint'leri.
Ana api.py'ye router olarak eklenir.
"""

import os
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt as pyjwt
import psycopg as psycopg2
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, Field

log = logging.getLogger(__name__)

JWT_SECRET  = os.getenv("JWT_SECRET", "degistir-production-da")
JWT_EXPIRE  = int(os.getenv("JWT_EXPIRE_HOURS", "8"))  # Saat
ALGORITHM   = "HS256"

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Pydantic modeller ─────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    full_name:  str   = Field(..., min_length=3, max_length=100)
    email:      EmailStr
    password:   str   = Field(..., min_length=8)
    bar_number: str   = Field(..., description="Baro sicil numarası")
    baro:       str   = Field(..., description="Bağlı olunan baro")
    firm_name:  str   = ""   # İsteğe bağlı


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    lawyer_id:    int
    full_name:    str
    expires_in:   int   # saniye


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(payload: dict) -> str:
    data = payload.copy()
    data["exp"] = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE)
    return pyjwt.encode(data, JWT_SECRET, algorithm=ALGORITHM)


def get_db():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    try:
        yield conn
    finally:
        conn.close()


# ── Endpoint'ler ──────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, conn=Depends(get_db)):
    """Yeni avukat kaydı."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM lawyers WHERE email=%s", (body.email,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı")

        # Firma oluştur/bul
        firm_id = None
        if body.firm_name:
            slug = body.firm_name.lower().replace(" ", "-")[:50]
            cur.execute("""
                INSERT INTO firms (name, slug)
                VALUES (%s, %s)
                ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name
                RETURNING id
            """, (body.firm_name, slug))
            firm_id = cur.fetchone()[0]

        # Avukat kaydı
        cur.execute("""
            INSERT INTO lawyers
                (firm_id, full_name, bar_number, email, password_hash)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (
            firm_id,
            body.full_name,
            body.bar_number,
            body.email,
            hash_password(body.password),
        ))
        lawyer_id = cur.fetchone()[0]
        conn.commit()

    token = create_token({
        "lawyer_id": lawyer_id,
        "email":     body.email,
        "name":      body.full_name,
        "baro":      body.baro,
        "sicil":     body.bar_number,
    })
    log.info(f"Yeni avukat kaydedildi: {body.email} [#{lawyer_id}]")

    return TokenResponse(
        access_token = token,
        lawyer_id    = lawyer_id,
        full_name    = body.full_name,
        expires_in   = JWT_EXPIRE * 3600,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, conn=Depends(get_db)):
    """Avukat girişi — JWT token döner."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT l.id, l.full_name, l.password_hash, l.bar_number, l.is_active,
                   f.name AS firm_name
            FROM lawyers l
            LEFT JOIN firms f ON f.id = l.firm_id
            WHERE l.email = %s
        """, (body.email,))
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı")

    lawyer_id, full_name, pw_hash, bar_number, is_active, firm_name = row

    if not is_active:
        raise HTTPException(status_code=403, detail="Hesabınız askıya alınmış")

    if not verify_password(body.password, pw_hash):
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı")

    token = create_token({
        "lawyer_id": lawyer_id,
        "email":     body.email,
        "name":      full_name,
        "baro":      firm_name or "",
        "sicil":     bar_number or "",
    })
    log.info(f"Giriş: {body.email}")

    return TokenResponse(
        access_token = token,
        lawyer_id    = lawyer_id,
        full_name    = full_name,
        expires_in   = JWT_EXPIRE * 3600,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(authorization: str, conn=Depends(get_db)):
    """Mevcut token'ı yeniler (henüz süresi dolmamış olmalı)."""
    try:
        token   = authorization.replace("Bearer ", "")
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Geçersiz token")

    # Veritabanından güncel bilgileri al
    with conn.cursor() as cur:
        cur.execute(
            "SELECT full_name, bar_number, is_active FROM lawyers WHERE id=%s",
            (payload["lawyer_id"],)
        )
        row = cur.fetchone()

    if not row or not row[2]:
        raise HTTPException(status_code=403, detail="Hesap bulunamadı veya askıya alınmış")

    new_token = create_token({
        "lawyer_id": payload["lawyer_id"],
        "email":     payload["email"],
        "name":      row[0],
        "baro":      payload.get("baro", ""),
        "sicil":     row[1] or "",
    })

    return TokenResponse(
        access_token = new_token,
        lawyer_id    = payload["lawyer_id"],
        full_name    = row[0],
        expires_in   = JWT_EXPIRE * 3600,
    )
