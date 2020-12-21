from typing import Tuple, Optional
import math
import datetime as dt
from adplus import MqPlus

"""
# TODO

* Loggers - NOT RIGHT. Figure out better. Monkeypatching isn't working. 
"""


def offstate(
    entity: str,
    stateobj: dict,
    config: dict,
    mqapi: MqPlus,
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
            mqapi.info(
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


def turn_off_entity(
    mqapi: MqPlus,
    entity: str,
    stateobj: dict,
    config: dict,
    test_mode: bool = False,
) -> None:

    attributes = stateobj["attributes"]
    off_rule = config

    if "temperature" not in attributes:
        mqapi.log(f"{entity} - Offline. Can not turn off.")
        return

    if not off_rule:
        mqapi.error(f"No off_rule for entity: {entity}. Can not turn off.")
        return

    if off_rule["off_state"] == "off":
        retval = mqapi.call_service("climate/turn_off", entity_id=entity)
        mqapi.lb_log(f"{entity} - Turn off")
    elif off_rule["off_state"] == "away":
        retval = mqapi.call_service(
            "climate/set_preset_mode",
            entity_id=entity,
            preset_mode="Away",
        )
        mqapi.lb_log(f"{entity} -  Set away mode")
    elif off_rule["off_state"] == "perm_hold":
        retval1 = mqapi.call_service(
            "climate/set_temperature",
            entity_id=entity,
            temperature=off_rule["off_temp"],
        )

        retval2 = mqapi.call_service(
            "climate/set_preset_mode",
            entity_id=entity,
            preset_mode="Permanent Hold",
        )
        mqapi.log(
            f"{entity} - Set Perm Hold to {off_rule['off_temp']}. retval1: {retval1} -- retval2: {retval2}"
        )
    else:
        mqapi.error(f"Programming error. Unexpected off_rule: {off_rule}")


def occupancy_length(entity_id, hassapi, days=10):
    """
    returns: state (on/off), duration_off (hours float / None), last_on_date (datetime, None)
    {
        "entity_id": "binary_sensor.seattle_occupancy",
        "state": "off",
        "attributes": {
            "friendly_name": "Seattle Occupancy",
            "device_class": "occupancy"
        },
        "last_changed": "2020-10-28T13:10:47.384057+00:00",
        "last_updated": "2020-10-28T13:10:47.384057+00:00"
    }
    """
    data = hassapi.get_history(entity_id=entity_id, days=days)

    if len(data) == 0:
        hassapi.warn(f"get_history returned no data for entity: {entity_id}. Exiting")
        return "error", None, None
    edata = data[0]

    # the get_history() fn doesn't say it guarantees sort (though it appears to be)
    edata = list(reversed(sorted(edata, key=lambda rec: rec["last_updated"])))

    current_state = edata[0]["state"]
    if current_state == "on":
        return "on", None, None

    last_on_date = None
    for rec in edata:
        if rec.get("state") == "on":
            last_on_date = dt.datetime.fromisoformat(rec["last_updated"])
            now = hassapi.get_now()
            duration_off_hours = round(
                (now - last_on_date).total_seconds() / (60 * 60), 2
            )
            return "off", duration_off_hours, last_on_date

    # Can not find a last on time. Give the total time shown.
    min_time_off = round(
        (
            hassapi.get_now() - dt.datetime.fromisoformat(edata[-1]["last_updated"])
        ).seconds
        / (60 * 60),
        2,
    )
    return "off", min_time_off, None
