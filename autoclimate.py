import datetime as dt
import json  # noqa
import math
from typing import Optional, Tuple

import adplus
from adplus import Hass

adplus.importlib.reload(adplus)
from autoclimate.unoccupied import get_unoccupied_time_for
import autoclimate.turn_off as turn_off
from autoclimate.mocks import Mocks
from autoclimate.state import State

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
    "auto_off": { # Sync with State.CONFIG_SCHEMA
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

        self.TRIGGER_HEAT_OFF = f"app.{self.appname}_turn_off_all"

        self.climates = list(self.argsn["off_rules"].keys())
        self.log(f"Climates controlled: {self.climates}")

        #
        # Initialize sub-classes
        #
        self.state_module = State(
            config=self.argsn["off_rules"],
            appname = self.appname,
            climates=self.climates,
            create_temp_sensors=self.argsn["create_temp_sensors"],
            test_mode=self.test_mode,
        )

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
