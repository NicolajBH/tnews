from datetime import datetime, timedelta
import re
import logging
import secrets
from typing import Optional, Tuple, List
from fastapi import HTTPException, status
from passlib.context import CryptContext
from jose import JWTError, jwt
from src.core.config import settings
from src.core.exceptions import PasswordTooWeakError
from src.clients.redis import RedisClient

logger = logging.getLogger(__name__)

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

REFRESH_TOKEN_EXPIRE_DAYS = 30
REFRESH_TOKEN_BYTES = 32


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
        elif "maximum_length" in failed_requirements:
            error_message = "Password exceeds maximum length of 128 characters."
        elif "common_password" in failed_requirements:
            error_message = "Password too common."
        elif "character_diversity" in failed_requirements:
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


async def blacklist_token(token: str) -> bool:
    """
    Add a token to the blacklist in redis

    The token will automatically expire from the blacklist after its JWT expires
    """
    try:
        # extract token expiration time
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_signature": True},
        )
        exp_timestamp = payload.get("exp")

        if not exp_timestamp:
            logger.warning("Token has no expiration, using default expiry time")
            ttl = ACCESS_TOKEN_EXPIRE_MINUTES * 60
        else:
            # calculate remanining ttl in seconds
            current_timestmap = datetime.now().timestamp()
            ttl = max(1, int(exp_timestamp - current_timestmap))

        # store token in blacklist with ttl matching its expiration
        redis_client = RedisClient()
        await redis_client.initialize()
        await redis_client.set(f"blacklist:{token}", "1", expire=ttl)
        return True
    except Exception as e:
        logger.error(f"Failed to blacklist token: {e}")
        return False


async def is_token_blacklisted(token: str) -> bool:
    """
    Check if a token is in the blacklist

    Returns True if token is blacklisted, False otherwise
    """
    try:
        redis_client = RedisClient()
        await redis_client.initialize()
        result = await redis_client.get(f"blacklist:{token}")
        return result is not None
    except Exception as e:
        logger.error(f"Failed to check token blacklist: {e}")
        return False


async def verify_token_with_blacklist_check(token: str) -> dict:
    """
    Verify a JWT token and ensure it's not blacklisted.

    Raises an HTTPException if the token is invalid or blacklisted
    Returns the token payload if valid
    """
    try:
        if await is_token_blacklisted(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not verify credentials",
        )


def create_refresh_token() -> str:
    """
    Generates a cryptographically secure refresh token

    Returns:
        str: A secure random token string
    """
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def create_tokens(data: dict) -> Tuple[str, str, datetime]:
    """
    Create both access token and refresh token for a user

    Args:
        data: Dictionary containing user information (should include 'sub' with username)

    Returns:
        Tuple of (access_token, refresh_token, refresh_token_expiry)
    """
    access_token = create_access_token(data)
    refresh_token = create_refresh_token()
    refresh_token_expires = datetime.now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    return access_token, refresh_token, refresh_token_expires


async def blacklist_refresh_token(refresh_token: str, expires_at: datetime) -> bool:
    """
    Add a refresh token to the blacklist in Redis

    Args:
        refresh_token: The refrsh token to blacklist
        expires_at: When the token expires

    Returns:
        bool: True if succesful, False otherwise
    """
    try:
        # calculate ttl in seconds
        current_timestamp = datetime.now().timestamp()
        exp_timestamp = expires_at.timestamp()
        ttl = max(1, int(exp_timestamp - current_timestamp))

        # store token in blacklist with ttl matching its expiration
        redis_client = RedisClient()
        await redis_client.initialize()
        await redis_client.set(f"refresh_blacklist{refresh_token}", "1", expire=ttl)
        return True
    except Exception as e:
        logger.error(f"Failed to blacklist refresh token: {str(e)}")
        return False


async def is_refresh_token_blacklisted(refresh_token: str) -> bool:
    """
    Checks if a refresh token is in the blacklist

    Args:
        refresh_token: The refresh token to check

    Returns:
        bool: True if token is blacklisted, False otherwise
    """
    try:
        redis_client = RedisClient()
        await redis_client.initialize()
        result = await redis_client.get(f"refresh_blacklist:{refresh_token}")
        return result is not None
    except Exception as e:
        logger.error(f"Failed to check refresh token blacklist: {str(e)}")
        return False
