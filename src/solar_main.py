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

# Zeitsteuerung (nur noch Fallback bei Rechenfehler in is_night)
sunset = 21               # Sonnenuntergang Stunde Fallback
sunrise = 8               # Sonnenaufgang Stunde Fallback (= MORNING_START_HOUR)

# Aktueller Lokal-Offset zur UTC in Stunden (1=MEZ, 2=MESZ) - wird in sync_time gesetzt
tz_offset_hours = 2

# MQTT-Status und Timing
mqtt_connected = False    # MQTT-Verbindungsstatus
last_mqtt_publish = 0     # Letzter MQTT-Publish Zeitstempel
mqtt_publish_interval = 30000  # MQTT-Publish Intervall in ms (30 Sekunden)
last_mqtt_connect_attempt = 0  # Letzter MQTT-Verbindungsversuch
_boot_info_published = False  # tele/solar/BOOT nur einmal je Boot senden
mqtt_reconnect_interval = 60000  # MQTT-Reconnect Intervall in ms (60 Sekunden)
last_mqtt_ping = 0        # Letzter MQTT-Ping (Throttle - sonst 20x/s)
mqtt_ping_interval = 30000     # MQTT-Ping nur alle 30 Sekunden

# Stale-Watchdog: letzter erfolgreicher SENSOR-Publish ans Broker.
# Wenn der Loop laeuft (WDT happy) aber 5 min kein Publish mehr durchgeht,
# sind WLAN/MQTT/Heap tot - dann hilft nur noch ein harter Reboot.
last_successful_publish_ticks = 0
PUBLISH_STALE_MS = 300000      # 5 Minuten ohne erfolgreichen Publish -> machine.reset()

# Self-Echo-Watchdog: ESP publisht alle 60s einen Token auf tele/solar/PING_ECHO
# und subscribed sich selbst auf den Topic. Der Broker liefert die eigene
# Message zurueck -> wir wissen sicher, dass publish + receive funktionieren.
# Faengt den 'silent publish' Fall ab (TCP CLOSE_WAIT, WLAN-Modem stuck), den
# der reine Stale-Watchdog nicht sieht (umqtt.simple publish QoS=0 = fire-and-forget).
last_ping_sent_token = 0       # 0 = noch nie / Echo schon zurueckgekommen
last_ping_sent_ticks = 0
last_echo_seen_ticks = 0       # Zeitpunkt letzter beliebiger empfangener Echo (Heartbeat)
ECHO_INTERVAL_MS = 60000       # PING alle 60s
ECHO_TIMEOUT_MS = 120000       # 2 min ohne Echo-Roundtrip -> machine.reset()

# Periodischer Hard-Reboot: alle 6h sicherer Reset, um Memory-Fragmentation und
# stille Driver-Stalls (die selbst Layer 1+2 ueberleben koennten) zu killen.
boot_ticks = 0
SCHEDULED_REBOOT_MS = 21600000  # 6 * 3600 * 1000 = 6h

# Netzwerk-Keepalive (UDP an Gateway): haelt WLAN-MAC aktiv,
# pflegt ARP-Cache der anderen Hosts im Subnet.
udp_keepalive = None      # UDP-Socket fuer Outbound-Keepalive
udp_keepalive_gw = None   # Gateway-IP (str) fuer das sendto

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
Aktuell: {0}° <small>(roh: {6})</small><br>
Ziel: {1:.1f}°<br>
Motor: {2}<br>
Bereich: {3:.1f}° – {7:.1f}°<br>
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

def _solar_elevation_at(offset_hours=0.0):
    """Sonnen-Elevation (Grad) zu now + offset_hours. Fuer Sunset-Vorausschau."""
    t = time.localtime()
    doy = t[7]
    local_hour = t[3] + t[4]/60.0 + t[5]/3600.0 + offset_hours
    utc_hour = local_hour - tz_offset_hours
    lat = math.radians(getattr(env, "LATITUDE", 48.066))
    lon = getattr(env, "LONGITUDE", 11.667)
    B = math.radians(360.0/365.0 * (doy - 81))
    decl = math.radians(23.45) * math.sin(B)
    eot_min = 9.87*math.sin(2*B) - 7.53*math.cos(B) - 1.5*math.sin(B)
    solar_time = utc_hour + lon/15.0 + eot_min/60.0
    H = math.radians((solar_time - 12.0) * 15.0)
    sin_elev = math.sin(decl)*math.sin(lat) + math.cos(decl)*math.cos(lat)*math.cos(H)
    sin_elev = max(-1.0, min(1.0, sin_elev))
    return math.degrees(math.asin(sin_elev))

def _solar_position():
    """Aktuelle Sonnenposition (elevation, azimuth) in Grad.
    Azimuth: 0=Nord, 90=Ost, 180=Sued, 270=West."""
    t = time.localtime()
    doy = t[7]
    local_hour = t[3] + t[4]/60.0 + t[5]/3600.0
    utc_hour = local_hour - tz_offset_hours
    lat = math.radians(getattr(env, "LATITUDE", 48.066))
    lon = getattr(env, "LONGITUDE", 11.667)
    B = math.radians(360.0/365.0 * (doy - 81))
    decl = math.radians(23.45) * math.sin(B)
    eot_min = 9.87*math.sin(2*B) - 7.53*math.cos(B) - 1.5*math.sin(B)
    solar_time = utc_hour + lon/15.0 + eot_min/60.0
    H = math.radians((solar_time - 12.0) * 15.0)
    sin_elev = math.sin(decl)*math.sin(lat) + math.cos(decl)*math.cos(lat)*math.cos(H)
    sin_elev = max(-1.0, min(1.0, sin_elev))
    elev = math.asin(sin_elev)
    den = math.cos(elev)*math.cos(lat)
    if abs(den) < 1e-9:
        azi = math.pi
    else:
        cos_azi = (math.sin(decl) - math.sin(elev)*math.sin(lat)) / den
        cos_azi = max(-1.0, min(1.0, cos_azi))
        azi = math.acos(cos_azi)
    if H > 0:
        azi = 2*math.pi - azi
    return math.degrees(elev), math.degrees(azi)


def calculate_optimal_angle():
    """Panel-Neigung folgt der Sonnen-Elevation: tilt = 90 - elev.
    Single-Axis Tracker mit Nord-Sued-Kippachse: Panel zeigt damit immer
    moeglichst senkrecht zur aktuellen Sonnenhoehe. Auf MIN/MAX clamped."""
    try:
        elev_deg, _ = _solar_position()
        if elev_deg <= 0:
            return env.MIN_ANGLE
        tilt_deg = 90.0 - elev_deg
        min_a = env.MIN_ANGLE
        max_a = getattr(env, "MAX_ANGLE", 70.0)
        result = max(min_a, min(max_a, tilt_deg))
        print("Sonne: elev={:.1f}deg -> ideal={:.1f}deg -> Ziel={:.1f}deg".format(
            elev_deg, tilt_deg, result))
        return round(result, 1)
    except Exception as e:
        print("Winkel-Berechnung Fehler:", e)
        return env.MIN_ANGLE

def is_night():
    """Nacht-/Ruhephase fuer den Tracker.
    - Vor MORNING_START_HOUR (Default 08:00 lokal) -> Nacht (Panel flach).
    - Sonst pruefen, ob in SUNSET_MARGIN_HOURS (Default 1.0 h) die Sonne unter
      dem Horizont steht. Wenn ja -> jetzt schon flach hinlegen.
    - Fallback bei Rechenfehler: alte feste Stunden-Logik (sunrise/sunset)."""
    t = time.localtime()
    morning_start = int(getattr(env, "MORNING_START_HOUR", 8))
    if t[3] < morning_start:
        return True
    try:
        margin = float(getattr(env, "SUNSET_MARGIN_HOURS", 1.0))
        if _solar_elevation_at(margin) <= 0.0:
            return True
        return False
    except Exception:
        return t[3] >= sunset

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
            global tz_offset_hours
            tz_offset_hours = 2 if is_dst else 1
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

def load_calibration():
    """Persistierten Offset aus /calib.json laden (ueberschreibt env-Defaults)."""
    try:
        with open("/calib.json", "r") as f:
            d = ujson.loads(f.read())
        if "SENSOR_OFFSET" in d:
            env.SENSOR_OFFSET = float(d["SENSOR_OFFSET"])
            print("Calib geladen: SENSOR_OFFSET =", env.SENSOR_OFFSET)
        if "SENSOR_SIGN" in d:
            env.SENSOR_SIGN = int(d["SENSOR_SIGN"])
            print("Calib geladen: SENSOR_SIGN =", env.SENSOR_SIGN)
    except OSError:
        pass  # keine Calib-Datei -> env-Defaults aktiv
    except Exception as e:
        print("Calib-Load Fehler:", e)


def save_calibration():
    """Aktuellen Offset/Sign nach /calib.json persistieren."""
    try:
        d = {
            "SENSOR_OFFSET": getattr(env, "SENSOR_OFFSET", 0.0),
            "SENSOR_SIGN": getattr(env, "SENSOR_SIGN", 1),
        }
        with open("/calib.json", "w") as f:
            f.write(ujson.dumps(d))
        print("Calib gespeichert:", d)
        return True
    except Exception as e:
        print("Calib-Save Fehler:", e)
        return False


def mqtt_on_message(topic, msg):
    """Callback fuer eingehende MQTT-Befehle (cmnd/solar/...) und Self-Echo."""
    global emergency_mode, target, manual_override, angle, current_angle
    global last_ping_sent_token, last_echo_seen_ticks
    try:
        t = topic.decode() if isinstance(topic, (bytes, bytearray)) else topic
        m_raw = msg.decode() if isinstance(msg, (bytes, bytearray)) else msg
        # Echo-Topic ist hot-path (alle 60s) - nicht spammig loggen
        if t.endswith("/PING_ECHO"):
            last_echo_seen_ticks = time.ticks_ms()
            # Wenn empfangener Token == zuletzt gesendeter, ist Roundtrip bestaetigt
            try:
                if int(m_raw) == last_ping_sent_token:
                    last_ping_sent_token = 0  # consumed
            except Exception:
                pass
            return
        m = m_raw.strip().lower()
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
                    target = angle if not is_night() else env.MIN_ANGLE
                    print("EMERGENCY OFF - target={:.1f}".format(target))
                    mqtt_publish_debug("Emergency OFF")
                try:
                    mqtt.publish(f"{env.MQTT_TOPIC_SENSOR}/Emergency", "true" if new else "false")
                except:
                    pass
        elif t.endswith("/SETANGLE"):
            # Live-Kalibrierung: User misst echten Winkel, schickt Wert -> wir
            # rechnen den Offset so, dass PanelAngle dem entspricht. raw bleibt,
            # nur env.SENSOR_OFFSET wird angepasst und persistiert.
            try:
                target_actual = float(m_raw.strip())
            except Exception:
                mqtt_publish_debug("SETANGLE: payload nicht numerisch")
                return
            if current_angle_raw is None:
                mqtt_publish_debug("SETANGLE: noch kein MPU-Wert, ignoriert")
                return
            sign = getattr(env, "SENSOR_SIGN", 1) or 1
            new_offset = current_angle_raw - (target_actual / sign)
            env.SENSOR_OFFSET = new_offset
            save_calibration()
            current_angle = round(sign * (current_angle_raw - new_offset), 1)
            print("Kalibrierung: SENSOR_OFFSET={:.2f} (raw={:.2f} -> {:.1f}deg)".format(
                new_offset, current_angle_raw, target_actual))
            mqtt_publish_debug("SETANGLE {:.1f}deg -> offset={:.2f}".format(target_actual, new_offset))
            # Werte sofort frisch publizieren, sonst sieht HA 30s alte JSON
            try:
                mqtt_publish_sensor_data()
            except:
                pass
        elif t.endswith("/RECALC"):
            # Manueller Trigger: Sun-Position sofort neu rechnen
            angle = calculate_optimal_angle()
            if not emergency_mode and not is_night():
                target = angle
            mqtt_publish_debug("Recalc angle={:.1f}deg target={:.1f}deg".format(angle, target))
    except Exception as e:
        print("MQTT-Callback Fehler:", e)


def mqtt_connect():
    """MQTT-Verbindung aufbauen und auf Commands subscriben."""
    global mqtt, mqtt_connected, system_status
    try:
        if mqtt:
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
        print(f"MQTT verbunden mit {env.MQTT_SERVER}:{env.MQTT_PORT}")

        # Subscribe auf Command-Topics (retain-Messages kommen sofort)
        cmd_base = getattr(env, 'MQTT_TOPIC_CMD', 'cmnd/solar')
        for sub in ("/EMERGENCY", "/SETANGLE", "/RECALC"):
            try:
                mqtt.subscribe(cmd_base + sub)
                print("Subscribed:", cmd_base + sub)
            except Exception as e:
                print("Subscribe-Fehler:", cmd_base + sub, e)

        # Self-Echo-Watchdog: auf eigenen PING_ECHO-Topic subscriben.
        # Broker liefert eigene publishes zurueck -> wir sehen sicher dass
        # publish + receive WIRKLICH durch's Netz gegangen sind (nicht nur
        # ein QoS=0 fire-and-forget das stillschweigend verloren ging).
        try:
            mqtt.subscribe(b"tele/solar/PING_ECHO")
            print("Subscribed: tele/solar/PING_ECHO (Self-Echo-Watchdog)")
        except Exception as e:
            print("Subscribe-Fehler PING_ECHO:", e)

        # Status-Nachricht senden
        mqtt_publish_status("online", retain=True)

        # Boot-Info einmalig retained publizieren (aus /_boot_info.txt von boot.py)
        try:
            _publish_boot_info_once()
        except Exception as e:
            print("Boot-Info-Publish Fehler:", e)

        return True

    except Exception as e:
        mqtt_connected = False
        system_status['last_error'] = f"MQTT connect error: {str(e)}"
        print(f"MQTT-Verbindung fehlgeschlagen: {e}")
        return False

def _publish_boot_info_once():
    """Liest /_boot_info.txt (von boot.py geschrieben) und publiziert es
    einmalig retained nach tele/solar/BOOT, damit HA den letzten Reset-Grund
    auch dann sieht, wenn der ESP gerade offline ist."""
    global _boot_info_published
    if _boot_info_published or not mqtt_connected:
        return
    try:
        with open("_boot_info.txt", "r") as f:
            line = f.read().strip()
    except OSError:
        line = "rc=UNK code=-1 heap=0 t=0"
    try:
        t = time.localtime()
        ts = "{:02d}.{:02d}.{:04d} {:02d}:{:02d}:{:02d}".format(
            t[2], t[1], t[0], t[3], t[4], t[5])
    except Exception:
        ts = ""
    dev = getattr(env, "MQTT_CLIENT_ID", "esp_solar")
    payload = '{"Time":"' + ts + '","Boot":"' + line + '","Device":"' + dev + '"}'
    try:
        mqtt.publish("tele/solar/BOOT", payload, retain=True)
        _boot_info_published = True
        print("BOOT publiziert:", payload)
    except Exception as e:
        print("tele/solar/BOOT publish Fehler:", e)

def mqtt_publish_sensor_data():
    """Sensordaten via MQTT veröffentlichen"""
    global system_status, last_successful_publish_ticks
    if not mqtt_connected:
        return False
    
    try:
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
                "IsNight": is_night()
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

        # Nur EIN JSON-Payload publishen (HA holt sich Werte per value_template).
        # Frueher: 1 JSON + 11 Einzeltopics = 12 publish/Cycle = ~12kB Heap-Burn.
        # Heute: 1 publish, GC vor und nach dumps fuer minimale Heap-Spitze.
        gc.collect()
        payload = ujson.dumps(sensor_data)
        sensor_data = None  # Referenz freigeben vor publish
        mqtt.publish(env.MQTT_TOPIC_SENSOR, payload)
        payload = None
        gc.collect()

        # %-format statt f-string: spart String-Allocations im hot path
        print("MQTT-Daten gesendet: Panel=%.1f Ziel=%.1f Sonne=%.1f Heap=%d" %
              (current_angle if current_angle is not None else -999.0,
               target, angle, gc.mem_free()))
        last_successful_publish_ticks = time.ticks_ms()
        return True

    except Exception as e:
        print("MQTT-Publish Fehler:", e)
        system_status['last_error'] = "MQTT publish error: " + str(e)
        return False

def mqtt_publish_status(status, retain=False):
    """Status-Nachricht via MQTT senden"""
    if not mqtt_connected:
        return False
    
    try:
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

def mqtt_publish_debug(message):
    """Debug-Nachricht via MQTT senden"""
    if not mqtt_connected:
        return False
    
    try:
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

            emerg_banner = "<div class='emerg'>NOTFALL aktiv - Panel flach auf MIN_ANGLE</div>" if emergency_mode else ""
            response_body = html_template.format(
                angle_text, target, motion_text, env.MIN_ANGLE, env.MIN_ANGLE,
                current_time, raw_text, max_angle, emerg_banner
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
    global last_mqtt_publish, system_status, mqtt_connected, last_successful_publish_ticks
    global last_ping_sent_token, last_ping_sent_ticks, last_echo_seen_ticks

    last_sensor_read = 0
    last_angle_calc = 0
    last_time_sync = 0
    last_print_time = 0
    last_printed_angle = None
    last_gc = 0
    last_sleep_check = 0
    last_keepalive = 0
    last_wlan_check = 0
    WLAN_CHECK_INTERVAL_MS = 30000   # alle 30s pruefen ob Assoziation noch steht

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

            # WLAN-Assoziation pruefen - wenn der AP wegfaellt,
            # bleibt der ESP sonst stundenlang ohne Netzwerk-Stack erreichbar
            # waehrend der Loop weiterlaeuft + WDT brav gefuettert wird.
            # Vor MQTT-Check, damit ein MQTT-Reconnect nicht in tote Sockets rennt.
            if time.ticks_diff(current_time, last_wlan_check) > WLAN_CHECK_INTERVAL_MS:
                last_wlan_check = current_time
                try:
                    _wlan = network.WLAN(network.STA_IF)
                    if not _wlan.isconnected():
                        print("WLAN getrennt - reconnect zu", env.WIFI_SSID)
                        mqtt_connected = False
                        try:
                            _wlan.disconnect()
                        except Exception:
                            pass
                        try:
                            _wlan.active(True)
                            _wlan.connect(env.WIFI_SSID, env.WIFI_PASSWORD)
                        except Exception as e:
                            print("WLAN reconnect Fehler:", e)
                        # Modem-Sleep nach Reconnect wieder hart auf NONE
                        try:
                            esp.sleep_type(esp.SLEEP_NONE)
                        except Exception:
                            pass
                except Exception as e:
                    print("WLAN-Check Fehler:", e)

            # Stale-Watchdog: wenn der Loop laeuft, aber 5 min lang kein MQTT-Publish
            # mehr durchgegangen ist, sind WLAN/MQTT/Heap so kaputt, dass nur ein
            # harter Reboot hilft. Greift wenn WLAN-Reconnect + mqtt_check_connection
            # alleine die Verbindung nicht mehr zurueckholen koennen (z.B. OOM).
            if last_successful_publish_ticks != 0 and time.ticks_diff(current_time, last_successful_publish_ticks) > PUBLISH_STALE_MS:
                stale_ms = time.ticks_diff(current_time, last_successful_publish_ticks)
                print("Stale-Watchdog: kein Publish seit %d ms - machine.reset()" % stale_ms)
                try:
                    with open("_reset_info.txt", "w") as _f:
                        _f.write("stale-publish %dms heap=%d\n" % (stale_ms, gc.mem_free()))
                except Exception:
                    pass
                try:
                    rel1.off(); rel2.off()
                except Exception:
                    pass
                time.sleep(1)  # Log/Relay-Aus durchlassen
                machine.reset()

            # Self-Echo-Watchdog (L2): faengt den 'silent publish' Fall ab den
            # der reine Stale-Watchdog nicht sieht (QoS=0 publish() returnt success
            # auch bei TCP CLOSE_WAIT / WLAN-Modem-Stuck).
            # Loesung: ESP publisht alle 60s einen Token, broker liefert ihn an
            # uns selbst zurueck via Subscribe. 120s kein Echo -> machine.reset().
            if mqtt_connected:
                if time.ticks_diff(current_time, last_ping_sent_ticks) > ECHO_INTERVAL_MS:
                    try:
                        last_ping_sent_token = current_time & 0x3FFFFFFF or 1  # nie 0
                        mqtt.publish(b"tele/solar/PING_ECHO", str(last_ping_sent_token).encode())
                        last_ping_sent_ticks = current_time
                        # Grace bei erstem Ping: last_echo_seen_ticks auf jetzt setzen
                        if last_echo_seen_ticks == 0:
                            last_echo_seen_ticks = current_time
                    except Exception as e:
                        print("Echo-Publish Fehler:", e)
                # Timeout-Check (nur wenn schon mal gepingt wurde)
                if last_echo_seen_ticks != 0 and time.ticks_diff(current_time, last_echo_seen_ticks) > ECHO_TIMEOUT_MS:
                    elapsed = time.ticks_diff(current_time, last_echo_seen_ticks)
                    print("Echo-Watchdog: %d ms ohne Roundtrip - machine.reset()" % elapsed)
                    try:
                        with open("_reset_info.txt", "w") as _f:
                            _f.write("echo-timeout %dms heap=%d\n" % (elapsed, gc.mem_free()))
                    except Exception:
                        pass
                    try:
                        rel1.off(); rel2.off()
                    except Exception:
                        pass
                    time.sleep(1)
                    machine.reset()

            # Periodischer Hard-Reboot (L3): alle 6h sicheres Reset, killt
            # akkumulierte Memory-Fragmentation und stille Driver-Stalls
            # die selbst L1+L2 ueberleben koennten. Pragmatisch & garantiert.
            if boot_ticks != 0 and time.ticks_diff(current_time, boot_ticks) > SCHEDULED_REBOOT_MS:
                uptime_ms = time.ticks_diff(current_time, boot_ticks)
                print("Scheduled-Reboot: %d ms uptime erreicht - machine.reset()" % uptime_ms)
                try:
                    with open("_reset_info.txt", "w") as _f:
                        _f.write("scheduled-6h %dms heap=%d\n" % (uptime_ms, gc.mem_free()))
                except Exception:
                    pass
                try:
                    rel1.off(); rel2.off()
                except Exception:
                    pass
                time.sleep(1)
                machine.reset()

            # MQTT-Verbindung prüfen
            mqtt_check_connection()

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
            
            # Recalculate angle every 10 minutes (Emergency override hat Vorrang)
            if time.ticks_diff(current_time, last_angle_calc) > 600000:
                angle = calculate_optimal_angle()
                if emergency_mode:
                    target = env.MIN_ANGLE
                elif is_night():
                    target = env.MIN_ANGLE
                else:
                    target = angle
                print("Neues Ziel: {:.1f}° (Sonne: {:.1f}°, Emergency={}) - {}".format(
                    target, angle, emergency_mode, get_formatted_time()
                ))
                last_angle_calc = current_time

                # Debug-Nachricht via MQTT
                mqtt_publish_debug(f"Angle recalculated: Sun={angle:.1f}° Target={target:.1f}°")
            
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
    global last_successful_publish_ticks, boot_ticks

    print("Initialisierung...")
    gc.collect()
    # Stale-Watchdog: Grace-Window startet ab init(). 5 Minuten ohne
    # ersten Publish nach Boot -> Reboot.
    last_successful_publish_ticks = time.ticks_ms()
    # Scheduled-Reboot (L3): boot_ticks markiert Boot-Zeitpunkt fuer 6h-Timer.
    boot_ticks = time.ticks_ms()

    # Kalibrierung aus /calib.json laden (ueberschreibt env.SENSOR_OFFSET/_SIGN)
    load_calibration()

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
    elif is_night():
        target = env.MIN_ANGLE
    else:
        target = angle
    print("Ziel: {:.1f}° (Sonne: {:.1f}°)".format(target, angle))

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