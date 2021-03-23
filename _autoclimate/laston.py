import datetime as dt
from typing import List, Optional, Dict
import json

from _autoclimate.utils import climate_name
from _autoclimate.state import State
from adplus import Hass

"""
Laston - create new sensors that track the last time the climate 
was "on" as defined by autoclimate entity_rules.

sensor.autoclimate_gym_laston = <datetime>
"""


class Laston:
    def __init__(
        self,
        hass: Hass,
        config: dict,
        appname: str,
        climates: list,
        appstate_entity: str,
        test_mode: bool,
    ):
        self.hass = hass
        self.aconfig = config
        self.appname = appname
        self.test_mode = test_mode
        self.climates = climates
        self.appstate_entity = appstate_entity

        self.hass.run_in(self.create_laston_sensors, 0)
        self.hass.run_in(self.init_laston_listeners, 0.1)

        self.climate_states: Dict[str, TurnonState] = {}
        self.hass.run_in(self.initialize_states, 0)

    def initialize_states(self, kwargs):
        for climate in self.climates:
            self.climate_states[climate] = TurnonState(self.hass, self.aconfig, climate)
            print(self.climate_states[climate])

    def laston_sensor_name(self, climate):
        return self.laston_sensor_name_static(self.appname, climate)

    @staticmethod
    def laston_sensor_name_static(appname, climate):
        return f"sensor.{appname}_{climate_name(climate)}_laston"

    def create_laston_sensors(self, kwargs):
        history = self.get_history_data()
        first_date = history[-1].get("last_changed") if len(history) > 0 else None
        for climate in self.climates:
            laston_sensor_name = self.laston_sensor_name(climate)
            laston_date = self.find_laston_from_history(climate, history)
            self.hass.update_state(
                laston_sensor_name,
                state=laston_date if laston_date else first_date,
                attributes={
                    "freindly_name": f"{climate_name(climate)} - Last date climate was turned on",
                    "device_class": "timestamp",
                },
            )
            self.hass.log(
                f"Created sensor: {laston_sensor_name}. Initial state: {laston_date}"
            )

    def init_laston_listeners(self, kwargs):
        self.hass.listen_state(
            self.update_laston_sensors, entity=self.appstate_entity, attribute="all"
        )

    def update_laston_sensors(self, entity, attribute, old, new, kwargs):
        # Listener for climate entity
        for climate in self.climates:
            key = f"{climate_name(climate)}_state"

            oldval = {} if old is None else old.get("attributes", {}).get(key)
            newval = new["attributes"].get(key)
            if oldval == newval:
                continue
            if newval != "on":
                continue

            sensor_name = self.laston_sensor_name(climate)
            sensor_state = self.hass.get_state(sensor_name)
            if sensor_state == (laston_date := new["last_changed"]):
                continue
            self.hass.update_state(sensor_name, state=laston_date)
            self.hass.log(f"Updated state for {sensor_name}: {laston_date}")

    def get_history_data(self, days: int = 10) -> List:
        data: List = self.hass.get_history(entity_id=self.appstate_entity, days=days)  # type: ignore

        if not data or len(data) == 0:
            self.hass.warn(
                f"get_history returned no data for entity: {self.appstate_entity}. Exiting"
            )
            return []
        edata = data[0]

        # the get_history() fn doesn't say it guarantees sort (though it appears to be)
        edata = list(reversed(sorted(edata, key=lambda rec: rec["last_updated"])))
        return edata

    def find_laston_from_history(self, climate: str, history: List):
        key = f"{climate_name(climate)}_state"
        retval = None
        for rec in history:
            if rec["attributes"].get(key) == "on":
                retval = rec["last_changed"]
                break

        return retval


class TurnonState():
    """
    .last_turned_on() -> None, datetime

    returns the last time a climate went from "off" to "on" 
    (based on autoclimate config)

    This requires the current state, the previous state, and the state before that. (since it could be "on", "off", and "offline")
    """
    def __init__(self, hass: Hass, config: dict, climate_entity: str) -> None:
        self.hass = hass
        self.config = config[climate_entity]
        self.climate_entity = climate_entity

        # states: "on", "off", "offline"
        self.curr: Optional[str]= None
        self.curr_m1: Optional[str]= None # curr minus t1 ie: prev
        self.curr_m2: Optional[str]= None # curr minus t2 ie: prev prev

        self._curr_dt: Optional[dt.datetime] = None
        self._curr_dt_m1: Optional[dt.datetime] = None

        self._initialize_from_history()

    def add_state(self, stateobj: dict):
        if self._curr_dt and stateobj.get("last_updated") < self._curr_dt:
            raise RuntimeError(f'Adding state earlier than lastest saved state. Can only add states in increasing datetime. stateobj: {json.dumps(stateobj)}')

        state = self.entity_state(stateobj)
        if state == self.curr:
            return
        else:
            self.curr_m2 = self.curr_m1
            self.curr_m1 = self.curr
            self.curr = state

            self._curr_dt_m1 = self._curr_dt
            self._curr_dt = stateobj["last_updated"]
        

    def entity_state(self, stateobj: dict) -> str:
        return State.offstate(self.climate_entity, stateobj, self.config, self.hass)[0]

    @property
    def last_turned_on(self) -> Optional[dt.datetime]:
        # For debugging logic
        try:
            assert self.curr in ["on", "off", "offline"]
            # assert self.curr_m1 in ["on", "off", "offline"]
            # assert self.curr_m2 in ["on", "off", "offline"]
        except Exception as err:
            print(f'Err: {err}')

        if self.curr == "offline":
            return None
        elif self.curr == "on":
            if self.curr_m1 == "off":
                return self._curr_dt
            else:
                return None
        elif self.curr == "off":
            if self.curr_m1 == "on":
                return self._curr_dt_m1
            else:
                return None
        else:
            raise RuntimeError('Programming Error')

    def _initialize_from_history(self):
        history = self._get_history_data()

        for stateobj in history:
            self.add_state(stateobj)

    def _get_history_data(self, days: int = 10) -> List:
        """
        returns state history for self.climate_entity 
          **IN CHRONOLOGICAL ORDER**
        """
        data: List = self.hass.get_history(entity_id=self.climate_entity, days=days)  # type: ignore

        if not data or len(data) == 0:
            self.hass.warn(
                f"get_history returned no data for entity: {self.climate_entity}. Exiting"
            )
            return []
        edata = data[0]

        # the get_history() fn doesn't say it guarantees sort (though it appears to be)
        edata = list(sorted(edata, key=lambda rec: rec["last_updated"]))
        return edata

    def __str__(self):
        return f'TurnOnState: {self.climate_entity} - {self.curr} - {self.curr_m1} - {self.curr_m2} - {self._curr_dt} - {self._curr_dt_m1} - **{self.last_turned_on}'

