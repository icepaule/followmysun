# FollowMySun

> Astronomisch geführte Sonnenstand-Nachführung für ein einzelnes PV-Modul auf einem Gartenhaus-Dach. Basierend auf ESP8266 (ESP12F-Relay-X4), MPU-6050-Beschleunigungssensor und einem 12 V Linear-Aktuator – mit MQTT-Anbindung an Home Assistant inkl. Sturm-Notfallmodus.

![Gesamtansicht – Gartenhaus mit aufgestelltem PV-Panel](docs/img/gartenhaus-gesamtansicht.jpeg)

---

## Was macht das Ding?

Ein einzelnes PV-Modul auf dem 32°-Dach eines Gartenhauses wird durch einen 12 V Linear-Aktuator zwischen 32° (flach auf dem Dach) und ca. 59° (Aktuator voll ausgefahren) verstellt. Ein MicroPython-Programm auf einem ESP12F berechnet aus Datum, Uhrzeit und Standort den optimalen Panel-Winkel zur Sonne, misst per MPU-6050-Beschleunigungssensor den aktuellen Ist-Winkel und steuert über zwei Relais die Polarität am Aktuator.

Alle Werte werden per MQTT an einen Broker geschickt – damit baut sich in Home Assistant ein Live-Dashboard. Über ein Command-Topic (`cmnd/solar/EMERGENCY = on`) lässt sich das Panel bei Unwetterwarnung sofort flach auf das Dach fahren.

## Features

- **Astronomische Sonnenstand-Berechnung** für jeden Tag des Jahres und jede Tageszeit
- **MPU-6050-Regelung** mit asymmetrischer Hysterese (Start ab 2° Abweichung, Stopp ab 0,5° + Overshoot-Erkennung)
- **MQTT** mit JSON-Vollpayload + einzelnen Topics für Home-Assistant-Sensoren
- **Notfallmodus** über MQTT (`cmnd/solar/EMERGENCY`) – Panel sofort in Schutzposition
- **Hardware-Watchdog** (~3 s) gegen ESP-Hänger
- **WebREPL** zur Wartung übers WLAN (kein USB nötig nach Einbau)
- **Mini-Webserver** zur manuellen Steuerung im Browser
- **Kalibrierungs-Layer** mit Offset/Sign – Sensor-Achsenrichtung muss nicht physisch perfekt sitzen

## Hardware

| Bauteil | Funktion |
|---|---|
| **ESP12F-Relay-X4 v1.2** | ESP8266 + 4 Relais, davon 2 genutzt | 
| **MPU-6050 (GY-521)** | Beschleunigungssensor zur Winkelmessung |
| **Linear-Aktuator 12 V** mit Endschaltern | Verstellt das Panel-Gestell |
| **DC/DC-Stepdown-Wandler** | 12 V → 5 V Versorgung des ESP |
| **CAT5-Kabel ~2,5 m** | Verlängert I2C-Bus vom Controller zum Sensor am Panel |

### Steuerung im Gartenhaus

![ESP12F-Relay-X4 Controller im Gehäuse](docs/img/controller-esp12f-relay-x4.jpeg)

Der Controller hängt geschützt unter der Dachschräge. Die zwei roten LEDs zeigen, welches Relais gerade aktiv ist.

### Stromversorgung

![DC/DC-Stepdown-Wandler 12V→5V](docs/img/stromversorgung-dcdc.jpeg)

Ein einstellbarer Stepdown-Wandler erzeugt die 5 V für den ESP aus der 12 V Aktuator-Versorgung – ein Netzteil reicht für alles.

### MPU-Sensor am Panel

![MPU-6050 am Panel-Rahmen](docs/img/mpu-sensor-am-panel.jpeg)

Der MPU-6050 sitzt in einem 3D-gedruckten Gehäuse direkt am PV-Rahmen und misst die Neigung gegen die Schwerkraft. Verkabelt mit CAT5 zum Controller.

## Schnellstart

1. **Hardware nach Pinbelegung verdrahten** (siehe [docs/hardware.md](docs/hardware.md))
2. **MicroPython auf ESP12F flashen** ([docs/installation.md](docs/installation.md))
3. **`src/env.example.py` → `env.py` kopieren** und Werte einfüllen (WLAN, MQTT, Sensor-Achsen)
4. **Code als `.mpy` kompilieren** (sonst MemoryError beim Parsen):
   ```bash
   python -m mpy_cross solar_main.py
   ```
5. **Dateien hochladen** (USB oder WebREPL): `boot.py`, `main.py`, `env.py`, `mpu6050.mpy`, `solar_main.mpy`
6. **Strom an** – fertig. Webseite unter `http://<esp-ip>/`, MQTT-Topics unter `tele/solar/...`

Detaillierte Anleitung: **[docs/installation.md](docs/installation.md)**

## MQTT-Topics für Home Assistant

| Topic | Richtung | Beispiel | Beschreibung |
|---|---|---|---|
| `tele/solar/SENSOR` | ESP→ | JSON | Vollpayload mit allen Werten |
| `tele/solar/SENSOR/PanelAngle` | ESP→ | `35.4` | Aktueller Panel-Winkel (kalibriert) |
| `tele/solar/SENSOR/TargetAngle` | ESP→ | `42.1` | Soll-Winkel |
| `tele/solar/SENSOR/SunAngle` | ESP→ | `45.0` | Berechneter optimaler Winkel |
| `tele/solar/SENSOR/MotionText` | ESP→ | `Hoch` | `Stopp` / `Hoch` / `Runter` |
| `tele/solar/SENSOR/MinAngle` | ESP→ | `32.0` | Mechanisches Untermass |
| `tele/solar/SENSOR/MaxAngle` | ESP→ | `58.7` | Mechanisches Obermass |
| `tele/solar/SENSOR/Emergency` | ESP→ | `false` | Notfall-Status |
| `cmnd/solar/EMERGENCY` | →ESP | `on` / `off` | Notfall an/aus (retained!) |

Vollständig: **[docs/mqtt.md](docs/mqtt.md)** · NodeRED-Sturm-Automatik: **[docs/nodered-stormwatch.md](docs/nodered-stormwatch.md)**

## Notfall-Modus für Sturmwarnung

Aus Node-RED bei Unwetterwarnung:

```javascript
msg.topic = 'cmnd/solar/EMERGENCY';
msg.payload = 'on';
msg.retain = true;   // wichtig: ueberlebt ESP-Reboot
return msg;
```

Der ESP fährt das Panel sofort auf `MIN_ANGLE` (Dachneigung, flach) und ignoriert Auto-Modus + manuelle Web-Befehle. Bei `off` wechselt er zurück in den Astro-Modus.

## Repo-Struktur

```
followmysun/
├── README.md                  # diese Datei
├── src/                       # MicroPython-Code fuer ESP12F
│   ├── boot.py
│   ├── main.py                # Loader fuer solar_main.mpy
│   ├── solar_main.py          # Hauptlogik (Astro, MQTT, Web, Motor)
│   ├── mpu6050.py             # I2C-Treiber MPU-6050
│   ├── env.example.py         # Konfigurations-Template
│   └── webrepl_cli.py         # Datei-Upload via WebREPL
├── docs/                      # Detail-Dokumentation
│   ├── hardware.md
│   ├── installation.md
│   ├── mqtt.md
│   ├── calibration.md
│   └── img/                   # Fotos vom realen Aufbau
└── _config.yml                # Jekyll Konfiguration (GitHub Pages)
```

## Tech-Stack

- **MicroPython 1.28** auf ESP8266 (ESP12F)
- **mpy-cross** für Bytecode-Kompilierung (sonst RAM-Limit)
- **paho-mqtt / mosquitto** als Broker
- **MPU-6050** mit `atan2`-basierter Roll-Berechnung
- **SoftI2C @ 100 kHz** (wegen 2,5 m CAT5-Strecke)

Details siehe [docs/software.md](docs/software.md).

## Lessons Learned

Drei Sachen, die mich am meisten Zeit gekostet haben:

1. **`mqtt.ping()` darf nicht in jeder Loop-Iteration aufgerufen werden** – sonst stempelt der Broker dich als misbehaving und schmeißt dich mit `ECONNRESET` raus. Throttling auf 1×/30 s.
2. **ESP8266 WLAN braucht aktiven Outbound-Traffic**, sonst lernen Router/Switches die MAC nicht zuverlässig zurück – ein UDP-Keepalive pro Sekunde an die Gateway-IP löst's.
3. **`solar_main.py` ist mit 33 KB zu groß zum Parsen** auf dem ESP8266 (Heap ~35 KB). Lösung: vorher mit `mpy-cross` zu `.mpy` (10 KB) kompilieren.

## Lizenz

MIT – siehe [LICENSE](LICENSE).
