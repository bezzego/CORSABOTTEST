from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest
from urllib.parse import urlparse
from apscheduler.triggers.cron import CronTrigger

from src.database.crud.notifications import (
    bulk_upsert_schedule,
    cancel_user_schedules,
    fetch_due_schedules,
    get_rule,
    get_rules,
    mark_schedule_error,
    mark_schedule_sent,
    upsert_schedule,
)
from src.database.crud.users import get_users
from src.database.crud.keys import get_user_keys
from src.database.models import NotificationRule, NotificationType
from src.logs import getLogger

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore


logger = getLogger(__name__)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _calc_interval(rule: NotificationRule) -> timedelta:
    delta = timedelta()
    if rule.repeat_every_days:
        delta += timedelta(days=rule.repeat_every_days)
    if rule.repeat_every_hours:
        delta += timedelta(hours=rule.repeat_every_hours)
    return delta


def _calc_offset(rule: NotificationRule) -> timedelta:
    delta = timedelta()
    if rule.offset_days:
        delta += timedelta(days=rule.offset_days)
    if rule.offset_hours:
        delta += timedelta(hours=rule.offset_hours)
    return delta


class NotificationService:
    dispatcher_job_id = "notifications_dispatcher"

    def __init__(self) -> None:
        self.scheduler = None

    async def init(self, scheduler, bot: Bot) -> None:
        self.scheduler = scheduler
        scheduler.add_job(
            self.dispatch_due_notifications,
            "interval",
            seconds=60,
            args=[bot],
            id=self.dispatcher_job_id,
            replace_existing=True,
        )
        logger.info("NotificationService initialized: dispatcher job added (id=%s)", self.dispatcher_job_id)
        logger.info("Dispatcher job started and will run every 60s")
        await self.refresh_global_jobs(bot)

    async def refresh_global_jobs(self, bot: Bot) -> None:
        if not self.scheduler:
            return

        existing_ids = {job.id for job in self.scheduler.get_jobs()}
        target_prefix = "notification_global_"
        for job_id in existing_ids:
            if job_id.startswith(target_prefix):
                self.scheduler.remove_job(job_id)

        rules = await get_rules(NotificationType.global_weekly, active_only=True)
        for rule in rules:
            if rule.weekday is None or rule.time_of_day is None:
                continue
            tz_name = rule.timezone or "UTC"
            trigger = CronTrigger(
                day_of_week=str(rule.weekday),
                hour=rule.time_of_day.hour,
                minute=rule.time_of_day.minute,
                second=0,
                timezone=ZoneInfo(tz_name),
            )
            job_id = f"notification_global_{rule.id}"
            self.scheduler.add_job(
                self.enqueue_global_rule,
                trigger,
                args=[bot, rule.id],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=120,
            )
            # log scheduling details for easier debugging
            job = self.scheduler.get_job(job_id)
            # APScheduler Job may not expose `next_run_time` attribute depending on version
            next_run = getattr(job, "next_run_time", None) if job is not None else None
            logger.info(
                "Scheduled global notification job: id=%s rule_id=%s tz=%s time=%s next_run=%s",
                job_id,
                rule.id,
                tz_name,
                rule.time_of_day.strftime("%H:%M"),
                next_run,
            )

    async def enqueue_global_rule(self, bot: Bot, rule_id: int) -> None:
        rule = await get_rule(rule_id)
        if not rule or not rule.is_active:
            return
        # normalize rule.type to enum if DB returned a raw string
        try:
            rtype = rule.type if isinstance(rule.type, NotificationType) else NotificationType(rule.type)
            rule.type = rtype
        except Exception:
            pass

        now = datetime.now(ZoneInfo(rule.timezone or "UTC"))
        planned_at = now.astimezone(timezone.utc)

        try:
            users = await get_users() or []
            user_count = len(users)
            entries = []
            for user in users:
                dedup_key = f"{user.id}:{rule.id}:{int(planned_at.timestamp())}"
                entries.append((user.id, rule.id, planned_at, dedup_key))

            if entries:
                await bulk_upsert_schedule(entries)
                logger.info(
                    "Enqueued global rule=%s for %d users at planned_at=%s (utc)",
                    rule.id,
                    len(entries),
                    planned_at,
                )
                logger.info("Starting dispatch of due notifications after enqueue")
                await self.dispatch_due_notifications(bot)
            else:
                logger.info(
                    "Enqueue global rule=%s: no users found (user_count=%s) planned_at=%s",
                    rule.id,
                    user_count,
                    planned_at,
                )

        except Exception as exc:  # pragma: no cover - log DB/network errors
            logger.error("Failed to enqueue global rule=%s: %s", rule.id, exc, exc_info=True)
            return

    async def dispatch_due_notifications(self, bot: Bot) -> None:
        # run until no due schedules left (process in batches)
        total_processed = 0
        while True:
            schedules = await fetch_due_schedules(limit=50)
            if not schedules:
                break
            logger.debug("Dispatching batch of %d due schedules", len(schedules))
            await self._process_batch(bot, schedules)
            total_processed += len(schedules)
        if total_processed:
            logger.info("Dispatch complete: processed %d schedules", total_processed)

    async def _process_batch(self, bot: Bot, schedules: Sequence) -> None:
        for schedule in schedules:
            rule: NotificationRule = schedule.rule
            if not rule or not rule.is_active:
                await mark_schedule_error(
                    schedule.id,
                    "Rule inactive",
                    user_id=schedule.user_id,
                    rule_id=getattr(rule, "id", None),
                )
                continue

            try:
                message_id = await self._send_message(bot, schedule.user_id, rule)
                await mark_schedule_sent(
                    schedule.id,
                    message_id=message_id,
                    user_id=schedule.user_id,
                    rule_id=rule.id,
                )

                if _calc_interval(rule) and await self._should_repeat(rule, schedule.user_id):
                    await self._schedule_next_repeat(schedule.user_id, rule, schedule.planned_at)

            except Exception as exc:  # pragma: no cover
                logger.error(
                    f"Failed to send notification rule={rule.id} user={schedule.user_id}: {exc}",
                    exc_info=True,
                )
                await mark_schedule_error(
                    schedule.id,
                    str(exc),
                    user_id=schedule.user_id,
                    rule_id=rule.id,
                )

    async def _schedule_next_repeat(
        self,
        user_id: int,
        rule: NotificationRule,
        previous_planned_at: datetime,
    ) -> None:
        interval = _calc_interval(rule)
        if not interval:
            return

        next_planned = _ensure_utc(previous_planned_at) + interval
        try:
            rtype = rule.type if isinstance(rule.type, NotificationType) else NotificationType(rule.type)
        except Exception:
            rtype = None
        dedup_key = f"{user_id}:{rule.id}:{int(next_planned.timestamp())}"
        await upsert_schedule(user_id, rule.id, next_planned, dedup_key)

    async def _should_repeat(self, rule: NotificationRule, user_id: int) -> bool:
        keys = await get_user_keys(user_id)
        now = datetime.now()
        has_active_paid = any(not key.is_test and key.finish >= now for key in keys)
        has_any_active = any(key.finish >= now for key in keys)
        try:
            rtype = rule.type if isinstance(rule.type, NotificationType) else NotificationType(rule.type)
        except Exception:
            rtype = rule.type

        if rtype in (NotificationType.trial_expired, NotificationType.trial_expiring_soon):
            return not has_active_paid
        if rtype in (NotificationType.paid_expired, NotificationType.paid_expiring_soon):
            return not has_active_paid
        if rtype == NotificationType.new_user_no_keys:
            return not has_any_active
        return False

    async def _send_message(self, bot: Bot, user_id: int, rule: NotificationRule) -> str | None:
        template = rule.message_template or {}
        text = template.get("text")
        parse_mode = template.get("parse_mode", ParseMode.HTML)
        buttons = template.get("buttons") or []
        media_type = template.get("media_type")
        media_id = template.get("media_id")

        reply_markup = self._build_reply_markup(buttons) if buttons else None

        try:
            if media_type == "photo" and media_id:
                message = await bot.send_photo(user_id, photo=media_id, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
            elif media_type == "video" and media_id:
                message = await bot.send_video(user_id, video=media_id, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
            elif media_type == "document" and media_id:
                message = await bot.send_document(user_id, document=media_id, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
            else:
                message = await bot.send_message(user_id, text or "", parse_mode=parse_mode, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            # Log and re-raise so caller can mark schedule as error
            logger.error("TelegramBadRequest while sending to user %s rule=%s: %s", user_id, getattr(rule, "id", None), exc, exc_info=True)
            raise

        return str(message.message_id) if message else None

    def _build_reply_markup(self, buttons_schema: Iterable[Iterable[dict]]) -> InlineKeyboardMarkup:
        inline_rows = []
        for row in buttons_schema:
            inline_row = []
            for button in row:
                # button must be a dict with at least 'text'
                if not isinstance(button, dict):
                    logger.warning("Skipping invalid button (not a dict): %s", button)
                    continue
                text = button.get("text")
                if not text:
                    logger.warning("Skipping button without text: %s", button)
                    continue
                url = button.get("url")
                callback_data = button.get("callback_data")
                if url:
                    parsed = urlparse(url)
                    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                        logger.warning("Skipping button with invalid url: %s", url)
                        continue
                    inline_row.append(InlineKeyboardButton(text=text, url=url))
                elif callback_data:
                    # Telegram limits callback_data to 64 bytes
                    if len(callback_data) > 64:
                        logger.warning("Skipping button with too long callback_data: %s", callback_data)
                        continue
                    inline_row.append(InlineKeyboardButton(text=text, callback_data=callback_data))
                else:
                    # no actionable field
                    logger.warning("Skipping button without url or callback_data: %s", button)
                    continue
            if inline_row:
                inline_rows.append(inline_row)
        return InlineKeyboardMarkup(inline_keyboard=inline_rows)

    async def plan_event_notifications(
        self,
        user_id: int,
        event_type: NotificationType,
        base_datetime: datetime,
    ) -> None:
        base_utc = _ensure_utc(base_datetime)
        rules = await get_rules(event_type, active_only=True)
        entries = []
        for rule in rules:
            offset = _calc_offset(rule)
            planned_at = base_utc + offset
            dedup_key = f"{user_id}:{rule.id}:{int(planned_at.timestamp())}"
            entries.append((user_id, rule.id, planned_at, dedup_key))

        if entries:
            await bulk_upsert_schedule(entries)

    async def on_user_registered(self, user_id: int, registered_at: datetime) -> None:
        await self.plan_event_notifications(user_id, NotificationType.new_user_no_keys, registered_at)

    async def on_trial_key_created(self, user_id: int, _trial_finish: datetime) -> None:
        await cancel_user_schedules(
            user_id,
            [
                NotificationType.new_user_no_keys,
                NotificationType.trial_expired,
                NotificationType.trial_expiring_soon,
            ],
        )
        # Plan notifications based on the trial finish event (reminder and finish)
        await self.plan_event_notifications(user_id, NotificationType.trial_expiring_soon, _trial_finish)
        await self.plan_event_notifications(user_id, NotificationType.trial_expired, _trial_finish)

    async def on_paid_key_created(self, user_id: int, _finish_datetime: datetime) -> None:
        await cancel_user_schedules(
            user_id,
            [
                NotificationType.new_user_no_keys,
                NotificationType.trial_expired,
                NotificationType.trial_expiring_soon,
                NotificationType.paid_expired,
                NotificationType.paid_expiring_soon,
            ],
        )
        # Plan notifications for paid key: reminder and finish
        await self.plan_event_notifications(user_id, NotificationType.paid_expiring_soon, _finish_datetime)
        await self.plan_event_notifications(user_id, NotificationType.paid_expired, _finish_datetime)

    async def on_paid_key_prolonged(self, user_id: int, _finish_datetime: datetime) -> None:
        await cancel_user_schedules(
            user_id,
            [
                NotificationType.paid_expired,
                NotificationType.paid_expiring_soon,
            ],
        )


    async def preview_rule(self, bot: Bot, user_id: int, rule: NotificationRule) -> str | None:
        return await self._send_message(bot, user_id, rule)


notification_service = NotificationService()
