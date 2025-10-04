from colorama import Fore, Style, init
from src.config import settings

init(convert=settings.logging.cmd_convert_revert)
LEVEL = "DEBUG" if settings.logging.debug else "INFO"

console_format = (
    f"{Fore.WHITE}%(asctime)s{Style.RESET_ALL} | "
    f"{Fore.GREEN}%(levelname)-8s{Style.RESET_ALL} | "
    f"{Fore.CYAN}%(name)s{Style.RESET_ALL} | "
    f"{Fore.CYAN}%(lineno)d{Style.RESET_ALL} - "
    f"{Fore.WHITE}%(message)s{Style.RESET_ALL}"
)

file_format = "%(asctime)s | %(levelname)-8s| %(name)s | %(lineno)d - %(message)s"
dictLogConfig = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "stream_format": {
            "format": console_format,
        },
        "file_format": {
            "format": file_format,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": LEVEL,
            "formatter": "stream_format",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "file_format",
            "filename": "src/logs/logs.log",
            "encoding": "utf8",
            "maxBytes": 1 * 1024 * 1024,
            "backupCount": 3
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "ERROR",
            "formatter": "file_format",
            "filename": "src/logs/error_logs.log",
            "encoding": "utf8",
            "maxBytes": 1 * 1024 * 1024,
            "backupCount": 3
        },
    },
    "root": {
        "level": LEVEL,
        "handlers": ["console", "file", "error_file"],
    },
}
