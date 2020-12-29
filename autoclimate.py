import datetime as dt
import json  # noqa
import math
from typing import Optional, Tuple

import adplus
from adplus import Hass

adplus.importlib.reload(adplus)
from autoclimate.unoccupied import get_unoccupied_time_for
from autoclimate.utils import climate_name, offstate
import autoclimate.turn_off as turn_off
from autoclimate.mocks import Mocks

adplus.importlib.reload(turn_off)


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


class AutoClimateApp(adplus.Hass):
    """
    # AutoClimateApp
    This provides serveral services for thermostat management.

    See README.md for documentation.
    See autoclimate.yaml.sample for sample configuration.

    ## Events
    Events have TWO names:
    event = "autoclimate" for ALL events
    sub_event = app.{appname}_event - this is the event you actually care about

    Why? To trigger an event in Lovelace, you need to trigger a script, where you
    have to hardcode the event name, but can send template data in the body. So
    rather than have to write different scripts for each event, here you create
    *one* script to trigger the event and put the event you care about in a
    sub_event kwarg.
    """

    EVENT_TRIGGER = "autoclimate"

    def initialize(self):
        self.log("Initialize")

        self.argsn = adplus.normalized_args(self, SCHEMA, self.args, debug=False)
        self.extra_validation(self.argsn)
        self.test_mode = self.argsn.get("test_mode")
        self.appname = self.argsn["name"]
        self.poll_frequency = self.argsn["poll_frequency"]
        self.create_temp_sensors = self.argsn["create_temp_sensors"]
        self.state = {}
        self._current_temps = {}  # {climate: current_temp}
        self.APP_STATE = f"app.{self.appname}_state"
        self.TRIGGER_HEAT_OFF = f"app.{self.appname}_turn_off_all"

        self.climates = list(self.argsn["off_rules"].keys())
        self.log(f"Climates controlled: {self.climates}")

        #
        # Initialize sub-classes
        #
        self.mocks = Mocks(
            mock_config=self.argsn["mocks"],
            test_mode=self.test_mode,
            mock_callbacks=[self.autooff_scheduled_cb],
            init_delay=1,
            mock_delay=1,
        )

        # Initialize
        turn_off.init_listeners(self, self.appname)

        self.init_create_states()
        self.init_states()

        # ROSS REMOVE ALL MQ
        # self.mq_listen_event(self.turn_off_all, self.TRIGGER_HEAT_OFF)

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

    def trigger_sub_events(self):
        pass

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
                        "freindly_name": f"Temperatue for {climate_name(climate)}",
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
        mock_data = kwargs.get("mock_data")
        self.get_all_entities_state(mock_data=mock_data)  # Update state copy

        self.publish_state()

    def get_entity_state(
        self, entity: str, mock_data: Optional[dict] = None
    ) -> Tuple[str, str, float]:
        state_obj: dict = self.get_state(entity, attribute="all")  # type: ignore
        return offstate(
            entity,
            state_obj,
            self.argsn["off_rules"][entity],
            self,
            self.test_mode,
            mock_data,
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

    def get_unoccupied_time_for(
        self, entity
    ) -> Tuple[Optional[str], Optional[float], Optional[dt.datetime]]:
        try:
            config = self.argsn["auto_off"][entity]
        except KeyError:
            self.error(f"Unable to get config for {entity}")
            return None, None, None

        hassapi: Hass = self.get_plugin_api("HASS")  # type: ignore
        return get_unoccupied_time_for(entity, config, hassapi)

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
                    self.fire_event(turn_off.EVENT_TURN_OFF_ENTITY, entity=entity)
