from typing import Tuple, Optional, List
import math
import datetime as dt
from appdaemon.adapi import ADAPI
from appdaemon.plugins.hass.hassapi import Hass

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


def turn_off_entity(
    adapi: ADAPI,
    entity: str,
    stateobj: dict,
    config: dict,
    test_mode: bool = False,
) -> None:

    attributes = stateobj["attributes"]

    if "temperature" not in attributes:
        adapi.log(f"{entity} - Offline. Can not turn off.")
        return

    if not config:
        adapi.error(f"No off_rule for entity: {entity}. Can not turn off.")
        return

    # Set to "off"
    if config["off_state"] == "off":
        retval = adapi.call_service("climate/turn_off", entity_id=entity)
        adapi.lb_log(f"{entity} - Turn off")

    # Set to "away"
    elif config["off_state"] == "away":
        retval = adapi.call_service(
            "climate/set_preset_mode",
            entity_id=entity,
            preset_mode="Away",
        )
        adapi.lb_log(f"{entity} -  Set away mode")

    # Set to "perm_hold"
    elif config["off_state"] == "perm_hold":
        retval1 = adapi.call_service(
            "climate/set_temperature",
            entity_id=entity,
            temperature=config["off_temp"],
        )

        retval2 = adapi.call_service(
            "climate/set_preset_mode",
            entity_id=entity,
            preset_mode="Permanent Hold",
        )
        adapi.log(
            f"{entity} - Set Perm Hold to {config['off_temp']}. retval1: {retval1} -- retval2: {retval2}"
        )

    # Invalid config
    else:
        adapi.error(f"Programming error. Unexpected off_rule: {config}")


def occupancy_length(entity_id: str, hassapi: Hass, days: int = 10):
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
    data: List = hassapi.get_history(entity_id=entity_id, days=days)  # type: ignore

    if not data or len(data) == 0:
        hassapi.warn(f"get_history returned no data for entity: {entity_id}. Exiting")
        return "error", None, None
    edata = data[0]

    # the get_history() fn doesn't say it guarantees sort (though it appears to be)
    edata = list(reversed(sorted(edata, key=lambda rec: rec["last_updated"])))

    current_state = edata[0]["state"]
    if current_state == "on":
        return "on", None, None

    last_on_date = None
    now: dt.datetime = hassapi.get_now()  # type: ignore
    for rec in edata:
        if rec.get("state") == "on":
            last_on_date = dt.datetime.fromisoformat(rec["last_updated"])
            duration_off_hours = round(
                (now - last_on_date).total_seconds() / (60 * 60), 2
            )
            return "off", duration_off_hours, last_on_date

    # Can not find a last on time. Give the total time shown.
    min_time_off = round(
        (now - dt.datetime.fromisoformat(edata[-1]["last_updated"])).seconds
        / (60 * 60),
        2,
    )
    return "off", min_time_off, None


def climate_name(entity):
    # climate.my_thermostat ==> my_thermostat
    return entity.split(".")[1]


def get_unoccupied_time_for(
    entity: str, config: dict, hassapi: Hass
) -> Tuple[Optional[str], Optional[float], Optional[dt.datetime]]:
    try:
        oc_sensor = config["occupancy_sensor"]
    except KeyError:
        hassapi.error(f"Unable to get occupancy_sensor for {entity}")
        return None, None, None

    state, duration_off, last_on_date = occupancy_length(oc_sensor, hassapi)
    return state, duration_off, last_on_date
