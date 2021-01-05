import adplus
import json  # noqa
import math
from typing import Optional, Tuple

import adplus
from adplus import Hass

adplus.importlib.reload(adplus)
from _autoclimate.occupancy import Occupancy
from _autoclimate.utils import climate_name
from _autoclimate.schema import SCHEMA


class TurnOff:
    def __init__(
        self,
        hass: Hass,
        config: dict,
        poll_frequency: int,
        appname: str,
        climates: list,
        test_mode: bool,
        climate_state: dict,
    ):
        self.hass = hass
        self.config = config
        self.poll_frequency = poll_frequency
        self.appname = appname
        self.app_state_name = f"app.{self.appname}_state"
        self.test_mode = test_mode
        self.climates = climates
        self.climate_state = climate_state

        self.state: dict = {}
        self._current_temps: dict = {}  # {climate: current_temp}

        self.init_listeners()
        self.hass.run_every(
            self.autooff_scheduled_cb, "now", self.poll_frequency * 60 * 60
        )

    def init_listeners(self):
        self.hass.listen_event(self.cb_turn_off_all, event=self.event_all_off_name())
        self.hass.log(f"Listening to event: {self.event_all_off_name()}")
        self.hass.listen_event(
            self.cb_turn_off_climate, event=self.event_entity_off_name()
        )
        self.hass.log(f"Listening to event: {self.event_entity_off_name()}")

    def event_all_off_name(self) -> str:
        return f"app.{self.appname}_turn_off_all"

    def event_entity_off_name(self) -> str:
        return f"app.{self.appname}_turn_off_climate"

    def turn_off_climate(
        self, climate: str, config: dict = None, test_mode: bool = False
    ) -> None:
        """
        Turn "off" a climate climate, where "off" is defined by an off rule such as:
        climate.cabin:
            off_state: "away"
            off_temp:  55
        config - if given, will use from self.config. If passed, will use passed config
        """
        if config is None:
            config = self.config[climate]
        else:
            # Config passed in.
            schema = SCHEMA["entity_rules"]["valuesrules"]["schema"]
            try:
                config = adplus.normalized_args(self.hass, schema, config)
            except adplus.ConfigException as err:
                self.hass.error(
                    f"turn_off_climate called with passed-in config that does not validate: {config}"
                )
                return

        stateobj = self.hass.get_state(climate, attribute="all")
        attributes = stateobj["attributes"]

        if "temperature" not in attributes:
            self.hass.log(f"{climate} - Offline. Can not turn off.")
            return

        if not config:
            self.hass.error(f"No off_rule for climate: {climate}. Can not turn off.")
            return

        # Set to "off"
        if config["off_state"]["state"] == "off":
            if not test_mode:
                self.hass.call_service("climate/turn_off", entity_id=climate)
            self.hass.lb_log(f"{climate} - Turn off")

        # Set to "away"
        elif config["off_state"]["state"] == "away":
            if not test_mode:
                self.hass.call_service(
                    "climate/set_preset_mode",
                    entity_id=climate,
                    preset_mode="Away",
                )
            self.hass.lb_log(f"{climate} -  Set away mode")

        # Set to "perm_hold"
        elif config["off_state"]["state"] == "perm_hold":
            if not test_mode:
                self.hass.call_service(
                    "climate/set_temperature",
                    entity_id=climate,
                    temperature=config["off_state"]["temp"],
                )
                self.hass.call_service(
                    "climate/set_preset_mode",
                    entity_id=climate,
                    preset_mode="Permanent Hold",
                )
            self.hass.log(
                f"{climate} - Set Perm Hold to {config['off_state']['temp']}. "
            )

        # Invalid config
        else:
            self.hass.error(f"Programming error. Unexpected off_rule: {config}")

    def cb_turn_off_climate(self, event_name, data, kwargs):
        """
        kwargs:
            entity: climate_string
            config: OFF_SCHEMA (see above)
            test_mode: bool (optional)
        """
        climate = data["climate"]
        config = data.get("config")
        test_mode = data.get("test_mode")
        return self.turn_off_climate(climate, config=config, test_mode=test_mode)

    def cb_turn_off_all(self, event_name, data, kwargs):
        test_mode = data.get("test_mode")
        for climate in self.climates:
            config = data["config"].get(climate, {}) if "config" in data else None
            self.turn_off_climate(climate, config=config, test_mode=test_mode)

    def autooff_scheduled_cb(self, kwargs):
        """
        Turn off any thermostats that have been on too long.
        """
        for climate, state in self.climate_state.items():
            self.hass.debug(f'autooff: {climate} - {state["state"]}')

            config = self.config.get(climate)
            if not config:
                self.hass.log(f"autooff: No config. skipping {climate}")
                continue
            if not "auto_off_hours" in config:
                self.hass.log(f"autooff: No auto_off_hours for {climate}. Skipping.")
                continue
            if state["state"] == "off":
                continue
            if state["offline"]:
                continue  # Can't do anything
            if state["state"] == "error_off":
                # Off but should not be
                self.hass.log(
                    f"{climate} is off but should not be! Attempting to turn on."
                )
                if not self.test_mode:
                    self.hass.call_service("climate/turn_on", entity_id=climate)
                self.hass.lb_log(f"{climate} - Turned thermostat on.")

            duration_off = self.climate_state[f"{climate}_unoccupied"]

            if duration_off is None:
                self.hass.warn(f"Programming error - duration_off None for {climate}")
            elif duration_off < 0:
                self.hass.warn(
                    f"Programming error - Negative duration off for {climate}: {duration_off}"
                )
            elif duration_off > config["auto_off_hours"] or self.test_mode:
                self.hass.lb_log(f"Autooff - Turning off {climate}")
                if not self.test_mode:
                    self.turn_off_climate(climate)
