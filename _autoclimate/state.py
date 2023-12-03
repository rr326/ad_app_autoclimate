import json  # noqa
import math
from typing import Optional, Tuple

import adplus
from adplus import Hass

adplus.importlib.reload(adplus)
from _autoclimate.occupancy import Occupancy
from _autoclimate.utils import climate_name, in_inactive_period


class State:
    def __init__(
        self,
        hass: Hass,
        config: dict,
        poll_frequency: int,
        appname: str,
        climates: list,
        create_temp_sensors: bool,
        test_mode: bool,
        inactive_period: Optional[str]
    ):
        self.hass = hass
        self.aconfig = config
        self.poll_frequency = poll_frequency
        self.appname = appname
        self.app_state_name = f"app.{self.appname}_state"
        self.test_mode = test_mode
        self.use_temp_sensors = create_temp_sensors
        self.climates = climates
        self.inactive_period = inactive_period

        self.state: dict = {}
        self._current_temps: dict = {}  # {climate: current_temp}

        self.init_states()

        self.hass.run_in(self.create_hass_stateobj, 0)
        if self.use_temp_sensors:
            self.hass.run_in(self.create_temp_sensors, 0)
        self.hass.run_in(self.init_climate_listeners, 0)

        self.hass.run_every(
            self.get_and_publish_state, "now", 60 * 60 * self.poll_frequency
        )

        self.hass.run_in(self.register_services, 0)

    def create_hass_stateobj(self, kwargs):
        # APP_STATE
        self.hass.update_state(
            self.app_state_name,
            attributes={"friendly_name": f"{self.appname} State"},
        )

    def create_temp_sensors(self, kwargs):
        # Temperature Sensors
        for climate in self.climates:
            sensor_name = self.sensor_name(climate)
            self.hass.update_state(
                sensor_name,
                attributes={
                    "unit_of_measurement": "°F",
                    "freindly_name": f"Temperatue for {climate_name(climate)}",
                    "device_class": "temperature",
                },
            )
            self.hass.log(f"Created sensor for {sensor_name}")

    def init_states(self):
        for climate in self.climates:
            self.state[climate] = {
                "offline": None,
                "state": None,
                "unoccupied": None,
                "state_reason": None,
            }

    def init_climate_listeners(self, kwargs):
        for climate in self.climates:
            self.hass.listen_state(
                self.get_and_publish_state, entity_id=climate, attribute="all"
            )

    def sensor_name(self, entity):
        return f"sensor.{self.appname}_{climate_name(entity)}_temperature"

    def publish_state(
        self,
    ):
        """
        This publishes the current state, as flat attributes,
        to APP_STATE (eg: app.autoclimate_state)
        """

        data = {
            f"{climate_name(entity)}_{key}": value
            for (entity, rec) in self.state.items()
            for (key, value) in rec.items()
        }
        # app.autoclimate_state ==> autoclimate_state
        data["summary_state"] = self.autoclimate_overall_state

        self.hass.update_state(
            self.app_state_name, state=self.autoclimate_overall_state, attributes=data
        )

        if self.use_temp_sensors:
            for climate, current_temp in self._current_temps.items():
                sensor_name = self.sensor_name(climate)
                self.hass.update_state(sensor_name, state=(current_temp if not math.isnan(current_temp) else None))

        # self.log(
        #     f"DEBUG LOGGING\nPublished State\n============\n{json.dumps(data, indent=2)}"
        # )

    def get_and_publish_state(self, *args, **kwargs):
        mock_data = kwargs.get("mock_data")
        self.get_all_entities_state(mock_data=mock_data)  # Update state copy

        self.publish_state()

    def get_entity_state(
        self, entity: str, mock_data: Optional[dict] = None
    ) -> Tuple[str, str, float]:
        state_obj: dict = self.hass.get_state(entity, attribute="all")  # type: ignore
        return self.offstate(
            entity,
            state_obj,
            self.aconfig[entity],
            self.hass,
            self.test_mode,
            mock_data,
            self.inactive_period
        )

    def get_all_entities_state(self, *args, mock_data: Optional[dict] = None):
        """
        temp
            * value = valid setpoint
            * not found: offline
            * None = system is off
        """
        for entity in self.climates:
            summarized_state, state_reason, current_temp = self.get_entity_state(
                entity, mock_data
            )

            #
            # Current_temp
            #
            self._current_temps[entity] = current_temp

            #
            # Offline
            #
            if summarized_state == "offline":
                self.state[entity] = {
                    "offline": True,
                    "state": "offline",
                    "unoccupied": "offline",
                }
                continue
            else:
                self.state[entity]["offline"] = False

            #
            # State
            #
            self.state[entity]["state"] = summarized_state
            self.state[entity]["state_reason"] = state_reason

            #
            # Occupancy
            #
            if not self.state[entity]["offline"]:
                try:
                    last_on_date = self.hass.get_state(
                        Occupancy.unoccupied_sensor_name_static(self.appname, entity)
                    )
                    if last_on_date == Occupancy.UNOCCUPIED_SINCE_OCCUPIED_VALUE:
                        self.state[entity]["unoccupied"] = False
                    elif last_on_date in [None, "off"]:
                        self.state[entity]["unoccupied"] = None
                    else:
                        self.state[entity][
                            "unoccupied"
                        ] = Occupancy.duration_off_static(self.hass, last_on_date)
                except Exception as err:
                    self.hass.error(
                        f"Error getting occupancy for {entity}. Err: {err}."
                    )

    @property
    def autoclimate_overall_state(self):
        """
        Overall state:
            * on - any on
            * offline - not on and any offline
            * error - any "error_off" - meaning any are off but should not be
            * off - all properly off, confirmed.
        """
        substates = {entity["state"] for entity in self.state.values()}
        if "on" in substates:
            return "on"
        elif "offline" in substates:
            return "offline"
        elif "error_off" in substates:
            return "error"
        elif {"off"} == substates:
            return "off"
        else:
            self.hass.log(f"Unexpected overall state found: {substates}")
            return "programming_error"

    @staticmethod
    def offstate(
        entity: str,
        stateobj: dict,
        config: dict,
        hass: Hass,
        test_mode: bool = False,
        mock_data: Optional[dict] = None,
        inactive_period: Optional[str] = None
    ) -> Tuple[str, str, float]:
        """
        Returns: on/off/offline, reason, current_temp

        if test_mode it will merge self.mocked_attributes to the state

        This tests to see if a climate entity's state is what it should be.
        The logic is pretty complex due to challenges with offline/online,
        priorities, differences in behavior from different thermostats, etc.
        """
        offconfig = config["off_state"]
        attributes = stateobj["attributes"] if stateobj else {}

        # Mocks
        if test_mode and mock_data:
            if mock_data.get("entity_id") == entity:
                mock_attributes = mock_data["mock_attributes"]
                hass.info(
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
            if offconfig["state"] == "off":
                return "off", "Thermostat is off", current_temp
            else:
                if not in_inactive_period(hass, inactive_period):
                    return "error_off", "Thermostat is off but should not be!", current_temp
                else:
                    return "off", "Thermostat is off in inactive_period", current_temp

        # Thermostat is on.
        elif offconfig["state"] == "off":
            return "on", "Thermostat is not off, but it should be", current_temp

        # Is away mode?
        elif offconfig["state"] == "away":
            if attributes.get("preset_mode").lower() != "away":
                return "on", "Not away mode, but should be", current_temp
            else:
                # Proper away mode setting?
                if (off_temp := offconfig.get("temp")) is None:
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
        elif offconfig["state"] == "perm_hold":
            if attributes.get("preset_mode") != offconfig["perm_hold_string"]:
                return (
                    "on",
                    f"Not proper permanent hold. Actual: {attributes.get('preset_mode')} -- {attributes.get('temperature')}",
                    current_temp,
                )
            elif temp > offconfig["temp"]:
                return (
                    "on",
                    f"Perm hold at {temp}. Should be <= {offconfig['temp']}",
                    current_temp,
                )
            else:
                return "off", f"Perm hold at {temp}", current_temp

        # Unexpected value
        return "none", "error - should not be here", current_temp

    def is_offline(self, namespace, domain, service, kwargs) -> bool:
        return self.state[kwargs["climate"]]["offline"]

    def is_on(self, namespace, domain, service, kwargs) -> bool:
        return self.state[kwargs["climate"]]["state"] == "on"

    def is_off(self, namespace, domain, service, kwargs) -> bool:
        return self.state[kwargs["climate"]]["state"] == "off"

    def entity_state(self, namespace, domain, service, kwargs) -> Optional[str]:
        self.hass.log(
            f">>DEBUG: entity_state: {kwargs['climate']} = {self.state[kwargs['climate']]['state']}"
        )
        return self.state[kwargs["climate"]]["state"]

    def is_hardoff(self, namespace, domain, service, kwargs) -> bool:
        state = self.hass.get_state(entity_id=kwargs["climate"])
        return state == "off"

    def is_error_off(self, namespace, domain, service, kwargs) -> bool:
        return self.state[kwargs["climate"]]["state"] == "error_off"

    def is_error(self, namespace, domain, service, kwargs) -> bool:
        return self.state[kwargs["climate"]]["state"] == "error"

    def register_services(self, kwargs: dict):
        callbacks = [
            self.is_offline,
            self.is_on,
            self.is_off,
            self.entity_state,
            self.is_hardoff,
            self.is_error_off,
            self.is_error,
        ]
        for callback in callbacks:
            service_name = f"{self.appname}/{callback.__name__}"
            self.hass.register_service(service_name, callback)
            self.hass.log(f"Registered service: {service_name}")
