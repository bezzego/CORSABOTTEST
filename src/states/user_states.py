from aiogram.fsm.state import State, StatesGroup


class TariffState(StatesGroup):
    """
    select_device have msg_select_device_id attr
    buy_tariff have msg_buy_tariff_id and tariff_obj attr
    payment have payment_uuid and tariff_obj attr
    """
    select_device = State()
    buy_tariff = State()
    promo_enter = State()
    payment = State()


class TestSubState(StatesGroup):
    """
    select_device have user_obj attr
    """
    select_device = State()
    create_key = State()
