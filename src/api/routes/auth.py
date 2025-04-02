from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import select

from src.auth.rate_limit import rate_limit_dependency
from src.auth.security import verify_password, get_password_hash, create_access_token
from src.auth.models import Token, UserCreate
from src.models.db_models import Users
from src.db.database import SessionDep

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post(
    "/register",
    response_model=Token,
    dependencies=[Depends(rate_limit_dependency("register"))],
)
def register_user(user: UserCreate, session: SessionDep, request: Request):
    existing_user = session.exec(
        select(Users).where(Users.username == user.username)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    db_user = Users(
        username=user.username, password_hash=get_password_hash(user.password)
    )
    session.add(db_user)
    session.commit()
    session.refresh(db_user)

    access_token = create_access_token(data={"sub": user.username})
    return Token(access_token=access_token, token_type="bearer")


@auth_router.post(
    "/login",
    response_model=Token,
    dependencies=[Depends(rate_limit_dependency("register"))],
)
def login(user: UserCreate, session: SessionDep, request: Request):
    db_user = session.exec(select(Users).where(Users.username == user.username)).first()

    if not db_user or not verify_password(user.password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    access_token = create_access_token(data={"sub": user.username})
    return Token(access_token=access_token, token_type="bearer")
