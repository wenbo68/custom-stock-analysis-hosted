# -*- coding: utf-8 -*-
"""User accounts (the ``users`` table).

One row per (provider, provider account id). The row stores only what
the sign-in screen and run attribution need: email, display name,
avatar. Nothing else about the person is kept.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _session():
    from src.storage import DatabaseManager

    return DatabaseManager.get_instance().get_session()


def public_user(row: Any) -> Dict[str, Any]:
    """The shape the API hands to the browser."""
    return {
        "id": row.id,
        "provider": row.provider,
        "email": row.email,
        "display_name": row.display_name,
        "avatar_url": row.avatar_url,
    }


def upsert_from_identity(identity: Any) -> Dict[str, Any]:
    """Create the user on first sign-in; refresh the profile fields and
    the last-login time after that. Returns the public shape."""
    from src.storage import UserRecord, utc_naive_now

    with _session() as session:
        row = (
            session.query(UserRecord)
            .filter_by(provider=identity.provider, provider_subject=identity.subject)
            .one_or_none()
        )
        if row is None:
            row = UserRecord(provider=identity.provider,
                             provider_subject=identity.subject)
            session.add(row)
        row.email = identity.email
        row.display_name = identity.display_name
        row.avatar_url = identity.avatar_url
        row.last_login_at = utc_naive_now()
        session.commit()
        session.refresh(row)
        return public_user(row)


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    from src.storage import UserRecord

    with _session() as session:
        row = session.get(UserRecord, int(user_id))
        return public_user(row) if row is not None else None
