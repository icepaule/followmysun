# boot.py - ESP12F (ESP8266) Solarpanel-Steuerung
import gc
import esp
import time
import machine

esp.osdebug(None)
# WiFi-Modem nicht zwischen Beacons schlafen lassen -> ARP/Inbound bleibt zuverlaessig.
# (Default ist SLEEP_MODEM=2; das laesst ARP-Requests waehrend Sleep-Intervallen fallen.)
try:
    esp.sleep_type(esp.SLEEP_NONE)
except Exception as e:
    print("sleep_type-Fehler:", e)

# AP-Interface ausschalten - kann sonst STA-ARP stoeren.
try:
    import network
    network.WLAN(network.AP_IF).active(False)
except Exception as e:
    print("AP_IF deakt. Fehler:", e)

gc.collect()

# Reset-Ursache loggen: zeigt nach einem naechtlichen Stall, welcher
# Reset-Typ greift (Knopf vs. Watchdog vs. Brownout vs. Software-Reset).
# - PWRON  = Stromschwankung / Kaltstart (Brownout-Verdacht)
# - HARD   = Reset-Knopf
# - WDT    = Hardware-Watchdog hat doch zugeschlagen (gut)
# - SOFT   = machine.reset() aus dem Code (Health-Watchdog)
def _name_reset_cause(rc):
    for nm in ("PWRON_RESET", "HARD_RESET", "WDT_RESET", "DEEPSLEEP_RESET", "SOFT_RESET"):
        v = getattr(machine, nm, None)
        if v is not None and v == rc:
            return nm.replace("_RESET", "")
    return "UNK({})".format(rc)

try:
    _rc = machine.reset_cause()
    _rc_name = _name_reset_cause(_rc)
    _heap = gc.mem_free()
    _line = "rc={} code={} heap={} t={}".format(_rc_name, _rc, _heap, time.ticks_ms())
    print("Boot reason:", _rc_name, "(code", _rc, "), heap free", _heap)

    # Ringpuffer: die letzten 10 Boots
    try:
        with open("last_boot.txt", "r") as _f:
            _old = [l for l in _f.read().splitlines() if l]
    except OSError:
        _old = []
    _old.append(_line)
    _old = _old[-10:]
    try:
        with open("last_boot.txt", "w") as _f:
            _f.write("\n".join(_old) + "\n")
    except Exception as _e:
        print("last_boot.txt schreiben Fehler:", _e)

    # Aktueller Boot fuer MQTT-Publish aus solar_main
    try:
        with open("_boot_info.txt", "w") as _f:
            _f.write(_line + "\n")
    except Exception as _e:
        print("_boot_info.txt schreiben Fehler:", _e)
except Exception as _e:
    print("Reset-Cause-Log Fehler:", _e)

print("ESP12F Solar-Steuerung")
print("Freq: {} MHz, Heap frei: {} B".format(machine.freq() // 1000000, gc.mem_free()))

# WebREPL gemaess env.py
try:
    import env
    if getattr(env, "USE_WEBREPL", False):
        import webrepl
        webrepl.start(password=env.WEBREPL_PASSWORD)
        print("WebREPL aktiv")
except Exception as e:
    print("WebREPL Fehler:", e)

# main.py wird von MicroPython automatisch nach boot.py geladen.
