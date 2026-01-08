from enum import Enum
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.mutable import MutableList
from src.database.database import Base

msk = ZoneInfo("Europe/Moscow")

# Все временные значения работают по московскому времени (Europe/Moscow)


class PaymentStatus(str, Enum):
    pending = "pending"
    success = "success"
    failed = "failed"
    error = "error"  # Платеж с ошибкой, который не может быть обработан (например, тариф не найден)


class PaymentsOrm(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tariff_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(default=PaymentStatus.pending)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    promo: Mapped[int] = mapped_column(BigInteger, nullable=True)
    device: Mapped[str] = mapped_column(Text, nullable=True)
    key_issued_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), onupdate=func.now(), default=func.now())


class UsersOrm(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=True)
    balance: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    test_sub: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trial_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    used_promo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enter_start_text: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    info: Mapped[dict] = mapped_column(JSON)

    @property
    def trial_time_left(self) -> dict:
        """Возвращает оставшееся время по пробному периоду."""
        if not self.trial_expires_at:
            return {"expired": True, "days": 0, "hours": 0}

        now = datetime.now(msk)
        delta = self.trial_expires_at - now
        if delta.total_seconds() <= 0:
            return {"expired": True, "days": 0, "hours": 0}

        days = delta.days
        hours = delta.seconds // 3600
        return {"expired": False, "days": days, "hours": hours}


class AdminsOrm(Base):
    __tablename__ = "admins"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class BannedOrm(Base):
    __tablename__ = "banned"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    ban_reason: Mapped[str] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))


class TariffsOrm(Base):
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    discount: Mapped[int] = mapped_column(Integer, nullable=True)


class PromoOrm(Base):
    __tablename__ = "promo"

    code: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    users_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    finish_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    users: Mapped[list] = mapped_column(MutableList.as_mutable(ARRAY(BigInteger)), default=[])
    tariffs: Mapped[list] = mapped_column(MutableList.as_mutable(ARRAY(BigInteger)), default=[])


class ServersOrm(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(String, nullable=False)
    login: Mapped[str] = mapped_column(String, nullable=False)
    password: Mapped[str] = mapped_column(Text, nullable=False)
    max_users: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class KeysOrm(Base):
    __tablename__ = "keys"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'), nullable=False)
    server_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    device: Mapped[str] = mapped_column(String, nullable=False)
    payment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # Связь с платежом
    active: Mapped[bool] = mapped_column(Boolean, nullable=True, default=True)
    alerted: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    finish: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False)

    @property
    def time_left(self) -> dict:
        """Возвращает оставшееся время до окончания ключа."""
        now = datetime.now(msk)
        delta = self.finish - now
        if delta.total_seconds() <= 0:
            return {"expired": True, "days": 0, "hours": 0}
        days = delta.days
        hours = delta.seconds // 3600
        return {"expired": False, "days": days, "hours": hours}


class TextSettingsOrm(Base):
    __tablename__ = "text_settings"

    iphone_video: Mapped[str] = mapped_column(Text, default="BAACAgIAAxkBAAOCZ5acW_rIbe0U5CnPJccDRXoxINcAAtdsAAKBr7hIkNFQUjRFl_Q2BA", nullable=True)
    iphone_url: Mapped[str] = mapped_column(Text, default="https://apps.apple.com/ru/app/streisand/id6450534064", nullable=True)

    android_video: Mapped[str] = mapped_column(Text, default="BAACAgIAAxkBAAOCZ5acW_rIbe0U5CnPJccDRXoxINcAAtdsAAKBr7hIkNFQUjRFl_Q2BA", nullable=True)
    android_url: Mapped[str] = mapped_column(Text, default="https://play.google.com/store/apps/details?id=com.v2ray.ang", nullable=True)

    macos_video: Mapped[str] = mapped_column(Text, default="BAACAgIAAxkBAAJYwWWXvpkxxgVJsLgjm9Km6s8YPQABKwAC4z4AArntwUilAdot2TtUQjQE", nullable=True)
    macos_url: Mapped[str] = mapped_column(Text, default="https://apps.apple.com/ru/app/streisand/id6450534064", nullable=True)

    windows_video: Mapped[str] = mapped_column(Text, default="BAACAgIAAxkBAAJZDmWZY4D2OTOynOdcIKdTqbFFqk5NAALfRAACjpHRSEZfmtGQIVMtNAQ", nullable=True)
    windows_url: Mapped[str] = mapped_column(Text, default="https://github.com/MatsuriDayo/nekoray/releases/download/3.26/nekoray-3.26-2023-12-09-windows64.zip", nullable=True)

    faq_list: Mapped[str] = mapped_column(MutableList.as_mutable(ARRAY(Text)), default=list)
    test_hours: Mapped[int] = mapped_column(Integer, default=48)


class NotificationType(str, Enum):
    trial_expiring_soon = "trial_expiring_soon"
    trial_expired = "trial_expired"
    paid_expiring_soon = "paid_expiring_soon"
    paid_expired = "paid_expired"
    new_user_no_keys = "new_user_no_keys"
    global_weekly = "global_weekly"


class NotificationRule(Base):
    __tablename__ = "notification_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[NotificationType] = mapped_column(SAEnum(NotificationType, name="notificationtype"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    offset_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repeat_every_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repeat_every_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_of_day: Mapped[time | None] = mapped_column(nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True, default="UTC")
    message_template: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    schedules: Mapped[list["UserNotificationSchedule"]] = relationship(back_populates="rule", cascade="all, delete-orphan")


class NotificationScheduleStatus(str, Enum):
    planned = "planned"
    sent = "sent"
    skipped = "skipped"
    cancelled = "cancelled"
    error = "error"


class UserNotificationSchedule(Base):
    __tablename__ = "user_notification_schedules"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_notification_schedule_dedup"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("notification_rules.id", ondelete="CASCADE"))
    planned_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[NotificationScheduleStatus] = mapped_column(
        SAEnum(NotificationScheduleStatus, name="notificationschedulestatus"),
        default=NotificationScheduleStatus.planned,
    )
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    rule: Mapped["NotificationRule"] = relationship(back_populates="schedules")


class NotificationLogStatus(str, Enum):
    ok = "ok"
    failed = "failed"


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("notification_rules.id"), nullable=True)
    schedule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_notification_schedules.id", ondelete="SET NULL")
    )
    status: Mapped[NotificationLogStatus] = mapped_column(SAEnum(NotificationLogStatus, name="notificationlogstatus"))
    message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


# Backwards-compatibility alias
User = UsersOrm