SCHEMA = {
    "name": {"required": True, "type": "string"},
    "poll_frequency": {"required": True, "type": "number"},
    "test_mode": {"required": False, "type": "boolean", "default": False},
    "run_mocks": {"required": False, "type": "boolean", "default": False},
    "create_temp_sensors": {"required": True, "type": "boolean"},
    "turn_on_error_off": {"required": False, "type": "boolean", "default": True},
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
                "auto_off_hours": {"type": "number", "required": False},
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
