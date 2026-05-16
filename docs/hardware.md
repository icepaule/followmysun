---
title: Hardware-Aufbau
---

# Hardware-Aufbau

Komplette Stückliste, Pinbelegung und Verkabelung.

## Stückliste

| # | Bauteil | Bezugsquelle (Beispiel) | Preis ca. |
|---|---|---|---|
| 1 | **ESP12F-Relay-X4 v1.2** (ESP8266 + 4 SPDT-Relais) | AliExpress | ~10 € |
| 2 | **MPU-6050 GY-521** Beschleunigungssensor | AliExpress | ~2 € |
| 3 | **Linear-Aktuator 12 V** mit integrierten Endschaltern (Hub passend) | Amazon | 30–80 € |
| 4 | **DC/DC-Stepdown-Wandler** 12 V→5 V (z.B. MP1584) | AliExpress | ~3 € |
| 5 | **12 V Netzteil** (Strom ≥ Aktuator-Anlaufstrom, ~2 A) | – | 10–20 € |
| 6 | **CAT5-Kabel** (~2,5 m je nach Distanz Controller↔Sensor) | – | – |
| 7 | **PV-Modul** mit Schwenk-Gestell | – | – |
| 8 | 3D-gedrucktes Sensor-Gehäuse (optional, witterungsfest) | selbst | – |
| 9 | Aderendhülsen, Schraubklemmen, Lüsterklemmen | – | – |

## Pinbelegung ESP12F-Relay-X4

Das Board nutzt intern feste GPIO-Pins für seine Relais:

| Relais | GPIO | Code-Konstante | Funktion |
|---|---|---|---|
| K1 | GPIO 16 | `PIN_RELAY1` | **Motor Runter** (Aktuator einfahren) |
| K2 | GPIO 14 | `PIN_RELAY2` | **Motor Hoch** (Aktuator ausfahren) |
| K3 | GPIO 12 | – | (frei) |
| K4 | GPIO 13 | – | (frei) |

Freie GPIOs für I2C:

| Pin | GPIO | Code-Konstante | Funktion |
|---|---|---|---|
| D2 | GPIO 4 | `PIN_I2C_SDA` | I2C SDA (Daten) |
| D1 | GPIO 5 | `PIN_I2C_SCL` | I2C SCL (Takt) |

![Steuerung im Gartenhaus](img/controller-esp12f-relay-x4.jpeg)

## Verkabelung Motor (Polaritätsumkehr-Schaltung)

Linear-Aktuator hat zwei Drähte – die Drehrichtung kommt aus der Polarität. Mit zwei SPDT-Relais wird die Polarität umgeschaltet. **NO/COM/NC sind die drei Anschlüsse pro Relais auf der Klemmleiste.**

```
+12V (gross) ────┬──────────┐
                 │          │
              K1.NO       K2.NO
                 │          │
              K1.COM     K2.COM
                 │          │
            Aktuator-A   Aktuator-B
                 │          │
              K1.NC      K2.NC
                 │          │
 GND (gross) ────┴──────────┘
```

| K1 | K2 | Draht A | Draht B | Aktuator |
|---|---|---|---|---|
| OFF | OFF | GND | GND | steht (beidseitig GND = Bremse) |
| **ON** | OFF | **+12 V** | GND | fährt eine Richtung |
| OFF | **ON** | GND | **+12 V** | fährt andere Richtung |

**Wenn nach erstem Test die Richtung verkehrt herum ist:** nicht im Code drehen, sondern Aktuator-Drähte A↔B tauschen. Der Code-Kommentar (`K1 = Runter, K2 = Hoch`) bleibt dann konsistent.

## Verkabelung MPU-6050

I2C-Bus, vier Drähte. Bei meinem Aufbau ~2,5 m **CAT5-Patchkabel** zwischen Controller im Gartenhaus und Sensor am Panel. Verwendete Aderbelegung (eigene Konvention – einmal festgelegt und durchgehalten):

| MPU-6050-Pin | ESP12F-Pin | CAT5-Ader |
|---|---|---|
| **VCC (3,3 V)** | 3V3 | **blau** |
| **GND** | GND | **grün** |
| **SDA** | D2 (GPIO 4) | **orange** |
| **SCL** | D1 (GPIO 5) | **braun** |

Die jeweils mit-verdrillte „weiß-…"-Ader der CAT5-Paare wird nicht benutzt oder als zweite GND-Ader genutzt. **Wichtig**: SDA und SCL nicht im gleichen verdrillten Paar zusammen – die hohen Pegelwechsel würden sich gegenseitig stören. Lieber Power-Paar (blau+weißblau für VCC/GND) und Daten-Paare getrennt.

> Bei längeren Strecken (>1 m) sollte I2C auf **100 kHz** statt 400 kHz laufen, sonst CRC-Fehler. Im Code per `machine.SoftI2C(..., freq=100000)` gesetzt.

> **MPU-Modul** mit 5 V VCC funktioniert auch, hat dann aber den onboard-LDO als Wärmequelle. 3,3 V direkt vom ESP-Board ist sauberer.

![MPU-Sensor am Panel-Rahmen](img/mpu-sensor-am-panel.jpeg)

## MPU-Orientierung am Panel

Der MPU misst Roll als `atan2(accel_y, accel_z)`. Damit positive Werte „Panel steiler" bedeuten, gilt folgende Konvention:

| MPU-Achse | muss zeigen nach… |
|---|---|
| **+Z** (aus Bauteilseite raus) | weg vom Panel (Bauteilseite ins Freie, Pin-Header-Seite ans Panel) |
| **X** | parallel zur Drehachse des Panels (entlang Pin-Header-Reihe) |
| **+Y** | zur Hochkante des Panels (wo das Panel beim Aufstellen hochgeht) |

**Wenn beim ersten Test der Wert verkehrtes Vorzeichen hat oder einen ~90°-Offset zeigt:** im Code über die Kalibrierungs-Parameter korrigieren statt am Sensor schrauben. Siehe [calibration.md](calibration.md).

## Stromversorgung

Ein einziges **12 V Netzteil** versorgt zwei Pfade:

```
                ┌──────────────────────────┐
12 V Netzteil ──┤  Aktuator (über Relais)  │
                └──────────────────────────┘
                ┌──────────────────────────┐
            └───┤  DC/DC Stepdown 12V→5V   │
                │        ↓                 │
                │     ESP-Board VIN        │
                └──────────────────────────┘
```

**12 V-Pfad:**
- Direkt auf die große grüne Klemmleiste am ESP12F-Relay-X4 (versorgt das Board)
- Zusätzlich per Drahtbrücken auf `K1.NO`+`K2.NO` (= +12 V für Aktuator)
- GND-Brücken auf `K1.NC`+`K2.NC` (= GND für Aktuator-Rückführung)

**5 V-Pfad** (für ESP-Logik):
- Stepdown-Wandler hat zwei Schraubklemmen Eingang (12 V IN, GND) und zwei Ausgang (5 V OUT, GND)
- Ausgang auf 5 V einstellen (Poti drehen, mit Multimeter messen, **bevor** der ESP angeschlossen wird)
- Dann 5 V an den ESP-Board-Vin-Pin (nicht 3V3 – der hat einen eigenen Onboard-LDO)

Der Stepdown sollte für mindestens 500 mA bei 5 V ausgelegt sein. ESP braucht meist 100–300 mA, Spitzenstrom beim WLAN-Senden bis 500 mA. Typen wie **MP1584** oder **LM2596** mit Display sind günstig und solide.

![Stromversorgung 12V→5V](img/stromversorgung-dcdc.jpeg)

Auf dem Display sieht man im Betrieb `IN ≈ 12,46 V / OUT ≈ 5,16 V` – der Wandler hält die 5 V auch bei Aktuator-Anlauflasten stabil.

## Empfohlene Erweiterungen

- **Sicherung 2 A** in der 12 V-Leitung vor dem Aktuator (Brand-Schutz)
- **Optokoppler oder zusätzliche Trennung** zwischen ESP und Aktuator-Versorgung (Funkenflug bei Relais-Schalten)
- **Wasserdichtes Gehäuse** für den MPU am Panel (IP65)
- **Endschalter-Backup** im Code (auch wenn der Aktuator eigene Endschalter hat)

## Gesamtansicht

![Gartenhaus mit aufgestelltem Panel](img/gartenhaus-gesamtansicht.jpeg)

Der schwarze Aktuator-Arm ist gut zu sehen – er hebt das Panel über die First-Linie hinaus an, sodass es der Sonne nachgeführt wird.
