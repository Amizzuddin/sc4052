################################################################################
#  Filename:      utilities/logger.py                                          #
#  Project:       Web Network Visualizer                                       #
#  Created Date:  Tuesday, May 27th 2025, 7:11:59 am                           #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   Utility function for logging                                 #
#  --------------------------------------------------------------------------- #
#  Last Modified: Tuesday May 27th 2025 8:14:57 am                             #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
#  2025-05-27   AAC   Initial implementation                                   #
################################################################################

import logging
import sys
import time
from datetime import timedelta
from enum import Enum
from os import environ

logger = logging.getLogger(environ["PROJECT"])
logger.setLevel(logging.DEBUG)
logger.propagate = True  # This is needed for pytest caplog fixture (log output assertion)
# this will autoflush every command

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)


class LoggingColor(Enum):
    RED = "\x1b[31;20m"
    GREEN = "\x1b[32;20m"
    YELLOW = "\x1b[33;20m"
    BLUE = "\x1b[34;20m"
    RESET = "\x1b[0m"


class ElapsedFormatter(logging.Formatter):
    # https://stackoverflow.com/questions/25194864/python-logging-time-since-start-of-program

    COLORS = {
        "DEBUG": LoggingColor.BLUE.value,
        "WARNING": LoggingColor.YELLOW.value,
        "ERROR": LoggingColor.RED.value,
        "CRITICAL": LoggingColor.RED.value,
    }

    def __init__(self, format: str) -> None:
        super().__init__(format)
        self.start_time = time.time()

    def format(self, record: logging.LogRecord) -> str:
        if record.levelname in self.COLORS:
            levelname_color = self.COLORS[record.levelname] + record.levelname + LoggingColor.RESET.value
            record.levelname = levelname_color

        elapsed_seconds = record.created - self.start_time

        # using timedelta here for convenient default formatting
        elapsed = timedelta(seconds=elapsed_seconds)
        record.delta = elapsed

        # return "{} {}".format(elapsed, record.getMessage())
        return super().format(record)


format = "%(delta)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s"
elapsed_formatter = ElapsedFormatter(format)
handler.setFormatter(elapsed_formatter)
logger.addHandler(handler)
