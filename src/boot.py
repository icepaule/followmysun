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
