from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from src.database.crud import get_tariffs, get_tariff, change_tariff_value, delete_tariff, add_tariff
from src.keyboards.admin_callback_datas import EditTariffs, AddTariff
from src.keyboards.inline_admin import get_edit_tariffs_buttons, get_edit_tariff_buttons, get_confirm_buttons
from src.keyboards.reply_admin import get_reply_admin_btn
from src.logs import getLogger
from src.states.admin_states import AdminTariffs, AdminMenu
from src.utils.utils_async import auth_admin_role

router = Router(name=__name__)
logger = getLogger(__name__)

"""───────────────────────────────────────────── Func ─────────────────────────────────────────────"""


async def show_tariff(tariff_id: int, callback: CallbackQuery, reply_markup=None):
    tariff = await get_tariff(tariff_id)
    if tariff:
        await callback.answer()
        return await callback.message.answer(
            text=f"Тариф: <code>{tariff.name}</code>\nСтоимость: <code>{tariff.price}</code>₽\nКоличество дней: <code>{tariff.days}</code> дней",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup)


async def show_tariffs(message: Message):
    tariffs = await get_tariffs()
    if not tariffs:
        await message.answer(
            text="⚠️ Нету тарифов в бд.")
        return

    await message.answer(
        text="Список тарифов:",
        reply_markup=get_edit_tariffs_buttons(tariffs))


"""───────────────────────────────────────────── Commands and Reply ─────────────────────────────────────────────"""


@router.message(F.text == get_reply_admin_btn("adm_edit"), StateFilter(AdminMenu.tariffs_menu, AdminTariffs.edit))
@auth_admin_role
async def cmd_edit_tariffs(message: Message, state: FSMContext):
    await show_tariffs(message)
    await state.set_state(AdminTariffs.edit)


@router.message(F.text == get_reply_admin_btn("adm_add"), StateFilter(AdminMenu.tariffs_menu, AdminTariffs.edit))
@auth_admin_role
async def cmd_add_new_tariff(message: Message, state: FSMContext):
    await message.answer(
        text="<b>Создание нового тарифа:</b>\n\nВведите название для тарифа  ⬇️",
        parse_mode=ParseMode.HTML)
    await state.set_state(AdminTariffs.add_name)


"""───────────────────────────────────────────── Callbacks Edit Tariffs ─────────────────────────────────────────────"""


@router.callback_query(EditTariffs.filter(F.action == "pagination"), AdminTariffs.edit)
async def clb_paginate_tariffs(callback: CallbackQuery, callback_data: EditTariffs):
    tariffs = await get_tariffs()
    new_markup = get_edit_tariffs_buttons(tariffs, callback_data.page)

    await callback.message.edit_reply_markup(reply_markup=new_markup)
    await callback.answer()


@router.callback_query(EditTariffs.filter(F.action == "show_tariff"), AdminTariffs.edit)
async def clb_show_tariff(callback: CallbackQuery, callback_data: EditTariffs):
    await show_tariff(callback_data.tariff_id, callback)


@router.callback_query(EditTariffs.filter(F.action == "edit_tariff"), AdminTariffs.edit)
async def clb_edit_tariff(callback: CallbackQuery, callback_data: EditTariffs):
    msg = await show_tariff(callback_data.tariff_id, callback, get_edit_tariff_buttons(callback_data.tariff_id, callback_data.page))
    if not msg:
        return


@router.callback_query(EditTariffs.filter(F.action == "delete_tariff"), AdminTariffs.edit)
async def clb_delete_tariff(callback: CallbackQuery, callback_data: EditTariffs, state: FSMContext):
    await callback.answer()
    tariff = await get_tariff(callback_data.tariff_id)
    await callback.message.answer(
        text=f"Вы уверены что хотите удалить тариф: <b>{tariff.name}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_confirm_buttons(EditTariffs, tariff_id=callback_data.tariff_id, page=callback_data.page))

    await state.set_state(AdminTariffs.delete_confirm)

"""───────────────────────────────────────────────────────────────────────────────────────────────────  """


@router.callback_query(EditTariffs.filter(F.action == "change_name"))
async def clb_change_name(callback: CallbackQuery, callback_data: EditTariffs, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новое имя для тарифа  ⬇️")
    await state.set_state(AdminTariffs.change_name)
    await state.update_data(callback_data=callback_data)


@router.callback_query(EditTariffs.filter(F.action == "change_price"))
async def clb_change_price(callback: CallbackQuery, callback_data: EditTariffs, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новую цену для тарифа  ⬇️")
    await state.set_state(AdminTariffs.change_price)
    await state.update_data(callback_data=callback_data)


@router.callback_query(EditTariffs.filter(F.action == "change_days"))
async def clb_change_days(callback: CallbackQuery, callback_data: EditTariffs, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        text="Введите новое количество дней для тарифа  ⬇️")
    await state.set_state(AdminTariffs.change_days)
    await state.update_data(callback_data=callback_data)


@router.callback_query(EditTariffs.filter(F.action == "back"))
async def clb_cancel(callback: CallbackQuery, callback_data: EditTariffs):
    await callback.message.delete()


@router.callback_query(EditTariffs.filter(F.action == "cancel_change"), StateFilter(
    AdminTariffs.change_price_confirm, AdminTariffs.change_days_confirm, AdminTariffs.change_name_confirm, AdminTariffs.delete_confirm))
async def clb_change_cancel(callback: CallbackQuery, callback_data: EditTariffs, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Успешно, отмена изменений!")
    await state.clear()


"""───────────────────────────────────────────── Callbacks Edit Name ─────────────────────────────────────────────"""


@router.message(AdminTariffs.change_name)
async def get_text_change_name(message: Message, state: FSMContext):
    try:
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить название тарифа на: <code>{message.text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditTariffs, tariff_id=callback_data.tariff_id, page=callback_data.page))

        await state.set_state(AdminTariffs.change_name_confirm)
        await state.update_data(new_name=message.text)
    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditTariffs.filter(F.action == "confirm_change"), AdminTariffs.change_name_confirm)
async def clb_change_name_confirm(callback: CallbackQuery, callback_data: EditTariffs, state: FSMContext):
    state_data = await state.get_data()
    await change_tariff_value(int(callback_data.tariff_id), name=state_data["new_name"])
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение названия тарифа!\n\nНовое имя - <code>{state_data['new_name']}</code>",
        parse_mode=ParseMode.HTML)

    await show_tariffs(callback.message)
    await state.set_state(AdminTariffs.edit)


"""───────────────────────────────────────────── Callbacks Edit Price ─────────────────────────────────────────────"""


@router.message(AdminTariffs.change_price)
async def get_text_change_price(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return
        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить цену тарифа на: <code>{message.text}</code>₽",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditTariffs, tariff_id=callback_data.tariff_id, page=callback_data.page))

        await state.set_state(AdminTariffs.change_price_confirm)
        await state.update_data(new_price=int(message.text))

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditTariffs.filter(F.action == "confirm_change"), AdminTariffs.change_price_confirm)
async def clb_change_name_confirm(callback: CallbackQuery, callback_data: EditTariffs, state: FSMContext):
    state_data = await state.get_data()
    await change_tariff_value(tariff_id=int(callback_data.tariff_id), price=int(state_data["new_price"]))
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменение цену тарифа!\n\nНовая цена - <code>{state_data['new_price']}</code>",
        parse_mode=ParseMode.HTML)
    await show_tariffs(callback.message)
    await state.set_state(AdminTariffs.edit)


"""───────────────────────────────────────────── Callbacks Edit Days ─────────────────────────────────────────────"""


@router.message(AdminTariffs.change_days)
async def get_text_change_days(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return

        state_data = await state.get_data()
        callback_data = state_data["callback_data"]
        await message.answer(
            text=f"Вы уверены что хотите изменить количество дней на: <code>{message.text}</code> дней",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(EditTariffs, tariff_id=callback_data.tariff_id, page=callback_data.page))

        await state.set_state(AdminTariffs.change_days_confirm)
        await state.update_data(new_days=int(message.text))

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(EditTariffs.filter(F.action == "confirm_change"), AdminTariffs.change_days_confirm)
async def clb_change_days_confirm(callback: CallbackQuery, callback_data: EditTariffs, state: FSMContext):
    state_data = await state.get_data()
    await change_tariff_value(tariff_id=int(callback_data.tariff_id), days=int(state_data["new_days"]))
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, изменено количество дней!\n\nНовое количество - <code>{state_data['new_days']}</code> дней.",
        parse_mode=ParseMode.HTML)
    await show_tariffs(callback.message)
    await state.set_state(AdminTariffs.edit)

"""───────────────────────────────────────────── Callbacks Delete Tariff ─────────────────────────────────────────────"""


@router.callback_query(EditTariffs.filter(F.action == "confirm_change"), AdminTariffs.delete_confirm)
async def clb_delete_tariff_confirm(callback: CallbackQuery, callback_data: EditTariffs, state: FSMContext):
    await delete_tariff(int(callback_data.tariff_id))
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно, тариф был удален.",
        parse_mode=ParseMode.HTML)

    await show_tariffs(callback.message)
    await state.set_state(AdminTariffs.edit)

"""───────────────────────────────────────────── Callbacks Add Tariff ─────────────────────────────────────────────"""


@router.message(AdminTariffs.add_name)
async def get_text_add_name(message: Message, state: FSMContext):
    try:
        await message.answer(
            text=f"Получено название: <code>{message.text}</code>\n\nВведите цену для тарифа  ⬇️",
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminTariffs.add_price)
        await state.update_data(name=str(message.text))

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminTariffs.add_price)
async def get_text_add_price(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return

        await message.answer(
            text=f"Получена цена: <code>{message.text}</code>₽\n\nВведите количество выдаваемых дней для тарифа  ⬇️",
            parse_mode=ParseMode.HTML)

        await state.set_state(AdminTariffs.add_days)
        await state.update_data(price=int(message.text))

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.message(AdminTariffs.add_days)
async def get_text_add_days(message: Message, state: FSMContext):
    try:
        if not message.text.isdigit():
            await message.answer("Ошибка! Введите числовой тип, попробуйте снова.")
            return

        state_data = await state.get_data()
        await message.answer(
            text=f"<b>Создание нового тарифа:</b>\n\nНазвание: <b>{state_data['name']}</b>\nСтоимость: <b>{state_data['price']}</b>₽\nКоличество дней: <b>{message.text}</b>\n\nСоздать тариф с вышеуказанными параметрами?",
            parse_mode=ParseMode.HTML,
            reply_markup=get_confirm_buttons(AddTariff, name=state_data['name'], price=state_data['price'], days=int(message.text)))

        await state.set_state(AdminTariffs.add_confirm)

    except Exception as e:
        await message.answer(f"Error:\n{e}")
        logger.error(e, exc_info=True)
        await state.clear()


@router.callback_query(AddTariff.filter(F.action == "confirm_change"), AdminTariffs.add_confirm)
async def clb_create_tariff_confirm(callback: CallbackQuery, callback_data: AddTariff, state: FSMContext):
    await add_tariff(callback_data.name, callback_data.price, callback_data.days)
    await callback.answer()
    await callback.message.answer(
        text=f"Успешно! Тариф был создан",
        parse_mode=ParseMode.HTML)

    await show_tariffs(callback.message)
    await state.set_state(AdminTariffs.edit)
