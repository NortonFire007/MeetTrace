"""Audio backend abstractions and Windows Core Audio / WASAPI implementation.

This module defines backend protocols for audio stream I/O and endpoint management,
along with the production Windows implementation backed by pyaudiowpatch and pycaw/comtypes.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from meettrace.capture.models import AudioSource, DeviceFlow

logger = logging.getLogger(__name__)


@runtime_checkable
class AudioStream(Protocol):
    """Protocol for an active audio input/loopback stream."""

    def read(self, num_frames: int) -> bytes:
        """Read PCM audio frames from the stream.

        Args:
            num_frames: Number of frames to read.

        Returns:
            Raw 16-bit PCM bytes.
        """
        ...

    def close(self) -> None:
        """Stop and close the audio stream, releasing hardware buffers."""
        ...

    @property
    def sample_rate(self) -> int:
        """Sample rate of the stream in Hz."""
        ...

    @property
    def channels(self) -> int:
        """Number of channels in the stream (1 for mono, 2 for stereo)."""
        ...


@dataclass(frozen=True, slots=True)
class DeviceEndpointInfo:
    """Metadata describing a Windows Core Audio endpoint."""

    endpoint_id: str
    friendly_name: str


@runtime_checkable
class AudioBackend(Protocol):
    """Protocol for discovering audio endpoints, creating streams, and listening to device changes."""

    def open_stream(self, source: AudioSource, frames_per_buffer: int = 1024) -> AudioStream:
        """Open a capture stream for the specified audio source.

        Args:
            source: 'mic' for default microphone or 'loopback' for default render loopback.
            frames_per_buffer: Buffer chunk size in frames.

        Returns:
            An active AudioStream.

        Raises:
            OSError: If device is unavailable or stream initialization fails.
        """
        ...

    def get_default_endpoint(self, flow: DeviceFlow) -> DeviceEndpointInfo:
        """Query current default audio endpoint information.

        Args:
            flow: 'render' for output/speakers or 'capture' for input/mic.

        Returns:
            DeviceEndpointInfo containing endpoint ID and friendly name.
        """
        ...

    def start_notifications(self, callback: Callable[[DeviceFlow, str, str], None]) -> None:
        """Register a callback for Windows default audio device change notifications.

        Args:
            callback: Function invoked with (flow, endpoint_id, friendly_name) on device switch.
        """
        ...

    def stop_notifications(self) -> None:
        """Unregister the device change notification listener."""
        ...

    def close(self) -> None:
        """Release any global resources allocated by the backend."""
        ...


class PyAudioStreamAdapter:
    """Adapts a pyaudio.Stream instance to conform to AudioStream protocol."""

    def __init__(self, stream: Any, sample_rate: int, channels: int) -> None:
        self._stream = stream
        self._sample_rate = sample_rate
        self._channels = channels
        self._closed = False

    def read(self, num_frames: int) -> bytes:
        if self._closed:
            raise OSError("Cannot read from a closed audio stream.")
        return bytes(self._stream.read(num_frames, exception_on_overflow=False))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            with contextlib.suppress(OSError, RuntimeError):
                self._stream.stop_stream()
            with contextlib.suppress(OSError, RuntimeError):
                self._stream.close()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels


class WindowsAudioBackend:
    """Production Windows audio backend.

    Uses pyaudiowpatch for WASAPI loopback and microphone streaming,
    and pycaw / comtypes for IMMNotificationClient endpoint notifications.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._notification_callback: Callable[[DeviceFlow, str, str], None] | None = None
        self._device_enumerator: Any = None
        self._notification_client: Any = None
        self._listener_com_obj: Any = None

    def open_stream(self, source: AudioSource, frames_per_buffer: int = 1024) -> AudioStream:
        """Open a new WASAPI stream for microphone or loopback."""
        with self._lock:
            import pyaudiowpatch as pyaudio

            pa = pyaudio.PyAudio()
            try:
                if source == "mic":
                    device_info = pa.get_default_wasapi_device(d_in=True)
                    channels = int(device_info["maxInputChannels"])
                    # Fallback to mono if device reports 0 or invalid channels
                    channels = max(1, min(channels, 2))
                    rate = int(device_info["defaultSampleRate"])
                    stream = pa.open(
                        format=pyaudio.paInt16,
                        channels=channels,
                        rate=rate,
                        input=True,
                        input_device_index=int(device_info["index"]),
                        frames_per_buffer=frames_per_buffer,
                    )
                elif source == "loopback":
                    device_info = pa.get_default_wasapi_loopback()
                    channels = int(device_info["maxInputChannels"])
                    channels = max(1, min(channels, 2))
                    rate = int(device_info["defaultSampleRate"])
                    stream = pa.open(
                        format=pyaudio.paInt16,
                        channels=channels,
                        rate=rate,
                        input=True,
                        input_device_index=int(device_info["index"]),
                        frames_per_buffer=frames_per_buffer,
                    )
                else:
                    raise ValueError(f"Unsupported audio source for stream creation: {source!r}")

                return PyAudioStreamAdapter(stream=stream, sample_rate=rate, channels=channels)
            except Exception:
                with contextlib.suppress(OSError, RuntimeError):
                    pa.terminate()
                raise

    def get_default_endpoint(self, flow: DeviceFlow) -> DeviceEndpointInfo:
        """Query default endpoint ID and friendly name using pycaw."""
        import comtypes
        from pycaw.pycaw import AudioUtilities

        comtypes.CoInitialize()
        try:
            enumerator = AudioUtilities.GetDeviceEnumerator()
            flow_int = 0 if flow == "render" else 1
            device = enumerator.GetDefaultAudioEndpoint(flow_int, 0)  # 0 = eConsole
            dev_id = device.GetId()
            friendly_name = "Default Device"
            for d in AudioUtilities.GetAllDevices():
                if getattr(d, "id", None) == dev_id:
                    friendly_name = getattr(d, "FriendlyName", friendly_name)
                    break
            return DeviceEndpointInfo(endpoint_id=dev_id, friendly_name=friendly_name)
        except (OSError, RuntimeError) as exc:
            logger.warning("Failed to resolve default %s endpoint: %s", flow, exc)
            return DeviceEndpointInfo(
                endpoint_id="default", friendly_name=f"Default {flow.capitalize()}"
            )
        finally:
            comtypes.CoUninitialize()

    def start_notifications(self, callback: Callable[[DeviceFlow, str, str], None]) -> None:
        """Register COM notification listener for default device switches."""
        import comtypes
        from pycaw.pycaw import AudioUtilities, IMMNotificationClient

        with self._lock:
            if self._notification_client is not None:
                self.stop_notifications()

            self._notification_callback = callback

            try:
                comtypes.CoInitialize()
                self._device_enumerator = AudioUtilities.GetDeviceEnumerator()

                backend_ref = self

                class _Listener(comtypes.COMObject):
                    _com_interfaces_: ClassVar[list[Any]] = [IMMNotificationClient]

                    def OnDefaultDeviceChanged(
                        self, flow_int: int, role_int: int, pwstr_default_device_id: str
                    ) -> int:
                        # 0 = eConsole, 2 = eCommunications
                        if role_int in (0, 2):
                            flow_str: DeviceFlow = "render" if flow_int == 0 else "capture"
                            backend_ref._dispatch_device_change(flow_str, pwstr_default_device_id)
                        return 0

                    def OnDeviceStateChanged(self, pwstr_device_id: str, dw_new_state: int) -> int:
                        return 0

                    def OnDeviceAdded(self, pwstr_device_id: str) -> int:
                        return 0

                    def OnDeviceRemoved(self, pwstr_device_id: str) -> int:
                        return 0

                    def OnPropertyValueChanged(self, pwstr_device_id: str, key: Any) -> int:
                        return 0

                self._listener_com_obj = _Listener()
                self._notification_client = self._listener_com_obj.QueryInterface(
                    IMMNotificationClient
                )
                self._device_enumerator.RegisterEndpointNotificationCallback(
                    self._notification_client
                )
                logger.info("Registered Windows Core Audio device change notifications.")
            except (OSError, RuntimeError) as exc:
                logger.warning("Could not register device change notification callback: %s", exc)

    def _dispatch_device_change(self, flow: DeviceFlow, endpoint_id: str) -> None:
        """Internal helper to resolve friendly name and trigger registered callback."""
        if self._notification_callback is None:
            return

        endpoint_info = self.get_default_endpoint(flow)
        friendly_name = endpoint_info.friendly_name
        self._notification_callback(flow, endpoint_id, friendly_name)

    def stop_notifications(self) -> None:
        """Unregister the COM notification listener."""
        with self._lock:
            if self._device_enumerator is not None and self._notification_client is not None:
                try:
                    self._device_enumerator.UnregisterEndpointNotificationCallback(
                        self._notification_client
                    )
                    logger.info("Unregistered Windows Core Audio notifications.")
                except (OSError, RuntimeError) as exc:
                    logger.debug("Error unregistering Core Audio notification callback: %s", exc)
                finally:
                    self._device_enumerator = None
                    self._notification_client = None
                    self._listener_com_obj = None
                    self._notification_callback = None

    def close(self) -> None:
        """Release backend resources."""
        self.stop_notifications()
