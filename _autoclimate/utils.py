def climate_name(entity):
    # climate.my_thermostat ==> my_thermostat
    return entity.split(".")[1]
