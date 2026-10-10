import _thread
import math
import time

try:
    from .config import *
    from .audio_wave import AudioWaveConfig, AudioWaveEffector
    from .led_driver import LedDriver
    from .state import get_global_brightness, get_global_timing
except ImportError:
    from config import *
    from audio_wave import AudioWaveConfig, AudioWaveEffector
    from led_driver import LedDriver
    from state import get_global_brightness, get_global_timing


def xy2pos(x: int, y: int) -> int:
    if y % 2 == 0:
        # even row: left -> right
        return x + y * LED_DOT_PER_LINE
    else:
        # odd row: right -> left
        return (LED_DOT_PER_LINE - 1 - x) + y * LED_DOT_PER_LINE

def rainbow_color(position: int) -> tuple[int, int, int]:
    position = position % 256
    if position < 85:
        return (position * 3, 255 - position * 3, 0)
    if position < 170:
        position -= 85
        return (255 - position * 3, 0, position * 3)
    position -= 170
    return (0, position * 3, 255 - position * 3)

def interpolate_color_state(start: tuple[int, int, int, int], target: tuple[int, int, int, int], step: int, steps: int) -> tuple[int, int, int, int]:
    if steps <= 0 or step >= steps:
        return target
    if step <= 0:
        return start

    values = []
    for index in range(4):
        delta = target[index] - start[index]
        if delta >= 0:
            value = start[index] + (delta * step) // steps
        else:
            value = start[index] - ((-delta * step) // steps)
        values.append(value)
    return tuple(values)

class Effector:
    def __init__(self, driver: LedDriver) -> None:
        self.driver = driver
        self.interrupt_flag = True
        self._effect_generation = 0
        self._effect_lock = _thread.allocate_lock()
        self.audio_wave = AudioWaveEffector(driver)

    def _start_effect(self, clear: bool = True) -> int:
        self.stop(clear=clear)
        self._effect_lock.acquire()
        try:
            self._effect_generation += 1
            self.interrupt_flag = False
            return self._effect_generation
        finally:
            self._effect_lock.release()

    def _effect_active(self, generation: int) -> bool:
        self._effect_lock.acquire()
        try:
            return generation == self._effect_generation and not self.interrupt_flag
        finally:
            self._effect_lock.release()

    def _begin_frame(self, generation: int) -> bool:
        self._effect_lock.acquire()
        if generation != self._effect_generation or self.interrupt_flag:
            self._effect_lock.release()
            return False
        return True

    def _end_frame(self) -> None:
        self.driver.show()
        self._effect_lock.release()

    def _fill_frame(self, generation: int, color: tuple[int, int, int], brightness: int = None) -> bool:
        self._effect_lock.acquire()
        try:
            if generation != self._effect_generation or self.interrupt_flag:
                return False
            if brightness is None:
                self.driver.fill(color)
            else:
                self.driver.fill(color, min(brightness, get_global_brightness()))
            return True
        finally:
            self._effect_lock.release()
    
    def stop(self, clear: bool = True) -> None:
        self._effect_lock.acquire()
        try:
            self._effect_generation += 1
            self.interrupt_flag = True
            if clear:
                self.driver.clear()
        finally:
            self._effect_lock.release()
        self.audio_wave.stop(clear=False)

    def start_audio(self, config: AudioWaveConfig) -> None:
        self._start_effect(clear=False)
        self.audio_wave.start(config)

    def update_audio(self, frame) -> bool:
        return self.audio_wave.update(frame)

    def stop_audio(self, clear: bool = False) -> None:
        self.audio_wave.stop(clear=clear)
        self.stop(clear=clear)
    
    def fade(self, color: tuple[int, int, int] = COLOR_WHITE, start_brightness: int = 0,end_brightness: int = 255) -> None:
        generation = self._start_effect()

        def effect() -> None:
            if start_brightness < end_brightness:
                brightness_range = range(start_brightness, end_brightness + 1)
            else:
                brightness_range = range(start_brightness, end_brightness - 1, -1)

            for bright in  brightness_range:
                if not self._fill_frame(generation, color, bright):
                    return
        
        _thread.start_new_thread(effect, ())

    def transition(self, target: tuple[int, int, int, int], duration: int = 500) -> None:
        start = self.driver.current_state
        target = (
            max(0, min(255, int(target[0]))),
            max(0, min(255, int(target[1]))),
            max(0, min(255, int(target[2]))),
            max(0, min(255, int(target[3]))),
        )
        duration = max(0, int(duration))

        generation = self._start_effect(clear=False)

        steps = max(1, duration // 10)
        interval = max(1, duration // steps) if duration else 1

        def effect() -> None:
            for step in range(steps + 1):
                state = interpolate_color_state(start, target, step, steps)
                if not self._fill_frame(generation, (state[0], state[1], state[2]), state[3]):
                    return

                if step < steps:
                    time.sleep_ms(interval)

        _thread.start_new_thread(effect, ())
    
    def breathe(self, colors: list[tuple[int, int, int]] = [COLOR_WHITE], dark_brightness: int = 0, bright_brightness: int = 255) -> None:
        generation = self._start_effect()

        # check if dark_brightness and bright_brightness are valid
        if dark_brightness > bright_brightness:
            dark_brightness, bright_brightness = bright_brightness, dark_brightness
        
        def effect() -> None:
            color_idx = 0
            steps = max(1, LED_MAX_BRIGHTNESS - dark_brightness)

            while self._effect_active(generation):
                c1 = colors[color_idx]
                c2 = colors[(color_idx + 1) % len(colors)]

                for step in range(steps + 1):
                    if not self._effect_active(generation):
                        return

                    t = step / steps

                    # 呼吸曲线（亮度）
                    k_breathe = 0.5 * (1 - math.cos(2 * math.pi * t))

                    current_bright = max(dark_brightness, get_global_brightness())
                    brightness = dark_brightness + (current_bright - dark_brightness) * k_breathe
                    factor = brightness / 255

                    # 颜色渐变（线性插值）
                    r = int((c1[0] * (1 - t) + c2[0] * t) * factor)
                    g = int((c1[1] * (1 - t) + c2[1] * t) * factor)
                    b = int((c1[2] * (1 - t) + c2[2] * t) * factor)

                    if not self._fill_frame(generation, (r, g, b)):
                        return

                    time.sleep_ms(get_global_timing(20))

                # 下一组颜色
                color_idx = (color_idx + 1) % len(colors)

        _thread.start_new_thread(effect, ())
    
    def blink(self, color: tuple[int, int, int] = COLOR_WHITE, dark_brightness: int = 0, bright_brightness: int = 255, count: int = 1, interval: int = 500) -> None:
        generation = self._start_effect()

        if dark_brightness > bright_brightness:
            dark_brightness, bright_brightness = bright_brightness, dark_brightness

        def blink_once() -> None:
            current_bright = min(bright_brightness, get_global_brightness())
            current_interval = get_global_timing(interval)
            if not self._fill_frame(generation, color, current_bright):
                return False
            time.sleep_ms(current_interval)
            if not self._fill_frame(generation, color, dark_brightness):
                return False
            time.sleep_ms(current_interval)
            return True
        
        def effect() -> None:
            if count == 0:
                while True:
                    if not self._effect_active(generation):
                        return

                    if not blink_once():
                        return
            else:
                for _ in range(count):
                    if not self._effect_active(generation):
                        return

                    if not blink_once():
                        return
        
        _thread.start_new_thread(effect, ())
    
    def scan_line_x(self, color: tuple[int, int, int] = COLOR_WHITE,
                    start_x: int = 0, end_x: int = LED_DOT_PER_LINE - 1, brightness: int = 255,
                    interval: int = 500, duration: int = 1,
                    pingpong: bool = False, rainbow: bool = False) -> None:
        
        generation = self._start_effect()

        if start_x > end_x:
            if start_x >= LED_DOT_PER_LINE:
                start_x = LED_DOT_PER_LINE - 1
            if end_x < 0:
                end_x = 0
        else:
            if start_x < 0:
                start_x = 0
            if end_x >= LED_DOT_PER_LINE:
                end_x = LED_DOT_PER_LINE - 1

        def effect(start_x: int, end_x: int) -> None:
            last_x = None

            while self._effect_active(generation):
                if start_x < end_x:
                    x_range = range(start_x, end_x + 1)
                else:
                    x_range = range(start_x, end_x - 1, -1)

                for x in x_range:
                    if not self._begin_frame(generation):
                        return
                        
                    frame_color = rainbow_color(x) if rainbow else color
                    for y in range(LED_LINE):
                        pos = xy2pos(x, y)
                        self.driver.set_pixel(pos, frame_color, min(brightness, get_global_brightness()), False)
                        if last_x is not None and last_x != x:
                            self.driver.set_pixel(xy2pos(last_x, y), COLOR_BLACK, 0, False)
                    last_x = x
                    self._end_frame()

                    time.sleep_ms(get_global_timing(duration))
                
                if pingpong:
                    start_x, end_x = end_x, start_x

                if not pingpong:
                    self._effect_lock.acquire()
                    try:
                        if generation == self._effect_generation and not self.interrupt_flag:
                            self.driver.clear()
                    finally:
                        self._effect_lock.release()
                    time.sleep_ms(interval)
        
        _thread.start_new_thread(effect, (start_x, end_x))

    def rainbow(self,
                start_x: int = 0, end_x: int = LED_DOT_PER_LINE - 1,
                brightness: int = 255, interval: int = 500,
                duration: int = 1, pingpong: bool = False) -> None:
        generation = self._start_effect()

        if start_x > end_x:
            if start_x >= LED_DOT_PER_LINE:
                start_x = LED_DOT_PER_LINE - 1
            if end_x < 0:
                end_x = 0
        else:
            if start_x < 0:
                start_x = 0
            if end_x >= LED_DOT_PER_LINE:
                end_x = LED_DOT_PER_LINE - 1

        duration = max(1, int(duration))

        def effect(start_x: int, end_x: int) -> None:
            hue_offset = 0
            hue_phase = 0

            while self._effect_active(generation):
                if start_x < end_x:
                    x_range = range(start_x, end_x + 1)
                else:
                    x_range = range(start_x, end_x - 1, -1)

                span = max(1, abs(end_x - start_x))
                if not self._begin_frame(generation):
                    return

                for x in x_range:
                    hue = hue_offset + ((x - start_x) * 255 // span)
                    color = rainbow_color(hue)
                    for y in range(LED_LINE):
                        self.driver.set_pixel(xy2pos(x, y), color, get_global_brightness(), False)
                self._end_frame()
                time.sleep_ms(RAINBOW_FRAME_INTERVAL)

                hue_phase += RAINBOW_HUE_STEP
                hue_offset = (hue_phase // RAINBOW_HUE_DIVISOR) % 256
                if pingpong:
                    start_x, end_x = end_x, start_x

        _thread.start_new_thread(effect, (start_x, end_x))

    def floor_tile_x(self, color: tuple[int, int, int] = COLOR_WHITE,
                     start_x: int = 0, end_x: int = LED_DOT_PER_LINE - 1, brightness: int = 255,
                     loop: bool = False, fade: bool = True, fade_reverse: bool = False,
                     duration: int = 1, fade_delay: int = 1, interval: int = 500) -> None:
        
        generation = self._start_effect()

        if start_x > end_x:
            if start_x >= LED_DOT_PER_LINE:
                start_x = LED_DOT_PER_LINE - 1
            if end_x < 0:
                end_x = 0
        else:
            if start_x < 0:
                start_x = 0
            if end_x >= LED_DOT_PER_LINE:
                end_x = LED_DOT_PER_LINE - 1
        
        def floor_from_side(color: tuple[int, int, int], start_x: int, end_x: int) -> None:
            if start_x < end_x:
                x_range = range(start_x, end_x + 1)
            else:
                x_range = range(start_x, end_x - 1, -1)
            
            for x in x_range:
                if not self._effect_active(generation):
                    return

                if not self._begin_frame(generation):
                    return
                for y in range(LED_LINE):
                    pos = xy2pos(x, y)
                    self.driver.set_pixel(pos, color, min(brightness, get_global_brightness()), False)
                self._end_frame()

                time.sleep_ms(get_global_timing(duration))

        def effect() -> None:
            while self._effect_active(generation):
                floor_from_side(color, start_x, end_x)

                if fade:
                    time.sleep_ms(fade_delay)

                    if fade_reverse:
                        floor_from_side(COLOR_BLACK, end_x, start_x)
                    else:
                        floor_from_side(COLOR_BLACK, start_x, end_x)
                
                if loop:
                    time.sleep_ms(get_global_timing(interval))
                    self._fill_frame(generation, COLOR_BLACK, 0)
                else:
                    return
        
        _thread.start_new_thread(effect, ())
    
    def fill_range(self, color: tuple[int, int, int] = COLOR_WHITE,
                   start_xy: tuple[int, int] = (0, 0), end_xy: tuple[int, int] = (LED_DOT_PER_LINE - 1, LED_LINE - 1),
                   brightness: int = 255) -> None:
        
        self.stop()

        start_pos = xy2pos(start_xy[0], start_xy[1])
        end_pos = xy2pos(end_xy[0], end_xy[1])

        if start_pos > end_pos:
            start_pos, end_pos = end_pos, start_pos
        
        if start_pos < 0:
            start_pos = 0
        if end_pos >= LED_COUNT:
            end_pos = LED_COUNT - 1

        for i in range(start_pos, end_pos + 1):
            self.driver.set_pixel(i, color, brightness, False)
        
        self.driver.show()
    
    def fill_square(self, color: tuple[int, int, int] = COLOR_WHITE,
                    start_xy: tuple[int, int] = (0, 0), end_xy: tuple[int, int] = (LED_DOT_PER_LINE - 1, LED_LINE - 1),
                    brightness: int = 255) -> None:
        
        self.stop()

        w = abs(end_xy[0] - start_xy[0]) + 1
        h = abs(end_xy[1] - start_xy[1]) + 1

        if start_xy[0] + w > LED_DOT_PER_LINE:
            w = LED_DOT_PER_LINE - start_xy[0]
        if start_xy[1] + h > LED_LINE:
            h = LED_LINE - start_xy[1]
        
        start_pos = xy2pos(start_xy[0], start_xy[1])
        for y in range(h):
            for x in range(w):
                pos = start_pos + x + y * LED_DOT_PER_LINE
                self.driver.set_pixel(pos, color, brightness, False)
        
        self.driver.show()

