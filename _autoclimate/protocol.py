from typing import Protocol

from adplus import Hass

"""
For type hints
"""


class AutoClimateProto(Hass, Protocol):
    argsn: dict
    test_mode: bool
    appname: str
