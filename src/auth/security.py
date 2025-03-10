from datetime import datetime, timedelta
import re
from typing import Optional, Tuple, List
from fastapi import HTTPException, status
from passlib.context import CryptContext
from jose import JWTError, jwt
from src.core.config import settings
from src.core.exceptions import PasswordTooWeakError

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def validate_password_strength(password: str) -> Tuple[bool, str, List[str]]:
    failed_requirements = []
    if len(password) < 8:
        failed_requirements.append("minimum_length")
    if len(password) > 128:
        failed_requirements.append("maximum_length")
    common_passwords = ["123456", "123456789", "12345678", "password", "qwerty123"]
    if password.lower() in common_passwords:
        failed_requirements.append("common_password")

    has_lowercase = re.search(r"[a-z]", password) is not None
    has_uppercase = re.search(r"[A-Z]", password) is not None
    has_digit = re.search(r"\d", password) is not None
    has_special = re.search(r'[!@#$%^&*(),.?":{}|<>]', password) is not None

    strength_points = sum([has_lowercase, has_uppercase, has_digit, has_special])
    if strength_points < 3:
        failed_requirements.append("character_diversity")

    if failed_requirements:
        if "minimum_length" in failed_requirements:
            error_message = "Password must be at least 8 characters long."
        if "maximum_length" in failed_requirements:
            error_message = "Password must not exceed 128 characters."
        if "common_password" in failed_requirements:
            error_message = "Password too common."
        if "character_diversity" in failed_requirements:
            error_message = "Password must contain at least 3 of the following: lowercase letter, uppercase letter, digit, special character."
        else:
            error_message = "Password does not meet security requirements."

        return False, error_message, failed_requirements

    return True, "", []


def get_password_hash(password: str) -> str:
    is_valid, error_message, failed_requirements = validate_password_strength(password)
    if not is_valid:
        raise PasswordTooWeakError(
            detail=error_message, requirements_failed=failed_requirements
        )
    return pwd_context.hash(password)


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not verify credentials",
        )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
