from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User, now


def session_token(user: User):
    return jwt.encode(
        {"sub": user.id, "exp": now() + timedelta(hours=8), "iss": "ai-cerbos", "aud": "dashboard"},
        settings().session_secret,
        algorithm="HS256",
    )


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("cerbos_session")
    try:
        claims = jwt.decode(
            token or "",
            settings().session_secret,
            algorithms=["HS256"],
            issuer="ai-cerbos",
            audience="dashboard",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Sign in to continue") from None
    user = db.get(User, claims["sub"])
    if not user or not user.active:
        raise HTTPException(401, "Account is unavailable")
    return user
