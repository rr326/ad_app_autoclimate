# Issues

## 0. Restructure
Restructure Autoclimate from a single configurable app into a series of services AND a configureable app. This wasy you can use ClimatePlus in any HomeAssistant automation. Probably needs to use MQTT for signaling. 

### Calling method
How to enable these services?

* MQTT - easiest for me - already done
* services/xxx - ideal, but doesn't work!
* state? 
* event? 
### Services
1. turn_off(entity, off_config)
2. turn_off_all()
3. publish_state()
4. create_temp_sensors()
5. publish_unoccupied_for()
6. auto_off_app()

## 0.5 New app: Entity Color
I *really* don't like my dashboard. Part is HA's fault. If I did my JinjaPlus idea it would make it better.

But I'd prefer to have all my "business logic" configuration with my app, not hidden in the dashboard. I'd like to define my states here, and then have the dashboard dumbly reference it. As I think about it, probably the easiest is a python file. So the config isnt' listed with the rest of my config, but that's ok. 

## 1. Autooff - reset when manual override
This is like LightFade - if someone hits the swithc when it is within the fade period, cancel the fade.

Here, if I'm away and I set the Ecobee to Home, I don't want it to automatically turn it off again!

### How?
* Track "state" of a climate - excluding offline
    * climate.cabin.current_setting = away_55
    * climate_gaym.current_setting = off
    * climate.master_bath.current_setting = perm_hold_41
* PERMANENT track last current_setting change
    * Separte file? autoclimate.json
    * History database?
* Unoccupied time gets reset whenever current_setting changes
    * unoccupied_time = now - max(last_occupied, last_setting_change)
* ??: Do I need to make this configurable? Why wouldn't you use this?
* ??: How do I *expose* this info so it's clear to the user what is going on and why?
* ??: Is this sufficient? Can I do it automatically, or do I need to make it *signaled* 
  like `mqtt.climate_cabin_setting_changed`. The good thing is the is *explicit*. The bad thing is you always need to use a custom button / code to change the thermostat. Can't just use the Ecobee. That seems bad. It feels like this should be avoided, but I keep feeling like if I try to do it automatically it will run into some problems, like my dimmer double tap did.
* ??: Should this be tied to my home state? For instance, home_state=(home, away, leaving, **get_ready**). Maybe a *guard* for different auto-off rules? This feels unnecessary and complicated. 


## 3. error_off / auto-on
Right now now I have an embedded rule that states: "{entity} is off but should not be! Attempting to turn on."

This should be exposed and configurable.

## 4. Clean up
This is a big, complex file. I need to split up.

## 5. Auto-away mode?
I should probably set HomeState to away automatically. Probably a different logic.





# AutoClimateApp for AppDaemon
This provides several services for thermostat management.

The key goals are to enable:

* Monitoring multiple thermostats to see if on, off, or offline
* 1 button click to turn off multiple thermostats
* Automatically "turn off" thermostats if unoccupied for some amount of time. 
* ("turn off" could be setting to Away mode, setting a low permanent hold temp, or even turning off completely.)

(This is an [Appdaemon](https://appdaemon.readthedocs.io/en/latest/) application that works with [Home Assistant](https://www.home-assistant.io/) home automation.)

## Sample Use Case
I have a cabin that has a main thermostat (ecobee), one in an unheated garage shop, and a Nuheat floor heater. I want to be sure that we don't accidentally leave the heat on and either cost us a ton of money (heating an uninsulated garage in the dead of winter) or even burn up our whole tank of propane. 

With this, I press one button to turn it all off when I leave. If I forget, after a configurable amount of time it will turn things off properly. For the house, that is setting the ecobee to "Away". For the garage, it is turning it completely off. For the floor heater, which does not have an "Away" mode, it is setting a "permanent hold" to 41 degrees - the lowest it accepts.

Finally, this also enables cool dashboard monitoring (with [Lovelace](https://www.home-assistant.io/lovelace/)) that shows the temperature, if it is "offline" and a color for red (bad), yellow (warning), or green (good).

### Sample Dashboard
![Dashboard](dashboard.png)

This uses [custom-button-card](https://github.com/custom-cards/button-card), [card-mod](https://github.com/thomasloven/lovelace-card-mod), and my forked version of bignumber - [bignumber-fork](https://github.com/rr326/bignumber-card).
## Features

1. **Summarized State**  
(Eg: app.autoclimate_state)  
This listens for changes to watched thermostat climate entities and creates a master state. See "Exposed State" below.
2. **Polling**  
Although listening for climate enitity changes should be enough, it also polls regularly (every {poll_frequency} hours) just in case.
3. **app: auto_off**  
This will turn off climates when unoccupied for X time. "Off" could be "Away" mode, a preset temperature, or literally off.
4. **Turn Heat Off MQ Event**  
You can register an MQ event (such as `app.autoclimate_turn_off_all`)
and when it is triggered, the app will set all climates to their "off" state.
5. **Extra Temp Sensors**  
    * If you set `create_temp_sensors: true`, this will create a new temp sensor for each climate with a name like `sensor.autoclimate_house_temperature`. This is the same as normal temperature sensors except if the `climate` is offline, this sensor will report a null value.
    * The existing sensors defined by the integrations will always show the last value, even if the sensor has been down for a week! [Github Issue](https://github.com/home-assistant/core/issues/43897)
6. **Test_mode with Mocks**  
(This is for advanced users and developers.)  
When you set `test_mode: true`, it will run the automation and print to teh log, but not actually take the actions (like turning off the thermostat.) If you set mocks (see `autoclimate.yaml.sample`), it will set each entity to the given state, wait a second, and then run the next mock.


## Requirements

1. [AdPlus](https://github.com/rr326/adplus)
2. [MQTT](https://www.home-assistant.io/integrations/mqtt/) - Installed, working, integrated to Appdaemon, and tested. Only required if you want the abilty to trigger the all_off() functionality by sending an evetn to `app.autoclimate_turn_off_all`.
## Configuration
See [autoclimate.yaml.sample](./autoclimate.yaml.sample)

## Exposed State
The app will expose a helpful state object under: `app.{name}_state` where
name is defined in `autoclimate.yaml`. (For instance: `app.autoclimate_state`.)

Here is an example:
```yaml
# app.autoclimate_state, in yaml
friendly_name: autoclimate State
summary_state: offline
ecobee1_offline: false
ecobee1_state: 'off'
ecobee1_unoccupied: 2.62
ecobee1_state_reason: 'Away mode at proper temp: 55'
nuheat1_offline: true
nuheat1_state: offline
nuheat1_unoccupied: offline
ecobee2_offline: false
ecobee2_state: 'off'
ecobee2_unoccupied: 2.62
ecobee2_state_reason: Thermostat is off
```

### Details
|field|type|values|explanation|
|-|-|-|-|
|friendly_name|string|{name} State|
|summary_state|string|on \| off \| offline \| error| Summarized state across all entities
|entity_offline|boolean|true \| false|
|entity_state|string|on \| off \| offline \| error | Summarized state for this entity
|entity_state_reason|string|*explanation*|Explanation of why. Helpful for debugging.
|entity_unoccupied|float|*duration*|How long the autooff sensor has shown unoccupied.

## MQ Events
    listens:
        app.{name}_turn_off_all
        ("name" from autoclimate.yaml "name")
    fires:
        None

## Extra Temp Sensors
See the description above in Features. 
A few sub points:

* The sensor name is: `sensor.{config.name}_{climate_entity_name}_temperature`
* Return value when offline: `math.nan`
* [Github Issue](https://github.com/home-assistant/core/issues/43897)

## Integrations
This has been tested with:
* Ecobee
* Nuheat
