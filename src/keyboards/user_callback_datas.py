from aiogram.filters.callback_data import CallbackData


class VideoInstruction(CallbackData, prefix="video_inst"):
    action: str
    device: str


class Tariffs(CallbackData, prefix="tariffs"):
    action: str
    tariff_id: str
    device: None | str
    key_id: None | int


class TestSub(CallbackData, prefix="test_sub"):
    action: str
    device: None | str


class MyKeys(CallbackData, prefix="my_keys"):
    button_type: str
    key_id: None | int
    page: int
