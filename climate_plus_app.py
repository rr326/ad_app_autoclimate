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


class ClimatePlus(adplus.MqPlus):
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

    OFF_RULES_SCHEMA = {"required": True, "type": "dict", "valuesrules": OFF_SCHEMA}

    def initialize(self):
        self.log("Initialize")
        self.namespace = self.args.get("namespace", "autoclimate")

        self.register_service("climate/turn_off_entity", self.cb_turn_off_entity)
        self.register_service("climate/turn_off_all", self.cb_turn_off_all)

        # self.test_services()
        # self.register_service('climate_plus/turn_off_entity', cb_turn_off_entity)
        # self.register_service('climate_plus/turn_off_all', cb_turn_off_all)

    def cb_turn_off_entity(self, namespace, domain, service, kwargs):
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

    def cb_turn_off_all(self, namespace, domain, service, kwargs):
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
                namespace,
                domain,
                service,
                kwargs={
                    "entity": entity,
                    "config": config.get(entity, {}),
                    "test_mode": test_mode,
                },
            )

    #
    # Weird - can't use namespace = "default"
    #
    def test_services(self):
        self.register_service(
            "climate_plus/test_call_service",
            self.cb_test_call_service,
            namespace=self.namespace,
        )
        self.call_service(
            "climate_plus/test_call_service",
            kwarg1="val1",
            kwarg2="val2",
            namespace=self.namespace,
        )

    def cb_test_call_service(self, namespace, domain, service, kwargs):
        self.log(
            f"test_call_service - {namespace} -- {domain} -- {service} -- {kwargs}"
        )
