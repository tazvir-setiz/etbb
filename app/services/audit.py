import logging
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

logger = logging.getLogger(__name__)

# Ensure voter identities and vote scores are NEVER logged in audit records
FORBIDDEN_AUDIT_KEYS = {"voter_id", "voter_user_id", "voters", "vote_id", "scores"}


class AuditError(ValueError):
    """Raised when an audit record violates privacy or security constraints."""


async def record_audit_log(
    session: AsyncSession,
    *,
    platform: str,
    actor_id: int,
    action: str,
    target_type: str,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    safe_details = dict(details or {})
    # Strip any potentially sensitive keys that could disclose voter identity
    for forbidden in FORBIDDEN_AUDIT_KEYS:
        if forbidden in safe_details:
            del safe_details[forbidden]

    entry = AuditLog(
        platform=platform,
        actor_user_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=safe_details,
    )
    session.add(entry)
    await session.commit()
    logger.info(
        "[%s] Audit log recorded: actor=%s action=%s target_type=%s target_id=%s details=%s",
        platform,
        actor_id,
        action,
        target_type,
        target_id,
        safe_details,
    )
    return entry


async def list_audit_logs(
    session: AsyncSession,
    *,
    platform: str,
    limit: int = 15,
    offset: int = 0,
) -> tuple[list[AuditLog], int]:
    total = (
        await session.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.platform == platform)
        )
    ) or 0
    query = (
        select(AuditLog)
        .where(AuditLog.platform == platform)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    results = (await session.scalars(query)).all()
    return list(results), total
