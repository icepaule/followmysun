---
title: Kalibrierung
---

# Kalibrierung MPU-6050

Der MPU misst Roll als Winkel zwischen Y- und Z-Achse. Je nachdem wie das Modul physisch eingebaut ist, stimmt der Roh-Wert nicht 1:1 mit dem echten Panel-Winkel zur Horizontalen. Zwei Parameter in `env.py` machen das geradeziehen ohne dass du am Sensor schrauben musst:

```python
SENSOR_OFFSET = 87.3   # Nullpunkt-Verschiebung
SENSOR_SIGN   = 1      # +1 oder -1, je nach Achsen-Orientierung

# Umrechnung im Code:
# echter_winkel = SENSOR_SIGN * (raw - SENSOR_OFFSET)
```

## Einmessverfahren – 2 Datenpunkte reichen

Du brauchst zwei mechanisch klare Positionen:
- **Aktuator komplett eingefahren** (Panel liegt flach auf dem Dach)
- **Aktuator komplett ausgefahren** (Endschalter erreicht)

Die echten Winkel beider Positionen musst du messen oder ableiten:
- **Eingefahren** = Dachneigung (z.B. 32° bei meinem Gartenhaus, mit Wasserwaage / Handy-Libellen-App messen)
- **Ausgefahren** = Dachneigung + Aktuator-Hub-Winkel (bei mir 58.7°, mit Wasserwaage am Panel gemessen)

### Schritt 1: Aktuator einfahren, Roh-Wert ablesen

Über Webseite oder MQTT:
```bash
mosquitto_sub -h <broker> -u user -P pw \
  -t tele/solar/SENSOR/PanelAngleRaw -v
```

Beispiel-Ablesung: `raw_min = 119.3` bei echtem Winkel 32°.

### Schritt 2: Aktuator ausfahren, Roh-Wert ablesen

Auf der Webseite: `⬆️` klicken, warten bis Aktuator am Endschalter steht (Wert bewegt sich nicht mehr, dauert ~30–60 s je nach Hub), dann Roh-Wert ablesen.

Beispiel: `raw_max = 146.0` bei echtem Winkel 58.7°.

### Schritt 3: Vorzeichen prüfen

```
raw_max > raw_min  →  SENSOR_SIGN = +1   (steigender Raw = steigender Winkel)
raw_max < raw_min  →  SENSOR_SIGN = -1   (fallender Raw = steigender Winkel)
```

In meinem Beispiel: `146.0 > 119.3` → **SIGN = +1**.

### Schritt 4: Offset berechnen

```
SENSOR_OFFSET = raw_min - (echter_winkel_min * SIGN)
              = 119.3 - 32.0
              = 87.3
```

### Schritt 5: MAX_ANGLE setzen

```
MAX_ANGLE = SIGN * (raw_max - SENSOR_OFFSET)
          = 1 * (146.0 - 87.3)
          = 58.7
```

In `env.py` eintragen, speichern, hochladen, ESP rebooten.

### Verifikation

Webseite öffnen:
- Bei eingefahrenem Aktuator: Aktuell-Wert ≈ deine `MIN_ANGLE`
- Bei ausgefahrenem Aktuator: Aktuell-Wert ≈ deine `MAX_ANGLE`
- Bereich-Anzeige zeigt `32.0° – 58.7°`

## Häufige Fälle

| Beobachtung | Diagnose | Fix |
|---|---|---|
| Raw bei eingefahren ist ~120, sollte ~32 sein | 90°-Achsen-Verdrehung im Sensor | `OFFSET = raw - real`, hier ~88 |
| Aktuator fährt aus, Raw wird **kleiner** | Y-Achse zeigt zur Unterkante | `SENSOR_SIGN = -1` |
| Beim Bewegen zwischen Endlagen springt der Wert wild | Z-Achse nicht senkrecht zum Panel | mechanisch umorientieren – Kalibrierung kann das nicht retten |
| Werte stabil aber ±2° Drift | Normal für MPU-6050 ohne Gyro-Fusion | mit der `tolerance`-Konstante im Code abfangen (default 2°) |

## Toleranzen und Tiefpass

Der Code hat eine asymmetrische Hysterese in `solar_main.py`:

```python
START_TOLERANCE = 2.0   # Motor startet erst ab dieser Abweichung
STOP_TOLERANCE  = 0.5   # Motor stoppt sobald innerhalb dieser Grenze
```

Das verhindert das Hin-und-her-Klacken der Relais bei kleinen Sensor-Rauschen. Wenn du noch ruhigeres Verhalten willst (z.B. bei windigem Aufbau), bietet sich ein Moving-Average über die letzten 5 Messungen an (nicht standardmäßig drin, kann als Erweiterung eingebaut werden).
