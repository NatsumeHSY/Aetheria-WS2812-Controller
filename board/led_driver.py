try:
    from .config import (
        COLOR_BLACK,
        LED_COUNT,
        LED_MAX_BRIGHTNESS,
        LED_MIN_BRIGHTNESS,
        LED_PIN,
    )
    from .state import get_global_white_balance
except ImportError:
    from config import (
        COLOR_BLACK,
        LED_COUNT,
        LED_MAX_BRIGHTNESS,
        LED_MIN_BRIGHTNESS,
        LED_PIN,
    )
    from state import get_global_white_balance


def _clamp_byte(value: int) -> int:
    return max(0, min(255, int(value)))


def apply_white_balance(color: tuple[int, int, int], white_balance: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(
        (_clamp_byte(color[index]) * _clamp_byte(white_balance[index])) // 255
        for index in range(3)
    )


def scale_with_brightness(color: tuple[int, int, int], brightness: int) -> tuple[int, int, int]:
    brightness = _clamp_byte(brightness)
    return tuple((_clamp_byte(channel) * brightness) // 255 for channel in color)


class LedDriver:
    def __init__(self) -> None:
        try:
            from machine import Pin
            from neopixel import NeoPixel
        except ImportError as error:
            raise RuntimeError("LedDriver requires MicroPython machine and neopixel modules") from error

        self.np = NeoPixel(Pin(LED_PIN, Pin.OUT), LED_COUNT)
        self.current_state = (0, 0, 0, 0)

    def begin(self) -> None:
        self.np.fill(COLOR_BLACK)
        self.np.write()
        self.current_state = (0, 0, 0, 0)

    def set_pixel(
        self,
        index: int,
        color: tuple[int, int, int],
        brightness: int = 255,
        auto_write: bool = False,
    ) -> None:
        if index < 0 or index >= LED_COUNT:
            return

        corrected = apply_white_balance(color, get_global_white_balance())
        output = scale_with_brightness(corrected, brightness)
        self.np[index] = output
        if auto_write:
            self.np.write()

    def show(self):
        self.np.write()

    def fill(self, color: tuple[int, int, int], brightness: int = 255) -> None:
        corrected = apply_white_balance(color, get_global_white_balance())
        output = scale_with_brightness(corrected, brightness)
        self.np.fill(output)
        self.np.write()
        self.current_state = (
            int(color[0]),
            int(color[1]),
            int(color[2]),
            _clamp_byte(brightness),
        )

    def clear(self) -> None:
        self.np.fill(COLOR_BLACK)
        self.np.write()
        self.current_state = (0, 0, 0, 0)
