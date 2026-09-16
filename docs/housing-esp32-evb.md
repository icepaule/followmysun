---
title: 3D-Druck-Gehäuse für Olimex ESP32-EVB-EA Rev.L
---

# 3D-Druck-Gehäuse für Olimex ESP32-EVB-EA Rev.L

Für die neue ESP32-Version des FollowMySun-Controllers gibt es ein eigenes parametrisches Gehäuse. Es ist speziell für die **Überkopfmontage innerhalb des Schuppens unter dem Dach** konstruiert: Die Grundplatte bleibt am Dach verschraubt, während der Deckel zur Wartung von unten abgenommen werden kann.

![Gesamtansicht des Olimex-Gehäuses](img/housing-esp32-evb/preview_v0.3.jpg)

Aktueller Stand: **v0.3**. Die Geometrie basiert auf den Board-Koordinaten des offiziellen OLIMEX-KiCad-Layouts für **ESP32-EVB Rev.L**.

## Konstruktionsprinzip

- Vier außenliegende Laschen befestigen die Grundplatte an der Unterseite des Schuppendachs.
- Das Olimex-Board sitzt auf drei 4-mm-Standoffs an den originalen Rev-L-Montagepunkten.
- Die Bauteilseite zeigt nach unten in das Gehäuse.
- Der Deckel wird von unten aufgesetzt und mit vier M3-Schrauben befestigt.
- Der Reset-Taster `RST1` ist über einen separaten gedruckten Plunger erreichbar.
- Belüftungsschlitze liegen auf der nach unten gerichteten Seite und sind damit gegen den meisten herabfallenden Staub geschützt.

## Anschlüsse

| Anschluss | Gehäuseöffnung | Zweck |
|---|---:|---|
| WLAN / externe Antenne | Ø **10,0 mm** | Durchführung für den externen Antennenanschluss |
| PWR1 | **11 × 11 mm** | 5-V-Hohlstecker / Kabelkörper |
| UEXT1 | **16 × 7 mm** | einzelne Dupont-Leitungen zum MPU-6050 |
| USB-UART1 / Micro-USB | **13 × 8,5 mm** | lokale Konsole, Flashen und Wartung |
| CON1 + CON2 | **33,1 × 13,5 mm** seitlich | sechs Relais-/Aktuator-Klemmen |
| Klemmschrauben | **2 × 13 × 14 mm** unten | Schraubendreherzugang zu beiden 3-poligen Klemmenblöcken |
| RST1 | Ø **4,2 mm** | gedruckter Reset-Plunger |
| CAN | **keine Öffnung** | für FollowMySun nicht benötigt |

Die beiden DG306-5.0-Klemmen `CON1` und `CON2` sitzen direkt an der Platinenkante. Die v0.3 verwendet deshalb eine gemeinsame seitliche Öffnung für alle sechs Anschlusspositionen und zusätzlich zwei getrennte Wartungsfenster im Deckel. Dadurch lassen sich die Aktuatorleitungen auch bei montierter Grundplatte von unten lösen oder nachziehen.

## Explosionsansicht

![Explosionsansicht des Olimex-Gehäuses](img/housing-esp32-evb/exploded_v0.3.jpg)

Das Board bleibt bei Wartungsarbeiten auf der dachseitigen Grundplatte. Deckel und Reset-Plunger können separat demontiert werden.

## Abmessungen

- Gehäuse ohne Befestigungslaschen: **94 × 92 × 31 mm**
- Wandstärke: **2,6 mm**
- PCB-Standoff: **4,0 mm**
- Dach-Montagebohrungen: **Ø 4,5 mm**
- RST-Plunger-Schaft: **Ø 3,55 mm**, Länge **11,0 mm**

Die Passmaße sind am Anfang der SCAD-Datei als Parameter definiert und können ohne Neukonstruktion geändert werden.

## Quelldateien und STL-Build

Die parametrische Quelle liegt hier:

[`hardware/enclosure/olimex-esp32-evb-ea-v0.3/`](../hardware/enclosure/olimex-esp32-evb-ea-v0.3/)

Wichtige Dateien:

- [`olimex_esp32_evb_ea_roof_housing_v0.3.scad`](../hardware/enclosure/olimex-esp32-evb-ea-v0.3/olimex_esp32_evb_ea_roof_housing_v0.3.scad) – komplettes Modell
- [`SOURCE_POSITIONS.md`](../hardware/enclosure/olimex-esp32-evb-ea-v0.3/SOURCE_POSITIONS.md) – verwendete Rev-L-Koordinaten
- [`MESH_QA.json`](../hardware/enclosure/olimex-esp32-evb-ea-v0.3/MESH_QA.json) – Prüfung der Referenz-STLs
- [`build.sh`](../hardware/enclosure/olimex-esp32-evb-ea-v0.3/build.sh) – erzeugt Base, Lid, Reset-Button, Fit-Test und das ZIP-Paket

Mit installiertem OpenSCAD:

```bash
cd hardware/enclosure/olimex-esp32-evb-ea-v0.3
chmod +x build.sh
./build.sh
```

Danach enthält `dist/`:

```text
base_v0.3.stl
lid_v0.3.stl
rst_button_v0.3.stl
fit_test_v0.3.stl
olimex_esp32_evb_ea_roof_housing_v0.3.zip
MANIFEST_SHA256.txt
```

## Vor dem großen Druck: Fit-Test

Zuerst nur `fit_test_v0.3.stl` drucken. Damit lassen sich die kritischen realen Passungen mit sehr wenig Material prüfen:

1. WLAN-Anschluss durch Ø10 mm testen.
2. PWR-Stecker gegen 11 × 11 mm prüfen.
3. Micro-USB-Kabel samt Kunststoffkörper durch 13 × 8,5 mm prüfen.
4. UEXT/Dupont-Kabelbündel gegen 16 × 7 mm prüfen.
5. Schraubendreherzugang für die Aktuator-Klemmen prüfen.

Erst danach Base und Lid drucken. FDM-Bohrungen fallen abhängig von Drucker und Material oft geringfügig kleiner aus; deshalb ist der Testcoupon Bestandteil des Modells.

## Druckempfehlung

Für den endgültigen Einsatz unter dem Schuppendach **PETG oder ASA** verwenden. PLA ist für Passproben geeignet, kann sich aber bei sommerlicher Hitze unter dem Dach verformen.

Startwerte:

- 0,20 mm Layerhöhe
- 4 Perimeter
- 25–35 % Infill
- 5 Top-/Bottom-Layer
- Base flach, Posts nach oben
- Lid ist im STL bereits mit der geschlossenen Außenseite zum Druckbett orientiert
- RST-Button mit der Kappe auf dem Druckbett
- normalerweise keine Supports erforderlich

## Mesh-Prüfung

Die Referenz-STLs der v0.3 wurden nach dem Rendern geprüft. Base, Lid, RST-Button und Fit-Test sind jeweils **wasserdichte Einzelmeshes** (`watertight = true`, jeweils eine Komponente). Details stehen in [`MESH_QA.json`](../hardware/enclosure/olimex-esp32-evb-ea-v0.3/MESH_QA.json).

## Zusammenhang mit dem Controller-Umbau

Das Gehäuse gehört zur Migration des Trackers auf den Olimex-Controller:

- [Hardware-Migration ESP12F → Olimex ESP32-EVB-EA](hardware-migration-esp32-evb.html)
- [Wiring-Übersicht ESP32-EVB](wiring-esp32-evb.html)

Die sechs zugänglichen Schraubanschlüsse sind dabei die beiden Onboard-Relais `CON1`/`CON2`, über die 12-V-Versorgung und Linear-Aktuator im Polarity-Reverse-Schema angeschlossen werden.
