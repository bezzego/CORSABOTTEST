# Все операции с датами выполняются по московскому времени (Europe/Moscow)

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
msk = ZoneInfo("Europe/Moscow")
from typing import Collection, Iterable, Sequence, Set

from sqlalchemy import delete, select, update, func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from src.database.database import AsyncSessionLocal, async_engine
from src.database.models import (
    KeysOrm,
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


KEY_RULE_TYPES: set[NotificationType] = {
    NotificationType.trial_expiring_soon,
    NotificationType.trial_expired,
    NotificationType.paid_expiring_soon,
    NotificationType.paid_expired,
}
REMINDER_RULE_TYPES: set[NotificationType] = {
    NotificationType.trial_expiring_soon,
    NotificationType.paid_expiring_soon,
}
FINISH_RULE_TYPES: set[NotificationType] = {
    NotificationType.trial_expired,
    NotificationType.paid_expired,
}
TRIAL_RULE_TYPES: set[NotificationType] = {
    NotificationType.trial_expiring_soon,
    NotificationType.trial_expired,
}
PAID_RULE_TYPES: set[NotificationType] = {
    NotificationType.paid_expiring_soon,
    NotificationType.paid_expired,
}
_DEDUP_ROUNDING_SECONDS = 60  # round planned_at to minute precision for deduplication


def _ensure_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=msk)
    return dt.astimezone(msk)


def _rounded_for_dedup(dt: datetime) -> datetime:
    # round down to the nearest minute for stability
    seconds = (dt.second // _DEDUP_ROUNDING_SECONDS) * _DEDUP_ROUNDING_SECONDS
    return dt.replace(second=seconds, microsecond=0)


# Все вычисления planned_at теперь делаются по московскому времени (Europe/Moscow)
def _calc_planned_at_for_key(rule: NotificationRule, finish: datetime, now: datetime) -> datetime | None:
    """Return planned_at in MSK for the given key finish or None if it should be skipped."""
    finish_msk = _ensure_aware_utc(finish)
    if finish_msk is None:
        return None
    # Normalize rule.type to NotificationType in case DB returned a raw string
    try:
        rtype = rule.type if isinstance(rule.type, NotificationType) else NotificationType(rule.type)
    except Exception:
        rtype = rule.type

    if finish_msk <= now.astimezone(msk) and rtype in REMINDER_RULE_TYPES:
        return None
    if finish_msk < now.astimezone(msk) and rtype in FINISH_RULE_TYPES:
        return None

    if rtype in FINISH_RULE_TYPES:
        planned_local = finish_msk
    else:
        offset = timedelta(days=rule.offset_days or 0, hours=rule.offset_hours or 0)
        planned_local = finish_msk - offset
        if planned_local < now.astimezone(msk):
            planned_local = now.astimezone(msk)

    return planned_local


async def _delete_existing_planned(rule_id: int, user_ids: Collection[int] | None = None) -> None:
    """Remove pending planned schedules so we can rebuild them."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = delete(UserNotificationSchedule).where(
                UserNotificationSchedule.rule_id == rule_id,
                UserNotificationSchedule.status == NotificationScheduleStatus.planned,
            )
            if user_ids:
                stmt = stmt.where(UserNotificationSchedule.user_id.in_(list(set(user_ids))))
            await session.execute(stmt)


async def _load_keys_for_rule(
    rule: NotificationRule,
    user_ids: Collection[int] | None = None,
    key_ids: Collection[int] | None = None,
) -> list[KeysOrm]:
    stmt = select(KeysOrm).where(KeysOrm.finish.isnot(None))
    if rule.type in TRIAL_RULE_TYPES:
        stmt = stmt.where(KeysOrm.is_test.is_(True))
    elif rule.type in PAID_RULE_TYPES:
        stmt = stmt.where(KeysOrm.is_test.is_(False))
    else:
        return []

    if user_ids:
        stmt = stmt.where(KeysOrm.user_id.in_(list(set(user_ids))))
    if key_ids:
        stmt = stmt.where(KeysOrm.id.in_(list(set(key_ids))))

    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        keys = list(result.scalars().all())

    return keys


async def regenerate_rule_schedules(
    rule: NotificationRule,
    *,
    user_ids: Collection[int] | None = None,
    key_ids: Collection[int] | None = None,
) -> int:
    """Rebuild schedules for the given rule limited to provided users or keys."""
    if rule.type not in KEY_RULE_TYPES or not rule.is_active:
        return 0

    now = datetime.now(timezone.utc)
    keys = await _load_keys_for_rule(rule, user_ids=user_ids, key_ids=key_ids)
    if not keys:
        return 0

    entries: "OrderedDict[str, tuple[int, int, datetime, str]]" = OrderedDict()
    affected_user_ids: Set[int] = set()
    for key in keys:
        planned_at = _calc_planned_at_for_key(rule, key.finish, now)
        if planned_at is None:
            continue
        rounded = _rounded_for_dedup(planned_at)
        # ensure we use enum value for dedup key even if rule.type is a raw string
        try:
            rtype_val = rule.type.value if isinstance(rule.type, NotificationType) else NotificationType(rule.type).value
        except Exception:
            rtype_val = str(rule.type)
        dedup_key = f"{rule.id}:{key.user_id}:{rtype_val}:{rounded.isoformat()}"
        entries[dedup_key] = (key.user_id, rule.id, planned_at, dedup_key)
        affected_user_ids.add(key.user_id)

    if not entries:
        return 0

    await _delete_existing_planned(rule.id, affected_user_ids if user_ids or key_ids else None)
    await bulk_upsert_schedule(entries.values())
    logger.info(
        "Regenerated %s schedules for rule_id=%s (users=%s, keys=%s)",
        len(entries),
        rule.id,
        sorted(affected_user_ids) if user_ids or key_ids else "ALL",
        "filtered" if key_ids else "ALL",
    )
    return len(entries)


async def sync_user_key_rules(user_id: int, key_ids: Collection[int] | None = None) -> int:
    """Sync schedules for key-related rules (A–D) for the given user."""
    rules = await get_rules(active_only=True)
    total = 0
    for rule in rules:
        if rule.type not in KEY_RULE_TYPES:
            continue
        total += await regenerate_rule_schedules(rule, user_ids=[user_id], key_ids=key_ids)
    return total


async def _auto_create_schedules_for_all_users(rule_id: int) -> int:
    """Populate schedules for the given rule using a dedicated session.
    Для правил типа new_user_no_keys также создаёт расписания для пользователей без активных ключей.
    """
    async with AsyncSessionLocal() as session:
        rule = await session.get(NotificationRule, rule_id)

    if not rule or not rule.is_active:
        return 0

    total_created = 0
    # If rule is key-based, use regenerate_rule_schedules
    if rule.type in KEY_RULE_TYPES:
        total_created = await regenerate_rule_schedules(rule)
        logger.info("Auto-created %s schedules for rule_id=%s (key-based)", total_created, rule.id)
        return total_created

    # Поддержка пользователей без активных ключей для специальных правил
    # Например, правило типа new_user_no_keys
    if getattr(rule.type, "value", rule.type) == "new_user_no_keys":
        # Найти пользователей, у которых нет активных ключей (ключи с finish > now)
        # models.py declares the user ORM as `UsersOrm` — import it under the name `User` for compatibility
        from src.database.models import UsersOrm as User
        now = datetime.now(msk)
        # KeysOrm.finish is stored as TIMESTAMP (naive) in the DB; convert the aware UTC now to naive
        # before using it in comparisons to avoid asyncpg datetime type errors.
        naive_now = _to_db_naive(now)
        async with AsyncSessionLocal() as session:
            # Подзапрос: выбрать user_id, у которых есть хотя бы один незавершённый ключ
            subq = select(KeysOrm.user_id).where(KeysOrm.finish > naive_now).distinct()
            # Все пользователи, которых нет в этом подзапросе
            users_stmt = select(User.id).where(~User.id.in_(subq))
            users_result = await session.execute(users_stmt)
            user_ids = [row[0] for row in users_result.all()]
        if not user_ids:
            logger.info("No users without active keys found for rule_id=%s", rule.id)
            return 0
        entries = []
        planned_at = now
        dedup_suffix = f"{rule.id}:{getattr(rule.type, 'value', rule.type)}"
        for user_id in user_ids:
            dedup_key = f"{rule.id}:{user_id}:{dedup_suffix}:{planned_at.isoformat()}"
            entries.append((user_id, rule.id, planned_at, dedup_key))
        await bulk_upsert_schedule(entries)
        logger.info("Auto-created %s schedules for rule_id=%s (users without keys)", len(entries), rule.id)
        return len(entries)

    # Non key-based rules are handled elsewhere (e.g. global weekly jobs)
    logger.info("No auto-creation logic for rule_id=%s type=%s", rule.id, rule.type)
    return 0


async def create_rule(*, auto_schedule: bool = True, **kwargs) -> NotificationRule:
    await _ensure_notification_enum()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            rule = NotificationRule(**kwargs)
            session.add(rule)
        await session.refresh(rule)
        logger.debug(f"Create notification rule: {rule}")
    # После коммита вызываем _auto_create_schedules_for_all_users в новом контексте
    if auto_schedule and rule.is_active:
        try:
            # Новый контекст сессии
            async with AsyncSessionLocal() as _:
                created_count = await _auto_create_schedules_for_all_users(rule.id)
                logger.info("Created %s schedules for rule_id=%s after rule creation", created_count, rule.id)
        except Exception:
            logger.exception("Failed to auto-generate schedules for rule_id=%s on create", rule.id)
    return rule


async def update_rule(rule_id: int, **kwargs) -> NotificationRule | None:
    if "type" in kwargs:
        await _ensure_notification_enum()

    # detect previous is_active to understand state transition
    old_is_active: bool | None = None
    updated_rule: NotificationRule | None = None

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # fetch current is_active before update (may be None if rule does not exist)
            res_old = await session.execute(
                select(NotificationRule.is_active).where(NotificationRule.id == rule_id)
            )
            old_is_active = res_old.scalar_one_or_none()

            stmt = (
                update(NotificationRule)
                .where(NotificationRule.id == rule_id)
                .values(**kwargs)
                .returning(NotificationRule)
            )
            result = await session.execute(stmt)
            updated_rule = result.scalar()

    logger.debug(f"Update notification rule {rule_id}: {kwargs}")

    if updated_rule is None:
        return None

    try:
        if "is_active" in kwargs and updated_rule.is_active is False:
            await cancel_schedules_by_rule(updated_rule.id)
            return updated_rule

        refreshed_rule = await get_rule(rule_id) or updated_rule
        rebuild_triggers = {"offset_days", "offset_hours", "type", "is_active"}

        should_rebuild = False
        if "is_active" in kwargs and old_is_active is False and refreshed_rule.is_active is True:
            should_rebuild = True
        elif refreshed_rule.is_active and rebuild_triggers.intersection(kwargs.keys()):
            should_rebuild = True

        if should_rebuild:
            await regenerate_rule_schedules(refreshed_rule)
    except Exception:
        logger.exception(
            "Post-update side-effect failed for rule_id=%s (old_active=%s, new_active=%s)",
            rule_id,
            old_is_active,
            getattr(updated_rule, "is_active", None),
        )

    return updated_rule


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
                    sent_at=datetime.now(msk),
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
                    sent_at=datetime.now(msk),
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
                stmt.values(status=NotificationScheduleStatus.cancelled, updated_at=_to_db_naive(datetime.now(msk)))
            )


async def cancel_schedules_by_rule(rule_id: int, user_id: int | None = None) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stmt = update(UserNotificationSchedule).where(UserNotificationSchedule.rule_id == rule_id)
            if user_id:
                stmt = stmt.where(UserNotificationSchedule.user_id == user_id)
            await session.execute(
                stmt.values(status=NotificationScheduleStatus.cancelled, updated_at=_to_db_naive(datetime.now(msk)))
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
