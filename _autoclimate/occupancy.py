import datetime as dt
from typing import List, Optional, Tuple
from _autoclimate.utils import climate_name
import math

from adplus import Hass

"""
Create new sensors
Reason: That way you do auto off if unoccupied since AND last_manual_change > X hours

* unoccupied_since:
    * Last unoccupied
    * None if no data
    * datetime.max if currently occupied
* last_manual_change
    * Timestamps as above

# TODO
* Offline - handle
"""

class Occupancy:
    def __init__(
        self,
        hass: Hass,
        config: dict,
        appname: str,
        climates: list,
        test_mode: bool,
    ):
        self.hass = hass
        self.config = config
        self.appname = appname
        self.test_mode = test_mode
        self.climates = climates

        self.hass.run_in(self.create_occupancy_sensors, 0)

    def unoccupied_sensor_name(self, entity):
        return f"sensor.{self.appname}_{climate_name(entity)}_unoccupied_since"

    def create_occupancy_sensors(self, kwargs):
        # Unoccupied Since  Sensors
        for climate in self.climates:
            unoccupied_sensor_name = self.unoccupied_sensor_name(climate)
            last_on_date = self.history_last_on_date(climate=climate)
            self.hass.update_state(
                unoccupied_sensor_name,
                state=last_on_date,
                attributes={
                    "freindly_name": f"{climate_name(climate)} - unoccupied since",
                    "device_class": "timestamp",
                },
            )
            self.hass.log(f"Created sensor: {unoccupied_sensor_name}. Initial state: {last_on_date}")     

    def get_sensor(self, climate=None, sensor=None):
        if climate and sensor:
            raise RuntimeError(f'Programming error - history_last_on_date: give climate OR sensor')
        elif climate is None and sensor is None:
            raise RuntimeError(f'Programming error - need a climate or sensor. Got None.')
        elif sensor:
            return sensor
        else:
            try:
                oc_sensor = self.config[climate]["occupancy_sensor"]
            except KeyError:
                raise RuntimeError(f"Unable to get occupancy_sensor for {climate}")  
            return oc_sensor  

    def history_last_on_date(self, climate=None, sensor=None):
        state, duration_off, last_on_date = self.get_unoccupied_time_for(climate, sensor)
        if state == "on":
            return dt.datetime.max
        elif state in  ["off", "unavailable"]:
            return last_on_date
        else:
            self.hass.log(f'Unexpected last_on_date state: {state}')
            # Error or offline
            return None

    def get_unoccupied_time_for(self, climate=None, sensor=None):
        oc_sensor = self.get_sensor(climate=climate, sensor=sensor)

        state, duration_off, last_on_date = _occupancy_length(oc_sensor, self.hass)
        return state, duration_off, last_on_date

def get_unoccupied_time_for(
    entity: str, config: dict, hassapi: Hass
) -> Tuple[Optional[str], Optional[float], Optional[dt.datetime]]:
    hassapi.log('## REMOVE get_unoccupied_time_for')
    try:
        oc_sensor = config["occupancy_sensor"]
    except KeyError:
        hassapi.error(f"Unable to get occupancy_sensor for {entity}")
        return None, None, None

    state, duration_off, last_on_date = _occupancy_length(oc_sensor, hassapi)
    return state, duration_off, last_on_date


def _occupancy_length(sensor_id: str, hassapi: Hass, days: int = 10):
    """
    returns: state (on/off/unavailable), duration_off (hours float / None), last_on_date (datetime, None)
    state = state of occupancy sensor

    All based on an occupancy sensor's history data.
    {
        "entity_id": "binary_sensor.seattle_occupancy",
        "state": "off", # on/off/unavailable 
        "attributes": {
            "friendly_name": "Seattle Occupancy",
            "device_class": "occupancy"
        },
        "last_changed": "2020-10-28T13:10:47.384057+00:00",
        "last_updated": "2020-10-28T13:10:47.384057+00:00"
    }

    Note - it looks like the occupancy sensor properly handles offline by returning 
    an "unavailble" status. (Unlike temp sensors, which show the last value.)
    """
    data: List = hassapi.get_history(entity_id=sensor_id, days=days)  # type: ignore

    if not data or len(data) == 0:
        hassapi.warn(f"get_history returned no data for entity: {sensor_id}. Exiting")
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
            return current_state, duration_off_hours, last_on_date

    # Can not find a last on time. Give the total time shown.
    min_time_off = round(
        (now - dt.datetime.fromisoformat(edata[-1]["last_updated"])).seconds
        / (60 * 60),
        2,
    )
    return current_state, min_time_off, None
