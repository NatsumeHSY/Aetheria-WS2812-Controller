import asyncio
import io
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from client.controller import ControllerError
from client.media_color import MediaColorEffect, MediaSnapshot, WindowsMediaReader, extract_theme_color


def cover(color, mode="RGB"):
    image = Image.new(mode, (32, 32), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class Reader:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    async def read(self):
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot


class Controller:
    connected = True

    def __init__(self):
        self.calls = []
        self.fail = False

    def transition(self, target, duration):
        if self.fail:
            raise ControllerError("no ACK")
        self.calls.append((target, duration))
        return len(self.calls)


class MediaColorTests(unittest.IsolatedAsyncioTestCase):
    def make_effect(self, snapshot):
        controller = Controller()
        reader = Reader(snapshot)
        effect = MediaColorEffect(controller, reader=reader, autostart=False)
        effect.activate((17, 34, 51), 180)
        return effect, controller, reader

    async def test_playing_cover_transitions_once_until_color_changes(self):
        effect, controller, reader = self.make_effect(MediaSnapshot(True, cover((220, 40, 70))))
        await effect.refresh()
        await effect.refresh()
        self.assertEqual(controller.calls, [((220, 40, 70, 180), 800)])
        reader.snapshot = MediaSnapshot(True, cover((40, 170, 220)))
        await effect.refresh()
        self.assertEqual(controller.calls[-1], ((40, 170, 220, 180), 800))

    async def test_no_playback_missing_or_corrupt_cover_uses_default(self):
        for snapshot in (
            MediaSnapshot(False, cover((220, 40, 70))),
            MediaSnapshot(True, None),
            MediaSnapshot(True, b""),
            MediaSnapshot(True, b"not an image"),
            MediaSnapshot(True, cover((255, 0, 0, 0), "RGBA")),
            OSError("media API unavailable"),
        ):
            effect, controller, _ = self.make_effect(snapshot)
            await effect.refresh()
            self.assertEqual(controller.calls, [((17, 34, 51, 180), 800)])
            self.assertEqual(effect.status()["source"], "default")

    async def test_default_change_applies_only_while_falling_back(self):
        effect, controller, reader = self.make_effect(MediaSnapshot(True, cover((220, 40, 70))))
        await effect.refresh()
        effect.activate((100, 110, 120), 180)
        await effect.refresh()
        self.assertEqual(len(controller.calls), 1)
        reader.snapshot = MediaSnapshot(False)
        await effect.refresh()
        self.assertEqual(controller.calls[-1], ((100, 110, 120, 180), 800))

    async def test_failed_transition_retries_and_disconnected_device_is_not_written(self):
        effect, controller, _ = self.make_effect(MediaSnapshot(False))
        controller.fail = True
        await effect.refresh()
        controller.fail = False
        await effect.refresh()
        self.assertEqual(len(controller.calls), 1)
        controller.connected = False
        await effect.refresh()
        self.assertEqual(len(controller.calls), 1)
        controller.connected = True
        await effect.refresh()
        self.assertEqual(len(controller.calls), 2)

    async def test_brightness_change_during_transition_repairs_the_old_target(self):
        effect, controller, _ = self.make_effect(MediaSnapshot(False))
        await effect.refresh()
        effect.set_brightness(220)  # A0 does not cancel the board's active fade.
        await effect.refresh()
        self.assertEqual(controller.calls, [((17, 34, 51, 180), 800), ((17, 34, 51, 220), 800)])

    async def test_brightness_after_finished_transition_does_not_restart_it(self):
        effect, controller, _ = self.make_effect(MediaSnapshot(False))
        with patch("client.media_color.time.monotonic", return_value=10.0):
            await effect.refresh()
        with patch("client.media_color.time.monotonic", return_value=11.0):
            effect.set_brightness(220)
            await effect.refresh()
        self.assertEqual(controller.calls, [((17, 34, 51, 180), 800)])

    async def test_switching_mode_discards_a_cover_read_already_in_flight(self):
        effect, controller, reader = self.make_effect(MediaSnapshot(False))
        entered = asyncio.Event()
        release = asyncio.Event()

        async def delayed_read():
            entered.set()
            await release.wait()
            return MediaSnapshot(True, cover((220, 40, 70)))

        reader.read = delayed_read
        task = asyncio.create_task(effect.refresh())
        await entered.wait()
        effect.deactivate()
        release.set()
        await task
        self.assertEqual(controller.calls, [])
        self.assertFalse(effect.status()["active"])


class ThemeColorTests(unittest.TestCase):
    def test_dominant_color_is_not_an_average_of_unrelated_regions(self):
        image = Image.new("RGB", (64, 64), (220, 40, 70))
        image.paste((40, 170, 220), (0, 0, 16, 64))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self.assertEqual(extract_theme_color(output.getvalue()), (220, 40, 70))

    def test_transparent_pixels_are_ignored_and_monochrome_is_supported(self):
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        image.paste((20, 80, 200, 255), (0, 0, 16, 32))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self.assertEqual(extract_theme_color(output.getvalue()), (20, 80, 200))
        self.assertEqual(extract_theme_color(cover((200, 200, 200))), (200, 200, 200))


class MediaWorkerTests(unittest.TestCase):
    def test_background_worker_sends_then_closes_without_late_transitions(self):
        controller = Controller()
        reader = Reader(MediaSnapshot(False))
        sent, closed = threading.Event(), threading.Event()
        original_transition = controller.transition

        def transition(target, duration):
            original_transition(target, duration)
            sent.set()

        controller.transition = transition
        reader.close = closed.set
        effect = MediaColorEffect(controller, reader=reader, poll_interval=0.05)
        try:
            effect.activate((17, 34, 51), 180)
            self.assertTrue(sent.wait(2))
        finally:
            effect.close()
        self.assertTrue(closed.is_set())
        self.assertFalse(effect._thread.is_alive())
        self.assertEqual(controller.calls, [((17, 34, 51, 180), 800)])


class WindowsMediaReaderTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows WinRT stream integration")
    async def test_real_winrt_artwork_stream_is_read_and_closed(self):
        import winrt.windows.foundation
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        data = cover((220, 40, 70))
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(data)
        await writer.store_async()
        writer.detach_stream()
        writer.close()
        stream.seek(0)

        async def open_read():
            return stream

        async def properties():
            return SimpleNamespace(thumbnail=SimpleNamespace(open_read_async=open_read), title="Track", artist="Artist")

        session = SimpleNamespace(
            get_playback_info=lambda: SimpleNamespace(playback_status=4),
            try_get_media_properties_async=properties,
        )
        manager = SimpleNamespace(get_current_session=lambda: session, get_sessions=lambda: [session])
        snapshot = await WindowsMediaReader(manager=manager).read()
        self.assertEqual(snapshot.cover, data)
        self.assertEqual(extract_theme_color(snapshot.cover), (220, 40, 70))
        with self.assertRaises(OSError):
            stream.seek(0)

    async def test_only_playing_sessions_supply_covers(self):
        session = SimpleNamespace(get_playback_info=lambda: SimpleNamespace(playback_status=5))
        manager = SimpleNamespace(get_current_session=lambda: session, get_sessions=lambda: [session])
        reader = WindowsMediaReader(manager=manager)
        self.assertEqual(await reader.read(), MediaSnapshot(False))

    async def test_playing_session_without_thumbnail_is_reported(self):
        async def properties():
            return SimpleNamespace(thumbnail=None, title="Track", artist="Artist")

        session = SimpleNamespace(
            get_playback_info=lambda: SimpleNamespace(playback_status=4),
            try_get_media_properties_async=properties,
        )
        manager = SimpleNamespace(get_current_session=lambda: session, get_sessions=lambda: [session])
        reader = WindowsMediaReader(manager=manager)
        snapshot = await reader.read()
        self.assertTrue(snapshot.playing)
        self.assertIsNone(snapshot.cover)
        self.assertEqual(snapshot.title, "Track")


if __name__ == "__main__":
    unittest.main()
