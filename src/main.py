# main.py - Loader (eigentlicher Code in solar_main.mpy als Bytecode,
# das umgeht die ESP8266-Parser-RAM-Limits)
import gc
gc.collect()
import solar_main
