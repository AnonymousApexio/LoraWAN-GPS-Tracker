# --- WiFi / MQTT (mode "WIFI") ---
WIFI_SSID = "<WIFI_SSID>"
WIFI_PASS = "<WIFI_PASS>"
MQTT_BROKER = "<MQTT_BROKER>"
MQTT_PORT = 1883
MQTT_TOPIC = "<MQTT_TOPIC>"
# Identifiant unique, derive du numero de serie de la carte (evite l'erreur MQTT 104)
CLIENT_ID = "<CLIENT_ID>"
WIFI_INTERVAL = 5        # secondes entre deux publications MQTT
PUSHBULLET_TOKEN = "<PUSHBULLET_TOKEN>" # Token Pushbullet pour les notifications

# --- LoRaWAN OTAA (mode "LORA") ---
# Valeurs copiees depuis la page du device sur TTN, format hex MSB, sans espaces.
# NE PAS pousser ces cles sur un depot GitHub public.
DEV_EUI = "<DEV_EUI>"                   # DevEUI  (MAC LoRa du FiPy)
APP_EUI = "<APP_EUI>"                   # JoinEUI
APP_KEY = "<APP_KEY>"   # AppKey  (32 caracteres hex)