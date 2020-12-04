# keymaster
Home Assistant Zwave keymaster package

**N.B.**  After you add your devices (Zwave lock, door sensor) to your Z-Wvave network via the inlusion mode, use the Home Assistant Entity Registry and rename each entity that belongs to the device and append `_LOCKNAME` to it.  For example, if you are calling your lock `FrontDoor`, you will want to append _FrontDoor to each entity of the device.

`sensor.schlage_allegion_be469_touchscreen_deadbolt_alarm_level` 
would become 
`sensor.schlage_allegion_be469_touchscreen_deadbolt_alarm_level_frontdoor`

Do this step as well for your door sensor, if you have one.

This will automaticly generate the keymaster files just as the `setup.sh` script would have.
