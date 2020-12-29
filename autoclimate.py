import datetime as dt
import json  # noqa
import math
from typing import Optional, Tuple

import adplus
from adplus import Hass

adplus.importlib.reload(adplus)
from _autoclimate.unoccupied import get_unoccupied_time_for
import _autoclimate.turn_off as turn_off
from _autoclimate.mocks import Mocks
from _autoclimate.state import State
import _autoclimate
import _autoclimate.state
import _autoclimate.mocks

adplus.importlib.reload(_autoclimate)
adplus.importlib.reload(_autoclimate.state)
adplus.importlib.reload(_autoclimate.mocks)


SCHEMA = {
    "name": {"required": True, "type": "string"},
    "poll_frequency": {"required": True, "type": "number"},
    "test_mode": {"required": False, "type": "boolean", "default": False},
    "create_temp_sensors": {"required": True, "type": "boolean"},
    "entity_rules": {
        "required": True,
        "type": "dict",
        "valuesrules": {
            "type": "dict",
            "required": True,
            "schema": {
                "off_state": {
                    "type": "dict",
                    "required": True,
                    "schema": {
                        "state": {
                            "type": "string",
                            "required": True,
                            "allowed": ["away", "off", "perm_hold"],
                        },
                        "temp": {"type": "number", "required": False},
                        "perm_hold_string": {"type": "string", "required": False},
                    },
                },
                "occupancy_sensor": {"type": "string", "required": True},
                "auto_off_hours": {"type": "number", "required": True},
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


class AutoClimate(adplus.Hass):
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
        self.entity_rules = self.argsn["entity_rules"]
        self.extra_validation(self.argsn)
        self.test_mode = self.argsn.get("test_mode")
        self.appname = self.argsn["name"]
        self.poll_frequency = self.argsn["poll_frequency"]

        self.TRIGGER_HEAT_OFF = f"app.{self.appname}_turn_off_all"

        self.climates = list(self.entity_rules.keys())
        self.log(f"Climates controlled: {self.climates}")

        #
        # Initialize sub-classes
        #
        self.state_module = State(
            hass=self,
            config=self.entity_rules,
            poll_frequency=self.argsn["poll_frequency"],
            appname=self.appname,
            climates=self.climates,
            create_temp_sensors=self.argsn["create_temp_sensors"],
            test_mode=self.test_mode,
        )

        self.mock_module = Mocks(
            hass=self,
            mock_config=self.argsn["mocks"],
            test_mode=self.test_mode,
            mock_callbacks=[self.autooff_scheduled_cb],
            init_delay=1,
            mock_delay=1,
        )

        # Initialize
        turn_off.init_listeners(self, self.appname)
        return

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
        for climate, rule in self.entity_rules.items():
            offrule = rule.get("off_state", {})
            if offrule.get("state", "") == "perm_hold":
                if "temp" not in offrule:
                    self.error(f'Invalid offrule. Perm_hold needs an "temp": {offrule}')
                if "perm_hold_string" not in offrule:
                    self.error(
                        f'Invalid offrule. Perm_hold needs an "perm_hold_string": {offrule}'
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
        self.state_module.get_and_publish_state()
        for entity, state in self.state_module.state.items():
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
