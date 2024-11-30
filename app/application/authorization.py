from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt import decode as jwt_decode, PyJWTError

from app.env_validator import get_settings
from app.user.entities import User

from app.application.typevar import USER_ID

settings = get_settings()

security = HTTPBearer(scheme_name="Access Token")


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> USER_ID:
    try:
        token = credentials.credentials

        payload = jwt_decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])

        user_id: str = payload.get("uid")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )

        return user_id

    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


async def get_current_user_entity(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    try:
        token = credentials.credentials

        payload = jwt_decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])

        user_id: str = payload.get("uid")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )

        user = await User.get(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )
        return user

    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


async def get_current_auth_user_entity(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    try:
        token = credentials.credentials

        payload = jwt_decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])

        user_id: str = payload.get("uid")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )

        user = await User.get(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )
        return user

    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )
