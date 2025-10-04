from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from src.database.crud import get_tariff, get_user
from src.database.crud.promo import get_promo_by_code
from src.database.models import TariffsOrm, PromoOrm
from src.keyboards.inline_user import get_select_device_buttons, \
    edit_inline_keyboard_select_tariff, get_buy_tariff_buttons, \
    edit_inline_keyboard_select_device, edit_inline_markup_add_symbol, get_payments_buttons
from src.keyboards.user_callback_datas import Tariffs
from src.services.keys_manager import create_key, prolong_key
from src.services.payments import create_payment, check_payment
from src.states.user_states import TariffState
from src.utils.utils_async import update_inline_reply_markup, delete_message_from_state
from src.logs import getLogger

router = Router(name=__name__)
logger = getLogger(__name__)


async def create_select_device_menu(callback: CallbackQuery, callback_data: Tariffs):
    await update_inline_reply_markup(callback, edit_inline_keyboard_select_tariff)
    return await callback.message.answer(
        text="Выберите тип вашего устройства, для которого будет использован ключ:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_select_device_buttons(Tariffs, tariff_id=callback_data.tariff_id, key_id=callback_data.key_id))


async def create_tariff_menu(callback: CallbackQuery, callback_data: Tariffs, tariff: TariffsOrm):
    return await callback.message.answer(
        text=f"🚀 <b>Тариф «{tariff.name}»</b>\n\n<b>Стоимость -</b> {tariff.price}₽\n<b>Продолжительность -</b> {tariff.days} дней\n{f'<b>Девайс -</b> {callback_data.device.capitalize()}' if callback_data.device else ''}\n\nЖелаете активировать этот тариф? ⬇️",
        parse_mode=ParseMode.HTML,
        reply_markup=get_buy_tariff_buttons(callback_data))


"""───────────────────────────────────────────── Callbacks Tariffs ─────────────────────────────────────────────"""


@router.callback_query(Tariffs.filter(F.action == "select_tariff"))
async def clb_get_access_select_tariff(callback: CallbackQuery, callback_data: Tariffs, state: FSMContext):
    """Реакция на выбор какого-то тарифа"""
    await callback.answer()
    current_state = await state.get_state()
    logger.debug(f"clb_get_access_select_tariff: state: {current_state} | data: {callback.data}")

    if current_state == TariffState.select_device:
        state_data = await state.get_data()
        state_data = await delete_message_from_state(callback, state_data, "msg_select_device_id")

        await state.update_data(state_data)

    elif current_state == TariffState.buy_tariff:
        state_data = await state.get_data()
        state_data = await delete_message_from_state(callback, state_data, "msg_buy_tariff_id")
        state_data = await delete_message_from_state(callback, state_data, "msg_select_device_id")

        await state.update_data(state_data)

    if callback_data.key_id:
        tariff = await get_tariff(callback_data.tariff_id)

        await update_inline_reply_markup(callback, edit_inline_keyboard_select_tariff)
        msg = await create_tariff_menu(callback, callback_data, tariff)

        await state.set_state(TariffState.buy_tariff)
        await state.update_data(msg_buy_tariff_id=msg.message_id, tariff_obj=tariff)

    else:
        msg = await create_select_device_menu(callback, callback_data)

        await state.set_state(TariffState.select_device)
        await state.update_data(msg_select_device_id=msg.message_id)


@router.callback_query(Tariffs.filter(F.action == "select_device"))
async def clb_get_access_select_device(callback: CallbackQuery, callback_data: Tariffs, state: FSMContext):
    """Реакция на выбор девайса"""
    await callback.answer()
    current_state = await state.get_state()
    logger.debug(f"clb_get_access_select_device: state: {current_state} | data: {callback.data}")

    if current_state == TariffState.buy_tariff:
        state_data = await state.get_data()
        state_data = await delete_message_from_state(callback, state_data, "msg_buy_tariff_id")
        await state.update_data(state_data)

    tariff = await get_tariff(callback_data.tariff_id)

    await update_inline_reply_markup(callback, edit_inline_keyboard_select_device)
    msg = await create_tariff_menu(callback, callback_data, tariff)

    await state.set_state(TariffState.buy_tariff)
    await state.update_data(msg_buy_tariff_id=msg.message_id, tariff_obj=tariff)


@router.callback_query(Tariffs.filter(F.action == "promo"), TariffState.buy_tariff)
async def clb_get_access_promo(callback: CallbackQuery, callback_data: Tariffs, state: FSMContext):
    await callback.answer()
    user = await get_user(callback.from_user)
    if user.used_promo:
        await callback.message.answer(
            text="Вы уже использовали промокод")
        return

    msg = await callback.message.answer(
        text="Введите промокод, чтобы получить скидку  ⬇️")
    await state.set_state(TariffState.promo_enter)
    await state.update_data(callback_data=callback_data)


@router.message(TariffState.promo_enter)
async def get_text_promo(message: Message, state: FSMContext):
    try:
        state_data = await state.get_data()
        tariff = state_data["tariff_obj"]
        text = message.text
        promo = await get_promo_by_code(text)
        if not promo or message.from_user.id in promo.users:
            await message.answer(
                "Промокод не найден, попробуйте еще раз")
            await state.set_state(TariffState.buy_tariff)
            return

        elif tariff.id not in list(promo.tariffs):
            await message.answer(
                "Этот промокод не действует на этот тариф, попробуйте еще раз")
            await state.set_state(TariffState.buy_tariff)
            return

        elif promo.users_limit != -1:
            if len(promo.users) >= promo.users_limit:
                await message.answer(
                    "Промокод был использован или его срок действия истек, попробуйте еще раз")
                await state.set_state(TariffState.buy_tariff)
                return

        elif promo.finish_time is not None:
            if datetime.now() > promo.finish_time:
                await message.answer(
                    "Промокод был использован или его срок действия истек, попробуйте еще раз")
                await state.set_state(TariffState.buy_tariff)
                return

        await state.set_state(TariffState.buy_tariff)
        await state.update_data(promo=promo)
        await message.answer("🎁 <b>Промокод был активирован, при покупке скидка будет учтена</b> ➡️ <b>[💳 Купить тариф]</b>", parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(Tariffs.filter(F.action == "buy_tariff"), TariffState.buy_tariff)
async def clb_get_access_buy_tariff(callback: CallbackQuery, callback_data: Tariffs, state: FSMContext):
    await callback.answer()

    state_data = await state.get_data()
    tariff = state_data.get("tariff_obj")
    promo: PromoOrm = state_data.get("promo")
    logger.debug(f"clb_get_access_buy_tariff: tariff: {tariff} | data: {callback.data}")
    price = tariff.price if not promo else int((tariff.price / 100) * (100 - promo.price))
    discount = "" if not promo else f" <b>({tariff.price}₽ - {promo.price}% скидка)</b>"
    key_id = callback_data.key_id
    pay_url, label = await create_payment(
        tariff=tariff,
        price=price,
        user_id=callback.from_user.id,
        device=callback_data.device,
        key_id=key_id,
        promo=promo.id if promo else None)

    await update_inline_reply_markup(callback, edit_inline_markup_add_symbol, 0)

    text = f"🚀 <b>Тариф «{tariff.name}»</b>\n\nК оплате: <b>{price}₽{discount}</b>\n\n✅ Чтобы перейти на сайт платежной системы, нажмите ниже на кнопку.\n\n📌<b> После оплаты активация произойдёт автоматически.</b>"
    await callback.message.answer(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_payments_buttons(callback_data, pay_url))

    await state.clear()


@router.callback_query(Tariffs.filter(F.action == "cancel_payment"))
async def clb_cancel_payment(callback: CallbackQuery, callback_data: Tariffs, state: FSMContext):
    await callback.answer()
    logger.debug(f"clb_cancel_payment: data: {callback.data}")
    await callback.message.delete()
    await callback.message.answer(
        text="<b>Платеж был успешно отменен.</b>\n\nЧтобы продолжить использовать бота, воспользуйтесь клавиатурой ⬇️",
        parse_mode=ParseMode.HTML)

    await state.clear()

