import datetime as dt
import json  # noqa
from typing import Union

import adplus
from adplus import Hass

adplus.importlib.reload(adplus)
from _autoclimate.laston import Laston
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
        turn_on_error_off=False,
    ):
        self.hass = hass
        self.aconfig = config
        self.poll_frequency = poll_frequency
        self.appname = appname
        self.app_state_name = f"app.{self.appname}_state"
        self.test_mode = test_mode
        self.climates = climates
        self.climate_state = climate_state
        self.turn_on_error_off = turn_on_error_off

        self.state: dict = {}
        self._current_temps: dict = {}  # {climate: current_temp}

        self.init_listeners()

        if not self.any_autooff():
            self.hass.log("autooff: Not configured. Will not run.")
        else:
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
        config - if given, will use from self.aconfig. If passed, will use passed config
        """
        if config is None:
            config = self.aconfig[climate]
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

        stateobj: dict = self.hass.get_state(climate, attribute="all")  # type: ignore
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

    def any_autooff(self):
        for climate in self.climates:
            if self.aconfig.get(climate, {}).get("auto_off_hours") != None:
                return True
        return False

    def autooff_scheduled_cb(self, kwargs):
        """
        Turn off any thermostats that have been on too long.
        """
        for climate, state in self.climate_state.items():
            self.hass.debug(f'autooff: {climate} - {state["state"]}')

            config = self.aconfig.get(climate)
            if not config:
                continue
            if not "auto_off_hours" in config:
                continue
            if state["state"] == "off":
                continue
            if state["offline"]:
                continue  # Can't do anything
            if state["state"] == "error_off" and self.turn_on_error_off:
                # Off but should not be
                self.hass.log(
                    f"{climate} is off but should not be! Attempting to turn on."
                )
                if not self.test_mode:
                    self.hass.call_service("climate/turn_on", entity_id=climate)
                self.hass.lb_log(f"{climate} - Turned thermostat on.")

            hours_unoccupied = self.climate_state[climate]["unoccupied"]

            if hours_unoccupied is None:
                self.hass.warn(
                    f"Programming error - hours_unoccupied None for {climate}"
                )
            elif hours_unoccupied < 0:
                self.hass.warn(
                    f"Programming error - Negative duration off for {climate}: {hours_unoccupied}"
                )
            elif hours_unoccupied == 0:
                # Currently off
                pass
            elif hours_unoccupied > config["auto_off_hours"] or self.test_mode:
                # Maybe turn off?

                # First check to see if someone turned it on since last off.
                laston_sensor = Laston.laston_sensor_name_static(self.appname, climate)
                laston_date = self.hass.get_state(laston_sensor)
                if self.hours_since_laston(laston_date) < hours_unoccupied:
                    self.hass.log(
                        f"Autooff - NOT turning off {climate}. hours_unoccupied: {hours_unoccupied}. But last turned on: {laston_date}"
                    )
                    continue

                # Turn off
                self.hass.lb_log(f"Autooff - Turning off {climate}")
                if not self.test_mode:
                    self.turn_off_climate(climate)

    def hours_since_laston(self, laston_date: Union[str, dt.datetime]) -> float:
        if isinstance(laston_date, str):
            laston_date = dt.datetime.fromisoformat(laston_date)
        now = self.hass.get_now()
        return (now - laston_date).seconds / (60 * 60)  # type: ignore
