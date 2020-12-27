import math
from typing import Optional, Tuple

from appdaemon.adapi import ADAPI

"""
# TODO
* Add validation????
"""


def offstate(
    entity: str,
    stateobj: dict,
    config: dict,
    adapi: ADAPI,
    test_mode: bool = False,
    mock_data: Optional[dict] = None,
) -> Tuple[str, str, float]:
    """
    Returns: on/off/offline, reason, current_temp

    if test_mode it will merge self.mocked_attributes to the state

    This tests to see if a climate entity's state is what it should be.
    The logic is pretty complex due to challenges with offline/online,
    priorities, differences in behavior from different thermostats, etc.
    """

    attributes = stateobj["attributes"] if stateobj else {}

    # Mocks
    if test_mode and mock_data:
        if mock_data.get("entity_id") == entity:
            mock_attributes = mock_data["mock_attributes"]
            adapi.info(
                f"get_entity_state: using MOCKED attributes for entity {entity}: {mock_attributes}"
            )
            attributes = attributes.copy()
            attributes.update(mock_attributes)

    # Get current temperature
    current_temp: float = attributes.get("current_temperature", math.nan)

    #
    # Offline?
    #
    if "temperature" not in attributes:
        return "offline", "offline", current_temp

    #
    # Not offline. Check if mode == off_state.
    #
    temp = attributes.get("temperature")

    # Turned off?
    if temp is None:
        # Thermostat is turned off
        if config["off_state"] == "off":
            return "off", "Thermostat is off", current_temp
        else:
            return "error_off", "Thermostat is off but should not be!", current_temp

    # Thermostat is on.
    elif config["off_state"] == "off":
        return "on", "Thermostat is not off, but it should be", current_temp

    # Is away mode?
    elif config["off_state"] == "away":
        if attributes.get("preset_mode").lower() != "away":
            return "on", "Not away mode, but should be", current_temp
        else:
            # Proper away mode setting?
            if (off_temp := config.get("off_temp")) is None:
                return "off", "Away mode. No off_temp available.", current_temp
            else:
                if temp == off_temp:
                    return (
                        "off",
                        f"Away mode at proper temp: {off_temp}",
                        current_temp,
                    )
                else:
                    return (
                        "on",
                        f"Away mode but improper temp. Should be {off_temp}. Actual: {temp}.",
                        current_temp,
                    )

    # Perm_hold?
    elif config["off_state"] == "perm_hold":
        if attributes.get("preset_mode") != config["perm_hold_string"]:
            return (
                "on",
                f"Not proper permanent hold. Actual: {attributes.get('preset_mode')} -- {attributes.get('temperature')}",
                current_temp,
            )
        elif temp > config["off_temp"]:
            return (
                "on",
                f"Perm hold at {temp}. Should be <= {config['off_temp']}",
                current_temp,
            )
        else:
            return "off", f"Perm hold at {temp}", current_temp

    # Unexpected value
    return "none", "error - should not be here", current_temp


def climate_name(entity):
    # climate.my_thermostat ==> my_thermostat
    return entity.split(".")[1]
