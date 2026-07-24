# boot.py - Olimex ESP32-EVB-EA Solarpanel-Steuerung
# ESP32 (Xtensa LX6 Dual-Core), ESP32_GENERIC MicroPython
import gc
import time
import machine
import network

# WiFi-PowerSave aus: STA bleibt erreichbar fuer Inbound (ARP/MQTT-Reconnect).
# ESP32-Pendant zu ESP8266's esp.sleep_type(esp.SLEEP_NONE).
try:
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    sta.config(pm=sta.PM_NONE)
except Exception as e:
    print("pm-config Fehler:", e)

# AP-Interface ausschalten - sonst stoert es STA-ARP / verbraucht RAM.
try:
    network.WLAN(network.AP_IF).active(False)
except Exception as e:
    print("AP_IF deakt. Fehler:", e)

gc.collect()

print("Olimex ESP32-EVB-EA Solar-Steuerung")
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
