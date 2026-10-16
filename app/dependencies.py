from collections.abc import Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Membership, User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    def unauthorized() -> HTTPException:
        return HTTPException(
            status_code=401,
            detail="Missing, invalid, or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()

    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        if claims.get("type") != "access":
            raise jwt.InvalidTokenError("Unexpected token type")
        user_id = UUID(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized()

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


def require_team_roles(*allowed_roles: str) -> Callable[..., Membership]:
    """Return a dependency that requires team membership and, optionally, a role."""

    def dependency(
        team_id: UUID,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Membership:
        membership = db.get(Membership, (user.id, team_id))
        if membership is None:
            # Return 404 so callers cannot use this endpoint to discover other teams.
            raise HTTPException(status_code=404, detail="Team not found")
        if allowed_roles and membership.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Your team role cannot perform this action")
        return membership

    return dependency
