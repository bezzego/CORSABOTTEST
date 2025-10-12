import os
from pydantic_settings import BaseSettings, SettingsConfigDict

# просто логика выбора env файла
DEFAULT_ENV_FILE = os.environ.get("ENV_FILE", ".env.test")


class TelegramConfig(BaseSettings):
    token: str

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_prefix="TG_",
        env_file_encoding="utf-8",
        extra="allow"
    )


class PostgresqlConfig(BaseSettings):
    host: str
    port: str
    user: str
    password: str
    db_name: str

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_prefix="DB_",
        env_file_encoding="utf-8",
        extra="allow"
    )

    @property
    def database_url(self):
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"


class PaymentsConfig(BaseSettings):
    key: str
    token: str
    comment: str

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_prefix="PAYMENT_",
        env_file_encoding="utf-8",
        extra="allow"
    )


class LoggingConfig(BaseSettings):
    debug: bool = True
    cmd_convert_revert: bool = False


class Config(BaseSettings):
    telegram: TelegramConfig = TelegramConfig()
    db: PostgresqlConfig = PostgresqlConfig()
    payments: PaymentsConfig = PaymentsConfig()
    logging: LoggingConfig = LoggingConfig()
    prefix: str = "corsarvpn"
    # флаг для отключения уведомлений о ключах (например для тестов)
    disable_key_notifications: bool = False

    @classmethod
    def load(cls) -> "Config":
        print(f"Loading settings from env file: {DEFAULT_ENV_FILE}")
        return cls()


settings = Config.load()