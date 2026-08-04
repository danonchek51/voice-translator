"""Перечисление устройств записи и выбор нужного.

При переносе настроек на другой компьютер индексы устройств не совпадают,
поэтому поиск идёт сначала по индексу, потом по имени, потом по системному
устройству по умолчанию. Пользователь узнаёт о подмене из уведомления.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AudioDevice:
    index: int
    name: str
    channels: int
    is_default: bool = False

    def label(self) -> str:
        return f"{self.name} (по умолчанию)" if self.is_default else self.name


@dataclass(frozen=True, slots=True)
class DeviceResolution:
    """Результат выбора устройства."""

    device: AudioDevice | None
    #: Пояснение, если выбрано не то устройство, которое просили.
    note: str = ""


def _sounddevice():  # type: ignore[no-untyped-def]
    """Ленивый импорт: без звуковой подсистемы остальное приложение работает."""
    try:
        import sounddevice
    except (ImportError, OSError) as exc:
        logger.warning("Звуковая подсистема недоступна: %s", exc)
        return None
    return sounddevice


def list_input_devices() -> list[AudioDevice]:
    """Список доступных устройств записи. Пустой, если звук недоступен."""
    sd = _sounddevice()
    if sd is None:
        return []

    try:
        raw_devices = sd.query_devices()
        default_input = sd.default.device[0]
    except Exception:
        logger.exception("Не удалось получить список устройств записи")
        return []

    devices: list[AudioDevice] = []
    for index, info in enumerate(raw_devices):
        channels = int(info.get("max_input_channels", 0))
        if channels <= 0:
            continue
        devices.append(
            AudioDevice(
                index=index,
                name=str(info.get("name", f"Устройство {index}")),
                channels=channels,
                is_default=index == default_input,
            )
        )
    return devices


def resolve_device(
    device_id: int | None,
    device_name: str,
    available: list[AudioDevice] | None = None,
) -> DeviceResolution:
    """Выбирает устройство: по индексу, затем по имени, затем по умолчанию."""
    devices = list_input_devices() if available is None else available
    if not devices:
        return DeviceResolution(device=None, note="Устройства записи не найдены")

    by_index = {device.index: device for device in devices}

    if device_id is not None and device_id in by_index:
        found = by_index[device_id]
        if not device_name or found.name == device_name:
            return DeviceResolution(device=found)
        # Индекс совпал, но за ним другое устройство — доверяем имени.

    if device_name:
        exact = [device for device in devices if device.name == device_name]
        if exact:
            return DeviceResolution(
                device=exact[0],
                note=(
                    f"Устройство «{device_name}» найдено под другим номером"
                    if device_id is not None and exact[0].index != device_id
                    else ""
                ),
            )

    default = next((device for device in devices if device.is_default), devices[0])
    if device_id is None and not device_name:
        return DeviceResolution(device=default)

    requested = device_name or f"№{device_id}"
    return DeviceResolution(
        device=default,
        note=(
            f"Устройство «{requested}» недоступно, "
            f"использую «{default.name}»"
        ),
    )
