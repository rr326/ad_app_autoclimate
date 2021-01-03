import datetime as dt
from typing import List, Optional, Tuple
from _autoclimate.utils import climate_name
import math
from dateutil import tz

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
    UNOCCUPIED_SINCE_OCCUPIED_VALUE = dt.datetime(dt.MAXYEAR, 12, 29, tzinfo=tz.tzutc())

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
        self.hass.run_in(self.init_occupancy_listeners, 0.1)

    def unoccupied_sensor_name(self, climate):
        return self.unoccupied_sensor_name_static(self.appname, climate)
    
    @staticmethod
    def unoccupied_sensor_name_static(appname, climate):
        return f"sensor.{appname}_{climate_name(climate)}_unoccupied_since"

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
    
    def init_occupancy_listeners(self, kwargs):
        """
        This will create a different occupancy sensor for each climate, 
        so if multiple climates have the same oc_sensor, you'll get multiple
        listeners.  
        """
        for climate in self.climates:
            oc_sensor = self.get_sensor(climate=climate)
            self.hass.log(f'listen_state: {oc_sensor}')
            self.hass.listen_state(
                self.update_occupancy_sensor, entity=oc_sensor, attribute="all",climate=climate
            )         

    def update_occupancy_sensor(self, entity, attribute, old, new, kwargs):
        climate = kwargs["climate"]
        # self.hass.log(f'update_occupancy_sensor: {entity} -- {climate} -- {new} -- {attribute}')
        last_on_date = self.oc_sensor_val_to_last_on_date(new["state"], new["last_updated"])
        unoccupied_sensor_name = self.unoccupied_sensor_name(climate)
        self.hass.update_state(
            unoccupied_sensor_name,
            state=last_on_date,
        )
        self.hass.log(f'update_occupancy_sensor - {unoccupied_sensor_name} - state: {last_on_date}')
        

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

    def oc_sensor_val_to_last_on_date(self, state, last_on_date):
        if state == "on":
            return self.UNOCCUPIED_SINCE_OCCUPIED_VALUE
        elif state in  ["off", "unavailable"]:
            return last_on_date
        else:
            self.hass.log(f'Unexpected last_on_date state: {state}')
            # Error or offline
            return None

    def history_last_on_date(self, climate=None, sensor=None):
        state, duration_off, last_on_date = self.get_unoccupied_time_for(climate, sensor)
        return self.oc_sensor_val_to_last_on_date(state, last_on_date)

    def get_unoccupied_time_for(self, climate=None, sensor=None):
        oc_sensor = self.get_sensor(climate=climate, sensor=sensor)

        state, duration_off, last_on_date = self._history_occupancy_info(oc_sensor)
        return state, duration_off, last_on_date

    @staticmethod
    def duration_off_static(hass, dateval):
        if isinstance(dateval, str):
            dateval = dt.datetime.fromisoformat(dateval)
        if dateval.tzinfo is None:
            dateval.replace(tzinfo=tz.tzlocal())

        now = hass.get_now()
        if dateval > now:
            return None

        duration_off_hours = round(
            (now - dateval).total_seconds() / (60 * 60), 2
        )
        return duration_off_hours


    def _history_occupancy_info(self,sensor_id: str, days: int = 10):
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
        data: List = self.hass.get_history(entity_id=sensor_id, days=days)  # type: ignore

        if not data or len(data) == 0:
            self.hass.warn(f"get_history returned no data for entity: {sensor_id}. Exiting")
            return "error", None, None
        edata = data[0]

        # the get_history() fn doesn't say it guarantees sort (though it appears to be)
        edata = list(reversed(sorted(edata, key=lambda rec: rec["last_updated"])))

        current_state = edata[0]["state"]
        if current_state == "on":
            return "on", None, None

        last_on_date = None
        now: dt.datetime = self.hass.get_now()  # type: ignore
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
