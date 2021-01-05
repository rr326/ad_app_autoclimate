from typing import List

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
        self.config = config
        self.appname = appname
        self.test_mode = test_mode
        self.climates = climates
        self.appstate_entity = appstate_entity

        self.hass.run_in(self.create_laston_sensors, 0)
        self.hass.run_in(self.init_laston_listeners, 0.1)

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
            self.hass.set_state(
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

            if old["attributes"].get(key) == (newval := new["attributes"].get(key)):
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
