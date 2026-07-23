---
title: Wiring-Übersicht ESP32-EVB
---

# Wiring-Übersicht — Olimex ESP32-EVB-EA

Alle vier Schaltbilder der Migration **ESP12F-Relay-X4 v1.2 → Olimex ESP32-EVB-EA Rev.L**
auf einer Seite — zum Ausdrucken oder als Werkbank-Referenz auf dem Tablet.

Die ausführliche Doku mit Bauteilliste, Auslegung und Checkliste steht in
[Hardware-Migration ESP12F → Olimex ESP32-EVB-EA](hardware-migration-esp32-evb.html).

> ⚠️ **Die eine Regel, die alles killt:** Der Olimex ist **strikt 5 V**
> (onboard TPS62A02, abs. Max 6.5 V). 12 V an DC-Jack, UEXT Pin 1 oder Micro-USB
> zerstört den Regler sofort. Deshalb der Mini-360-Split in Diagramm 2a.

<style>
.fms-legend { display:flex; flex-wrap:wrap; gap:14px; margin:18px 0 26px; padding:0; list-style:none; }
.fms-legend li { display:flex; align-items:center; gap:7px; font-size:0.9em; }
.fms-swatch { display:inline-block; width:15px; height:15px; border-radius:3px; border:1px solid rgba(0,0,0,.35); flex:0 0 auto; }
figure.fms-fig { margin:0 0 34px; padding:0; }
figure.fms-fig .fms-frame { background:#fff; border:1px solid #d8d8d8; border-radius:6px; padding:10px; overflow-x:auto; }
figure.fms-fig img { display:block; width:100%; height:auto; }
figure.fms-fig figcaption { font-size:0.86em; color:#555; margin-top:7px; line-height:1.45; }
</style>

**Farbcode in allen Diagrammen:**

<ul class="fms-legend">
  <li><span class="fms-swatch" style="background:#ffe0e0;border-color:#c00;"></span> 12 V + (Plus)</li>
  <li><span class="fms-swatch" style="background:#e0e0ff;border-color:#000055;"></span> 12 V − (Minus)</li>
  <li><span class="fms-swatch" style="background:#fff2b3;border-color:#c97a00;"></span> 5 V / Logik-Rail</li>
  <li><span class="fms-swatch" style="background:#e8f5e8;border-color:#2a7a2a;"></span> Aktuator-Last</li>
  <li><span class="fms-swatch" style="background:#cce4ff;border-color:#004a99;"></span> I²C / Sensor</li>
</ul>

---

## 1 — IST-Zustand: ESP12F-Relay-X4 v1.2

<figure class="fms-fig">
  <div class="fms-frame">
    <a href="img/hardware-esp32-evb/01_ist_esp12f.svg" title="In voller Größe öffnen">
      <img src="img/hardware-esp32-evb/01_ist_esp12f.svg" alt="Blockschaltbild des bisherigen Aufbaus mit ESP12F-Relay-X4: 12 V direkt an die VIN-Klemme, Boardregler auf 5 V und 3.3 V, Relais K1 an GPIO16 und K2 an GPIO14, MPU-6050 über GPIO4/GPIO5." />
    </a>
  </div>
  <figcaption>
    Der bisherige Aufbau: 12 V gehen <b>direkt</b> an die VIN-Klemme (DC 7–30 V), der
    Boardregler zieht selbst auf 5 V und 3.3 V herunter. K1 (GPIO16, „Motor Runter") und
    K2 (GPIO14, „Motor Hoch") schalten die Aktuator-Adern in Polaritätsumkehr.
    MPU-6050 hängt an GPIO4 (SDA) / GPIO5 (SCL).
  </figcaption>
</figure>

---

## 2a — SOLL: Power-Pfad mit 12 V-Split

<figure class="fms-fig">
  <div class="fms-frame">
    <a href="img/hardware-esp32-evb/02a_soll_power.svg" title="In voller Größe öffnen">
      <img src="img/hardware-esp32-evb/02a_soll_power.svg" alt="Power-Pfad des neuen Aufbaus: 12 V-Netzteil auf zwei WAGO-221-Klemmen, Zweig A über Mini-360-Buck auf 5,0 V und DC-Hohlstecker zum Olimex-DC-Jack, Zweig B direkt auf REL1-COM und REL2-COM." />
    </a>
  </div>
  <figcaption>
    Die 12 V-Zuleitung wird an zwei WAGO 221 (3-Leiter) aufgeteilt.
    <b>Zweig A (Logik):</b> 12 V → Mini-360 → auf exakt 5.00 V getrimmt →
    DC-Hohlstecker 5.5 × 2.1 mm (Innen = +, Ring = −) → Olimex DC-Jack →
    onboard TPS62A02 → 5 V / 3.3 V.
    <b>Zweig B (Last):</b> 12 V+ direkt an REL1-COM, 12 V− direkt an REL2-COM.
    Gemeinsame Masse ergibt sich automatisch — beide Zweige kommen aus derselben Quelle,
    ein extra GND-Kabel ist nicht nötig.
  </figcaption>
</figure>

---

## 2b — SOLL: Signal- und Lastpfad

<figure class="fms-fig">
  <div class="fms-frame">
    <a href="img/hardware-esp32-evb/02b_soll_signals.svg" title="In voller Größe öffnen">
      <img src="img/hardware-esp32-evb/02b_soll_signals.svg" alt="Signalpfad des neuen Aufbaus: ESP32 steuert REL1 über GPIO32 und REL2 über GPIO33 in Polarity-Reverse zum Linear-Aktuator, MPU-6050 vierdrahtig am UEXT-Stecker Pin 1, 2, 5 und 6." />
    </a>
  </div>
  <figcaption>
    Der ESP32 steuert die beiden <b>Onboard</b>-Relais: REL1 = GPIO32 („Motor Runter"),
    REL2 = GPIO33 („Motor Hoch"). Die Aktuator-Adern hängen in Polarity-Reverse an NO/NC —
    die zwei externen Relais des alten Aufbaus entfallen komplett.
    Der MPU-6050 hängt vierdrahtig am UEXT-Stecker (Pin 1/2/5/6), Pull-ups sind onboard.
  </figcaption>
</figure>

### UEXT-Pinout (Sicht von oben aufs Board, Pin 1 markiert)

```
   1 +3.3V    2 GND
   3 TXD      4 RXD
   5 SCL      6 SDA    ←── MPU-6050 hier
   7 MISO     8 MOSI
   9 SCK     10 SS
```

| MPU-6050 | ALT — ESP12F-Relay-X4 | NEU — Olimex UEXT |
|---|---|---|
| VCC | 3V3 Stiftleiste | **UEXT Pin 1 (+3.3 V)** |
| GND | GND Stiftleiste | **UEXT Pin 2 (GND)** |
| SCL | GPIO5 (D1) | **UEXT Pin 5 → GPIO16** |
| SDA | GPIO4 (D2) | **UEXT Pin 6 → GPIO13** |
| AD0 | an GND (Adr. 0x68) | an GND (unverändert) |

---

## 3 — Klemmen-Detail

<figure class="fms-fig">
  <div class="fms-frame">
    <a href="img/hardware-esp32-evb/03_klemmen_detail.svg" title="In voller Größe öffnen">
      <img src="img/hardware-esp32-evb/03_klemmen_detail.svg" alt="Klemmenplan: WAGO A für 12 V plus und WAGO B für 12 V minus, Mini-360 mit VIN und VOUT, DC-Hohlstecker Innen plus und Ring minus, sowie die Belegung der Olimex-Schraubklemmen REL1-COM, REL1-NO, REL1-NC, REL2-COM, REL2-NO und REL2-NC." />
    </a>
  </div>
  <figcaption>
    Ader für Ader, so wie es in die Klemmen geht. Bei sehr breitem Diagramm:
    Bild anklicken öffnet die SVG in voller Auflösung — SVG ist verlustfrei zoombar.
  </figcaption>
</figure>

### Klemmenbelegung als Tabelle

| Funktion | ALT — ESP12F-Relay-X4 | NEU — Olimex ESP32-EVB-EA |
|---|---|---|
| Steuerung „Motor Runter" | GPIO16 → K1-Spule | **GPIO32 (REL1)** — onboard |
| Steuerung „Motor Hoch" | GPIO14 → K2-Spule | **GPIO33 (REL2)** — onboard |
| 12 V **+** | K1-COM | **REL1-COM** |
| 12 V **−** | K2-COM | **REL2-COM** |
| Aktuator **+** | K1-NO | **REL1-NO + REL2-NC** |
| Aktuator **−** | K2-NO | **REL2-NO + REL1-NC** |
| Board-Versorgung | 12 V an VIN-Klemme | **5.0 V an DC-Jack** (aus Mini-360) |

**Wenn die Motorrichtung verkehrt ist:** entweder `PIN_RELAY1` / `PIN_RELAY2` in `env.py`
tauschen **oder** die Aktuator-Adern mechanisch in den Klemmen kreuzen — nicht beides,
sonst hebt es sich auf.

---

## Sicherheits-Reminder vor dem Power-On

- **Antenne zuerst.** IPEX-Pigtail eingerastet + SMA-Stab aufgeschraubt **vor** dem Einschalten — HF-Reflexion ohne Antenne schädigt das Modul.
- **Mini-360 auf der Werkbank trimmen**, ohne Olimex am Ausgang, mit Multimeter auf 5.00 V. Poti **nie unter Last** verstellen (Overshoot möglich).
- **Aktuator-Adern beim Erstboot abklemmen** — GPIO32/33 wackeln beim Boot, die Relais klicken.
- **Nie 12 V** in irgendeinen Anschluss des Olimex.
- **Keine 230 V** auf die Olimex-Relais — der Aufbau ist mechanisch nicht dafür isoliert.
- Der EVB hat **kein PoE** über RJ45 (das ist die separate `ESP32-POE`-Variante).

---

## Quellen

- [ESP32-EVB Rev.L Schaltplan (PDF, OLIMEX)](https://github.com/OLIMEX/ESP32-EVB/blob/master/HARDWARE/REV-L/ESP32-EVB_Rev_L.pdf)
- [ESP32-EVB User Manual (PDF, OLIMEX)](https://github.com/OLIMEX/ESP32-EVB/blob/master/DOCS/ESP32-EVB-user-manual.pdf)
- [TI TPS62A02 Datenblatt](https://www.ti.com/product/TPS62A02A)

[← zurück zur Startseite](../)
