---
title: Tracker-Debugging und Quellbasis
---

# Tracker-Debugging und Quellbasis

Diese Seite sammelt die für den Solar-Tracker aktuell relevante Quellbasis, die Laufzeit-Variante und die wichtigsten Hinweise für zukünftige Änderungen und Debugging-Schritte.

## Aktuelle Laufzeit-Variante

Der Tracker läuft im Feld nicht direkt aus der lesbaren Python-Datei, sondern aus der kompilierten MicroPython-Datei:

- `solar_main.mpy` – aktive Laufzeitdatei auf dem Tracker
- `src/solar_main.py` – lesbare Quellbasis für die Dokumentation und spätere Änderungen
- `src/env.py` – lokale Konfiguration, inklusive Pins, Sensor-Kalibrierung und MQTT-/WebREPL-Setup
- `src/mpu6050.py` – Sensor-Treiber für den MPU-6050
- `src/boot.py` – Start- und Boot-Logik
- `src/main.py` – Loader, der `solar_main.mpy` lädt

> Für die öffentliche Doku sollten die Werte aus `env.py` nur ohne sensible Zugangsdaten beschrieben werden. WLAN-, MQTT- und WebREPL-Credentials bleiben lokal und werden nicht im GitHub-Repo veröffentlicht.

## Was die aktive Quellbasis leistet

Die aktuelle Quellbasis des Trackers enthält im Kern:

- Astronomische Soll-Winkel-Berechnung
- Abgleich des aktuellen Winkelstands gegen den Sollwert
- Relaisgesteuerte Bewegung des Aktuators
- MQTT-Übermittlung von Status- und Sensorwerten
- Notfallmodus über MQTT
- Webserver für lokale Steuerung
- Watchdog-/Stabilitäts-Logik gegen Hänger

## Für zukünftige Debugging-Szenarien nützlich

Wenn der Tracker später erneut untersucht oder angepasst werden soll, ist diese Reihenfolge sinnvoll:

1. `src/solar_main.py` – eigentliche Regelungslogik verstehen
2. `src/env.py` – Konfiguration prüfen
3. `src/mpu6050.py` – Sensorwerte und Kalibrierung prüfen
4. `src/boot.py` – Startverhalten und WebREPL-Initialisierung prüfen
5. `src/main.py` – Loader-Mechanik sicherstellen

## Typische Debugging-Checkliste

- Ist `solar_main.mpy` wirklich die Datei, die auf dem Gerät läuft?
- Wurde nach Änderungen an `src/solar_main.py` auch neu mit `mpy_cross` kompiliert?
- Ist die Sensor-Kalibrierung (`SENSOR_OFFSET`, `SENSOR_SIGN`) korrekt?
- Läuft das MQTT-Handling stabil, oder sind Reconnects/Timeouts der Fehler?
- Funktioniert der Webserver und der WebREPL lokal im Netzwerk?
- Ist der Notfallmodus über MQTT weiterhin zuverlässig?

## Praktischer Ablauf für Änderungen

```bash
cd src
python -m mpy_cross solar_main.py
python -m mpy_cross mpu6050.py
```

Anschließend die neu erzeugten `.mpy`-Dateien auf den Tracker hochladen und mit einem Reboot prüfen.

## Hinweise zur Dokumentation

Für zukünftige Dokumentations- und Debug-Aufgaben sollte die Doku folgende Punkte enthalten:

- aktuelle Funktionsweise des Trackers
- verwendete Pin-Belegung
- Sensor-Kalibrierung und mechanische Endlagen
- MQTT-Topics und Bedeutung
- relevante Fehlermuster und bekannte Fixes
- Arbeitsweise von Webserver und WebREPL

Damit bleibt die Dokumentation als Wartungs- und Debug-Referenz auch über längere Zeit hinweg nutzbar.
