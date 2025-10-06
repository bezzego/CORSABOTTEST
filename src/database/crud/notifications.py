from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy import delete, select, update, func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from src.database.database import AsyncSessionLocal, async_engine
from src.database.models import (
    NotificationLog,
    NotificationLogStatus,
    NotificationRule,
    NotificationScheduleStatus,
    NotificationType,
    UserNotificationSchedule,
)
from src.logs import getLogger


logger = getLogger(__name__)


_enum_lock = asyncio.Lock()
_enum_ready = False


async def _ensure_notification_enum() -> None:
    global _enum_ready
    if _enum_ready:
        return
    async with _enum_lock:
        if _enum_ready:
            return
        async with async_engine.begin() as conn:
            for notif_type in NotificationType:
                enum_literal = notif_type.value.replace("'", "''")
                await conn.execute(
                    text(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{enum_literal}'")
                )
        logger.info("Ensured notificationtype enum contains all values: %s", [t.value for t in NotificationType])
        _enum_ready = True


def _to_db_naive(dt: datetime | None) -> datetime | None:
    """Convert datetime to naive UTC datetime suitable for TIMESTAMP WITHOUT TIME ZONE columns.

    If dt is None, returns None. If dt has tzinfo, convert to UTC and strip tzinfo.
    If dt is already naive, return as-is (assumed to be UTC).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


async def create_rule(**kwargs) -> NotificationRule:
    await _ensure_notification_enum()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            rule = NotificationRule(**kwargs)
            session.add(rule)
        await session.refresh(rule)
        logger.debug(f"Create notification rule: {rule}")
        return rule


async def update_rule(rule_id: int, **kwargs) -> NotificationRule | None:
    if "type" in kwargs:
        await _ensure_notification_enum()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = (
                update(NotificationRule)
                .where(NotificationRule.id == rule_id)
                .values(**kwargs)
                .returning(NotificationRule)
            )
            result = await session.execute(stmt)
            rule = result.scalar()
        logger.debug(f"Update notification rule {rule_id}: {kwargs}")
        return rule


async def set_rule_active(rule_id: int, is_active: bool) -> NotificationRule | None:
    return await update_rule(rule_id, is_active=is_active)


async def delete_rule(rule_id: int) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # remove dependent logs first to satisfy FK constraints
            await session.execute(
                delete(NotificationLog).where(NotificationLog.rule_id == rule_id)
            )
            # remove any scheduled entries referencing the rule
            await session.execute(
                delete(UserNotificationSchedule).where(UserNotificationSchedule.rule_id == rule_id)
            )
            # now safe to delete the rule itself
            await session.execute(delete(NotificationRule).where(NotificationRule.id == rule_id))
        logger.debug(f"Delete notification rule {rule_id}")


async def get_rule(rule_id: int) -> NotificationRule | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(NotificationRule).where(NotificationRule.id == rule_id))
        return result.scalar_one_or_none()


async def get_rules(rule_type: NotificationType | None = None, active_only: bool | None = None) -> Sequence[NotificationRule]:
    async with AsyncSessionLocal() as session:
        stmt = select(NotificationRule)
        if rule_type:
            stmt = stmt.where(NotificationRule.type == rule_type)
        if active_only is True:
            stmt = stmt.where(NotificationRule.is_active.is_(True))
        elif active_only is False:
            stmt = stmt.where(NotificationRule.is_active.is_(False))

        stmt = stmt.order_by(NotificationRule.priority.desc(), NotificationRule.id.asc())
        result = await session.execute(stmt)
        return result.scalars().all()


async def upsert_schedule(
    user_id: int,
    rule_id: int,
    planned_at: datetime,
    dedup_key: str,
) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = (
                insert(UserNotificationSchedule)
                .values(
                    user_id=user_id,
                    rule_id=rule_id,
                    planned_at=planned_at,
                    dedup_key=dedup_key,
                    status=NotificationScheduleStatus.planned,
                )
                .on_conflict_do_nothing(index_elements=[UserNotificationSchedule.dedup_key])
            )
            await session.execute(stmt)


async def bulk_upsert_schedule(entries: Iterable[tuple[int, int, datetime, str]]) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            values = [
                dict(
                    user_id=user_id,
                    rule_id=rule_id,
                    planned_at=planned_at,
                    dedup_key=dedup_key,
                    status=NotificationScheduleStatus.planned,
                )
                for user_id, rule_id, planned_at, dedup_key in entries
            ]
            if not values:
                return
            stmt = insert(UserNotificationSchedule).values(values)
            stmt = stmt.on_conflict_do_nothing(index_elements=[UserNotificationSchedule.dedup_key])
            await session.execute(stmt)


async def fetch_due_schedules(limit: int = 50) -> Sequence[UserNotificationSchedule]:
    async with AsyncSessionLocal() as session:
        # Use aware UTC timestamps for comparisons against TIMESTAMPTZ columns
        now_utc = datetime.now(timezone.utc)

        # Diagnostic: log how many planned schedules exist and earliest planned_at
        try:
            count_stmt = select(func.count()).select_from(UserNotificationSchedule).where(
                UserNotificationSchedule.status == NotificationScheduleStatus.planned
            )
            earliest_stmt = select(UserNotificationSchedule.planned_at).where(
                UserNotificationSchedule.status == NotificationScheduleStatus.planned
            ).order_by(UserNotificationSchedule.planned_at.asc()).limit(1)
            total_result = await session.execute(count_stmt)
            total_planned = total_result.scalar_one() or 0
            earliest_result = await session.execute(earliest_stmt)
            earliest = earliest_result.scalar_one_or_none()
            logger.debug("Planned schedules total=%s earliest_planned_at=%s now_utc=%s", total_planned, earliest, now_utc)
        except Exception:
            logger.exception("Failed to fetch diagnostic info for planned schedules")

        stmt = (
            select(UserNotificationSchedule)
            .options(selectinload(UserNotificationSchedule.rule))
            .where(
                UserNotificationSchedule.status == NotificationScheduleStatus.planned,
                UserNotificationSchedule.planned_at <= now_utc,
            )
            .order_by(UserNotificationSchedule.planned_at.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        logger.debug("fetch_due_schedules returning %d rows (limit=%s)", len(rows), limit)
        return rows


async def mark_schedule_sent(
    schedule_id: int,
    *,
    message_id: str | None = None,
    user_id: int | None = None,
    rule_id: int | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                update(UserNotificationSchedule)
                .where(UserNotificationSchedule.id == schedule_id)
                .values(
                    status=NotificationScheduleStatus.sent,
                    sent_at=datetime.now(timezone.utc),
                    last_error=None,
                )
            )
            log = NotificationLog(
                user_id=user_id,
                rule_id=rule_id,
                schedule_id=schedule_id,
                status=NotificationLogStatus.ok,
                message_id=message_id,
            )
            session.add(log)


async def mark_schedule_error(
    schedule_id: int,
    error: str,
    *,
    user_id: int | None = None,
    rule_id: int | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                update(UserNotificationSchedule)
                .where(UserNotificationSchedule.id == schedule_id)
                .values(
                    status=NotificationScheduleStatus.error,
                    last_error=error,
                    sent_at=datetime.now(timezone.utc),
                )
            )
            log = NotificationLog(
                user_id=user_id,
                rule_id=rule_id,
                schedule_id=schedule_id,
                status=NotificationLogStatus.failed,
                error=error,
            )
            session.add(log)


async def cancel_user_schedules(user_id: int, types: Iterable[NotificationType] | None = None) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = update(UserNotificationSchedule).where(UserNotificationSchedule.user_id == user_id)
            if types:
                type_ids_stmt = select(NotificationRule.id).where(NotificationRule.type.in_(list(types)))
                stmt = stmt.where(UserNotificationSchedule.rule_id.in_(type_ids_stmt))
            await session.execute(
                stmt.values(status=NotificationScheduleStatus.cancelled, updated_at=_to_db_naive(datetime.now(timezone.utc)))
            )


async def cancel_schedules_by_rule(rule_id: int, user_id: int | None = None) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = update(UserNotificationSchedule).where(UserNotificationSchedule.rule_id == rule_id)
            if user_id:
                stmt = stmt.where(UserNotificationSchedule.user_id == user_id)
            await session.execute(
                stmt.values(status=NotificationScheduleStatus.cancelled, updated_at=_to_db_naive(datetime.now(timezone.utc)))
            )


async def log_manual(
    user_id: int,
    rule_id: int,
    schedule_id: int | None,
    status: NotificationLogStatus,
    message_id: str | None = None,
    error: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            log_entry = NotificationLog(
                user_id=user_id,
                rule_id=rule_id,
                schedule_id=schedule_id,
                status=status,
                message_id=message_id,
                error=error,
            )
            session.add(log_entry)
