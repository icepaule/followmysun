# ESP32 Solar Panel Controller mit MPU-6050, MQTT, NTP und Webinterface
#
# Hardware:
# - MPU-6050 (GY-521) Gyro/Accel Sensor zur Winkelmessung
# - 2x Relays zur Motorsteuerung (Hoch/Runter)
# - ESP32 mit WLAN-Verbindung
#
# Funktionen:
# - Automatische Sonnenwinkel-Berechnung basierend auf Astronomie
# - NTP-Zeitaktualisierung mit präziser deutscher Zeitzone (MEZ/MESZ)
# - MQTT-Übertragung aller Sensordaten und Status
# - Webinterface zur manuellen Steuerung und Überwachung
# - WebREPL für Fernwartung
#
# Autor: Solar Controller v2.1
# Datum: 24.05.2025

import machine
import time
import network
import gc
import esp
import socket
import errno
import math
import uselect
import ujson
import uos
from umqtt.simple import MQTTClient
from mpu6050 import MPU6050

import env
print("env.py geladen")
# WebREPL wird bereits in boot.py gestartet.

# =============================================================================
# GLOBALE VARIABLEN UND KONFIGURATION
# =============================================================================

# Hardware-Objekte
sensor = None               # MPU-6050 Gyroskop/Accel-Sensor-Objekt
rel1 = None                # Relay 1 (Motor Runter)
rel2 = None                # Relay 2 (Motor Hoch)
mqtt = None                # MQTT-Client-Objekt
srv = None                 # Webserver-Socket-Objekt
wdt = None                 # Hardware-Watchdog (None bis init() erfolgreich war)

# Sensor- und Steuerungsdaten
current_angle = None       # Kalibrierter Panel-Winkel in Grad zur Horizontalen
current_angle_raw = None   # Roh-MPU-Wert (atan2 unkalibriert) - fuer Kalibrierung
angle = 35.0              # Berechneter optimaler Sonnenwinkel in Grad
target = 30.0             # Ziel-Neigungswinkel basierend auf Sonnenwinkel in Grad
tolerance = 2.0           # Toleranz für Winkelabweichung in Grad
motion_dir = 0            # Motor-Richtung: 0=Stopp, 1=Hoch, 2=Runter
manual_override = False   # Manueller Modus aktiv (True/False)
emergency_mode = False    # Notfall: Panel SOFORT auf MIN_ANGLE (Sturm-Schutz)

# Zeitsteuerung
sunset = 18               # Sonnenuntergang Stunde (lokale Zeit, grobes Fallback)
sunrise = 6               # Sonnenaufgang Stunde (lokale Zeit, grobes Fallback)

# Tracking-Aktiv-Fenster: Panel-Nachfuehrung laeuft nur zwischen TRACK_START_H
# und (echter Sonnenuntergang - TRACK_END_BEFORE_SUNSET_H). Davor und danach
# bleibt das Panel flach auf MIN_ANGLE liegen (Stromertrag in Randzeiten
# rechtfertigt die Verfahrwege nicht und reduziert Verschleiss/Risiko).
TRACK_START_H = 8.0
TRACK_END_BEFORE_SUNSET_H = 1.0

# MQTT-Status und Timing
mqtt_connected = False    # MQTT-Verbindungsstatus
last_mqtt_publish = 0     # Letzter MQTT-Publish Zeitstempel
mqtt_publish_interval = 30000  # MQTT-Publish Intervall in ms (30 Sekunden)
last_mqtt_connect_attempt = 0  # Letzter MQTT-Verbindungsversuch
mqtt_reconnect_interval = 60000  # MQTT-Reconnect Intervall in ms (60 Sekunden)
last_mqtt_ping = 0        # Letzter MQTT-Ping (Throttle - sonst 20x/s)
mqtt_ping_interval = 30000     # MQTT-Ping nur alle 30 Sekunden

# MQTT-Socket-Timeout in Sekunden. umqtt.simple legt den Socket OHNE Timeout
# an -> ein publish()/ping() auf eine tote bzw. halb-offene TCP-Verbindung
# blockiert dann *unendlich* in socket.send(). Fatal: waehrend eines
# blockierenden Syscalls fuettert das SDK beide Watchdogs (HW + Soft) weiter,
# es kommt also KEIN Reset - das Geraet haengt komplett und nur ein physischer
# Reset hilft. Genau dieses Symptom ("morgens haengt die Steuerung") killt der
# Timeout: send() wirft nach Ablauf ein OSError, das die vorhandene
# Fehlerbehandlung faengt -> Reconnect + Health-Watchdog greifen wieder.
# Bewusst kurz (< ~3,2 s Soft-WDT-Fenster), damit der Loop nach einem Stall
# weiterlaeuft, bevor irgendein Watchdog zuschlaegt.
MQTT_SOCKET_TIMEOUT = 2

# Netzwerk-Keepalive (UDP an Gateway): haelt WLAN-MAC aktiv,
# pflegt ARP-Cache der anderen Hosts im Subnet.
udp_keepalive = None      # UDP-Socket fuer Outbound-Keepalive
udp_keepalive_gw = None   # Gateway-IP (str) fuer das sendto

# Connectivity-Watchdog: Der Hardware-WDT (3s) faengt nur CPU-Hangs.
# Ein Netzwerk-Stall (WLAN noch "connected", aber MQTT-Socket tot, Loop
# laeuft munter weiter und fuettert den WDT) ueberlebt den HW-WDT.
# Darum tracken wir den letzten erfolgreichen MQTT-Publish und reseten
# das System wenn zu lange Funkstille herrscht.
last_successful_publish = 0          # ticks_ms() des letzten erfolgreichen publish
last_health_check = 0                # ticks_ms() der letzten Health-Pruefung
HEALTH_CHECK_INTERVAL_MS = 60000     # Health alle 60s pruefen
HEALTH_SOFT_RECONNECT_MS = 300000    # Nach 5 min Stille: WLAN+MQTT neu verbinden
HEALTH_HARD_RESET_MS = 900000        # Nach 15 min Stille: machine.reset()

# Reset-Cause-Diagnose: boot.py schreibt /_boot_info.txt mit dem letzten
# reset_cause(). Nach dem ersten erfolgreichen MQTT-Connect publishen wir
# das einmal auf tele/solar/BOOT (retained) - so kann der Broker auch nach
# einem 'raetselhaften' Stall belegen, welcher Reset-Typ wirklich gegriffen hat.
_boot_info_published = False

# System-Status für Monitoring
system_status = {
    'uptime': 0,          # Betriebszeit in Sekunden
    'heap_free': 0,       # Freier Heap-Speicher in Bytes
    'wifi_rssi': 0,       # WLAN-Signalstärke in dBm
    'last_error': None,   # Letzter aufgetretener Fehler
    'boot_time': None,    # Boot-Zeitstempel
    'ntp_sync_count': 0   # Anzahl erfolgreicher NTP-Synchronisationen
}

# HTML Template
html_template = """<!DOCTYPE html>
<html><head>
<meta http-equiv='refresh' content='5'>
<meta charset='UTF-8'>
<style>
body {{ background:#fff; font-family:sans-serif; padding:10px; }}
b {{ font-size:16px; }}
small {{ color:#666; }}
.emerg {{ background:#c00; color:#fff; padding:6px; margin-bottom:8px; font-weight:bold; }}
input,button {{ padding:4px; margin:2px; font-size:14px; }}
form {{ margin:8px 0; }}
</style></head><body>
{8}
<b>Solarpanel</b><br>
Aktuell: {0} <small>(roh: {6})</small><br>
Ziel: {1:.1f}°<br>
Motor: {2}<br>
Bereich: {3:.1f}° – {7:.1f}°<br>
Tracking: {9}<br>
<form method='POST'>
<input name='minangle' type='number' step='0.1' value='{4:.1f}'>
<input name='save' type='submit' value='Min setzen'>
<input name='reset' type='submit' value='Reset'>
</form>
<form method='POST'>
<button name='manual' value='down'>⬇️</button>
<button name='manual' value='up'>⬆️</button>
<button name='manual' value='auto'>🔁</button>
</form><small>Zeit: {5}</small>
</body></html>"""

# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def calculate_optimal_angle():
    """Optimaler Panel-Neigungswinkel (Grad zur Horizontalen, Sued-Ausrichtung)
    so dass die direkte Sonneneinstrahlung moeglichst senkrecht aufs Panel trifft.

    beta_opt = 90 - Sonnenhoehe(t, lat, lon)
    Sonnenhoehe per Standard-Astronomie (Deklination + Stundenwinkel).
    Frueher hier: base+decl+seasonal - das stand im Sommer falsch herum (steiler
    statt flacher) und lag bei hoher Sonne ~25 Grad daneben.
    """
    try:
        # Standort Muenchen
        lat = 48.1351
        lon = 11.5820

        # ESP-RTC laeuft auf lokaler Wandzeit (MEZ/MESZ, gesetzt in sync_time).
        # Fuer den Stundenwinkel brauchen wir UTC.
        t = time.localtime()
        month = t[1]
        hour = t[3]
        minute = t[4]
        doy = t[7]

        # MESZ etwa April-September, MEZ Nov-Februar. In Maerz/Oktober ist die
        # Heuristik um max 2 Tage daneben - das verschiebt beta_opt um <0.3 Grad.
        is_dst = 4 <= month <= 9 or month in (3, 10)
        tz_offset_h = 2 if is_dst else 1
        utc_h = (hour - tz_offset_h) + minute / 60.0

        # Deklination der Sonne
        decl = 23.45 * math.sin(math.radians(360 / 365 * (doy - 81)))

        # Zeitgleichung (Minuten)
        B = math.radians(360 / 365 * (doy - 81))
        eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)

        # Wahre Ortszeit am Laengengrad (Stunden)
        lst = utc_h + lon / 15.0 + eot / 60.0

        # Stundenwinkel (Grad, 0=Mittag, positiv = Nachmittag/West)
        omega = math.radians((lst - 12.0) * 15.0)

        # Sonnenhoehe ueber Horizont
        phi = math.radians(lat)
        delta = math.radians(decl)
        sin_h = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(omega)
        if sin_h > 1.0:
            sin_h = 1.0
        elif sin_h < -1.0:
            sin_h = -1.0
        elevation = math.degrees(math.asin(sin_h))

        optimal = 90.0 - elevation

        print("Astro: doy={} decl={:.1f} lst={:.2f}h elev={:.1f} beta_opt={:.1f}".format(
            doy, decl, lst, elevation, optimal))

        # Auf mechanische Endlagen des Aktuators clampen
        max_a = getattr(env, "MAX_ANGLE", 70.0)
        return max(env.MIN_ANGLE, min(max_a, round(optimal, 1)))
    except Exception as e:
        print("Winkel-Berechnung Fehler:", e)
        return env.MIN_ANGLE

def is_night():
    t = time.localtime()
    return t[3] < sunrise or t[3] >= sunset

def calculate_sunset_local_h():
    """Sonnenuntergang als lokale Wandzeit in Stunden (Float, z.B. 21.5 = 21:30).
    Aus dem Stundenwinkel beim Untergang: cos(omega) = -tan(phi)*tan(delta).
    Selbe Astronomie-Konstanten wie calculate_optimal_angle()."""
    try:
        lat = 48.1351
        lon = 11.5820
        t = time.localtime()
        month = t[1]
        doy = t[7]
        is_dst = 4 <= month <= 9 or month in (3, 10)
        tz_offset_h = 2 if is_dst else 1

        decl = 23.45 * math.sin(math.radians(360 / 365 * (doy - 81)))
        B = math.radians(360 / 365 * (doy - 81))
        eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)

        phi = math.radians(lat)
        delta = math.radians(decl)
        cos_omega = -math.tan(phi) * math.tan(delta)
        if cos_omega < -1.0 or cos_omega > 1.0:
            # Polartag/Polarnacht - in Muenchen unerreichbar. Fallback.
            return 18.0
        omega_sunset_rad = math.acos(cos_omega)
        half_day_h = math.degrees(omega_sunset_rad) / 15.0
        lst_sunset = 12.0 + half_day_h
        local_h = lst_sunset - lon / 15.0 - eot / 60.0 + tz_offset_h
        if local_h < 0:
            local_h += 24
        if local_h >= 24:
            local_h -= 24
        return local_h
    except Exception as e:
        print("Sunset-Berechnung Fehler:", e)
        return 18.0

def _current_local_h():
    t = time.localtime()
    return t[3] + t[4] / 60.0 + t[5] / 3600.0

def _fmt_hours_hhmm(h):
    """Float-Stunde -> 'HH:MM' (z.B. 20.5 -> '20:30')."""
    try:
        if h < 0:
            h += 24
        if h >= 24:
            h -= 24
        hh = int(h)
        mm = int(round((h - hh) * 60))
        if mm == 60:
            hh = (hh + 1) % 24
            mm = 0
        return "{:02d}:{:02d}".format(hh, mm)
    except Exception:
        return "--:--"

def tracking_window():
    """Liefert (start_h, end_h) des heutigen Aktiv-Fensters in lokalen Stunden."""
    start_h = TRACK_START_H
    end_h = calculate_sunset_local_h() - TRACK_END_BEFORE_SUNSET_H
    return start_h, end_h

def is_tracking_active():
    """True wenn das Panel aktuell aktiv nachgefuehrt werden soll.
    Ausserhalb -> target wird auf MIN_ANGLE gezogen (Panel flach)."""
    start_h, end_h = tracking_window()
    now_h = _current_local_h()
    return start_h <= now_h < end_h

def get_formatted_time():
    """Formatierte deutsche Zeit zurückgeben"""
    try:
        t = time.localtime()
        return "{:02d}.{:02d}.{} {:02d}:{:02d}:{:02d}".format(
            t[2], t[1], t[0], t[3], t[4], t[5]
        )
    except:
        return "Zeitfehler"

def sync_time():
    """NTP-Zeitaktualisierung mit präziser deutscher Zeitzone"""
    global system_status
    try:
        import ntptime
        print("Synchronisiere Zeit via NTP...")
        
        # Deutsche NTP-Server verwenden
        ntp_servers = [
            "pool.ntp.org",
            "de.pool.ntp.org", 
            "time.google.com",
            "ptbtime1.ptb.de"
        ]
        
        success = False
        for server in ntp_servers:
            try:
                ntptime.host = server
                ntptime.settime()
                success = True
                system_status['ntp_sync_count'] += 1
                print(f"Zeit synchronisiert mit {server}")
                break
            except Exception as e:
                print(f"NTP-Server {server} nicht erreichbar: {e}")
                continue
        
        if success:
            # Präzise deutsche Sommerzeit-Berechnung
            utc_time = time.localtime()
            year = utc_time[0]
            month = utc_time[1]
            day = utc_time[2]
            hour = utc_time[3]
            
            # Sommerzeit in Deutschland: Letzter Sonntag im März bis letzter Sonntag im Oktober
            # Berechnung der Übergangstage
            def last_sunday_of_month(year, month):
                # Letzter Tag des Monats
                if month == 12:
                    next_month_first = time.mktime((year + 1, 1, 1, 0, 0, 0, 0, 0, 0))
                else:
                    next_month_first = time.mktime((year, month + 1, 1, 0, 0, 0, 0, 0, 0))
                last_day = time.localtime(next_month_first - 86400)[2]
                
                # Finde letzten Sonntag
                for d in range(last_day, last_day - 7, -1):
                    weekday = time.localtime(time.mktime((year, month, d, 0, 0, 0, 0, 0, 0)))[6]
                    if weekday == 6:  # Sonntag
                        return d
                return last_day  # Fallback
            
            # Sommerzeit-Grenzen berechnen
            dst_start_day = last_sunday_of_month(year, 3)   # Letzter Sonntag im März
            dst_end_day = last_sunday_of_month(year, 10)    # Letzter Sonntag im Oktober
            
            # Prüfung ob aktuell Sommerzeit
            is_dst = False
            if month < 3 or month > 10:
                is_dst = False  # Januar, Februar, November, Dezember
            elif month > 3 and month < 10:
                is_dst = True   # April bis September
            elif month == 3:
                # März: Nach dem letzten Sonntag um 2:00 MEZ (1:00 UTC)
                if day > dst_start_day:
                    is_dst = True
                elif day == dst_start_day and hour >= 1:  # 2:00 MEZ = 1:00 UTC
                    is_dst = True
            elif month == 10:
                # Oktober: Vor dem letzten Sonntag um 3:00 MESZ (1:00 UTC)
                if day < dst_end_day:
                    is_dst = True
                elif day == dst_end_day and hour < 1:  # 3:00 MESZ = 1:00 UTC
                    is_dst = True
            
            # Zeitzone anwenden
            tz_offset = 7200 if is_dst else 3600  # MESZ: UTC+2, MEZ: UTC+1
            local_timestamp = time.mktime(utc_time) + tz_offset
            local_time = time.localtime(local_timestamp)
            
            # System-Zeit auf lokale Zeit setzen (MicroPython Workaround)
            try:
                # Zeitverschiebung für interne Uhr
                machine.RTC().datetime((
                    local_time[0], local_time[1], local_time[2], 
                    local_time[6], local_time[3], local_time[4], 
                    local_time[5], 0
                ))
            except:
                pass  # Fallback falls RTC nicht verfügbar
            
            # Boot-Zeit setzen wenn noch nicht gesetzt
            if system_status['boot_time'] is None:
                system_status['boot_time'] = get_formatted_time()
            
            print(f"Aktuelle Zeit: {local_time[2]:02d}.{local_time[1]:02d}.{local_time[0]} {local_time[3]:02d}:{local_time[4]:02d}:{local_time[5]:02d}")
            print(f"Zeitzone: {'MESZ (UTC+2)' if is_dst else 'MEZ (UTC+1)'}")
            
            # Debug-Informationen
            print(f"DST-Start: {dst_start_day}.03.{year}, DST-Ende: {dst_end_day}.10.{year}")
            
            return True
        else:
            print("Alle NTP-Server nicht erreichbar - verwende Systemzeit")
            system_status['last_error'] = "NTP sync failed"
            return False
            
    except ImportError:
        print("ntptime-Modul nicht verfügbar")
        system_status['last_error'] = "ntptime module missing"
        return False
    except Exception as e:
        print(f"Zeit-Synchronisation fehlgeschlagen: {e}")
        system_status['last_error'] = f"NTP sync error: {str(e)}"
        return False

# =============================================================================
# MQTT FUNKTIONEN
# =============================================================================

def mqtt_on_message(topic, msg):
    """Callback fuer eingehende MQTT-Befehle (cmnd/solar/...)."""
    global emergency_mode, target, manual_override, angle
    try:
        t = topic.decode() if isinstance(topic, (bytes, bytearray)) else topic
        m = (msg.decode() if isinstance(msg, (bytes, bytearray)) else msg).strip().lower()
        print("MQTT cmd:", t, "=", m)
        if t.endswith("/EMERGENCY"):
            new = m in ("on", "1", "true", "yes")
            if new != emergency_mode:
                emergency_mode = new
                manual_override = False
                if new:
                    target = env.MIN_ANGLE
                    print("EMERGENCY ON - target=MIN_ANGLE ({})".format(env.MIN_ANGLE))
                    mqtt_publish_debug("Emergency ON")
                else:
                    angle = calculate_optimal_angle()
                    target = angle if is_tracking_active() else env.MIN_ANGLE
                    print("EMERGENCY OFF - target={:.1f}".format(target))
                    mqtt_publish_debug("Emergency OFF")
                # State sofort zurueckspiegeln
                try:
                    mqtt.publish(f"{env.MQTT_TOPIC_SENSOR}/Emergency", "true" if new else "false")
                except:
                    pass
    except Exception as e:
        print("MQTT-Callback Fehler:", e)


def _mqtt_arm_timeout():
    """Setzt den Socket-Timeout auf dem aktiven MQTT-Socket (neu).
    MUSS vor jedem blockierenden publish()/ping()/disconnect() aufgerufen
    werden: umqtt.simple.check_msg() setzt den Socket per setblocking(True)
    jedes Mal wieder auf 'blockierend OHNE Timeout' zurueck. Ohne dieses
    Neu-Setzen kann ein einzelnes publish() den Loop fuer immer einfrieren
    (siehe Kommentar bei MQTT_SOCKET_TIMEOUT)."""
    try:
        if mqtt is not None and getattr(mqtt, 'sock', None) is not None:
            mqtt.sock.settimeout(MQTT_SOCKET_TIMEOUT)
    except Exception:
        pass


def mqtt_connect():
    """MQTT-Verbindung aufbauen und auf Commands subscriben."""
    global mqtt, mqtt_connected, system_status
    try:
        if mqtt:
            # Alter Socket koennte haengen -> Timeout setzen, damit das
            # disconnect() (sendet ein DISCONNECT-Paket) nicht blockiert.
            _mqtt_arm_timeout()
            try:
                mqtt.disconnect()
            except:
                pass

        mqtt = MQTTClient(
            env.MQTT_CLIENT_ID,
            env.MQTT_SERVER,
            port=env.MQTT_PORT,
            user=env.MQTT_USER,
            password=env.MQTT_PASSWORD,
            keepalive=60
        )
        mqtt.set_callback(mqtt_on_message)
        mqtt.connect()
        mqtt_connected = True
        # Frischer Socket -> sofort Timeout setzen, schuetzt alle folgenden
        # publish()/ping()-Aufrufe vor dem Endlos-Block.
        _mqtt_arm_timeout()
        print(f"MQTT verbunden mit {env.MQTT_SERVER}:{env.MQTT_PORT}")

        # Subscribe auf Command-Topics (retain-Messages kommen sofort)
        cmd_base = getattr(env, 'MQTT_TOPIC_CMD', 'cmnd/solar')
        cmd_topic = cmd_base + "/EMERGENCY"
        try:
            mqtt.subscribe(cmd_topic)
            print("Subscribed:", cmd_topic)
        except Exception as e:
            print("Subscribe-Fehler:", e)

        # Status-Nachricht senden
        mqtt_publish_status("online", retain=True)

        # Boot-Diagnose einmalig publishen (retained, ueberlebt also Broker-Restart)
        _publish_boot_info_once()
        return True

    except Exception as e:
        mqtt_connected = False
        system_status['last_error'] = f"MQTT connect error: {str(e)}"
        print(f"MQTT-Verbindung fehlgeschlagen: {e}")
        return False

def mqtt_publish_sensor_data():
    """Sensordaten via MQTT veröffentlichen"""
    global system_status, last_successful_publish, mqtt_connected
    if not mqtt_connected:
        return False
    
    try:
        # Heap defragmentieren BEVOR der grosse JSON-Payload gebaut wird -
        # der ESP8266 laeuft chronisch knapp (~6 kB frei), und genau dieser
        # Publish ist der groesste Einzel-Allokationspeak im Loop.
        gc.collect()
        # check_msg() hat den Socket-Timeout evtl. geloescht -> neu setzen.
        _mqtt_arm_timeout()
        # System-Status aktualisieren
        system_status['uptime'] = time.ticks_ms() // 1000
        system_status['heap_free'] = gc.mem_free()
        
        # WLAN-Signalstärke ermitteln
        try:
            wlan = network.WLAN(network.STA_IF)
            if wlan.isconnected():
                system_status['wifi_rssi'] = wlan.status('rssi') if hasattr(wlan, 'status') else -50
        except:
            system_status['wifi_rssi'] = -99
        
        # Hauptdaten-Payload erstellen
        sensor_data = {
            "Time": get_formatted_time(),
            "SENSOR": {
                "PanelAngle": round(current_angle, 1) if current_angle is not None else None,
                "PanelAngleRaw": round(current_angle_raw, 1) if current_angle_raw is not None else None,
                "TargetAngle": round(target, 1),
                "SunAngle": round(angle, 1),
                "MinAngle": round(env.MIN_ANGLE, 1),
                "MaxAngle": round(getattr(env, "MAX_ANGLE", 70.0), 1),
                "SensorOffset": getattr(env, "SENSOR_OFFSET", 0.0),
                "SensorSign": getattr(env, "SENSOR_SIGN", 1),
                "Tolerance": tolerance,
                "Motion": motion_dir,
                "MotionText": ["Stopp", "Hoch", "Runter"][motion_dir],
                "Manual": manual_override,
                "Emergency": emergency_mode,
                "IsNight": is_night(),
                "TrackingActive": is_tracking_active(),
                "TrackingStart": _fmt_hours_hhmm(tracking_window()[0]),
                "TrackingEnd": _fmt_hours_hhmm(tracking_window()[1])
            },
            "SYSTEM": {
                "Uptime": system_status['uptime'],
                "HeapFree": system_status['heap_free'],
                "WiFiRSSI": system_status['wifi_rssi'],
                "NTPSyncCount": system_status['ntp_sync_count'],
                "BootTime": system_status['boot_time'],
                "LastError": system_status['last_error']
            },
            "STATUS": {
                "Online": True,
                "IP": network.WLAN(network.STA_IF).ifconfig()[0] if network.WLAN(network.STA_IF).isconnected() else "0.0.0.0"
            }
        }

        # JSON-Payload senden
        payload = ujson.dumps(sensor_data)
        mqtt.publish(env.MQTT_TOPIC_SENSOR, payload)

        # Einzelne Topics fuer Home-Assistant-Sensoren (HA mag das lieber als JSON-Pfade)
        base = env.MQTT_TOPIC_SENSOR
        max_a = getattr(env, "MAX_ANGLE", 70.0)
        mqtt.publish(f"{base}/PanelAngle",    str(round(current_angle, 1)) if current_angle is not None else "null")
        mqtt.publish(f"{base}/PanelAngleRaw", str(round(current_angle_raw, 1)) if current_angle_raw is not None else "null")
        mqtt.publish(f"{base}/TargetAngle",   str(round(target, 1)))
        mqtt.publish(f"{base}/SunAngle",      str(round(angle, 1)))
        mqtt.publish(f"{base}/Motion",        str(motion_dir))
        mqtt.publish(f"{base}/MotionText",    ["Stopp", "Hoch", "Runter"][motion_dir])
        mqtt.publish(f"{base}/Manual",        "true" if manual_override else "false")
        mqtt.publish(f"{base}/MinAngle",      str(round(env.MIN_ANGLE, 1)))
        mqtt.publish(f"{base}/MaxAngle",      str(round(max_a, 1)))
        mqtt.publish(f"{base}/IsNight",       "true" if is_night() else "false")
        mqtt.publish(f"{base}/Emergency",     "true" if emergency_mode else "false")
        # Tracking-Status fuer HA-Sensoren
        _ts, _te = tracking_window()
        mqtt.publish(f"{base}/TrackingActive", "true" if is_tracking_active() else "false")
        mqtt.publish(f"{base}/TrackingStart",  _fmt_hours_hhmm(_ts))
        mqtt.publish(f"{base}/TrackingEnd",    _fmt_hours_hhmm(_te))

        # current_angle kann None sein (vereinzelter I2C-Read-Fehler) - dann darf
        # die f-string-Formatierung nicht crashen, sonst wird last_successful_publish
        # nie aktualisiert und der Health-Watchdog feuert einen falsch-positiven Reset.
        panel_str = "{:.1f}".format(current_angle) if current_angle is not None else "None"
        print("MQTT-Daten gesendet: Panel={}°, Ziel={:.1f}°, Sonne={:.1f}°".format(panel_str, target, angle))
        # Health-Marker: Beweis dass die MQTT-Pipe wirklich Daten transportiert hat.
        last_successful_publish = time.ticks_ms()
        return True

    except Exception as e:
        print(f"MQTT-Publish Fehler: {e}")
        system_status['last_error'] = f"MQTT publish error: {str(e)}"
        # Publish gescheitert (z.B. Socket-Timeout) -> Verbindung als tot
        # markieren, damit mqtt_check_connection() sauber neu verbindet,
        # statt 30 s spaeter wieder in denselben Timeout zu laufen.
        mqtt_connected = False
        return False

def mqtt_publish_status(status, retain=False):
    """Status-Nachricht via MQTT senden"""
    if not mqtt_connected:
        return False
    
    try:
        _mqtt_arm_timeout()
        status_data = {
            "Time": get_formatted_time(),
            "Status": status,
            "Device": env.MQTT_CLIENT_ID,
            "IP": network.WLAN(network.STA_IF).ifconfig()[0] if network.WLAN(network.STA_IF).isconnected() else "unknown"
        }
        
        payload = ujson.dumps(status_data)
        mqtt.publish(f"stat/{env.MQTT_CLIENT_ID}/STATUS", payload, retain=retain)
        return True
        
    except Exception as e:
        print(f"MQTT-Status Fehler: {e}")
        return False

# Reset-Cause-Codes des ESP8266 (system_get_rst_info()->reason). Achtung:
# diese decken sich NICHT 1:1 mit machine.*_RESET - Code 2 und 3 haben gar
# keine machine-Konstante, darum hier die vollstaendige Tabelle.
_RESET_CAUSE_NAMES = {
    0: "PWRON",       # Kaltstart / Power-On
    1: "HW_WDT",      # Hardware-Watchdog
    2: "EXCEPTION",   # Firmware-Crash (fatal exception) - Verdacht: RAM-Mangel
    3: "SOFT_WDT",    # Software-Watchdog (CPU-Stall > ~3,2 s)
    4: "SOFT_RESET",  # machine.reset() - z.B. unser Health-Watchdog
    5: "DEEPSLEEP",   # Deep-Sleep-Aufwachen
    6: "EXT_RESET",   # externer Reset (Reset-Knopf / EN-Pin)
}


def _publish_boot_info_once():
    """Sendet die Boot-Diagnose einmal pro Run auf tele/solar/BOOT (retained).

    Quelle ist machine.reset_cause() LIVE - bewusst NICHT die Datei
    _boot_info.txt: boot.py's Datei-Logging hat sich als unzuverlaessig
    erwiesen (last_boot.txt friert ein, Schreibzugriffe schlagen still fehl).
    reset_cause() dagegen stimmt immer. So zeigt das retained Topic nach
    einem naechtlichen Stall verlaesslich, welcher Reset-Typ gegriffen hat -
    ohne dass man live am USB haengen muss."""
    global _boot_info_published
    if _boot_info_published or not mqtt_connected:
        return
    try:
        rc = machine.reset_cause()
    except Exception:
        rc = -1
    rc_name = _RESET_CAUSE_NAMES.get(rc, "UNK")
    try:
        with open("_boot_info.txt", "r") as f:
            file_info = f.read().strip()
    except OSError:
        file_info = "(no file)"
    try:
        _mqtt_arm_timeout()
        payload = ujson.dumps({
            "Time": get_formatted_time(),
            "ResetCause": rc,
            "ResetName": rc_name,
            "HeapFree": gc.mem_free(),
            "BootFile": file_info,
            "Device": env.MQTT_CLIENT_ID
        })
        mqtt.publish("tele/solar/BOOT", payload, retain=True)
        _boot_info_published = True
        print("MQTT BOOT info published: cause={} ({}) heap={}".format(
            rc, rc_name, gc.mem_free()))
    except Exception as e:
        print("BOOT-Publish Fehler:", e)


def mqtt_publish_debug(message):
    """Debug-Nachricht via MQTT senden"""
    if not mqtt_connected:
        return False
    
    try:
        _mqtt_arm_timeout()
        debug_data = {
            "Time": get_formatted_time(),
            "Debug": message,
            "Device": env.MQTT_CLIENT_ID
        }
        
        payload = ujson.dumps(debug_data)
        debug_topic = getattr(env, 'MQTT_TOPIC_DEBUG', 'stat/solar/DEBUG')
        mqtt.publish(debug_topic, payload)
        return True
        
    except Exception as e:
        print(f"MQTT-Debug Fehler: {e}")
        return False

def health_check():
    """Connectivity-Watchdog: erkennt Netzwerk-Stalls die der HW-WDT nicht sieht.

    Trigger ist 'Zeit seit letztem erfolgreichen MQTT-Publish'. Da der Loop
    alle 30s ein publish versucht, ist 5 min Stille schon ein klares Signal
    dass die TCP-Pipe oder das WLAN-Routing hin sind, obwohl wlan.isconnected()
    noch True meldet (typischer FritzBox-/Modem-Sleep-Stall).

    Eskalation:
      - >5 min Stille  -> sanfter Reconnect (WLAN disconnect+connect + MQTT-Reconnect)
      - >15 min Stille -> harter machine.reset() (WLAN-Stack komplett tot)
    """
    global last_health_check, last_successful_publish

    current_time = time.ticks_ms()
    if time.ticks_diff(current_time, last_health_check) < HEALTH_CHECK_INTERVAL_MS:
        return
    last_health_check = current_time

    # Solange noch nie etwas publiziert wurde (frischer Boot ohne Broker)
    # ist die Bezugszeit der Boot-Moment. Sonst kickt der Watchdog sofort.
    if last_successful_publish == 0:
        last_successful_publish = current_time
        return

    silence_ms = time.ticks_diff(current_time, last_successful_publish)
    silence_s = silence_ms // 1000

    if silence_ms > HEALTH_HARD_RESET_MS:
        print("HEALTH: {} s ohne MQTT-Publish -> machine.reset()".format(silence_s))
        try:
            mqtt_publish_debug("Health: hard reset after {}s silence".format(silence_s))
        except Exception:
            pass
        # Relays sicherheitshalber aus, bevor wir resetten
        try:
            rel1.off(); rel2.off()
        except Exception:
            pass
        time.sleep(1)
        machine.reset()

    if silence_ms > HEALTH_SOFT_RECONNECT_MS:
        print("HEALTH: {} s ohne MQTT-Publish -> WLAN+MQTT reconnect".format(silence_s))
        try:
            wlan = network.WLAN(network.STA_IF)
            wlan.disconnect()
            time.sleep_ms(500)
            wlan.connect(env.WIFI_SSID, env.WIFI_PASSWORD)
            # Kurz warten, dem WLAN Zeit fuers Reassoc geben - aber WDT (3s) im Blick
            for _ in range(20):
                if wlan.isconnected():
                    break
                if wdt is not None:
                    wdt.feed()
                time.sleep_ms(100)
            # ARP-Cache am Gateway frisch halten
            try:
                if udp_keepalive is not None and udp_keepalive_gw is not None:
                    udp_keepalive.sendto(b'.', (udp_keepalive_gw, 9))
            except Exception:
                pass
        except Exception as e:
            print("Health: WLAN-Reconnect Fehler:", e)
        # MQTT-Reconnect erzwingen (mqtt_connect schliesst alten Socket implizit)
        mqtt_connect()


def mqtt_check_connection():
    """MQTT-Verbindung pruefen und ggf. wiederherstellen.
    WICHTIG: ping() darf NICHT jede Loop-Iteration aufgerufen werden
    (das waren 20 Pings/Sekunde - Broker schliesst dann ECONNRESET).
    check_msg() darf aber jede Iteration laufen - das ist nonblocking."""
    global mqtt_connected, last_mqtt_connect_attempt, last_mqtt_ping

    current_time = time.ticks_ms()

    # Nur alle 60 Sekunden Reconnect versuchen
    if not mqtt_connected and time.ticks_diff(current_time, last_mqtt_connect_attempt) > mqtt_reconnect_interval:
        print("MQTT-Reconnect Versuch...")
        last_mqtt_connect_attempt = current_time
        mqtt_connect()

    # Eingehende Commands abholen (nonblocking) - ruft mqtt_on_message bei Bedarf
    if mqtt_connected:
        try:
            mqtt.check_msg()
        except Exception as e:
            print("check_msg Fehler:", e)
            mqtt_connected = False

    # Ping gedrosselt: nur alle 30s (Standard-Keepalive-Pattern)
    if mqtt_connected and time.ticks_diff(current_time, last_mqtt_ping) > mqtt_ping_interval:
        try:
            _mqtt_arm_timeout()
            mqtt.ping()
            last_mqtt_ping = current_time
        except:
            print("MQTT-Verbindung verloren")
            mqtt_connected = False

# =============================================================================
# WEBSERVER-FUNKTIONEN
# =============================================================================

def handle_web_request():
    global manual_override, motion_dir
    try:
        # Check if connection is available (non-blocking)
        conn, addr = srv.accept()
        print("Client verbunden:", addr)

        # WDT vor potenziell blockierender Operation fuettern - sonst kann
        # Web-Request + UDP + Sensor zusammen ueber die 3s WDT-Frist gehen.
        if wdt is not None:
            wdt.feed()

        # Set connection to blocking mode for reliable data transfer.
        # 0.5s recv-Timeout: Browser sendet das Request in <100ms.
        # Laenger waere nur "zaeher Client" - der darf gerne den WDT triggern.
        conn.setblocking(True)
        conn.settimeout(0.5)
        
        try:
            # Receive request with timeout
            request = conn.recv(1024)
            if not request:
                return
            
            # MicroPython compatible decode
            try:
                req_str = request.decode('utf-8')
            except:
                req_str = str(request)
            
            print("Request empfangen")
            
            # Handle POST requests
            if "POST" in req_str:
                if "minangle=" in req_str:
                    try:
                        # Find value between minangle= and next & or space
                        start = req_str.find("minangle=") + 9
                        end = req_str.find("&", start)
                        if end == -1:
                            end = req_str.find(" ", start)
                        if end == -1:
                            end = len(req_str)
                        v = req_str[start:end]
                        env.MIN_ANGLE = max(0, min(70, float(v)))
                        print("Min-Angle gesetzt auf:", env.MIN_ANGLE)
                    except Exception as e:
                        print("Angle parse error:", e)
                        
                elif "reset" in req_str:
                    env.MIN_ANGLE = 32.0
                    print("Reset auf 32°")
                    
                elif "manual=" in req_str:
                    try:
                        start = req_str.find("manual=") + 7
                        end = req_str.find("&", start)
                        if end == -1:
                            end = req_str.find(" ", start)
                        if end == -1:
                            end = len(req_str)
                        m = req_str[start:end]
                        
                        if m == "up":
                            manual_override = True
                            rel1.off()
                            rel2.on()
                            motion_dir = 1
                            print("Manuell: Hoch")
                            mqtt_publish_debug("Manual: Up")
                        elif m == "down":
                            manual_override = True
                            rel1.on()
                            rel2.off()
                            motion_dir = 2
                            print("Manuell: Runter")
                            mqtt_publish_debug("Manual: Down")
                        elif m == "auto":
                            manual_override = False
                            rel1.off()
                            rel2.off()
                            motion_dir = 0
                            print("Auto-Modus")
                            mqtt_publish_debug("Auto mode")
                    except Exception as e:
                        print("Manual parse error:", e)
            
            # Prepare response
            angle_text = "Fehler" if current_angle is None else "{:.1f}°".format(current_angle)
            raw_text   = "--" if current_angle_raw is None else "{:.1f}°".format(current_angle_raw)
            motion_text = ["Stopp", "Hoch", "Runter"][motion_dir]
            current_time = get_formatted_time()
            max_angle = getattr(env, "MAX_ANGLE", 70.0)

            # Tracking-Status fuer das Web-Frontend - menschenlesbar
            _start_h, _end_h = tracking_window()
            _window_str = "{}-{}".format(_fmt_hours_hhmm(_start_h), _fmt_hours_hhmm(_end_h))
            if is_tracking_active():
                tracking_text = "aktiv (Fenster {})".format(_window_str)
            else:
                tracking_text = "pausiert - Panel flach (Fenster {})".format(_window_str)

            emerg_banner = "<div class='emerg'>NOTFALL aktiv - Panel flach auf MIN_ANGLE</div>" if emergency_mode else ""
            response_body = html_template.format(
                angle_text, target, motion_text, env.MIN_ANGLE, env.MIN_ANGLE,
                current_time, raw_text, max_angle, emerg_banner, tracking_text
            )
            
            # Send complete HTTP response
            response = "HTTP/1.1 200 OK\r\n"
            response += "Content-Type: text/html; charset=UTF-8\r\n"
            response += "Content-Length: {}\r\n".format(len(response_body))
            response += "Connection: close\r\n"
            response += "\r\n"
            response += response_body
            
            # MicroPython compatible send mit send-Loop (single send() kann
            # bei >1KB truncieren, dann sieht der Client einen IncompleteRead).
            data = response.encode('utf-8')
            sent = 0
            while sent < len(data):
                n = conn.send(data[sent:])
                if not n:
                    break
                sent += n
            print("Response gesendet ({} bytes)".format(sent))
            
        except OSError as e:
            if e.args[0] != 11:  # Ignore EAGAIN
                print("Request handling error:", e)
        except Exception as e:
            print("Request handling error:", e)
        finally:
            try:
                conn.close()
            except:
                pass
                
    except OSError as e:
        # EAGAIN (11) means no connection available - this is normal
        if e.args[0] != 11:
            print("Connection error:", e)
    except Exception as e:
        print("Unexpected error:", e)

def start_web():
    global srv
    try:
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('0.0.0.0', 80))
        srv.listen(2)  # Erhöhte Queue
        srv.setblocking(False)
        print("Webserver läuft auf Port 80")
        return True
    except Exception as e:
        print("Webserver Start-Fehler:", e)
        return False

# =============================================================================
# HAUPTFUNKTIONEN
# =============================================================================

def loop():
    global current_angle, current_angle_raw, motion_dir, manual_override, angle, target
    global last_mqtt_publish, system_status
    
    last_sensor_read = 0
    last_angle_calc = 0
    last_time_sync = 0
    last_print_time = 0
    last_printed_angle = None
    last_gc = 0
    last_sleep_check = 0
    last_keepalive = 0

    # Regelungs-Konstanten
    SENSOR_INTERVAL_MS = 150        # MPU schnell pollen, damit Stop sofort greift
    PRINT_INTERVAL_MS = 2000        # Log mindestens alle 2s, sonst nur bei Wertaenderung
    PRINT_DELTA_DEG = 0.5           # Wert-Aenderung ab der geloggt wird
    START_TOLERANCE = 2.0           # Motor starten ab dieser Abweichung vom Ziel
    STOP_TOLERANCE = 0.5            # Motor stoppen sobald Diff < diesem Wert (Traegheit antizipieren)

    while True:
        try:
            current_time = time.ticks_ms()

            # Check for web requests (non-blocking check)
            handle_web_request()

            # MQTT-Verbindung prüfen
            mqtt_check_connection()

            # Connectivity-Watchdog (ueber HW-WDT hinaus, erkennt Netzwerk-Stalls)
            health_check()

            # Zeit alle 24 Stunden neu synchronisieren
            if time.ticks_diff(current_time, last_time_sync) > 86400000:  # 24h in ms
                print("Tägliche Zeit-Synchronisation...")
                sync_time()
                last_time_sync = current_time

            # Sensor schnell pollen (Stop reagiert in <200ms statt 2s)
            if time.ticks_diff(current_time, last_sensor_read) > SENSOR_INTERVAL_MS:
                try:
                    new_reading = sensor.get_angle_roll()
                    if new_reading is not None:
                        current_angle_raw = new_reading
                        # Kalibrierung roh -> echter Winkel zur Horizontalen
                        sign = getattr(env, "SENSOR_SIGN", 1)
                        offset = getattr(env, "SENSOR_OFFSET", 0.0)
                        current_angle = round(sign * (new_reading - offset), 1)
                        # Print throttling: bei nennenswerter Aenderung ODER PRINT_INTERVAL_MS abgelaufen
                        should_print = (
                            last_printed_angle is None
                            or abs(current_angle - last_printed_angle) >= PRINT_DELTA_DEG
                            or time.ticks_diff(current_time, last_print_time) > PRINT_INTERVAL_MS
                        )
                        if should_print:
                            print("Sensor: {:.1f}° (Ziel: {:.1f}°) - {}".format(
                                current_angle, target, get_formatted_time()
                            ))
                            last_printed_angle = current_angle
                            last_print_time = current_time
                    last_sensor_read = current_time
                except Exception as e:
                    print("Sensor error:", e)
                    system_status['last_error'] = f"Sensor error: {str(e)}"
            
            # Recalculate angle every 10 minutes (Emergency override hat Vorrang,
            # danach Tracking-Aktiv-Fenster - ausserhalb bleibt das Panel flach)
            if time.ticks_diff(current_time, last_angle_calc) > 600000:
                angle = calculate_optimal_angle()
                if emergency_mode:
                    target = env.MIN_ANGLE
                elif not is_tracking_active():
                    target = env.MIN_ANGLE
                else:
                    target = angle
                start_h, end_h = tracking_window()
                print("Neues Ziel: {:.1f}° (Sonne: {:.1f}°, Emergency={}, Tracking-Fenster {}-{}) - {}".format(
                    target, angle, emergency_mode,
                    _fmt_hours_hhmm(start_h), _fmt_hours_hhmm(end_h),
                    get_formatted_time()
                ))
                last_angle_calc = current_time

                # Debug-Nachricht via MQTT
                mqtt_publish_debug(f"Angle recalculated: Sun={angle:.1f}° Target={target:.1f}° Tracking={is_tracking_active()}")
            
            # MQTT-Daten alle 30 Sekunden senden
            if time.ticks_diff(current_time, last_mqtt_publish) > mqtt_publish_interval:
                if mqtt_connected:
                    mqtt_publish_sensor_data()
                last_mqtt_publish = current_time
            
            # Motor control mit asymmetrischer Hysterese:
            # - Start nur wenn |diff| > START_TOLERANCE (vermeidet Mikro-Bewegungen)
            # - Stop schon bei |diff| < STOP_TOLERANCE (antizipiert Aktuator-Auslauf)
            # - Bei Ueberschiessen (Vorzeichenwechsel der Diff): sofort stoppen, nicht zurueckreversen
            old_motion_dir = motion_dir
            if not manual_override and current_angle is not None:
                diff = current_angle - target
                if motion_dir == 0:
                    # Motor steht. Nur starten wenn deutliche Abweichung.
                    if abs(diff) > START_TOLERANCE:
                        if diff > 0:  # zu steil -> runter
                            rel1.on()
                            rel2.off()
                            motion_dir = 2
                            print("Motor: Runter (diff={:.1f}°)".format(diff))
                            mqtt_publish_debug("Motor: Runter")
                        else:  # zu flach -> hoch
                            rel1.off()
                            rel2.on()
                            motion_dir = 1
                            print("Motor: Hoch (diff={:.1f}°)".format(diff))
                            mqtt_publish_debug("Motor: Hoch")
                else:
                    # Motor laeuft. Stop-Bedingungen:
                    overshot = (motion_dir == 2 and diff < 0) or (motion_dir == 1 and diff > 0)
                    if abs(diff) < STOP_TOLERANCE or overshot:
                        rel1.off()
                        rel2.off()
                        motion_dir = 0
                        if overshot:
                            print("Motor: Stopp (Ziel ueberschritten, diff={:.1f}°)".format(diff))
                            mqtt_publish_debug("Motor: Stopp (overshoot)")
                        else:
                            print("Motor: Stopp (diff={:.1f}°)".format(diff))
                            mqtt_publish_debug("Motor: Stopp")
            elif not manual_override:
                # Kein Sensor-Wert verfügbar - Sicherheitsstopp
                if motion_dir != 0:
                    rel1.off()
                    rel2.off()
                    motion_dir = 0
                    print("Motor: Stopp (kein Sensorwert)")
            
            # Bei Statusänderung sofort MQTT senden
            if old_motion_dir != motion_dir and mqtt_connected:
                mqtt_publish_sensor_data()

            # Heap-Fragmentierung gegensteuern (alle 30s)
            if time.ticks_diff(current_time, last_gc) > 30000:
                gc.collect()
                last_gc = current_time

            # WLAN-Modem-Sleep alle 60s zur Sicherheit auf NONE pruefen.
            # Manche WLAN-Events koennen das Setting kippen.
            if time.ticks_diff(current_time, last_sleep_check) > 60000:
                try:
                    if esp.sleep_type() != esp.SLEEP_NONE:
                        esp.sleep_type(esp.SLEEP_NONE)
                except Exception:
                    pass
                last_sleep_check = current_time

            # UDP-Keepalive an Gateway: alle 1s ein 1-Byte-Paket.
            # Haelt WLAN-Modem aktiv (kein Modem-Sleep) und sorgt dafuer,
            # dass die ARP-Caches anderer Geraete im Subnet die ESP-MAC
            # immer kennen. Empfaenger braucht nichts zu hoeren.
            if udp_keepalive is not None and time.ticks_diff(current_time, last_keepalive) > 1000:
                try:
                    udp_keepalive.sendto(b'.', (udp_keepalive_gw, 9))
                except Exception:
                    pass
                last_keepalive = current_time

            # Watchdog beruhigen - solange wir hier landen, lebt der Loop
            if wdt is not None:
                wdt.feed()

            # Short sleep to prevent CPU overload
            time.sleep(0.05)
            
        except Exception as e:
            print("Loop-Fehler:", e)
            system_status['last_error'] = f"Loop error: {str(e)}"
            # Sicherheit: Relays aus bei Fehler
            try:
                rel1.off()
                rel2.off()
                motion_dir = 0
                mqtt_publish_debug(f"Emergency stop: {str(e)}")
            except:
                pass
            time.sleep(1)

def init():
    global sensor, rel1, rel2, angle, target, wdt
    global udp_keepalive, udp_keepalive_gw

    print("Initialisierung...")
    gc.collect()

    # Hardware Setup
    try:
        # I2C-Bus initialisieren (SoftI2C fuer ESP8266, beliebige GPIOs)
        # 100 kHz statt 400 kHz wegen verlaengertem CAT5-Kabel (~2,5 m) zum MPU
        i2c = machine.SoftI2C(scl=machine.Pin(env.PIN_I2C_SCL), sda=machine.Pin(env.PIN_I2C_SDA), freq=100000)

        # MPU-6050 initialisieren (Standard-Adresse 0x68)
        sensor = MPU6050(i2c)

        # Relays initialisieren
        rel1 = machine.Pin(env.PIN_RELAY1, machine.Pin.OUT)
        rel2 = machine.Pin(env.PIN_RELAY2, machine.Pin.OUT)
        rel1.off()
        rel2.off()
        print("Hardware initialisiert (I2C + MPU-6050 + Relays)")
    except Exception as e:
        print("Hardware-Fehler:", e)
        return False
    
    # WLAN Setup
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    # Hostname fuer DHCP-Registrierung beim Router (=> solar.local erreichbar)
    try:
        hn = getattr(env, "HOSTNAME", "solar")
        wlan.config(dhcp_hostname=hn)
        print("Hostname:", hn)
    except Exception as e:
        print("Hostname-Setz-Fehler:", e)

    # Optionale statische IP-Konfiguration (Tuple: ip, netmask, gateway, dns)
    static = getattr(env, "STATIC_IP", None)
    if static:
        try:
            wlan.ifconfig(static)
            print("Statische IP gesetzt:", static[0])
        except Exception as e:
            print("Statische IP fehlgeschlagen:", e)

    # Bei SSID-Wechsel sauber disconnecten, damit der ESP nicht auf das alte WLAN re-attached
    if wlan.isconnected():
        try:
            cur = wlan.config('essid')
            if cur != env.WIFI_SSID:
                print("WLAN-Wechsel: %s -> %s" % (cur, env.WIFI_SSID))
                wlan.disconnect()
                time.sleep_ms(500)
        except Exception as e:
            print("SSID-Check Fehler:", e)

    if not wlan.isconnected():
        print("Verbinde WLAN: %s" % env.WIFI_SSID)
        wlan.connect(env.WIFI_SSID, env.WIFI_PASSWORD)
        
        for i in range(30):
            if wlan.isconnected():
                break
            print(".", end="")
            time.sleep(1)
        print()
    
    if not wlan.isconnected():
        print("WLAN-Verbindung fehlgeschlagen")
        return False
    
    print("WLAN OK:", wlan.ifconfig()[0])

    # WICHTIG: wlan.connect() setzt auf ESP8266 das Modem-Sleep zurueck.
    # Erst hier (nach erfolgreichem Connect) wirkt SLEEP_NONE wirklich.
    try:
        esp.sleep_type(esp.SLEEP_NONE)
        print("Modem-Sleep AUS (sleep_type=NONE) nach Connect")
    except Exception as e:
        print("sleep_type set Fehler:", e)

    # (esp.tx_power existiert auf esp8266-MicroPython nicht - weglassen)

    # UDP-Keepalive-Socket vorbereiten - im Loop alle 1s ans Gateway,
    # haelt WLAN-MAC aktiv und ARP-Cache der anderen Hosts frisch.
    try:
        udp_keepalive = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_keepalive_gw = wlan.ifconfig()[2]
        print("UDP-Keepalive Socket bereit (target {})".format(udp_keepalive_gw))
    except Exception as e:
        print("UDP-Keepalive Setup Fehler:", e)
        udp_keepalive = None
        udp_keepalive_gw = None

    # Zeit synchronisieren nach WLAN-Verbindung
    sync_time()
    
    # MQTT-Verbindung aufbauen
    mqtt_connect()
    
    # Webserver starten
    if not start_web():
        return False
    
    # Initial calculations (Emergency-Flag wird ggf. gleich danach vom
    # ersten check_msg gesetzt - retained-Message vom Broker)
    angle = calculate_optimal_angle()
    if emergency_mode:
        target = env.MIN_ANGLE
    elif not is_tracking_active():
        target = env.MIN_ANGLE
    else:
        target = angle
    start_h, end_h = tracking_window()
    print("Ziel: {:.1f}° (Sonne: {:.1f}°, Tracking-Fenster {}-{})".format(
        target, angle, _fmt_hours_hhmm(start_h), _fmt_hours_hhmm(end_h)))

    # Hardware-Watchdog erst nach erfolgreichem Init aktivieren.
    # ESP8266: Timeout fix ~3s, nicht konfigurierbar. Wird in loop() gefuettert.
    # Wenn der Loop irgendwo haengen bleibt -> automatischer Reset.
    try:
        wdt = machine.WDT()
        print("Watchdog aktiv (~3s Timeout)")
    except Exception as e:
        print("WDT-Init Fehler:", e)
        wdt = None

    return True

# Run when imported (used via tiny main.py loader)
if init():
    print("System bereit - Starte Hauptschleife")
    loop()
else:
    print("Initialisierung fehlgeschlagen")
    try:
        rel1 = machine.Pin(env.PIN_RELAY1, machine.Pin.OUT)
        rel2 = machine.Pin(env.PIN_RELAY2, machine.Pin.OUT)
        rel1.off()
        rel2.off()
    except:
        pass