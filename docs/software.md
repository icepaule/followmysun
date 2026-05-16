---
title: Software-Architektur
---

# Software-Architektur

Für Leser, die den Code lesen und ändern wollen.

## Datei-Layout auf dem ESP

```
/boot.py            #  64 B  - MicroPython startet zuerst
/main.py            # 155 B  - laedt solar_main.mpy (Bytecode-Trick fuer ESP8266-RAM)
/env.py             # ~3 KB  - lokale Konfiguration (Secrets - nicht im Git)
/mpu6050.mpy        # ~1 KB  - kompilierter I2C-Treiber
/solar_main.mpy     # ~12 KB - kompilierter Hauptcode
```

`solar_main.py` als Quelle ist ~33 KB – wegen RAM-Limit (~35 KB Heap) muss er als `.mpy` (compiled bytecode) hochgeladen werden, sonst `MemoryError` beim Parsen.

## Boot-Sequenz

1. **boot.py** wird von MicroPython automatisch zuerst geladen
   - `esp.sleep_type(esp.SLEEP_NONE)` – Modem-Sleep aus (wird später nochmal nach `wlan.connect()` gesetzt)
   - `network.WLAN(AP_IF).active(False)` – AP-Interface aus
   - WebREPL starten (Port 8266)
2. **main.py** importiert `solar_main` (= führt es aus)
3. **solar_main** lädt `env.py`, initialisiert Hardware, WLAN, NTP, MQTT, Webserver, dann `loop()` für immer

## Hauptloop

```
while True:
    handle_web_request()        # nonblocking accept, 0.5s recv timeout
    mqtt_check_connection()     # ggf. reconnect, check_msg(), ping (1×/30s)

    if 24h vorbei: sync_time()  # NTP
    if 150ms vorbei: sensor.get_angle_roll() + kalibrieren
    if 10min vorbei: calculate_optimal_angle() + target setzen
    if 30s vorbei: mqtt_publish_sensor_data()

    Motor-Control (Hysterese)

    if 30s vorbei: gc.collect()
    if 60s vorbei: sleep_type=NONE pruefen
    if 1s vorbei:  udp_keepalive zur Gateway

    wdt.feed()                  # Hardware-WDT, sonst Reset in 3s
    time.sleep(0.05)
```

## Astronomische Berechnung

`calculate_optimal_angle()` in `solar_main.py`. Vereinfachte Formel:

```python
declination = 23.45 * sin(360/365 * (day_of_year - 81))
base        = 90 - latitude              # München: 41.9°
equation_of_time = 9.87*sin(2B) - 7.53*cos(B) - 1.5*sin(B)
solar_time  = local_hour + longitude/15 + equation_of_time/60

# Saisonale + tageszeitliche Korrekturen
optimal_angle = base + declination + 0.5*declination + hour_correction
```

Anschließend wird auf `[MIN_ANGLE, MAX_ANGLE]` geclampt. Das Ergebnis bestimmt den Soll-Winkel bis zur nächsten Berechnung (in 10 min).

## Motor-Regelung (asymmetrische Hysterese)

```python
diff = current_angle - target

if motion_dir == 0:
    # Motor steht. Nur starten wenn deutliche Abweichung.
    if abs(diff) > START_TOLERANCE:    # 2.0
        if diff > 0:  rel1.on(); motion_dir = 2  # zu steil -> runter
        else:         rel2.on(); motion_dir = 1  # zu flach -> hoch
else:
    # Motor laeuft. Stop bei minimaler Diff ODER Vorzeichenwechsel.
    overshot = (motion_dir == 2 and diff < 0) or (motion_dir == 1 and diff > 0)
    if abs(diff) < STOP_TOLERANCE or overshot:
        rel1.off(); rel2.off()
        motion_dir = 0
```

- **`START_TOLERANCE = 2.0°`** – verhindert Mikro-Bewegungen bei Sensor-Rauschen
- **`STOP_TOLERANCE = 0.5°`** – stoppt frühzeitig, antizipiert Aktuator-Trägheit
- **Overshoot-Detektion** – wenn das Vorzeichen der Diff kippt, sofort Stopp, kein Zurückreversieren

## Watchdog

ESP8266 hat einen einfachen WDT mit festem Timeout (~3 s, nicht konfigurierbar):

```python
wdt = machine.WDT()          # in init() ganz am Ende aktiviert
...
while True:
    ...
    wdt.feed()               # genau einmal am Ende jeder Iteration
```

Wenn irgendetwas in der Iteration länger als 3 s blockiert (zäher Client im Webserver, MQTT-Hang, I2C-Lockup), kommt das System nicht zu `feed()` und der ESP wird hart resettet.

## Stabilitäts-Tricks (Lessons Learned)

### 1. `mqtt.ping()` darf nicht in jeder Loop-Iteration

```python
# FALSCH (war so):
if mqtt_connected:
    mqtt.ping()              # 20×/Sekunde

# RICHTIG:
if mqtt_connected and time.ticks_diff(now, last_ping) > 30000:
    mqtt.ping()
    last_ping = now
```

Symptom des Bugs: `ECONNRESET` direkt nach Connect, weil Broker den Client als misbehaving stempelt.

### 2. UDP-Keepalive zur Gateway

```python
udp_keepalive.sendto(b'.', (gateway_ip, 9))   # alle 1s
```

Hält das WLAN-Modem aktiv und pflegt die ARP-Tabelle aller Subnet-Hosts – ohne das verliert das ESP ~60% der Inbound-Pakete (klassisches ESP8266-WLAN-Sleep-Problem).

### 3. Web-Timeout kurz halten

```python
conn.settimeout(0.5)         # statt 5.0
```

Zäher Browser-Client darf NICHT 5 s blockieren – sonst hungert der WDT. Ein moderner Browser sendet das Request in <100 ms; alles längere ist verdächtig.

### 4. WDT vor blockierender Operation füttern

```python
def handle_web_request():
    ...
    conn, addr = srv.accept()
    if wdt is not None:
        wdt.feed()                # bevor recv() ggf. 0.5s wartet
    conn.settimeout(0.5)
    request = conn.recv(1024)
```

### 5. `i2c.scan()` vermeiden bei langen I2C-Strecken

`scan()` macht 112 I2C-Transaktionen. Über 2,5 m SoftI2C dauert das >2 s und kann WDT triggern. Stattdessen ein einzelnes `i2c.writeto(addr, b'\x00')` als Probe verwenden.

## MQTT-Subscribe-Flow

```python
def mqtt_on_message(topic, msg):
    if topic.endswith("/EMERGENCY"):
        emergency_mode = (msg in ("on","1","true","yes"))
        if emergency_mode:
            target = MIN_ANGLE
            manual_override = False
        ...

def mqtt_connect():
    mqtt.set_callback(mqtt_on_message)
    mqtt.connect()
    mqtt.subscribe("cmnd/solar/EMERGENCY")
    ...

# in Hauptloop:
mqtt.check_msg()    # nonblocking - ruft Callback wenn Nachricht da
```

Mit `retain=True` gesendete Commands kommen direkt beim Subscribe an – wichtig für Persistenz nach Reboot.

## Sensor-Kalibrierungs-Layer

```python
raw = sensor.get_angle_roll()                    # atan2(accel_y, accel_z)
current_angle = SENSOR_SIGN * (raw - SENSOR_OFFSET)
```

Damit ist die physische Achsen-Orientierung des MPU egal – durch Offset und Vorzeichen wird das auf den echten Winkel zur Horizontalen gemappt. Siehe [calibration.md](calibration.md).

## Webserver

Minimaler HTTP/1.0-Server in einem einzelnen Socket auf Port 80, nonblocking accept. POST-Bodies werden manuell aus dem Request-String geparsed (`minangle=`, `manual=up/down/auto`, `reset`). Kein Routing-Framework, kein Templating – nur eine einzelne HTML-Seite mit `meta http-equiv='refresh' content='5'` für Auto-Reload alle 5 s.

Pro Iteration wird genau ein Request bearbeitet (sequenziell). Reicht für eine Person, die mal F5 drückt – nicht für Last.
