import datetime as dt
import json  # noqa
import math
from typing import Tuple

import adplus

adplus.importlib.reload(adplus)

SCHEMA = {
    "name": {"required": True, "type": "string"},
    "poll_frequency": {"required": True, "type": "number"},
    "test_mode": {"required": False, "type": "boolean", "default": False},
    "create_temp_sensors": {"required": True, "type": "boolean"},
    "off_rules": {
        "required": True,
        "type": "dict",
        "valuesrules": {
            "type": "dict",
            "schema": {
                "off_state": {
                    "type": "string",
                    "required": True,
                    "allowed": ["away", "off", "perm_hold"],
                },
                "off_temp": {"type": "number", "required": False},
                "perm_hold_string": {"type": "string", "required": False},
            },
        },
    },
    "auto_off": {
        "required": False,
        "type": "dict",
        "valuesrules": {
            "type": "dict",
            "schema": {
                "occupancy_sensor": {"type": "string", "required": True},
                "unoccupied_for": {"type": "number", "required": True},
            },
        },
    },
    "mocks": {
        "required": False,
        "type": "list",
        "schema": {
            "type": "dict",
            "required": True,
            "schema": {
                "entity_id": {"required": True, "type": "string"},
                "mock_attributes": {"required": True, "type": "dict"},
            },
        },
    },
}


class AutoClimateApp(adplus.MqPlus):
    """
    # AutoClimateApp
    This provides serveral services for thermostat management.

    See README.md for documentation.
    See autoclimate.yaml.sample for sample configuration.
    """

    def initialize(self):
        self.log("Initialize")

        self.argsn = adplus.normalized_args(self, SCHEMA, self.args, debug=False)
        self.extra_validation(self.argsn)
        self.test_mode = self.argsn.get("test_mode")
        self.appname = self.argsn["name"]
        self.poll_frequency = self.argsn["poll_frequency"]
        self.create_temp_sensors = self.argsn["create_temp_sensors"]
        self.mock_data = None
        self.state = {}
        self._current_temps = {}  # {climate: current_temp}
        self.APP_STATE = f"app.{self.appname}_state"
        self.TRIGGER_HEAT_OFF = f"app.{self.appname}_turn_off_all"

        self.climates = list(self.argsn["off_rules"].keys())
        self.log(f"Climates controlled: {self.climates}")

        self.init_create_states()
        self.init_states()

        self.mq_listen_event(self.turn_off_all, self.TRIGGER_HEAT_OFF)

        #
        # get_and_publish_state:
        #  - Initialize
        #  - Listen to changes
        #  - Poll hourly (via autooff)
        self.run_in(self.get_and_publish_state, 0)
        self.run_in(self.init_climate_listeners, 0)

        # Auto off - every hour
        # This will also get_and_publish_state
        self.run_every(self.autooff_scheduled_cb, "now", 60 * 60 * self.poll_frequency)

        # Mocks
        if self.test_mode:
            self.run_in(self.init_mocks, 0)

    def extra_validation(self, args):
        # Validation that Cerberus doesn't do well
        for climate, rule in args["off_rules"].items():
            if rule.get("off_state", "") == "perm_hold":
                if "off_temp" not in rule:
                    self.error(f'Invalid rule. Perm_hold needs an "off_temp": {rule}')
                if "perm_hold_string" not in rule:
                    self.error(
                        f'Invalid rule. Perm_hold needs an "perm_hold_string": {rule}'
                    )

            state = self.get_state(climate, attribute="all")
            if state == None:
                self.error(
                    f"Probable misconfiguration (bad entity): could not get state for entity: {climate}"
                )

    def init_create_states(self):
        # APP_STATE
        self.set_state(
            self.APP_STATE,
            state="None",
            attributes={"friendly_name": f"{self.appname} State"},
        )

        # Temperature Sensors
        if self.create_temp_sensors:
            for climate in self.climates:
                sensor_name = self.sensor_name(climate)
                self.update_state(
                    sensor_name,
                    state=math.nan,
                    attributes={
                        "unit_of_measurement": "°F",
                        "freindly_name": f"Temperatue for {self.climate_name(climate)}",
                        "device_class": "temperature",
                    },
                )
                self.log(f"Created sensor for {sensor_name}")

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
            self.listen_state(
                self.get_and_publish_state, entity=climate, attribute="all"
            )

    @staticmethod
    def climate_name(entity):
        return entity.split(".")[1]

    def sensor_name(self, entity):
        return f"sensor.{self.appname}_{self.climate_name(entity)}_temperature"

    def publish_state(
        self,
    ):
        """
        This publishes the current state, as flat attributes,
        to APP_STATE (eg: app.autoclimate_state)
        """

        data = {
            f"{self.climate_name(entity)}_{key}": value
            for (entity, rec) in self.state.items()
            for (key, value) in rec.items()
        }
        # app.autoclimate_state ==> autoclimate_state
        data["summary_state"] = self.autoclimate_overall_state

        self.update_state(
            self.APP_STATE, state=self.autoclimate_overall_state, attributes=data
        )

        if self.create_temp_sensors:
            for climate, current_temp in self._current_temps.items():
                sensor_name = self.sensor_name(climate)
                self.update_state(sensor_name, state=current_temp)

        # self.log(
        #     f"DEBUG LOGGING\nPublished State\n============\n{json.dumps(data, indent=2)}"
        # )

    def get_and_publish_state(self, *args, **kwargs):
        self.get_all_entities_state()  # Update state copy

        self.publish_state()

    def get_entity_state(self, entity) -> Tuple[str, str, float]:
        """
        Returns: on/off/offline, reason

        if self.test_mode it will merge self.mocked_attributes to the state
        """

        state = self.get_state(entity, attribute="all")
        attributes = state["attributes"] if state else {}

        if self.test_mode and self.mock_data:
            if self.mock_data.get("entity_id") == entity:
                mock_attributes = self.mock_data["mock_attributes"]
                self.log(
                    f"get_entity_state: using MOCKED attributes for entity {entity}: {mock_attributes}"
                )
                attributes = attributes.copy()
                attributes.update(mock_attributes)

        # Get current temperature
        current_temp = attributes.get("current_temperature", math.nan)

        #
        # Offline?
        #
        if "temperature" not in attributes:
            return "offline", "offline", current_temp

        #
        # Heat is on?
        #
        temp = attributes.get("temperature")
        off_rule = self.argsn["off_rules"][entity]

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
                    f"Not permanent hold: {attributes.get, current_temp('preset_mode')}",
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

    def get_all_entities_state(self, *args):
        """
        temp
            * value = valid setpoint
            * not found: offline
            * None = system is off
        """
        for entity in self.climates:
            summarized_state, state_reason, current_temp = self.get_entity_state(entity)

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
                    state, duration_off, last_on_date = self.get_unoccupied_time_for(
                        entity
                    )
                    if state == "on":
                        self.state[entity]["unoccupied"] = False
                    else:
                        self.state[entity]["unoccupied"] = duration_off
                except Exception as err:
                    self.error(f"Error getting occupancy for {entity}. Err: {err}")

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
            self.log(f"Unexpected overall state found: {substates}")
            return "programming_error"

    def turn_off_entity(self, entity):
        state = self.get_state(entity, attribute="all")
        attributes = state["attributes"]
        off_rule = self.argsn["off_rules"].get(entity)

        if "temperature" not in attributes:
            self.log(f"{entity} - Offline. Can not turn off.")
            return

        if not off_rule:
            self.error(f"No off_rule for entity: {entity}. Can not turn off.")
            return

        if off_rule["off_state"] == "off":
            retval = self.call_service("climate/turn_off", entity_id=entity)
            self.lb_log(f"{entity} - Turn off. retval: {retval}")
        elif off_rule["off_state"] == "away":
            retval = self.call_service(
                "climate/set_preset_mode",
                entity_id=entity,
                preset_mode="Away",
            )
            self.lb_log(f"{entity} -  Set away mode. retval: {retval}")
        elif off_rule["off_state"] == "perm_hold":
            retval1 = self.call_service(
                "climate/set_temperature",
                entity_id=entity,
                temperature=off_rule["off_temp"],
            )

            retval2 = self.call_service(
                "climate/set_preset_mode",
                entity_id=entity,
                preset_mode="Permanent Hold",
            )
            self.log(
                f"{entity} - Set Perm Hold to {off_rule['off_temp']}. retval1: {retval1} -- retval2: {retval2}"
            )
        else:
            self.error(f"Programming error. Unexpected off_rule: {off_rule}")

    def turn_off_all(self, event_name, data, kwargs):
        self.log(
            f"Triggered - {self.TRIGGER_HEAT_OFF}: {event_name} -- {data} -- {kwargs}"
        )
        self.lb_log("Turn heat off triggered")
        if self.test_mode:
            self.log("Test mode - not actually turning off heat. ")
            return

        for entity in self.climates:
            self.turn_off_entity(entity)

    def occupancy_length(self, entity_id, days=10):
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
        hass = self.get_plugin_api("HASS")
        data = hass.get_history(entity_id=entity_id, days=days)

        if len(data) == 0:
            self.warn(f"get_history returned no data for entity: {entity_id}. Exiting")
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
                now = self.get_now()
                duration_off_hours = round(
                    (now - last_on_date).total_seconds() / (60 * 60), 2
                )
                return "off", duration_off_hours, last_on_date

        # Can not find a last on time. Give the total time shown.
        min_time_off = round(
            (
                self.get_now() - dt.datetime.fromisoformat(edata[-1]["last_updated"])
            ).seconds
            / (60 * 60),
            2,
        )
        return "off", min_time_off, None

    def get_unoccupied_time_for(self, entity):
        try:
            oc_sensor = self.argsn["auto_off"][entity]["occupancy_sensor"]
        except KeyError:
            self.error(f"Unable to get occupancy_sensor for {entity}")
            return None, None, None

        state, duration_off, last_on_date = self.occupancy_length(oc_sensor)
        return state, duration_off, last_on_date

    def autooff_scheduled_cb(self, kwargs):
        """
        Turn off any thermostats that have been on too long.
        """
        autooff_config = self.argsn.get("auto_off", {})
        self.get_and_publish_state()
        for entity, state in self.state.items():
            self.debug(f'autooff: {entity} - {state["state"]}')

            config = autooff_config.get(entity)
            if not config:
                self.log(f"autooff: No config. skipping {entity}")
                continue
            if state["state"] == "off":
                continue
            if state["offline"]:
                continue  # Can't do anything
            if state["state"] == "error_off":
                # Off but should not be
                self.log(f"{entity} is off but should not be! Attempting to turn on.")
                if not self.test_mode:
                    self.call_service("climate/turn_on", entity_id=entity)
                self.lb_log(f"{entity} - Turned thermostat on.")

            oc_state, duration_off, last_on_date = self.get_unoccupied_time_for(entity)
            if oc_state != state["state"] and not self.test_mode:
                self.warn(
                    f'Programming error - oc_state ({oc_state}) != state ({state["state"]}) for {entity}'
                )
            if duration_off is None:
                self.warn(f"Programming error - duration_off None for {entity}")
            elif duration_off > config["unoccupied_for"] or self.test_mode:
                self.lb_log(f"Autooff - Turning off {entity}")
                if not self.test_mode:
                    self.turn_off_entity(entity)

    def init_mocks(self, kwargs):
        if self.test_mode:
            mock_delay = 0
            for mock in self.argsn.get("mocks", []):
                self.run_in(
                    self.run_mock, mock_delay := mock_delay + 1, mock_config=mock
                )

    def run_mock(self, kwargs):
        config = kwargs["mock_config"]
        self.log(f"\n\n==========\nMOCK: {config}")
        self.mock_data = config
        self.run_in(self.autooff_scheduled_cb, 0)
