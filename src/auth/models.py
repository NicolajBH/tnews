from pydantic import BaseModel


class TokenData(BaseModel):
    username: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str | None = None


class UserCreate(BaseModel):
    username: str
    password: str


class TokenRefresh(BaseModel):
    refresh_token: str
