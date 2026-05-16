---
title: Installation
---

# Installation Schritt-für-Schritt

Ziel: Von „nichts" zu „läuft im Garten" in ~2 Stunden.

## Voraussetzungen

Auf deinem PC:
- **Python 3.10+**
- **pip** Pakete: `mpremote`, `mpy-cross`, `esptool` (alle pip-installierbar)
- **MicroPython-Firmware** für ESP8266: [micropython.org/download/ESP8266_GENERIC](https://micropython.org/download/ESP8266_GENERIC/)
- USB-zu-TTL-Adapter (3,3 V kompatibel, z.B. CP2102, FT232 oder das Adapter-Modul aus dem ESP12F-Relay-Board-Set)
- MQTT-Broker im selben Netz (Mosquitto, oder embedded in Home Assistant)

```bash
pip install mpremote mpy-cross esptool paho-mqtt
```

## Schritt 1: MicroPython auf den ESP12F flashen

Das ESP12F-Relay-X4-Board wird über das mitgelieferte USB-Adapter-Modul angeschlossen (steckt seitlich auf die Pinleiste). Position des Jumpers `Run/Prog` auf `Prog` setzen für Flash-Modus.

```bash
# COM-Port ermitteln (Windows)
mode

# Flash loeschen
esptool --port COM3 erase_flash

# Firmware schreiben (MicroPython 1.28 oder neuer)
esptool --port COM3 --baud 460800 write_flash --flash_size=detect 0 ESP8266_GENERIC-20251213-v1.28.0.bin
```

Jumper zurück auf `Run`, USB neu anstecken. Mit `mpremote` testen:

```bash
python -m mpremote connect COM3
# Es sollte ein MicroPython-Prompt erscheinen (>>>)
```

## Schritt 2: Repo klonen

```bash
git clone https://github.com/icepaule/followmysun.git
cd followmysun/src
```

## Schritt 3: Konfiguration

`env.example.py` nach `env.py` kopieren und die Werte einfüllen:

```python
WIFI_SSID     = "DeinWLAN"
WIFI_PASSWORD = "DeinPasswort"
MQTT_SERVER   = "192.168.178.50"      # IP deines Brokers
MQTT_USER     = "user"
MQTT_PASSWORD = "passwort"
WEBREPL_PASSWORD = "deinpwd"           # 4–9 Zeichen, frei waehlbar
HOSTNAME      = "solar"
```

> **Wichtig:** Die echte `env.py` ist in `.gitignore` ausgeschlossen und wird **nie** ins Git-Repo commitet.

## Schritt 4: Bytecode kompilieren

Der Hauptcode (`solar_main.py`) ist mit ~33 KB zu groß zum Parsen auf dem ESP8266 (Heap nur ~35 KB). Wir kompilieren ihn mit `mpy-cross` zu Bytecode:

```bash
python -m mpy_cross solar_main.py
python -m mpy_cross mpu6050.py
```

Ergebnis: `solar_main.mpy` (~12 KB) und `mpu6050.mpy` (~1 KB).

## Schritt 5: Dateien hochladen (per USB)

```bash
python -m mpremote connect COM3 cp boot.py :boot.py
python -m mpremote connect COM3 cp main.py :main.py
python -m mpremote connect COM3 cp env.py :env.py
python -m mpremote connect COM3 cp mpu6050.mpy :mpu6050.mpy
python -m mpremote connect COM3 cp solar_main.mpy :solar_main.mpy
```

Verifizieren:
```bash
python -m mpremote connect COM3 ls
# erwartet: boot.py env.py main.py mpu6050.mpy solar_main.mpy
```

## Schritt 6: Erster Boot

```bash
python -m mpremote connect COM3
# Im Prompt: Ctrl-D fuer Soft-Reset
```

Erwartet:
```
ESP12F Solar-Steuerung
WLAN OK: 192.168.178.92
Modem-Sleep AUS (sleep_type=NONE) nach Connect
MQTT verbunden mit 192.168.178.50:1883
Webserver läuft auf Port 80
Watchdog aktiv (~3s Timeout)
System bereit - Starte Hauptschleife
Sensor: 32.0° (Ziel: 35.0°)
```

Wenn das durchläuft: **System läuft.**

## Schritt 7: Webseite öffnen

`http://<ESP-IP>/` im Browser. Zeigt aktuellen Winkel, Soll-Winkel, Motorstatus.

## Schritt 8: Kalibrierung

Die `SENSOR_OFFSET` und `SENSOR_SIGN` in `env.py` sind nur Schätzwerte und müssen einmalig eingemessen werden. Siehe **[calibration.md](calibration.md)**.

## Spätere Updates – via WebREPL ohne USB

Wenn das Gerät erstmal im Feld ist, geht der Update-Weg übers WLAN:

```bash
# Code lokal aendern, neu kompilieren
python -m mpy_cross solar_main.py

# Hochladen
python webrepl_cli.py -p DEIN_WEBREPL_PWD solar_main.mpy <IP>:/solar_main.mpy

# Reboot via WebREPL (Browser unter https://micropython.org/webrepl/)
# Connect ws://<IP>:8266/ → "import machine; machine.reset()"
```

## Troubleshooting

| Symptom | Mögliche Ursache | Fix |
|---|---|---|
| `MemoryError` beim Boot | `.py` statt `.mpy` hochgeladen | mit `mpy_cross` kompilieren |
| Webseite Timeout, MQTT funktioniert | WLAN-Power-Save | bereits gefixt in `solar_main.py` ([siehe Lessons-Learned im README](../README.md#lessons-learned)) |
| Sensor liest Werte > 90° bei flachem Panel | MPU-Achsen 90° verdreht | `SENSOR_OFFSET` anpassen, [calibration.md](calibration.md) |
| Motor läuft permanent in eine Richtung | Sensor falsch herum, `SENSOR_SIGN` umdrehen | `SENSOR_SIGN = -1` setzen |
| ESP rebootet alle paar Sekunden | WDT triggert wegen langsamem `i2c.scan()` oder anderem Block | siehe Lessons Learned |
| MQTT `ECONNRESET` direkt nach Connect | Broker stempelt zu viele `ping()` als Misbehavior | bereits gefixt (Throttle auf 1×/30 s) |
