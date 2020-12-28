from appdaemon.adapi import ADAPI
import adplus


#
# Config
#
EVENT_TURN_OFF_ENTITY = "turn_off_entity"
EVENT_TURN_OFF_ALL = "turn_off_all"

#
# Event names, given app name
#
def event_all_off_name(appname:str) -> str:
    return f"app.{appname}_turn_off_all"

def event_entity_off_name(appname:str) -> str:
    return f"app.{appname}_turn_off_entity"

#
# Low-level function
#
def turn_off_entity(
    adapi: adplus.Hass,
    entity: str,
    stateobj: dict,
    config: dict,
    test_mode: bool = False,
) -> None:
    """
    Turn "off" a climate entity, where "off" is defined by an off rule such as:
    climate.cabin:
        off_state: "away"
        off_temp:  55
    """

    attributes = stateobj["attributes"]

    if "temperature" not in attributes:
        adapi.log(f"{entity} - Offline. Can not turn off.")
        return

    if not config:
        adapi.error(f"No off_rule for entity: {entity}. Can not turn off.")
        return

    # Set to "off"
    if config["off_state"] == "off":
        retval = adapi.call_service("climate/turn_off", entity_id=entity)
        adapi.lb_log(f"{entity} - Turn off")

    # Set to "away"
    elif config["off_state"] == "away":
        retval = adapi.call_service(
            "climate/set_preset_mode",
            entity_id=entity,
            preset_mode="Away",
        )
        adapi.lb_log(f"{entity} -  Set away mode")

    # Set to "perm_hold"
    elif config["off_state"] == "perm_hold":
        retval1 = adapi.call_service(
            "climate/set_temperature",
            entity_id=entity,
            temperature=config["off_temp"],
        )

        retval2 = adapi.call_service(
            "climate/set_preset_mode",
            entity_id=entity,
            preset_mode="Permanent Hold",
        )
        adapi.log(
            f"{entity} - Set Perm Hold to {config['off_temp']}. retval1: {retval1} -- retval2: {retval2}"
        )

    # Invalid config
    else:
        adapi.error(f"Programming error. Unexpected off_rule: {config}")


#
# Init Listeners
#
def init_listeners(self: adplus.Hass, appname):
    self.listen_event(
        cb_turn_off_all, event=event_all_off_name(appname)
    )
    self.listen_event(
        cb_turn_off_entity, event=event_entity_off_name(appname)
    )


#
# Callbacks
#
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
