"""Audio Capture Spike for Windows WASAPI Loopback and Microphone.

Demonstrates:
1. Concurrent capture from Windows default microphone (`eCapture`) and default output loopback (`eRender`).
2. Endpoint detection via Windows Core Audio (IMMDeviceEnumerator).
3. Dynamic device change handling via IMMNotificationClient (OnDefaultDeviceChanged).
4. Continuous mixing into a single WAV output (test.wav).
5. Robust error handling without application crashes on device disconnect/rebind.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import time
import wave
from typing import TYPE_CHECKING, Any, ClassVar

import comtypes
import numpy as np
import pyaudiowpatch as pyaudio
from pycaw.pycaw import AudioUtilities, IMMNotificationClient

if TYPE_CHECKING:
    from comtypes import IUnknown

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SpikeCapture")


def get_default_endpoint_info(flow: int) -> dict[str, Any]:
    """Get Windows default audio endpoint ID and friendly name using pycaw/CoreAudio.

    flow: 0 for eRender (output), 1 for eCapture (input).
    """
    try:
        enumerator = AudioUtilities.GetDeviceEnumerator()
        device = enumerator.GetDefaultAudioEndpoint(flow, 0)  # 0 = eConsole
        dev_id = device.GetId()
        friendly_name = "Unknown"
        for d in AudioUtilities.GetAllDevices():
            if getattr(d, "id", None) == dev_id:
                friendly_name = getattr(d, "FriendlyName", "Unknown")
                break
        return {"id": dev_id, "name": friendly_name}
    except (OSError, RuntimeError) as exc:
        return {"id": "N/A", "name": f"Error: {exc}"}


class DeviceNotificationListener(comtypes.COMObject):
    """COM client implementing IMMNotificationClient to detect default device changes."""

    _com_interfaces_: ClassVar[list[Any]] = [IMMNotificationClient]

    def __init__(self, spike: AudioCaptureSpike) -> None:
        super().__init__()
        self.spike = spike

    def OnDefaultDeviceChanged(self, flow: int, role: int, pwstr_default_device_id: str) -> int:
        """Handle Windows default device change event."""
        if role in (0, 2):  # 0 = eConsole, 2 = eCommunications
            flow_name = "Render (Speakers/Headphones)" if flow == 0 else "Capture (Microphone)"
            logger.info(
                ">>> [NOTIFICATION] Windows default %s changed to: %s",
                flow_name,
                pwstr_default_device_id,
            )
            self.spike.signal_rebind(reason=f"Default {flow_name} changed")
        return 0

    def OnDeviceStateChanged(self, pwstr_device_id: str, dw_new_state: int) -> int:
        return 0

    def OnDeviceAdded(self, pwstr_device_id: str) -> int:
        return 0

    def OnDeviceRemoved(self, pwstr_device_id: str) -> int:
        return 0

    def OnPropertyValueChanged(self, pwstr_device_id: str, key: Any) -> int:
        return 0


class AudioCaptureSpike:
    """Coordinates dual-stream WASAPI capture, notifications, mixing, and persistence."""

    def __init__(
        self,
        output_path: str = "test.wav",
        target_rate: int = 48000,
        simulate_rebind_at: float | None = None,
    ) -> None:
        self.output_path = output_path
        self.target_rate = target_rate
        self.simulate_rebind_at = simulate_rebind_at

        self.running = False
        self.start_time: float = 0.0

        self._rebind_flag = False
        self._rebind_reason = ""
        self.rebind_count = 0

        self.stats = {
            "mic_chunks": 0,
            "loopback_chunks": 0,
            "mixed_frames": 0,
        }

        self._notification_client: IUnknown | None = None
        self._device_enumerator: Any = None

    def signal_rebind(self, reason: str = "Requested") -> None:
        self._rebind_flag = True
        self._rebind_reason = reason

    def _setup_notifications(self) -> None:
        try:
            comtypes.CoInitialize()
            self._device_enumerator = AudioUtilities.GetDeviceEnumerator()
            handler = DeviceNotificationListener(self)
            self._notification_client = handler.QueryInterface(IMMNotificationClient)
            self._device_enumerator.RegisterEndpointNotificationCallback(self._notification_client)
            logger.info("IMMNotificationClient registered for dynamic device changes.")
        except (OSError, RuntimeError) as exc:
            logger.warning("Could not register CoreAudio notification callback: %s", exc)

    def _cleanup_notifications(self) -> None:
        if self._device_enumerator and self._notification_client:
            with contextlib.suppress(OSError, RuntimeError):
                self._device_enumerator.UnregisterEndpointNotificationCallback(
                    self._notification_client
                )
                logger.info("IMMNotificationClient unregistered cleanly.")

    def _open_capture_streams(
        self, pa: pyaudio.PyAudio
    ) -> tuple[pyaudio.Stream | None, pyaudio.Stream | None, dict[str, Any], dict[str, Any]]:
        """Query default devices and open mic and loopback streams."""
        mic_info: dict[str, Any] = {}
        loop_info: dict[str, Any] = {}
        mic_stream: pyaudio.Stream | None = None
        loop_stream: pyaudio.Stream | None = None

        # 1. Open Microphone stream
        try:
            mic_info = pa.get_default_wasapi_device(d_in=True)
            mic_rate = int(mic_info["defaultSampleRate"])
            mic_channels = int(mic_info["maxInputChannels"])
            mic_stream = pa.open(
                format=pyaudio.paInt16,
                channels=mic_channels,
                rate=mic_rate,
                input=True,
                input_device_index=mic_info["index"],
                frames_per_buffer=1024,
            )
            def_cap = get_default_endpoint_info(1)
            logger.info(
                "[MIC BOUND] '%s' (Channels: %d, Rate: %dHz) -> Endpoint ID: %s",
                mic_info["name"],
                mic_channels,
                mic_rate,
                def_cap["id"],
            )
        except (OSError, RuntimeError) as exc:
            logger.warning("[MIC INIT WARN] Failed to open default microphone: %s", exc)

        # 2. Open Render Loopback stream
        try:
            loop_info = pa.get_default_wasapi_loopback()
            loop_rate = int(loop_info["defaultSampleRate"])
            loop_channels = int(loop_info["maxInputChannels"])
            loop_stream = pa.open(
                format=pyaudio.paInt16,
                channels=loop_channels,
                rate=loop_rate,
                input=True,
                input_device_index=loop_info["index"],
                frames_per_buffer=1024,
            )
            def_ren = get_default_endpoint_info(0)
            logger.info(
                "[LOOPBACK BOUND] '%s' (Channels: %d, Rate: %dHz) -> Endpoint ID: %s",
                loop_info["name"],
                loop_channels,
                loop_rate,
                def_ren["id"],
            )
        except (OSError, RuntimeError) as exc:
            logger.warning("[LOOPBACK INIT WARN] Failed to open default loopback: %s", exc)

        return mic_stream, loop_stream, mic_info, loop_info

    def _close_capture_streams(
        self,
        pa: pyaudio.PyAudio | None,
        mic_stream: pyaudio.Stream | None,
        loop_stream: pyaudio.Stream | None,
    ) -> None:
        """Safely close active audio streams and terminate PyAudio."""
        if mic_stream is not None:
            with contextlib.suppress(OSError, RuntimeError):
                mic_stream.stop_stream()
                mic_stream.close()
        if loop_stream is not None:
            with contextlib.suppress(OSError, RuntimeError):
                loop_stream.stop_stream()
                loop_stream.close()
        if pa is not None:
            with contextlib.suppress(OSError, RuntimeError):
                pa.terminate()

    def _resample(self, data: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
        """Resample audio array to target sample rate using linear interpolation."""
        if orig_rate == target_rate or len(data) == 0:
            return data
        num_target = int(len(data) * target_rate / orig_rate)
        if num_target == 0:
            return np.empty((0, data.shape[1] if data.ndim > 1 else 1), dtype=data.dtype)
        x_orig = np.linspace(0, 1, len(data), endpoint=False)
        x_target = np.linspace(0, 1, num_target, endpoint=False)
        if data.ndim == 1:
            return np.interp(x_target, x_orig, data).astype(data.dtype)
        cols = [np.interp(x_target, x_orig, data[:, c]) for c in range(data.shape[1])]
        return np.column_stack(cols).astype(data.dtype)

    def run(self, duration: float = 10.0) -> None:
        """Run the audio capture spike for the specified duration (0 = until Ctrl+C)."""
        logger.info("=" * 70)
        logger.info("MeetTrace Audio Capture Spike (WASAPI Loopback + Microphone)")
        logger.info("=" * 70)

        def_render = get_default_endpoint_info(0)
        def_capture = get_default_endpoint_info(1)
        logger.info("Default Windows Output (eRender):  %s", def_render["name"])
        logger.info("  Endpoint ID: %s", def_render["id"])
        logger.info("Default Windows Input (eCapture):  %s", def_capture["name"])
        logger.info("  Endpoint ID: %s", def_capture["id"])
        logger.info(
            "Target WAV output: %s (%d Hz, Stereo 16-bit)", self.output_path, self.target_rate
        )
        logger.info("-" * 70)

        self._setup_notifications()
        self.running = True
        self.start_time = time.time()

        pa: pyaudio.PyAudio | None = None
        mic_stream: pyaudio.Stream | None = None
        loop_stream: pyaudio.Stream | None = None
        mic_info: dict[str, Any] = {}
        loop_info: dict[str, Any] = {}

        dur_desc = "until interrupted" if duration <= 0 else f"{duration} seconds"
        logger.info("[RECORDING STARTED] Capturing for %s... (Press Ctrl+C to stop)", dur_desc)

        last_report_time = time.time()
        simulated_rebind_done = False

        try:
            with wave.open(self.output_path, "wb") as wav_file:
                wav_file.setnchannels(2)  # Stereo output
                wav_file.setsampwidth(2)  # 16-bit PCM
                wav_file.setframerate(self.target_rate)

                pa = pyaudio.PyAudio()
                mic_stream, loop_stream, mic_info, loop_info = self._open_capture_streams(pa)

                while self.running:
                    now = time.time()
                    elapsed = now - self.start_time

                    if duration > 0 and elapsed >= duration:
                        break

                    # Handle simulated rebind if requested via CLI
                    if (
                        self.simulate_rebind_at
                        and not simulated_rebind_done
                        and elapsed >= self.simulate_rebind_at
                    ):
                        logger.info(
                            "\n>>> [SIMULATED EVENT] Triggering device rebind at %.1fs...",
                            elapsed,
                        )
                        self.signal_rebind(reason="Simulated CLI event")
                        simulated_rebind_done = True

                    # Handle dynamic device rebind
                    if self._rebind_flag:
                        self._rebind_flag = False
                        self.rebind_count += 1
                        logger.info(
                            ">>> [REBIND START #%d] %s. Reopening streams...",
                            self.rebind_count,
                            self._rebind_reason,
                        )
                        self._close_capture_streams(pa, mic_stream, loop_stream)
                        time.sleep(0.15)  # brief grace period for Windows audio graph
                        pa = pyaudio.PyAudio()
                        mic_stream, loop_stream, mic_info, loop_info = self._open_capture_streams(
                            pa
                        )
                        logger.info(">>> [REBIND COMPLETE #%d] Streams rebound.", self.rebind_count)

                    # Read chunk from microphone
                    mic_pcm = b""
                    if mic_stream is not None:
                        try:
                            mic_pcm = mic_stream.read(1024, exception_on_overflow=False)
                            self.stats["mic_chunks"] += 1
                        except (OSError, RuntimeError) as exc:
                            logger.warning("[MIC ERROR] Read failed: %s", exc)
                            self.signal_rebind(reason="Microphone read failure")

                    # Read chunk from loopback
                    loop_pcm = b""
                    if loop_stream is not None:
                        try:
                            loop_pcm = loop_stream.read(1024, exception_on_overflow=False)
                            self.stats["loopback_chunks"] += 1
                        except (OSError, RuntimeError) as exc:
                            logger.warning("[LOOPBACK ERROR] Read failed: %s", exc)
                            self.signal_rebind(reason="Loopback read failure")

                    # Format and mix audio
                    mic_samples: np.ndarray | None = None
                    if mic_pcm:
                        raw = np.frombuffer(mic_pcm, dtype=np.int16)
                        ch = mic_info.get("maxInputChannels", 1)
                        mic_samples = raw.reshape(-1, ch) if ch > 1 else raw.reshape(-1, 1)
                        if mic_info.get("defaultSampleRate", self.target_rate) != self.target_rate:
                            mic_samples = self._resample(
                                mic_samples, int(mic_info["defaultSampleRate"]), self.target_rate
                            )
                        # Broadcast mono to stereo
                        if mic_samples.shape[1] == 1:
                            mic_samples = np.column_stack([mic_samples[:, 0], mic_samples[:, 0]])

                    loop_samples: np.ndarray | None = None
                    if loop_pcm:
                        raw = np.frombuffer(loop_pcm, dtype=np.int16)
                        ch = loop_info.get("maxInputChannels", 2)
                        loop_samples = raw.reshape(-1, ch) if ch > 1 else raw.reshape(-1, 1)
                        if loop_info.get("defaultSampleRate", self.target_rate) != self.target_rate:
                            loop_samples = self._resample(
                                loop_samples, int(loop_info["defaultSampleRate"]), self.target_rate
                            )
                        if loop_samples.shape[1] == 1:
                            loop_samples = np.column_stack([loop_samples[:, 0], loop_samples[:, 0]])

                    # Mix signals: align lengths and sum with clipping
                    mixed: np.ndarray | None = None
                    if mic_samples is not None and loop_samples is not None:
                        min_len = min(len(mic_samples), len(loop_samples))
                        summed = mic_samples[:min_len].astype(np.int32) + loop_samples[
                            :min_len
                        ].astype(np.int32)
                        mixed = np.clip(summed, -32768, 32767).astype(np.int16)
                    elif mic_samples is not None:
                        mixed = mic_samples
                    elif loop_samples is not None:
                        mixed = loop_samples

                    if mixed is not None and len(mixed) > 0:
                        wav_file.writeframes(mixed.tobytes())
                        self.stats["mixed_frames"] += len(mixed)

                    # Report status periodically (every 1 second)
                    if now - last_report_time >= 1.0:
                        mins = int(elapsed // 60)
                        secs = elapsed % 60
                        mic_rms = (
                            float(np.sqrt(np.mean(mic_samples.astype(np.float32) ** 2)))
                            if mic_samples is not None
                            else 0.0
                        )
                        loop_rms = (
                            float(np.sqrt(np.mean(loop_samples.astype(np.float32) ** 2)))
                            if loop_samples is not None
                            else 0.0
                        )
                        logger.info(
                            "[%02d:%05.2f] Mic RMS: %6.1f | Loopback RMS: %6.1f | "
                            "Frames: %s | Rebinds: %d",
                            mins,
                            secs,
                            mic_rms,
                            loop_rms,
                            f"{self.stats['mixed_frames']:,}",
                            self.rebind_count,
                        )
                        last_report_time = now

        except KeyboardInterrupt:
            logger.info("[STOPPING] Interrupted by user.")
        finally:
            self.running = False
            self._close_capture_streams(pa, mic_stream, loop_stream)
            self._cleanup_notifications()

        total_elapsed = time.time() - self.start_time
        total_seconds = self.stats["mixed_frames"] / self.target_rate if self.target_rate else 0

        logger.info("=" * 70)
        logger.info("SPIKE SUMMARY")
        logger.info("Recorded wall time:    %.2f s", total_elapsed)
        logger.info("Output audio duration: %.2f s", total_seconds)
        logger.info("Mic chunks captured:   %d", self.stats["mic_chunks"])
        logger.info("Loopback chunks:       %d", self.stats["loopback_chunks"])
        logger.info("Rebind events handled: %d", self.rebind_count)
        logger.info("Output saved to:       %s", self.output_path)
        logger.info("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="MeetTrace Windows WASAPI Audio Capture Spike")
    parser.add_argument(
        "--duration",
        "-d",
        type=float,
        default=10.0,
        help="Recording duration in seconds (default: 10s; 0 for continuous)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="test.wav",
        help="Target output WAV filename (default: test.wav)",
    )
    parser.add_argument(
        "--rate",
        "-r",
        type=int,
        default=48000,
        help="Target sample rate in Hz (default: 48000)",
    )
    parser.add_argument(
        "--simulate-rebind",
        type=float,
        default=None,
        help="Simulate a device switch at N seconds into recording",
    )

    args = parser.parse_args()

    spike = AudioCaptureSpike(
        output_path=args.output,
        target_rate=args.rate,
        simulate_rebind_at=args.simulate_rebind,
    )
    spike.run(duration=args.duration)


if __name__ == "__main__":
    main()
