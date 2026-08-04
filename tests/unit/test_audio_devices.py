"""Выбор устройства записи при переносе настроек между компьютерами."""

from __future__ import annotations

from voiceflow.core.audio.devices import AudioDevice, resolve_device

MIC = AudioDevice(index=1, name="Микрофон (USB)", channels=1)
HEADSET = AudioDevice(index=2, name="Гарнитура", channels=2, is_default=True)
WEBCAM = AudioDevice(index=3, name="Камера", channels=1)

ALL = [MIC, HEADSET, WEBCAM]


def test_no_devices_reports_problem() -> None:
    resolution = resolve_device(device_id=1, device_name="Микрофон", available=[])

    assert resolution.device is None
    assert "не найдены" in resolution.note


def test_exact_index_and_name_match() -> None:
    resolution = resolve_device(device_id=1, device_name="Микрофон (USB)", available=ALL)

    assert resolution.device is MIC
    assert resolution.note == ""


def test_index_shifted_but_name_found() -> None:
    """Классический случай после переноса настроек: номера съехали."""
    resolution = resolve_device(device_id=3, device_name="Микрофон (USB)", available=ALL)

    assert resolution.device is MIC
    assert "под другим номером" in resolution.note


def test_unknown_device_falls_back_to_default_with_note() -> None:
    resolution = resolve_device(device_id=9, device_name="Студийный микрофон", available=ALL)

    assert resolution.device is HEADSET
    assert "Студийный микрофон" in resolution.note
    assert "Гарнитура" in resolution.note


def test_nothing_requested_uses_system_default() -> None:
    resolution = resolve_device(device_id=None, device_name="", available=ALL)

    assert resolution.device is HEADSET
    assert resolution.note == ""


def test_index_only_is_respected() -> None:
    resolution = resolve_device(device_id=3, device_name="", available=ALL)

    assert resolution.device is WEBCAM
    assert resolution.note == ""


def test_first_device_used_when_no_default_flag() -> None:
    devices = [
        AudioDevice(index=1, name="A", channels=1),
        AudioDevice(index=2, name="B", channels=1),
    ]

    resolution = resolve_device(device_id=None, device_name="", available=devices)

    assert resolution.device is devices[0]
