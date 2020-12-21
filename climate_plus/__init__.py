from typing import Tuple, Optional
import logging
import math


def offstate(
    entity: str,
    stateobj: dict,
    config: dict,
    test_mode: bool = False,
    mock_data: Optional[dict] = None,
) -> Tuple[str, str, float]:
    """
    Returns: on/off/offline, reason, current_temp

    if test_mode it will merge self.mocked_attributes to the state
    """

    state = stateobj
    attributes = state["attributes"] if state else {}

    if test_mode and mock_data:
        if mock_data.get("entity_id") == entity:
            mock_attributes = mock_data["mock_attributes"]
            logging.info(
                f"get_entity_state: using MOCKED attributes for entity {entity}: {mock_attributes}"
            )
            attributes = attributes.copy()
            attributes.update(mock_attributes)

    # Get current temperature
    current_temp: float  = attributes.get("current_temperature", math.nan)

    #
    # Offline?
    #
    if "temperature" not in attributes:
        return "offline", "offline", current_temp

    #
    # Heat is on?
    #
    temp = attributes.get("temperature")
    off_rule = config

    if temp is None:
        if off_rule["off_state"] == "off":
            return "off", "Thermostat is off", current_temp
        else:
            return "error_off", "Thermostat is off but should not be!", current_temp
    elif off_rule["off_state"] == "off":
        return "on", "Thermostat is not off, but it should be", current_temp
    elif off_rule["off_state"] == "away":
        if attributes.get("preset_mode").lower() != "away":
            return "on", "Not away mode, but should be", current_temp
        else:  # Away mode
            if (off_temp := off_rule.get("off_temp")) is None:
                return "off", "Away mode.", current_temp
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

    elif off_rule["off_state"] == "perm_hold":
        if attributes.get("preset_mode") != off_rule["perm_hold_string"]:
            return (
                "on",
                f"Not proper permanent hold. Actual: {attributes.get('preset_mode')} -- {attributes.get('temperature')}",
                current_temp,
            )
        elif temp > off_rule["off_temp"]:
            return (
                "on",
                f"Perm hold at {temp}. Should be <= {off_rule['off_temp']}",
                current_temp,
            )
        else:
            return "off", f"Perm hold at {temp}", current_temp

    return "none", "error - should not be here", current_temp
