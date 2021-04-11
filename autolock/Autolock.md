### Auto Lock

While some locks have AutoLock built in (please disable them if you use this or your own automations), this implementation has more functionality.  If `input_boolean.autolock` is on, then your door will automatically lock itself after a defined period.  But there are times when you may not want this, such as if you're hosting a party.  Turn AutoLock off so it's not becoming a problem for everyone.  Note, this will automatically turn on after 4 hours, though this duration is easily changed.

#### autolock_lovelace.yml
This defines a simple UI for controlling and monitoring AutoLock.  When enabled, AutoLock will watch for frontdoor to be locked/unlocked.  When the door is unlocked a timer will be started via the script *start_frontdoor_custom_timer*.  If the time is after dusk, the timer duration is 5 minutes otherwise it's 15.  

### autolock_automations.yml
The code that lets AutoLock does its thing

### autolock_definitions.yml
Contains various entity definitions, timers, scripts
