from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import select
from .security import verify_token_with_blacklist_check
from src.models.db_models import Users
from src.db.database import SessionDep

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


async def get_current_user(
    session: SessionDep, token: str = Depends(oauth2_scheme)
) -> Users:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = await verify_token_with_blacklist_check(token)
    username = payload.get("sub")
    if username is None or not isinstance(username, str):
        raise credentials_exception

    user = session.exec(select(Users).where(Users.username == username)).first()

    if user is None:
        raise credentials_exception

    return user
