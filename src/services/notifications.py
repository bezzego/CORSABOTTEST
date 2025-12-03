"""
Сервис управления уведомлениями для пользователей бота.

ОСНОВНЫЕ ПРИНЦИПЫ РАБОТЫ:

1. ТИПЫ УВЕДОМЛЕНИЙ:
   A) trial_expiring_soon - напоминание о скором окончании пробного ключа
   B) trial_expired - уведомление об окончании пробного ключа
   C) paid_expiring_soon - напоминание о скором окончании платного ключа
   D) paid_expired - уведомление об окончании платного ключа
   E) new_user_no_keys - уведомление для пользователей без ключей
   F) global_weekly - глобальная еженедельная рассылка

2. ВРЕМЕННЫЕ ЗОНЫ:
   - Все расчеты времени выполняются в московском времени (Europe/Moscow)
   - В БД значения хранятся как TIMESTAMPTZ (автоматически конвертируются в UTC)
   - При сравнении в БД используется UTC для корректной работы

3. ЛОГИКА ОТПРАВКИ:
   - Напоминания (expiring_soon): отправляются ДО события (finish - offset)
   - Уведомления об окончании (expired): отправляются ПОСЛЕ события (finish + offset)
   - Глобальные рассылки: по расписанию (день недели + время)

4. ПОВТОР УВЕДОМЛЕНИЙ:
   - Уведомления могут повторяться с указанным интервалом
   - Повтор работает только если пользователь все еще подходит под условия правила
   - Например, напоминания о пробном ключе повторяются только если нет платного ключа

5. АВТОМАТИЧЕСКОЕ ПЛАНИРОВАНИЕ:
   - При создании/обновлении ключа автоматически создаются расписания для правил A-D
   - При создании/обновлении правила автоматически создаются расписания для всех подходящих пользователей
   - При деактивации правила отменяются все запланированные уведомления

6. ОТПРАВКА УВЕДОМЛЕНИЙ:
   - Проверка готовых к отправке уведомлений выполняется каждые 60 секунд
   - Обработка выполняется батчами по 50 штук для эффективности
   - После отправки планируется повтор, если правило имеет интервал повтора
"""

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


# Все даты работают по московскому времени (Europe/Moscow) для расчетов,
# но в БД хранятся как TIMESTAMPTZ (автоматически конвертируются в UTC)
from zoneinfo import ZoneInfo

msk = ZoneInfo("Europe/Moscow")

def _ensure_msk(dt: datetime) -> datetime:
    """
    Преобразует datetime в московское время (Europe/Moscow).
    
    Используется для всех расчетов времени отправки уведомлений.
    В БД значения хранятся как TIMESTAMPTZ и автоматически конвертируются.
    """
    if dt.tzinfo is None:
        # Если tzinfo отсутствует — считаем, что это московское локальное время
        return dt.replace(tzinfo=msk)
    # Если уже указана таймзона, переводим в московскую
    return dt.astimezone(msk)


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
        """
        Инициализирует сервис уведомлений.
        
        Настраивает:
        - Периодическую проверку готовых к отправке уведомлений (каждые 60 секунд)
        - Расписание для глобальных еженедельных рассылок
        """
        self.scheduler = scheduler
        scheduler.add_job(
            self.dispatch_due_notifications,
            "interval",
            seconds=60,
            args=[bot],
            id=self.dispatcher_job_id,
            replace_existing=True,
            # max_instances=1 гарантирует, что только один экземпляр задачи выполняется одновременно
            max_instances=1,
            # misfire_grace_time позволяет выполнить пропущенные задачи, если они не старше 2 минут
            misfire_grace_time=120,
        )
        logger.info("NotificationService initialized: dispatcher job added (id=%s)", self.dispatcher_job_id)
        logger.info("Dispatcher job started and will run every 60s")
        
        # Сразу отправляем готовые уведомления при старте
        try:
            await self.dispatch_due_notifications(bot)
        except Exception:
            logger.exception("Failed to dispatch notifications on startup")
        
        await self.refresh_global_jobs(bot)

    async def refresh_global_jobs(self, bot: Bot) -> None:
        """
        Обновляет расписание для глобальных еженедельных рассылок.
        
        Удаляет старые задачи и создает новые на основе активных правил.
        По умолчанию используется таймзона Europe/Moscow.
        """
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
                logger.warning(
                    "Skipping global rule_id=%s: missing weekday or time_of_day",
                    rule.id
                )
                continue
            # По умолчанию используем московское время
            tz_name = rule.timezone or "Europe/Moscow"
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
        """
        Ставит в очередь глобальную еженедельную рассылку для всех пользователей.
        
        Использует таймзону из правила (по умолчанию Europe/Moscow).
        """
        rule = await get_rule(rule_id)
        if not rule or not rule.is_active:
            return
        # normalize rule.type to enum if DB returned a raw string
        try:
            rtype = rule.type if isinstance(rule.type, NotificationType) else NotificationType(rule.type)
            rule.type = rtype
        except Exception:
            pass

        # Используем таймзону из правила (по умолчанию Europe/Moscow)
        tz_name = rule.timezone or "Europe/Moscow"
        rule_tz = ZoneInfo(tz_name)
        now = datetime.now(rule_tz)
        # Сохраняем как aware datetime - PostgreSQL конвертирует в UTC при сохранении
        planned_at = now

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
                    "Enqueued global rule=%s for %d users at planned_at=%s (tz=%s)",
                    rule.id,
                    len(entries),
                    planned_at,
                    tz_name,
                )
                logger.info("Starting dispatch of due notifications after enqueue")
                await self.dispatch_due_notifications(bot)
            else:
                logger.info(
                    "Enqueue global rule=%s: no users found (user_count=%s) planned_at=%s (tz=%s)",
                    rule.id,
                    user_count,
                    planned_at,
                    tz_name,
                )

        except Exception as exc:  # pragma: no cover - log DB/network errors
            logger.error("Failed to enqueue global rule=%s: %s", rule.id, exc, exc_info=True)
            return

    async def dispatch_due_notifications(self, bot: Bot) -> None:
        """
        Отправляет все готовые к отправке уведомления.
        
        Обрабатывает расписания батчами по 50 штук до тех пор, пока не останется
        готовых к отправке. Это гарантирует, что все уведомления будут отправлены
        даже если их много.
        
        Вызывается:
        - каждые 60 секунд через планировщик (dispatcher_job)
        - после постановки в очередь глобальных рассылок
        - при старте сервиса
        
        Обработка выполняется в цикле для гарантии отправки всех готовых уведомлений,
        даже если их создалось много за один раз.
        """
        total_processed = 0
        batch_count = 0
        max_batches = 100  # Защита от бесконечного цикла (максимум 5000 уведомлений за раз)
        
        try:
            while batch_count < max_batches:
                schedules = await fetch_due_schedules(limit=50)
                if not schedules:
                    break
                batch_count += 1
                logger.debug("Dispatching batch #%d: %d due schedules", batch_count, len(schedules))
                await self._process_batch(bot, schedules)
                total_processed += len(schedules)
            
            if total_processed:
                logger.info(
                    "Dispatch complete: processed %d schedules in %d batches",
                    total_processed,
                    batch_count,
                )
            elif batch_count == max_batches:
                logger.warning(
                    "Dispatch stopped at max_batches limit (%d). "
                    "There may be more schedules to process.",
                    max_batches,
                )
        except Exception:
            logger.exception("Error in dispatch_due_notifications")
            raise

    async def _process_batch(self, bot: Bot, schedules: Sequence) -> None:
        """
        Обрабатывает батч расписаний: отправляет уведомления и планирует повторы.
        
        Для каждого расписания:
        1. Проверяет, что правило активно
        2. Отправляет сообщение пользователю
        3. Помечает расписание как отправленное
        4. Если правило имеет интервал повтора и пользователь все еще подходит -
           планирует следующее уведомление
        """
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

                # Планируем повтор, если правило имеет интервал повтора
                # и пользователь все еще подходит под условия правила
                repeat_interval = _calc_interval(rule)
                if repeat_interval and await self._should_repeat(rule, schedule.user_id):
                    await self._schedule_next_repeat(schedule.user_id, rule, schedule.planned_at)

            except Exception as exc:  # pragma: no cover
                logger.error(
                    "Failed to send notification rule=%s user=%s: %s",
                    rule.id,
                    schedule.user_id,
                    exc,
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

        # Преобразуем previous_planned_at в MSK для расчетов, затем сохраняем как aware datetime
        # PostgreSQL автоматически конвертирует TIMESTAMPTZ в UTC при сохранении
        next_planned_msk = _ensure_msk(previous_planned_at) + interval
        # Сохраняем как aware datetime (PostgreSQL конвертирует в UTC)
        next_planned = next_planned_msk
        try:
            rtype = rule.type if isinstance(rule.type, NotificationType) else NotificationType(rule.type)
        except Exception:
            rtype = None
        dedup_key = f"{user_id}:{rule.id}:{int(next_planned.timestamp())}"
        await upsert_schedule(user_id, rule.id, next_planned, dedup_key)

    async def _should_repeat(self, rule: NotificationRule, user_id: int) -> bool:
        """
        Определяет, нужно ли повторять уведомление для пользователя.
        
        Логика повтора:
        - Для уведомлений о пробных ключах: повторяем только если нет платного ключа
        - Для уведомлений о платных ключах: повторяем только если нет активного платного ключа
        - Для уведомлений пользователям без ключей: повторяем только если нет активных ключей
        
        Returns:
            True если уведомление должно повторяться, False иначе
        """
        keys = await get_user_keys(user_id)
        now = datetime.now(msk)  # Используем московское время для сравнения
        has_active_paid = any(not key.is_test and key.finish >= now for key in keys)
        has_any_active = any(key.finish >= now for key in keys)
        
        try:
            rtype = rule.type if isinstance(rule.type, NotificationType) else NotificationType(rule.type)
        except Exception:
            rtype = rule.type

        # Для уведомлений о пробных ключах: повторяем только если нет платного ключа
        if rtype in (NotificationType.trial_expired, NotificationType.trial_expiring_soon):
            return not has_active_paid
        
        # Для уведомлений о платных ключах: повторяем только если нет активного платного ключа
        if rtype in (NotificationType.paid_expired, NotificationType.paid_expiring_soon):
            return not has_active_paid
        
        # Для уведомлений пользователям без ключей: повторяем только если нет активных ключей
        if rtype == NotificationType.new_user_no_keys:
            return not has_any_active
        
        return False

    async def _send_message(self, bot: Bot, user_id: int, rule: NotificationRule) -> str | None:
        """
        Отправляет сообщение пользователю согласно шаблону правила.
        
        Поддерживает:
        - Текстовые сообщения
        - Фото с подписью
        - Видео с подписью
        - Документы с подписью
        - Inline-кнопки (URL или callback_data)
        
        Returns:
            message_id отправленного сообщения или None
        """
        template = rule.message_template or {}
        text = template.get("text")
        parse_mode = template.get("parse_mode", ParseMode.HTML)
        buttons = template.get("buttons") or []
        media_type = template.get("media_type")
        media_id = template.get("media_id")

        reply_markup = self._build_reply_markup(buttons) if buttons else None

        try:
            if media_type == "photo" and media_id:
                message = await bot.send_photo(
                    user_id,
                    photo=media_id,
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            elif media_type == "video" and media_id:
                message = await bot.send_video(
                    user_id,
                    video=media_id,
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            elif media_type == "document" and media_id:
                message = await bot.send_document(
                    user_id,
                    document=media_id,
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            else:
                # Текстовое сообщение
                if not text:
                    logger.warning(
                        "Empty text in rule_id=%s template, sending empty message",
                        getattr(rule, "id", None),
                    )
                message = await bot.send_message(
                    user_id,
                    text or "",
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
        except TelegramBadRequest as exc:
            # Пользователь заблокировал бота, удалил аккаунт и т.д.
            # Логируем и пробрасываем исключение, чтобы пометить расписание как ошибку
            logger.error(
                "TelegramBadRequest while sending to user %s rule=%s: %s",
                user_id,
                getattr(rule, "id", None),
                exc,
                exc_info=True,
            )
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
        """
        Планирует уведомления для события пользователя.
        
        Для напоминаний (expiring_soon): отправка ДО события (base_datetime - offset)
        Для уведомлений об окончании (expired): отправка ПОСЛЕ события (base_datetime + offset)
        
        Все расчеты выполняются в московском времени, в БД сохраняются как TIMESTAMPTZ.
        """
        # Преобразуем в московское время для расчетов
        base_msk = _ensure_msk(base_datetime)
        rules = await get_rules(event_type, active_only=True)
        entries = []
        for rule in rules:
            offset = _calc_offset(rule)
            if rule.type in (
                NotificationType.trial_expiring_soon,
                NotificationType.paid_expiring_soon,
            ):
                # Напоминания: отправляем ДО события
                planned_at = base_msk - offset
            else:
                # Уведомления об окончании: отправляем ПОСЛЕ события (или в момент, если offset=0)
                planned_at = base_msk + offset
            
            # Если запланированное время в прошлом, отправляем сейчас
            now_msk = datetime.now(msk)
            if planned_at < now_msk:
                planned_at = now_msk
            
            dedup_key = f"{user_id}:{rule.id}:{int(planned_at.timestamp())}"
            entries.append((user_id, rule.id, planned_at, dedup_key))

        if entries:
            await bulk_upsert_schedule(entries)

    async def on_user_registered(self, user_id: int, registered_at: datetime) -> None:
        await self.plan_event_notifications(user_id, NotificationType.new_user_no_keys, registered_at)

    async def on_trial_key_created(self, user_id: int, _trial_finish: datetime) -> None:
        """
        Обработчик создания пробного ключа.
        
        Отменяет уведомления для пользователей без ключей, так как теперь у пользователя есть ключ.
        Уведомления для пробного ключа (trial_expiring_soon, trial_expired) создаются
        автоматически через sync_user_key_rules при создании ключа в add_new_key.
        """
        await cancel_user_schedules(
            user_id,
            [
                NotificationType.new_user_no_keys,
            ],
        )

    async def on_paid_key_created(self, user_id: int, _finish_datetime: datetime) -> None:
        """
        Обработчик создания платного ключа.
        
        Отменяет уведомления для:
        - пользователей без ключей (теперь есть ключ)
        - пробных ключей (заменены платным)
        
        Уведомления для платного ключа (paid_expiring_soon, paid_expired) создаются
        автоматически через sync_user_key_rules при создании ключа в add_new_key.
        """
        await cancel_user_schedules(
            user_id,
            [
                NotificationType.new_user_no_keys,
                NotificationType.trial_expired,
                NotificationType.trial_expiring_soon,
            ],
        )

    async def on_paid_key_prolonged(self, user_id: int, _finish_datetime: datetime) -> None:
        """
        Обработчик продления платного ключа.
        
        Отменяет старые расписания для платного ключа, чтобы избежать дубликатов.
        Новые расписания будут пересозданы через sync_user_key_rules при обновлении ключа
        в update_key (который вызывается из prolong_key).
        """
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
