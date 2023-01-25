import datetime as dt
import json
from typing import Dict, List, Optional

from _autoclimate.state import State
from _autoclimate.utils import climate_name
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
        self.climate_states: Dict[str, TurnonState] = {}

        self.hass.run_in(self.initialize_states, 0)

    def initialize_states(self, kwargs):
        for climate in self.climates:
            self.climate_states[climate] = TurnonState(self.hass, self.aconfig, climate)

        # After initialization
        self.hass.run_in(self.create_laston_sensors, 0)
        self.hass.run_in(self.init_laston_listeners, 0.1)

    def laston_sensor_name(self, climate):
        return self.laston_sensor_name_static(self.appname, climate)

    @staticmethod
    def laston_sensor_name_static(appname, climate):
        return f"sensor.{appname}_{climate_name(climate)}_laston"

    def create_laston_sensors(self, kwargs):
        self.get_history_data()
        for climate in self.climates:
            laston_sensor_name = self.laston_sensor_name(climate)
            laston_date = self.climate_states[climate].last_turned_on
            self.hass.update_state(
                laston_sensor_name,
                state=laston_date,
                attributes={
                    "freindly_name": f"{climate_name(climate)} - Last date climate was turned on",
                    "device_class": "timestamp",
                },
            )
            self.hass.log(
                f"Created sensor: {laston_sensor_name}. Initial state: {laston_date}"
            )

    def init_laston_listeners(self, kwargs):
        for climate in self.climates:
            self.hass.listen_state(
                self.update_laston_sensors, entity_id=climate, attribute="all"
            )

    def update_laston_sensors(self, climate, attribute, old, new, kwargs):
        # Listener for climate entity
        self.climate_states[climate].add_state(new)
        laston_date = str(self.climate_states[climate].last_turned_on)

        sensor_name = self.laston_sensor_name(climate)
        sensor_state = self.hass.get_state(sensor_name)
        if sensor_state != laston_date:
            self.hass.update_state(sensor_name, state=laston_date)
            self.hass.log(
                f"Updated state for {sensor_name}: {laston_date}. Previous: {sensor_state}"
            )

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


class TurnonState:
    """
    .__init__() - initialize from history
    .add_state(stateobj) - add stateobj
    .last_turned_on [property] -> None, datetime
        returns the last time a climate went from "off" to "on"
        (based on autoclimate config)
        This requires the current state, the previous state, and the state before that.
    """

    def __init__(self, hass: Hass, config: dict, climate_entity: str) -> None:
        self.hass = hass
        self.config = config[climate_entity]
        self.climate_entity = climate_entity

        # states: "on", "off" (Ignore "offline")
        self.curr: Optional[str] = None
        self.curr_m1: Optional[str] = None  # curr minus t1 ie: prev
        self.curr_m2: Optional[str] = None  # curr minus t2 ie: prev prev

        self._curr_dt: Optional[dt.datetime] = None
        self._curr_dt_m1: Optional[dt.datetime] = None

        self._initialize_from_history()

    def add_state(self, stateobj: dict):
        """Must be added in chronologically increasing order!"""
        last_updated = stateobj.get("last_updated")
        if isinstance(last_updated, str):
            last_updated = dt.datetime.fromisoformat(stateobj["last_updated"])

        if self._curr_dt and last_updated < self._curr_dt:
            raise RuntimeError(
                f"Adding state earlier than lastest saved state. Can only add states in increasing datetime. stateobj: {json.dumps(stateobj)}"
            )

        state = self.entity_state(stateobj)
        assert state in ["on", "off", "offline", "error_off"]

        if state == self.curr or state == "offline":
            return
        else:
            self.curr_m2 = self.curr_m1
            self.curr_m1 = self.curr
            self.curr = state

            self._curr_dt_m1 = self._curr_dt
            self._curr_dt = last_updated

    def entity_state(self, stateobj: dict) -> str:
        """Return summarized state based on config: on, off, offline"""
        return State.offstate(self.climate_entity, stateobj, self.config, self.hass)[0]

    @property
    def last_turned_on(self) -> Optional[dt.datetime]:
        if self.curr == "on" and self.curr_m1 == "off":
            return self._curr_dt
        elif self.curr == "off" and self.curr_m1 == "on" and self.curr_m2 == "off":
            return self._curr_dt_m1
        else:
            return None

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
        def dtstr(val: Optional[dt.datetime]):
            if type(val) is str:
                print("here")
            return "None             " if not val else val.strftime("%y/%m/%d %H:%M:%S")

        return f"TurnOnState:  {self.climate_entity:35} **{dtstr(self.last_turned_on)}** - {self.curr} - {self.curr_m1} - {self.curr_m2} - {dtstr(self._curr_dt)} - {dtstr(self._curr_dt_m1)}"
