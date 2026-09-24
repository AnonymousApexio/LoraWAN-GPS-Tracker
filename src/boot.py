import time
import pycom
from network import WLAN

# boot.py -- run on boot-up
WIFI_SSID = "Anonymous"
WIFI_PASS = "123456789motdepasse"
# --- 1. Connexion WiFi ---
time.sleep(2)
# --- Diagnostic Scan ---
wlan = WLAN()
print("Scan des réseaux environnants...")
print(wlan.scan()) # Va afficher la liste des SSID visibles dans le terminal
wlan.connect(WIFI_SSID, auth=(WLAN.WPA2, WIFI_PASS), timeout=5000)
print("Connexion au WiFi en cours...")
while not wlan.isconnected():
    time.sleep(1)
print("WiFi connecté :", wlan.ifconfig()[0])