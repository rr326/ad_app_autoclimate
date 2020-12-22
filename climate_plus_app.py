"""
This provides services for climate entitities.

It usses support functions in the climate_plus package.

It can be used by an app like AutoClimateApp.

### Services
1. turn_off_entity()
2. turn_off_all()
3. publish_state()
4. create_temp_sensors()
5. publish_unoccupied_for()
"""

import json  # noqa

import adplus
import climate_plus

adplus.importlib.reload(adplus)
adplus.importlib.reload(climate_plus)
from climate_plus import turn_off_entity


class ClimatePlus(adplus.Hass):
    OFF_SCHEMA = {
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
    }

    EVENT_TURN_OFF_ENTITY = 'climate_plus.turn_off_entity'
    EVENT_TURN_OFF_ALL= 'climate_plus.turn_off_all'


    OFF_RULES_SCHEMA = {"required": True, "type": "dict", "valuesrules": OFF_SCHEMA}

    def initialize(self):
        self.log("Initialize")
        self.namespace = self.args.get("namespace", "autoclimate")
        self.test_mode = self.args.get("test_mode", False)

        self.listen_event(self.cb_turn_off_entity, self.EVENT_TURN_OFF_ENTITY)
        self.listen_event(self.cb_turn_off_all, self.EVENT_TURN_OFF_ALL)


    def cb_turn_off_entity(self, event_name, data, kwargs):
        """
        kwargs:
            entity: climate_string
            config: OFF_SCHEMA (see above)
            test_mode: bool (optional)
        """
        entity = kwargs["entity"]
        config = adplus.normalized_args(self, self.OFF_SCHEMA, kwargs["config"])
        test_mode = kwargs.get("test_mode", False)

        stateobj: dict = self.get_state(entity, attribute="all")  # type: ignore

        return turn_off_entity(self, entity, stateobj, config, test_mode)

    def cb_turn_off_all(self, event_name, data, kwargs):
        """
        kwargs:
            entities: [climate_string]
            config: OFF_SCHEMA (see above)
            test_mode: bool (optional)
        """
        entities = kwargs["entity"]
        config = adplus.normalized_args(self, self.OFF_RULES_SCHEMA, kwargs["config"])
        test_mode = kwargs.get("test_mode", False)

        self.lb_log("Turn heat off triggered")
        if self.test_mode:
            self.log("Test mode - not actually turning off heat. ")
            return

        for entity in entities:
            self.cb_turn_off_entity(
                event_name,
                data,
                kwargs={
                    "entity": entity,
                    "config": config.get(entity, {}),
                    "test_mode": test_mode,
                },
            )

   