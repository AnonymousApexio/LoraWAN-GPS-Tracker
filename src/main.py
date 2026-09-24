import time
import pycom
from network import WLAN
from lib.mqtt import MQTTClient
from lib.pycoproc_2 import Pycoproc 
from lib.L76GNSS import L76GNSS

# --- Configuration ---
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
MQTT_TOPIC = "sae501/vehicule/pos"
CLIENT_ID = "pycom-sae501"

# --- 1. Initialisation Pytrack (via Pycoproc) + GNSS ---
# On initialise la carte via Pycoproc en lui spécifiant le type de shield
py = Pycoproc(Pycoproc.PYTRACK) 
gps = L76GNSS(pytrack=py, timeout=30)  # Liaison avec le module GPS

# --- 2. Connexion MQTT ---
print("Connexion au broker MQTT...")
client = MQTTClient(CLIENT_ID, MQTT_BROKER, port=MQTT_PORT)
client.connect()
print("MQTT connecté !")

# --- 3. Boucle de lecture GNSS + publication MQTT ---
while True:
    try:
        # Retourne (lon, lat) ou (None, None)
        coord = gps.coordinates(debug=False)  

        if coord != (None, None) and coord[0] is not None:
            lon, lat = coord

            payload = '{{"lat":{},"lon":{}}}'.format(lat, lon)

            client.publish(MQTT_TOPIC, payload)

            print("Publié :", payload)
        else:
            print("Pas encore de fix GPS... (Mettez la carte près d'une fenêtre/à l'extérieur)")

    except Exception as e:
        print("Erreur dans la boucle :", e)

    time.sleep(5)