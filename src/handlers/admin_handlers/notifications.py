"""
Модуль для управления административными уведомлениями и их правилами.
Содержит хендлеры для создания, редактирования, удаления и предпросмотра правил рассылки.
"""

from __future__ import annotations

# NOTE: naive_now вынесен в отдельный модуль (см. utils/datetime_helpers.py)

from datetime import datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from urllib.parse import urlparse

from src.database.crud.notifications import (
    cancel_schedules_by_rule,
    create_rule,
    delete_rule,
    get_rule,
    get_rules,
    set_rule_active,
)
from src.database.models import NotificationRule, NotificationType
from src.keyboards.admin_callback_datas import (
    NotificationRuleCb,
    NotificationTypeCb,
    NotificationWeekdayCb,
)
from src.logs import getLogger
from src.services.notifications import notification_service
from src.states.admin_states import AdminMenu, AdminNotifications


router = Router(name=__name__)
logger = getLogger(__name__)


TYPE_LABELS: Dict[NotificationType, str] = {
    NotificationType.trial_expired:    "A) Закончился пробный ключ",
    NotificationType.paid_expired:     "B) Закончился платный ключ",
    NotificationType.new_user_no_keys: "C) Пользователь без ключей",
    NotificationType.global_weekly:    "D) Глобальная рассылка",
}

WEEKDAY_LABELS: Dict[int, str] = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}


async def open_notifications_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminMenu.notifications_menu)
    rules = await get_rules()
    text = build_rules_text(rules)
    keyboard = build_rules_keyboard(rules)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.message(Command("notify_rules"))
async def cmd_notify_rules(message: Message, state: FSMContext) -> None:
    await open_notifications_menu(message, state)


@router.callback_query(NotificationRuleCb.filter(F.action == "add"), AdminMenu.notifications_menu)
async def cb_add_rule(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminNotifications.create_type)
    # Show available notification types for selection instead of referencing
    # an undefined `notif_type` variable. The user should first pick a type.
    await callback.message.edit_text(
        "Выберите тип уведомления:",
        reply_markup=build_types_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(NotificationTypeCb.filter(F.action == "select"), AdminNotifications.create_type)
async def cb_select_type(callback: CallbackQuery, callback_data: NotificationTypeCb, state: FSMContext) -> None:
    await callback.answer()
    try:
        notif_type = NotificationType(callback_data.type_name)
    except Exception:
        await callback.answer("Неизвестный тип уведомления", show_alert=True)
        await callback.message.edit_text("Выберите тип уведомления:", reply_markup=build_types_keyboard())
        return
    await state.update_data(new_rule={"type": notif_type.value})
    await state.set_state(AdminNotifications.create_name)
    await callback.message.edit_text(
        f"Выбран тип: {TYPE_LABELS[notif_type]}\n\nВведите название правила:",
        parse_mode=ParseMode.HTML,
    )


@router.message(AdminNotifications.create_name)
async def process_rule_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    new_rule = data.get("new_rule", {})
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("Название должно содержать минимум 3 символа. Попробуйте снова.")
        return
    new_rule["name"] = name
    await state.update_data(new_rule=new_rule)
    notif_type = NotificationType(new_rule["type"])

    if notif_type == NotificationType.global_weekly:
        await state.set_state(AdminNotifications.create_weekday)
        await message.answer(
            "Выберите день недели:",
            reply_markup=build_weekday_keyboard(),
        )
    else:
        await state.set_state(AdminNotifications.create_offset)
        await message.answer(
            "Введите задержку отправки относительно события (например: 0, 12h, 2d, 1d6h):")


@router.callback_query(NotificationWeekdayCb.filter(F.action == "select"), AdminNotifications.create_weekday)
async def cb_select_weekday(callback: CallbackQuery, callback_data: NotificationWeekdayCb, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    new_rule = data.get("new_rule", {})
    new_rule["weekday"] = callback_data.weekday
    await state.update_data(new_rule=new_rule)
    await state.set_state(AdminNotifications.create_time)
    await callback.message.edit_text("Введите время отправки (формат ЧЧ:ММ):")


@router.callback_query(NotificationRuleCb.filter(F.action == "add_button"))
async def cb_add_button(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminNotifications.add_button_text)
    await callback.message.edit_text("Отправьте текст для кнопки:")


@router.message(AdminNotifications.add_button_text)
async def handle_add_button_text(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("Текст не может быть пустым. Попробуйте снова.")
        return
    await state.update_data(temp_button_text=text)
    await state.set_state(AdminNotifications.add_button_type)
    # ask for type
    await message.answer(
        "Выберите тип кнопки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="URL", callback_data=NotificationRuleCb(action="btn_type_url", rule_id=None).pack()),
                InlineKeyboardButton(text="Callback", callback_data=NotificationRuleCb(action="btn_type_callback", rule_id=None).pack()),
            ]
        ]),
    )


@router.callback_query(NotificationRuleCb.filter(F.action.in_(["btn_type_url", "btn_type_callback"])))
async def cb_button_type(callback: CallbackQuery, callback_data: NotificationRuleCb, state: FSMContext) -> None:
    await callback.answer()
    action = callback_data.action
    btn_type = "url" if action == "btn_type_url" else "callback"
    await state.update_data(temp_button_type=btn_type)
    await state.set_state(AdminNotifications.add_button_value)
    await callback.message.edit_text("Отправьте значение (URL или callback_data) для кнопки:")


@router.message(AdminNotifications.add_button_value)
async def handle_add_button_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get("temp_button_text")
    btn_type = data.get("temp_button_type")
    if not text or not btn_type:
        await message.answer("Не удалось собрать данные кнопки. Начните заново.")
        await state.set_state(AdminNotifications.collect_template)
        return
    value = message.text.strip()
    if not value:
        await message.answer("Значение не может быть пустым. Попробуйте снова.")
        return

    button = {"text": text}
    if btn_type == "url":
        # validate URL: must have http or https scheme and non-empty netloc
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            await message.answer("Неверный URL. Укажите полный URL, например: https://example.com")
            return
        button["url"] = value
    else:
        button["callback_data"] = value

    # append to new_rule.buttons
    new_data = await state.get_data()
    new_rule = new_data.get("new_rule", {})
    buttons = new_rule.get("buttons", [])
    # Each button as its own row
    buttons.append([button])
    new_rule["buttons"] = buttons
    await state.update_data(new_rule=new_rule)

    # clear temp fields
    await state.update_data(temp_button_text=None, temp_button_type=None)
    await state.set_state(AdminNotifications.collect_template)
    await message.answer("Кнопка добавлена. Отправьте шаблон сообщения или добавьте ещё кнопки.")


@router.message(AdminNotifications.create_time)
async def process_time(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await message.answer("Неверный формат времени. Используйте ЧЧ:ММ, например 18:30.")
        return

    # Safeguard: если вдруг parsed содержит tzinfo, делаем naive time
    if getattr(parsed, 'tzinfo', None) is not None:
        parsed = parsed.replace(tzinfo=None)

    data = await state.get_data()
    new_rule = data.get("new_rule", {})
    new_rule["time_of_day"] = parsed
    await state.update_data(new_rule=new_rule)
    await state.set_state(AdminNotifications.create_timezone)
    await message.answer(
        "Укажите таймзону (например Europe/Moscow). Отправьте '-' чтобы оставить UTC:")


@router.message(AdminNotifications.create_timezone)
async def process_timezone(message: Message, state: FSMContext) -> None:
    value = message.text.strip()
    tz_name = "UTC" if value == "-" or not value else value
    try:
        ZoneInfo(tz_name)
    except Exception:
        await message.answer("Не удалось распознать таймзону. Пример: Europe/Moscow. Попробуйте снова.")
        return

    # Safeguard: если вдруг tz_name содержит tzinfo (на практике это строка, но на будущее)
    if hasattr(tz_name, 'tzinfo') and getattr(tz_name, 'tzinfo', None) is not None:
        tz_name = tz_name.replace(tzinfo=None)

    data = await state.get_data()
    new_rule = data.get("new_rule", {})
    new_rule["timezone"] = tz_name
    await state.update_data(new_rule=new_rule)
    await state.set_state(AdminNotifications.collect_template)
    # Offer UI to add inline buttons or send a template message with buttons
    await message.answer(
        "Отправьте шаблон сообщения (текст или медиа). Можно добавить inline-кнопки.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить кнопку",
                    callback_data=NotificationRuleCb(action="add_button", rule_id=None).pack(),
                ),
                InlineKeyboardButton(
                    text="✅ Готово (отправьте шаблон)",
                    callback_data=NotificationRuleCb(action="template_done", rule_id=None).pack(),
                ),
            ]
        ]),
    )


@router.message(AdminNotifications.create_offset)
async def process_offset(message: Message, state: FSMContext) -> None:
    value = message.text.strip()
    if value in {"0", "-", ""}:
        delta = timedelta()
    else:
        try:
            delta = parse_interval(value)
        except ValueError as err:
            await message.answer(str(err))
            return

    data = await state.get_data()
    new_rule = data.get("new_rule", {})
    new_rule["offset"] = delta
    await state.update_data(new_rule=new_rule)
    await state.set_state(AdminNotifications.create_repeat)
    await message.answer(
        "Введите интервал повторения (0 - без повтора, например 24h или 3d):")


@router.message(AdminNotifications.create_repeat)
async def process_repeat(message: Message, state: FSMContext) -> None:
    value = message.text.strip()
    if value in {"0", "-", ""}:
        delta: Optional[timedelta] = None
    else:
        try:
            delta = parse_interval(value)
        except ValueError as err:
            await message.answer(str(err))
            return

    data = await state.get_data()
    new_rule = data.get("new_rule", {})
    new_rule["repeat"] = delta
    await state.update_data(new_rule=new_rule)
    await state.set_state(AdminNotifications.collect_template)
    await message.answer(
        "Отправьте шаблон сообщения (текст, фото, видео или документ). Чтобы добавить inline‑кнопки: нажмите «➕ Добавить кнопку», отправьте текст кнопки, выберите тип (URL/Callback) и укажите значение; повторите при необходимости или затем отправьте сам шаблон. Если вы отправите сообщение, уже содержащее кнопки — они будут использованы.")


@router.message(AdminNotifications.collect_template, F.text | F.photo | F.video | F.document)
async def process_template(message: Message, state: FSMContext) -> None:
    template = serialize_template_from_message(message)
    if not template:
        await message.answer("Не удалось распознать шаблон. Попробуйте снова.")
        return

    data = await state.get_data()
    new_rule = data.get("new_rule", {})
    # Guard: ensure we have required data collected in previous steps
    if "type" not in new_rule or "name" not in new_rule:
        await state.set_state(AdminMenu.notifications_menu)
        await message.answer("Не удалось собрать данные правила. Пожалуйста, начните заново.")
        await open_notifications_menu(message, state)
        return

    # Merge buttons built via constructor (if any) into the serialized template
    stored_buttons = new_rule.get("buttons")
    if stored_buttons:
        # if message already contains buttons, prefer explicit ones from the message; otherwise use stored
        if not template.get("buttons"):
            template["buttons"] = stored_buttons

    notif_type = NotificationType(new_rule["type"])

    rule_payload = {
        "name": new_rule["name"],
        "type": notif_type,
        "priority": 0,
        "message_template": template,
        "is_active": True,
    }

    if notif_type == NotificationType.global_weekly:
        # Safeguard: ensure time_of_day is naive
        time_of_day = new_rule["time_of_day"]
        if getattr(time_of_day, 'tzinfo', None) is not None:
            time_of_day = time_of_day.replace(tzinfo=None)
        tz_name = new_rule.get("timezone", "UTC")
        if hasattr(tz_name, 'tzinfo') and getattr(tz_name, 'tzinfo', None) is not None:
            tz_name = tz_name.replace(tzinfo=None)
        rule_payload.update(
            {
                "weekday": new_rule["weekday"],
                "time_of_day": time_of_day,
                "timezone": tz_name,
            }
        )
    else:
        offset_days, offset_hours = split_timedelta(new_rule.get("offset", timedelta()))
        rule_payload.update(
            {
                "offset_days": offset_days if offset_days else None,
                "offset_hours": offset_hours if offset_hours else None,
            }
        )
        repeat_delta: Optional[timedelta] = new_rule.get("repeat")
        if repeat_delta:
            repeat_days, repeat_hours = split_timedelta(repeat_delta)
            rule_payload.update(
                {
                    "repeat_every_days": repeat_days if repeat_days else None,
                    "repeat_every_hours": repeat_hours if repeat_hours else None,
                }
            )

    # created_at/updated_at можно добавить тут при необходимости, например:
    # rule_payload["created_at"] = naive_now()
    rule = await create_rule(**rule_payload)
    await state.set_state(AdminMenu.notifications_menu)
    await message.answer(f"Правило #{rule.id} создано.")

    if notif_type == NotificationType.global_weekly:
        await notification_service.refresh_global_jobs(message.bot)

    await open_notifications_menu(message, state)


@router.callback_query(NotificationRuleCb.filter(F.action == "show"), AdminMenu.notifications_menu)
async def cb_show_rule(callback: CallbackQuery, callback_data: NotificationRuleCb, state: FSMContext) -> None:
    rule = await get_rule(int(callback_data.rule_id))
    if not rule:
        await callback.answer("Правило не найдено", show_alert=True)
        return
    await callback.answer()
    await state.update_data(active_rule=rule.id)
    await callback.message.edit_text(
        format_rule(rule),
        reply_markup=build_rule_actions_keyboard(rule),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(NotificationRuleCb.filter(F.action == "back"))
async def cb_back_to_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    rules = await get_rules()
    await state.set_state(AdminMenu.notifications_menu)
    await callback.message.edit_text(
        build_rules_text(rules),
        reply_markup=build_rules_keyboard(rules),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(NotificationRuleCb.filter(F.action == "toggle"))
async def cb_toggle_rule(callback: CallbackQuery, callback_data: NotificationRuleCb) -> None:
    rule = await get_rule(int(callback_data.rule_id))
    if not rule:
        await callback.answer("Правило не найдено", show_alert=True)
        return
    await set_rule_active(rule.id, not rule.is_active)
    updated = await get_rule(rule.id)
    if not updated:
        await callback.answer("Правило не найдено", show_alert=True)
        return
    if not updated.is_active:
        await cancel_schedules_by_rule(updated.id)
    if updated.type == NotificationType.global_weekly:
        await notification_service.refresh_global_jobs(callback.bot)
    await callback.answer("Статус обновлён")
    await callback.message.edit_text(
        format_rule(updated),
        reply_markup=build_rule_actions_keyboard(updated),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(NotificationRuleCb.filter(F.action == "delete"))
async def cb_delete_rule(callback: CallbackQuery, callback_data: NotificationRuleCb) -> None:
    rule = await get_rule(int(callback_data.rule_id))
    if not rule:
        await callback.answer("Правило не найдено", show_alert=True)
        return
    await delete_rule(rule.id)
    if rule.type == NotificationType.global_weekly:
        await notification_service.refresh_global_jobs(callback.bot)
    await callback.answer("Правило удалено")
    rules = await get_rules()
    await callback.message.edit_text(
        build_rules_text(rules),
        reply_markup=build_rules_keyboard(rules),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(NotificationRuleCb.filter(F.action == "preview"))
async def cb_preview_rule(callback: CallbackQuery, callback_data: NotificationRuleCb) -> None:
    rule = await get_rule(int(callback_data.rule_id))
    if not rule:
        await callback.answer("Правило не найдено", show_alert=True)
        return
    await callback.answer("Отправляю пример")
    await notification_service.preview_rule(callback.bot, callback.from_user.id, rule)


@router.callback_query(NotificationRuleCb.filter(F.action == "template_done"))
async def cb_template_done(callback: CallbackQuery, callback_data: NotificationRuleCb, state: FSMContext) -> None:
    """Handler for the '✅ Готово (отправьте шаблон)' inline button.

    Many UIs present this button while the state is `collect_template`. Previously
    pressing it did nothing. This handler ensures we set the correct state and
    prompt the user to send the template (or add buttons).
    """
    await callback.answer()
    await state.set_state(AdminNotifications.collect_template)
    text = (
        "Отправьте шаблон сообщения (текст, фото, видео или документ). Чтобы добавить inline‑кнопки: нажмите «➕ Добавить кнопку», отправьте текст кнопки, выберите тип (URL/Callback) и укажите значение; повторите при необходимости или затем отправьте сам шаблон."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="➕ Добавить кнопку",
                callback_data=NotificationRuleCb(action="add_button", rule_id=None).pack(),
            ),
            InlineKeyboardButton(
                text="✅ Готово (отправьте шаблон)",
                callback_data=NotificationRuleCb(action="template_done", rule_id=None).pack(),
            ),
        ]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        # ignore harmless 'message is not modified' errors which happen when user
        # presses the button repeatedly or markup/text didn't change
        msg = str(e)
        if 'message is not modified' in msg.lower():
            logger.debug('Ignored TelegramBadRequest in cb_template_done: %s', msg)
        else:
            logger.error('TelegramBadRequest in cb_template_done: %s', msg, exc_info=True)
            raise



def build_rules_text(rules: Iterable[NotificationRule]) -> str:
    if not rules:
        return "Уведомления ещё не настроены. Нажмите 'Добавить правило', чтобы создать первое."

    grouped: Dict[NotificationType, List[NotificationRule]] = {t: [] for t in NotificationType}
    for rule in rules:
        grouped.setdefault(rule.type, []).append(rule)

    parts: List[str] = ["Текущие правила уведомлений:"]
    for notif_type, items in grouped.items():
        if not items:
            continue
        parts.append(f"\n<b>{TYPE_LABELS[notif_type]}</b>")
        for rule in sorted(items, key=lambda r: (not r.is_active, r.priority, r.id)):
            status = "✅" if rule.is_active else "🚫"
            parts.append(f"{status} #{rule.id} — {rule.name}")
    return "\n".join(parts)


def build_rules_keyboard(rules: Iterable[NotificationRule]) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    for rule in sorted(rules, key=lambda r: (r.type.value, r.priority, r.id)):
        status = "✅" if rule.is_active else "🚫"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status} #{rule.id} {rule.name}",
                callback_data=NotificationRuleCb(action="show", rule_id=rule.id).pack(),
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text="➕ Добавить правило",
            callback_data=NotificationRuleCb(action="add", rule_id=None).pack(),
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_rule_actions_keyboard(rule: NotificationRule) -> InlineKeyboardMarkup:
    status_text = "Отключить" if rule.is_active else "Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=status_text,
                    callback_data=NotificationRuleCb(action="toggle", rule_id=rule.id).pack(),
                ),
                InlineKeyboardButton(
                    text="Предпросмотр",
                    callback_data=NotificationRuleCb(action="preview", rule_id=rule.id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=NotificationRuleCb(action="delete", rule_id=rule.id).pack(),
                ),
                InlineKeyboardButton(
                    text="⬅ Назад",
                    callback_data=NotificationRuleCb(action="back", rule_id=None).pack(),
                ),
            ],
        ]
    )


def build_types_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for notif_type in NotificationType:
        rows.append([
            InlineKeyboardButton(
                text=TYPE_LABELS[notif_type],
                callback_data=NotificationTypeCb(action="select", type_name=notif_type.value).pack(),
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_weekday_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for weekday, title in WEEKDAY_LABELS.items():
        rows.append([
            InlineKeyboardButton(
                text=title,
                callback_data=NotificationWeekdayCb(action="select", weekday=weekday).pack(),
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_rule(rule: NotificationRule) -> str:
    parts = [
        f"<b>{TYPE_LABELS[rule.type]}</b>",
        f"Название: {rule.name}",
        f"Статус: {'Активно' if rule.is_active else 'Отключено'}",
    ]
    if rule.type == NotificationType.global_weekly:
        weekday = WEEKDAY_LABELS.get(rule.weekday or 0, str(rule.weekday))
        parts.append(f"Расписание: {weekday} {rule.time_of_day.strftime('%H:%M')} ({rule.timezone})")
    else:
        offset = format_timedelta(rule.offset_days, rule.offset_hours)
        parts.append(f"Отправка через: {offset}")
        repeat = format_timedelta(rule.repeat_every_days, rule.repeat_every_hours)
        if repeat != "0ч":
            parts.append(f"Повтор: каждые {repeat}")
    return "\n".join(parts)


def format_timedelta(days: Optional[int], hours: Optional[int]) -> str:
    total_days = days or 0
    total_hours = hours or 0
    parts = []
    if total_days:
        parts.append(f"{total_days}д")
    if total_hours:
        parts.append(f"{total_hours}ч")
    if not parts:
        parts.append("0ч")
    return " ".join(parts)


def parse_interval(value: str) -> timedelta:
    value = value.lower().replace(" ", "")
    if not value:
        raise ValueError("Введите значение, например 12h или 2d.")
    total = timedelta()
    number = ''
    for char in value:
        if char.isdigit():
            number += char
            continue
        if char not in {'h', 'd'} or not number:
            raise ValueError("Формат поддерживает только числа с суффиксом h или d. Пример: 24h, 2d.")
        amount = int(number)
        if char == 'h':
            total += timedelta(hours=amount)
        elif char == 'd':
            total += timedelta(days=amount)
        number = ''
    if number:
        total += timedelta(hours=int(number))
    if total == timedelta():
        raise ValueError("Значение не может быть нулевым. Используйте 0 для отключения.")
    return total


def split_timedelta(delta: timedelta) -> tuple[int, int]:
    days = delta.days
    hours = delta.seconds // 3600
    return days, hours


def serialize_template_from_message(message: Message) -> Dict:
    buttons = []
    if message.reply_markup and getattr(message.reply_markup, "inline_keyboard", None):
        from urllib.parse import urlparse

        for row in message.reply_markup.inline_keyboard:
            serialized_row = []
            for button in row:
                text_val = getattr(button, "text", None)
                if not text_val:
                    # skip buttons without text
                    continue
                btn_obj = {"text": text_val}
                url_val = getattr(button, "url", None)
                cb_val = getattr(button, "callback_data", None)
                if url_val:
                    parsed = urlparse(url_val)
                    if parsed.scheme in {"http", "https"} and parsed.netloc:
                        btn_obj["url"] = url_val
                    else:
                        # skip invalid url buttons
                        continue
                elif cb_val:
                    btn_obj["callback_data"] = cb_val
                serialized_row.append(btn_obj)
            if serialized_row:
                buttons.append(serialized_row)

    base = {
        "buttons": buttons,
    }

    if message.photo:
        base.update(
            {
                "media_type": "photo",
                "media_id": message.photo[-1].file_id,
                "text": message.caption_html or message.caption or "",
                "parse_mode": "HTML",
            }
        )
    elif message.video:
        base.update(
            {
                "media_type": "video",
                "media_id": message.video.file_id,
                "text": message.caption_html or message.caption or "",
                "parse_mode": "HTML",
            }
        )
    elif message.document:
        base.update(
            {
                "media_type": "document",
                "media_id": message.document.file_id,
                "text": message.caption_html or message.caption or "",
                "parse_mode": "HTML",
            }
        )
    elif message.text:
        base.update(
            {
                "media_type": "text",
                "text": message.html_text or message.text,
                "parse_mode": "HTML",
            }
        )
    else:
        return {}

    return base


__all__ = ["router", "open_notifications_menu"]
