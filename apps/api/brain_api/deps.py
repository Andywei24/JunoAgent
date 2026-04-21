"""FastAPI dependencies: database session + current user placeholder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from brain_api.config import Settings, get_settings
from brain_db.repositories import UserRepository
from brain_db.session import get_session


@dataclass(frozen=True)
class CurrentUser:
    """Minimal principal record used by downstream code.

    Stage 1 always resolves to the configured dev user. Real auth (API keys,
    OAuth, session tokens) can replace `get_current_user` without touching
    the rest of the app.
    """

    id: str
    email: str | None = None


def get_current_user(
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    users = UserRepository(db)
    user = users.upsert_dev_user(settings.dev_user_id, email=settings.dev_user_email)
    return CurrentUser(id=user.id, email=user.email)


DbSession = Annotated[Session, Depends(get_session)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
AppSettings = Annotated[Settings, Depends(get_settings)]
