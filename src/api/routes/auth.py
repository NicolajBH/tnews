from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, select
from datetime import datetime, timedelta

from src.auth.dependencies import get_current_user, oauth2_scheme
from src.auth.rate_limit import rate_limit_dependency
from src.auth.security import (
    verify_password,
    get_password_hash,
    blacklist_token,
    create_tokens,
    blacklist_refresh_token,
    is_refresh_token_blacklisted,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from src.auth.models import Token, UserCreate, TokenRefresh
from src.models.db_models import Users
from src.db.database import get_session

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post(
    "/register",
    response_model=Token,
    dependencies=[Depends(rate_limit_dependency("register"))],
)
def register_user(
    user: UserCreate, request: Request, session: Session = Depends(get_session)
):
    existing_user = session.exec(
        select(Users).where(Users.username == user.username)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    hashed_password = get_password_hash(user.password)

    access_token, refresh_token, refresh_expires = create_tokens({"sub": user.username})

    db_user = Users(
        username=user.username,
        password_hash=hashed_password,
        refresh_token=refresh_token,
        refresh_token_expires=refresh_expires,
        created_at=datetime.now(),
        last_login=datetime.now(),
        is_active=True,
    )

    session.add(db_user)
    session.commit()
    session.refresh(db_user)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@auth_router.post(
    "/login",
    response_model=Token,
    dependencies=[Depends(rate_limit_dependency("login"))],
)
def login(user: UserCreate, request: Request, session: Session = Depends(get_session)):
    db_user = session.exec(select(Users).where(Users.username == user.username)).first()
    if not db_user or not verify_password(user.password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # generate access token
    access_token, refresh_token, refresh_expires = create_tokens({"sub": user.username})

    # update user's refresh token and last login in database
    db_user.refresh_token = refresh_token
    db_user.refresh_token_expires = refresh_expires
    db_user.last_login = datetime.now()
    session.add(db_user)
    session.commit()

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@auth_router.post("/logout")
async def logout(
    request: Request,
    token: str = Depends(oauth2_scheme),
    current_user: Users = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    Logout the current user by blacklisting their tokens
    """
    await blacklist_token(token)

    if current_user.refresh_token:
        await blacklist_refresh_token(
            current_user.refresh_token,
            current_user.refresh_token_expires
            or datetime.now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )

        current_user.refresh_token = None
        current_user.refresh_token_expires = None
        session.add(current_user)
        session.commit()

    return {"detail": "Successfully logged out"}


@auth_router.post("/refresh", response_model=Token)
async def refresh_access_token(
    token_data: TokenRefresh,
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Endpoint to get a new access token using a refresh token
    """
    refresh_token = token_data.refresh_token

    if await is_refresh_token_blacklisted(refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    db_user = session.exec(
        select(Users).where(Users.refresh_token == refresh_token)
    ).first()

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    # check if token has expired
    if db_user.refresh_token_expires and db_user.refresh_token_expires < datetime.now():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has expired"
        )

    access_token, new_refresh_token, refresh_expires = create_tokens(
        {"sub": db_user.username}
    )

    db_user.refresh_token = new_refresh_token
    db_user.refresh_token_expires = refresh_expires
    session.add(db_user)
    session.commit()

    await blacklist_refresh_token(
        refresh_token, datetime.now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )

    return Token(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )
