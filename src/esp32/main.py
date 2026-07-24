# main.py - Loader fuer Olimex ESP32-EVB-EA.
# Auf ESP32 mit 520 KB RAM reicht .py direkt - kein .mpy-Trick noetig
# (anders als auf ESP8266, wo der Parser-RAM zwingend war).
import gc
gc.collect()
import solar_main
