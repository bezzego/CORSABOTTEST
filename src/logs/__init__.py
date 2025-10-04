import logging.config
from logging import getLogger
from .logger import dictLogConfig

logging.config.dictConfig(dictLogConfig)
