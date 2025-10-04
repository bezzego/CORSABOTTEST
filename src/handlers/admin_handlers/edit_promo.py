from datetime import datetime

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from src.database.crud import get_tariff, get_tariffs
from src.database.crud.promo import get_promos, get_promo_by_id, delete_promo, change_promo_value, change_promo_tariffs, \
    add_promo
from src.keyboards.admin_callback_datas import EditPromo, AddTariffsToPromo
from src.keyboards.inline_admin import get_edit_promos_buttons, get_edit_promos_buttons, get_edit_promo_buttons, \
    get_confirm_buttons, edit_inline_keyboard_select_tariff, get_admin_tariff_buttons
from src.keyboards.reply_admin import get_reply_admin_btn
from src.logs import getLogger
from src.states.admin_states import AdminMenu, AdminPromo
from src.utils.utils_async import auth_admin_role, update_inline_reply_markup

router = Router(name=__name__)
logger = getLogger(__name__)

"""───────────────────────────────────────────── Func ─────────────────────────────────────────────"""


async def show_promos(message: Message):
    promos = await get_promos()

    if not promos:
        await message.answer(
            text="⚠️ Нету промокодов в бд.")
        return

    await message.answer(
        text="Список промокодов:",
        reply_markup=get_edit_promos_buttons(promos))


async def show_promo(promo_id: int, callback: CallbackQuery, reply_markup=None):
    promo = await get_promo_by_id(int(promo_id))
    tariffs = [await get_tariff(i) for i in promo.tariffs]
    tariffs = [tariff.name for tariff in tariffs if tariff]
    if promo:
        await callback.answer()
        return await callback.message.answer(
            text=f"""
ID: <code>{promo.id}</code>
Код: <code>{promo.code}</code>
Скидка: <code>{promo.price}%</code>
Макс пользователей: <code>{promo.users_limit if promo.users_limit != -1 else "-"}</code>
Использований: <code>{len(promo.users)}</code>
Конец действия: <code>{promo.finish_time if promo.finish_time is not None else "-"}</code>
Тарифы: <code>{','.join(tariffs)}</code>

""",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup)

"""───────────────────────────────────────────── Commands and Reply ─────────────────────────────────────────────"""


@router.message(F.text == get_reply_admin_btn("adm_edit"), StateFilter(AdminMenu.promo_menu, AdminPromo.edit))
@auth_admin_role
async def cmd_edit_promo(message: Message, state: FSMContext):
    await show_promos(message)
    await state.set_state(AdminPromo.edit)


@router.message(F.text == get_reply_admin_btn("adm_add"), StateFilter(AdminMenu.promo_menu, AdminPromo.edit))
@auth_admin_role
async def cmd_add_new_promo(message: Message, state: FSMContext):
    await message.answer(
        text="<b>Создание нового промокода:</b>\n\nВведите код для промокода  ⬇️",
        parse_mode=ParseMode.HTML)
    await state.set_state(AdminPromo.add_code)

"""───────────────────────────────────────────── Callbacks Edit Promo ─────────────────────────────────────────────"""


@router.callback_query(EditPromo.filter(F.action == "pagination"), AdminPromo.edit)
async def clb_paginate_promo(callback: CallbackQuery, callback_data: EditPromo):
    promos = await get_promos()
    new_markup = get_edit_promos_buttons(promos, callback_data.page)

    await callback.message.edit_reply_markup(reply_markup=new_markup)
    await callback.answer()


@router.callback_query(EditPromo.filter(F.action == "show_promo"), AdminPromo.edit)
async def clb_show_promo(callback: CallbackQuery, callback_data: EditPromo):
    await show_promo(callback_data.promo_id, callback)


@router.callback_query(EditPromo.filter(F.action == "edit_promo"), AdminPromo.edit)
async def clb_edit_promo(callback: CallbackQuery, callback_data: EditPromo):
    msg = await show_promo(callback_data.promo_id, callback, get_edit_promo_buttons(callback_data.promo_id, callback_data.page))
    if not msg:
        return


@router.callback_query(EditPromo.filter(F.action == "delete_promo"), AdminPromo.edit)
async def clb_delete_promo(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    await callback.answer()
    promo = await get_promo_by_id(callback_data.promo_id)
    await callback.message.answer(
        text=f"Вы уверены что хотите удалить промокод: <b>{promo.code}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_confirm_buttons(EditPromo, promo_id=callback_data.promo_id, page=callback_data.page))

    await state.set_state(AdminPromo.delete_confirm)


@router.callback_query(EditPromo.filter(F.action == "back"))
async def clb_cancel(callback: CallbackQuery, callback_data: EditPromo):
    await callback.message.delete()


@router.callback_query(EditPromo.filter(F.action == "cancel_change"), StateFilter(
    AdminPromo.change_code_confirm))
async def clb_change_cancel(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Успешно, отмена изменений!")
    await state.clear()
    await state.set_state(AdminMenu.promo_menu)


"""───────────────────────────────────────────── Callbacks Delete Promo ─────────────────────────────────────────────"""


@router.callback_query(EditPromo.filter(F.action == "confirm_change"), AdminPromo.delete_confirm)
async def clb_delete_promo_confirm(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    await delete_promo(int(callback_data.promo_id))
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, промокод был удален.",
        parse_mode=ParseMode.HTML)

    await show_promos(callback.message)
    await state.set_state(AdminPromo.edit)

"""───────────────────────────────────────────── Callbacks Edit code ─────────────────────────────────────────────"""


@router.callback_query(EditPromo.filter(F.action == "change_code"))
async def clb_change_code(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новое код для промокода ⬇️")
    await state.set_state(AdminPromo.change_code)
    await state.update_data(callback_data=callback_data)


@router.message(AdminPromo.change_code)
async def get_text_change_code(message: Message, state: FSMContext):
    try:
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить код на: <code>{message.text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditPromo, promo_id=callback_data.promo_id, page=callback_data.page))

        await state.set_state(AdminPromo.change_code_confirm)
        await state.update_data(new_code=message.text)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditPromo.filter(F.action == "confirm_change"), AdminPromo.change_code_confirm)
async def clb_change_code_confirm(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    state_data = await state.get_data()
    await change_promo_value(int(callback_data.promo_id), code=state_data["new_code"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение кода!\n\nНовый код - <code>{state_data['new_code']}</code>",
        parse_mode=ParseMode.HTML)

    await show_promos(callback.message)
    await state.set_state(AdminPromo.edit)

"""───────────────────────────────────────────── Callbacks Edit Price ─────────────────────────────────────────────"""


@router.callback_query(EditPromo.filter(F.action == "change_price"))
async def clb_change_price(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новый процент скидки для промокода ⬇️")
    await state.set_state(AdminPromo.change_price)
    await state.update_data(callback_data=callback_data)


@router.message(AdminPromo.change_price)
async def get_text_change_price(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить процент скидки на: <code>{message.text}</code>%",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditPromo, promo_id=callback_data.promo_id, page=callback_data.page))

        await state.set_state(AdminPromo.change_price_confirm)
        await state.update_data(new_price=message.text)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditPromo.filter(F.action == "confirm_change"), AdminPromo.change_price_confirm)
async def clb_change_price_confirm(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    state_data = await state.get_data()
    await change_promo_value(int(callback_data.promo_id), price=int(state_data["new_price"]))
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение процента!\n\nНовый процент - <code>{state_data['new_price']}</code>%",
        parse_mode=ParseMode.HTML)

    await show_promos(callback.message)
    await state.set_state(AdminPromo.edit)

"""───────────────────────────────────────────── Callbacks Edit Max Users ─────────────────────────────────────────────"""


@router.callback_query(EditPromo.filter(F.action == "change_max_users"))
async def clb_change_max_users(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новые количество максимальных пользователей для промокода (без ограничения = -1) ⬇️")
    await state.set_state(AdminPromo.change_max_users)
    await state.update_data(callback_data=callback_data)


@router.message(AdminPromo.change_max_users)
async def get_text_change_max_users(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit() and message.text != "-1":
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить количество максимальных пользователей на: <code>{message.text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditPromo, promo_id=callback_data.promo_id, page=callback_data.page))

        await state.set_state(AdminPromo.change_max_users_confirm)
        await state.update_data(new_max_users=message.text)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditPromo.filter(F.action == "confirm_change"), AdminPromo.change_max_users_confirm)
async def clb_change_max_users_confirm(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    state_data = await state.get_data()
    await change_promo_value(int(callback_data.promo_id), users_limit=int(state_data["new_max_users"]))
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение количество максимальных пользователей!\n\nНовый значение - <code>{state_data['new_max_users']}</code>",
        parse_mode=ParseMode.HTML)

    await show_promos(callback.message)
    await state.set_state(AdminPromo.edit)

"""───────────────────────────────────────────── Callbacks Edit Finish Date ─────────────────────────────────────────────"""


@router.callback_query(EditPromo.filter(F.action == "change_finish_date"))
async def clb_change_finish_date(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новую дату окончания действия промокода формат: ДД.ММ.ГГГГ (без ограничения = -1) ⬇️")
    await state.set_state(AdminPromo.change_finish_date)
    await state.update_data(callback_data=callback_data)


@router.message(AdminPromo.change_finish_date)
async def get_text_change_finish_date(message: Message, state: FSMContext):
    try:
        if message.text == "-1":
            finish_date = None
        else:
            try:
                finish_date = datetime.strptime(message.text, '%d.%m.%Y')
            except Exception as e:
                await message.answer("Вы ввели дату не в неправильном формате\nПопробуйте еще раз, формат: ДД.ММ.ГГГГ")
                return

        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить дату окончания действия промокода на: <code>{message.text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditPromo, promo_id=callback_data.promo_id, page=callback_data.page))

        await state.set_state(AdminPromo.change_finish_date_confirm)
        await state.update_data(new_finish_time=finish_date)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditPromo.filter(F.action == "confirm_change"), AdminPromo.change_finish_date_confirm)
async def clb_change_finish_date_confirm(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    state_data = await state.get_data()
    await change_promo_value(int(callback_data.promo_id), finish_time=state_data["new_finish_time"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение даты окончания действия промокода!\n\nНовый значение - <code>{state_data['new_finish_time']}</code>",
        parse_mode=ParseMode.HTML)

    await show_promos(callback.message)
    await state.set_state(AdminPromo.edit)


"""───────────────────────────────────────────── Callbacks Edit Tariffs ─────────────────────────────────────────────"""


@router.callback_query(EditPromo.filter(F.action == "change_tariffs"))
async def clb_change_tariffs(callback: CallbackQuery, callback_data: EditPromo, state: FSMContext):
    await callback.answer()
    tariffs = await get_tariffs()
    await callback.message.answer(
        text="Выберите новый список тарифов для этого промокода ⬇️",
        reply_markup=get_admin_tariff_buttons(tariffs))
    await state.set_state(AdminPromo.change_tariffs)
    await state.update_data(callback_data=callback_data, selected_tariffs=[])


@router.callback_query(AddTariffsToPromo.filter(F.action == "select"), StateFilter(AdminPromo.change_tariffs, AdminPromo.add_tariffs))
async def clb_select_tariff(callback: CallbackQuery, callback_data: AddTariffsToPromo, state: FSMContext):
    await callback.answer()
    keyboard = edit_inline_keyboard_select_tariff(callback.message.reply_markup.inline_keyboard, callback.data)
    if keyboard:
        await callback.message.edit_reply_markup(reply_markup=keyboard)

    state_data = await state.get_data()
    selected_tariffs = state_data["selected_tariffs"]
    if callback_data.tariff_id not in selected_tariffs:
        selected_tariffs.append(callback_data.tariff_id)
    await state.update_data(selected_tariffs=selected_tariffs)


@router.callback_query(AddTariffsToPromo.filter(F.action == "confirm_change"), AdminPromo.change_tariffs)
async def clb_change_promo_tariffs_confirm(callback: CallbackQuery, callback_data: AddTariffsToPromo, state: FSMContext):
    state_data = await state.get_data()
    promo_id = state_data["callback_data"].promo_id
    await change_promo_tariffs(int(promo_id), tariffs=state_data["selected_tariffs"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, выбранные тарифы были добавлены!",
        parse_mode=ParseMode.HTML)

    await show_promos(callback.message)
    await state.set_state(AdminPromo.edit)


"""───────────────────────────────────────────── Callbacks Add Promo ─────────────────────────────────────────────"""


@router.message(AdminPromo.add_code)
async def get_text_add_code(message: Message, state: FSMContext):
    try:
        await message.answer(
            text=f"Получен код: <code>{message.text}</code>\n\nВведите процент скидки для промокода  ⬇️",
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminPromo.add_price)
        await state.update_data(code=str(message.text))

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminPromo.add_price)
async def get_text_add_price(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return

        elif int(message.text) > 100:
            await message.answer("Ошибка! Сумма не может быть больше 100%, попробуйте снова.")
            return

        await message.answer(
            text=f"Получено число: <code>{message.text}</code>%\n\nВведите максимальное количество пользователей (без ограничения = -1)  ⬇️",
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminPromo.add_max_users)
        await state.update_data(price=str(message.text))

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminPromo.add_max_users)
async def get_text_add_max_users(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit() and message.text != "-1":
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return

        await message.answer(
            text=f"Получено число: <code>{message.text}</code>\n\nВведите дату окончания действия промокода формат: ДД.ММ.ГГГГ (без ограничения = -1) ⬇️",
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminPromo.add_finish_date)
        await state.update_data(max_users=str(message.text))

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminPromo.add_finish_date)
async def get_text_add_finish_date(message: Message, state: FSMContext):
    try:
        if message.text == "-1":
            finish_date = None
        else:
            try:
                finish_date = datetime.strptime(message.text, '%d.%m.%Y')
            except Exception as e:
                await message.answer("Вы ввели дату не в неправильном формате\nПопробуйте еще раз, формат: ДД.ММ.ГГГГ")
                return
        tariffs = await get_tariffs()
        await message.answer(
            text=f"Получена дата: <code>{finish_date}</code>\n\nВыберите новый список тарифов для этого промокода ⬇️",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_tariff_buttons(tariffs))

        await state.set_state(AdminPromo.add_tariffs)
        await state.update_data(finish_date=finish_date, selected_tariffs=[])

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(AddTariffsToPromo.filter(F.action == "confirm_change"), AdminPromo.add_tariffs)
async def clb_add_promo_tariffs_confirm(callback: CallbackQuery, callback_data: AddTariffsToPromo, state: FSMContext):
    state_data = await state.get_data()
    await callback.answer()
    selected_tariffs = [int(t) for t in state_data["selected_tariffs"]]
    promo = await add_promo(
        code=state_data["code"],
        price=int(state_data["price"]),
        user_limit=int(state_data["max_users"]),
        finish_time=state_data["finish_date"],
        tariffs=selected_tariffs)

    await callback.message.answer(
        text=f"Успешно, новый промокод был создан!",
        parse_mode=ParseMode.HTML)

    await show_promo(promo.id, callback)
    await show_promos(callback.message)
    await state.set_state(AdminPromo.edit)
