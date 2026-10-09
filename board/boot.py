"""Minimal Wi-Fi bootstrap loaded before main.py by MicroPython."""

AP_SSID = "Natsume の LED Controller"
AP_PASSWORD = ";BPiRW2_Qk1@VOze"
AP_IFCONFIG = (
    "192.168.4.1",
    "255.255.255.0",
    "192.168.4.1",
    "192.168.4.1",
)

import gc
import network
import os
import time


gc.collect()
print(f"[INFO] AP starting with SSID: {AP_SSID}, Password: {AP_PASSWORD} ...")

try:
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(
        essid=AP_SSID,
        password=AP_PASSWORD,
        authmode=network.AUTH_WPA_WPA2_PSK,
    )

    for _ in range(20):
        if ap.active():
            break
        time.sleep_ms(50)

    time.sleep_ms(100)
    ap.ifconfig(AP_IFCONFIG)
    print("[INFO] AP started successfully")
    print(f"[INFO] Host IP: {ap.ifconfig()[0]}")
except Exception as error:
    print("[ERROR] Failed to start AP:", error)
    os._exit(1)
