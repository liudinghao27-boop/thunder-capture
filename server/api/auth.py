"""Auth routes."""

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.auth import create_access_token, get_current_user, hash_password, verify_password
from server.models import get_db
from server.models.user import User
from server.schemas.user import TokenResponse, UserLogin, UserOut, UserRegister
from server.secret_store import encrypt_secret, mask_secret

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(data: UserRegister, db: Session = Depends(get_db)):
    has_users = db.query(User.id).first() is not None
    allow_registration = os.getenv("THUNDER_ALLOW_REGISTRATION", "").lower() in {
        "1", "true", "yes", "on",
    }
    if has_users and not allow_registration:
        raise HTTPException(
            status_code=403,
            detail="Registration is closed. Set THUNDER_ALLOW_REGISTRATION=1 to enable it.",
        )
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


from pydantic import BaseModel

class UserSettingsOut(BaseModel):
    deepseek_key: str
    zhipu_key: str
    openai_key: str


class UserSettingsUpdate(BaseModel):
    deepseek_key: str | None = None
    zhipu_key: str | None = None
    openai_key: str | None = None


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/settings", response_model=UserSettingsOut)
def get_user_settings(
    current_user: User = Depends(get_current_user),
):
    return UserSettingsOut(
        deepseek_key=mask_secret(current_user.deepseek_key),
        zhipu_key=mask_secret(current_user.zhipu_key),
        openai_key=mask_secret(current_user.openai_key),
    )


@router.post("/settings", response_model=UserSettingsOut)
def update_user_settings(
    data: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.deepseek_key is not None:
        if "****" not in data.deepseek_key:
            current_user.deepseek_key = encrypt_secret(data.deepseek_key)
            
    if data.zhipu_key is not None:
        if "****" not in data.zhipu_key:
            current_user.zhipu_key = encrypt_secret(data.zhipu_key)
            
    if data.openai_key is not None:
        if "****" not in data.openai_key:
            current_user.openai_key = encrypt_secret(data.openai_key)

    db.commit()
    db.refresh(current_user)
    
    return UserSettingsOut(
        deepseek_key=mask_secret(current_user.deepseek_key),
        zhipu_key=mask_secret(current_user.zhipu_key),
        openai_key=mask_secret(current_user.openai_key),
    )
