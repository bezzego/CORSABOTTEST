import pytest
from datetime import timedelta
from types import SimpleNamespace

from src.handlers.admin_handlers.notifications import (
    parse_interval,
    split_timedelta,
    serialize_template_from_message,
)


def test_parse_interval_hours_and_days():
    assert parse_interval("12h") == timedelta(hours=12)
    assert parse_interval("2d") == timedelta(days=2)
    assert parse_interval("1d6h") == timedelta(days=1, hours=6)


def test_parse_interval_invalid():
    with pytest.raises(ValueError):
        parse_interval("")
    with pytest.raises(ValueError):
        parse_interval("5x")


def test_split_timedelta():
    d, h = split_timedelta(timedelta(days=3, hours=5))
    assert d == 3
    assert h == 5


class DummyButton:
    def __init__(self, text=None, url=None, callback_data=None):
        self.text = text
        self.url = url
        self.callback_data = callback_data


class DummyReplyMarkup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard


class DummyMessage:
    def __init__(self, text=None, photo=None, video=None, document=None, caption=None, reply_markup=None):
        self.text = text
        self.photo = photo or []
        self.video = video
        self.document = document
        self.caption = caption
        self.reply_markup = reply_markup
        # mimic aiogram message attributes
        self.html_text = text
        self.caption_html = caption


def test_serialize_template_from_text_message():
    msg = DummyMessage(text="Hello <b>world</b>")
    res = serialize_template_from_message(msg)
    assert res["media_type"] == "text"
    assert "text" in res


def test_serialize_template_with_buttons():
    btn1 = DummyButton(text="Click", url="https://example.com")
    btn2 = DummyButton(text="CB", callback_data="do_action")
    markup = DummyReplyMarkup(inline_keyboard=[[btn1, btn2]])
    msg = DummyMessage(text="Hi", reply_markup=markup)
    res = serialize_template_from_message(msg)
    assert res["buttons"] == [[{"text": "Click", "url": "https://example.com"}, {"text": "CB", "callback_data": "do_action"}]]
