from controller import LEDController


controller = LEDController()
if not controller.connect():
    raise SystemExit("无法连接 ESP32")

try:
    controller.fill((255, 255, 128), 80)
finally:
    controller.disconnect()
