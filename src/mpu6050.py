# MPU-6050 (GY-521) MicroPython-Treiber für Winkelmessung
# Misst Roll-Winkel zur Panel-Neigung-Bestimmung

import time
import math

class MPU6050:
    # Register-Adressen
    ADDR = 0x68
    PWR_MGMT_1 = 0x6B
    ACCEL_XOUT_H = 0x3B
    ACCEL_YOUT_H = 0x3D
    ACCEL_ZOUT_H = 0x3F
    GYRO_XOUT_H = 0x43

    def __init__(self, i2c, address=0x68):
        self.i2c = i2c
        self.address = address
        self._init_sensor()

    def _init_sensor(self):
        try:
            # Wake up sensor (clear SLEEP bit)
            self.i2c.writeto_mem(self.address, self.PWR_MGMT_1, b'\x00')
            time.sleep_ms(100)
            print(f"MPU-6050 auf I2C-Adresse 0x{self.address:02x} initialisiert")
        except Exception as e:
            print(f"MPU-6050 Initialisierung fehlgeschlagen: {e}")
            raise

    def _read_raw_data(self, register):
        """Liest 2 Bytes und wandelt zu 16-Bit signed integer"""
        try:
            data = self.i2c.readfrom_mem(self.address, register, 2)
            value = (data[0] << 8) | data[1]
            if value > 32767:
                value -= 65536
            return value
        except Exception as e:
            print(f"Fehler beim Lesen von Register 0x{register:02x}: {e}")
            return 0

    def get_accel(self):
        """Gibt X, Y, Z Beschleunigung in g zurück"""
        try:
            accel_x = self._read_raw_data(self.ACCEL_XOUT_H) / 16384.0
            accel_y = self._read_raw_data(self.ACCEL_YOUT_H) / 16384.0
            accel_z = self._read_raw_data(self.ACCEL_ZOUT_H) / 16384.0
            return accel_x, accel_y, accel_z
        except Exception as e:
            print(f"Fehler beim Auslesen der Beschleunigung: {e}")
            return 0, 0, 0

    def get_angle_roll(self):
        """
        Berechnet Roll-Winkel aus Beschleunigungsdaten
        Roll-Winkel: Rotation um X-Achse (nach vorne/hinten kippen)
        Bereich: -90° bis +90°
        Positiv = Panel nach oben geneigt
        """
        try:
            accel_x, accel_y, accel_z = self.get_accel()

            # Roll aus Accel_Y und Accel_Z berechnen
            # atan2(Y, Z) gibt Winkel zur Vertikalen
            roll = math.atan2(accel_y, accel_z) * 180 / math.pi

            return round(roll, 1)
        except Exception as e:
            print(f"Fehler bei Winkelberechnung: {e}")
            return None

    def get_angle_pitch(self):
        """
        Berechnet Pitch-Winkel aus Beschleunigungsdaten
        Pitch-Winkel: Rotation um Y-Achse (links/rechts drehen)
        Bereich: -90° bis +90°
        """
        try:
            accel_x, accel_y, accel_z = self.get_accel()

            # Pitch aus Accel_X und Accel_Z berechnen
            pitch = math.atan2(-accel_x, math.sqrt(accel_y**2 + accel_z**2)) * 180 / math.pi

            return round(pitch, 1)
        except Exception as e:
            print(f"Fehler bei Pitch-Berechnung: {e}")
            return None
