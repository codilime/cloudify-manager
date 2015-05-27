import logging
import logging.handlers

import celery.signals


LOGFILE_SIZE_BYTES = 5 * 1024 * 1024
LOGFILE_BACKUP_COUNT = 5


@celery.signals.setup_logging.connect
def setup_logging_handler(loglevel, logfile, format, **kwargs):
    logger = logging.getLogger('celery')
    handler = logging.handlers.RotatingFileHandler(
        logfile,
        maxBytes=LOGFILE_SIZE_BYTES,
        backupCount=LOGFILE_BACKUP_COUNT)
    handler.setFormatter(logging.Formatter(fmt=format))
    logger.handlers = []
    logger.addHandler(handler)
    logger.setLevel(loglevel)
