"""Tests del cliente de PulseAudio, con `pulsectl` sustituido: en la CI no hay servidor de sonido."""

from types import SimpleNamespace

import pytest

pulsectl = pytest.importorskip("pulsectl", reason="solo en Linux, con libpulse")

from vn_audiolibro.voz import volumen  # noqa: E402
from vn_audiolibro.voz.modelos import VozFallidaError  # noqa: E402
from vn_audiolibro.voz.volumen import ClientePulse, Flujo  # noqa: E402


class PulseFalso:
    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self.puestos: list[tuple[int, list[float]]] = []
        self.cerrado = False

    def sink_input_list(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                index=7,
                proplist={
                    "application.name": "Juego.exe",
                    "application.process.binary": "wine64-preloader",
                    "application.process.id": "100",
                },
                volume=SimpleNamespace(values=[1.0, 0.5]),
            ),
            SimpleNamespace(index=8, proplist={}, volume=SimpleNamespace(values=[1.0])),
        ]

    def sink_input_volume_set(self, indice: int, volumen: SimpleNamespace) -> None:
        if indice == 99:
            raise pulsectl.PulseOperationFailed(indice)
        self.puestos.append((indice, volumen.values))

    def close(self) -> None:
        self.cerrado = True


def test_cliente_pulse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(volumen.pulsectl, "Pulse", PulseFalso)
    monkeypatch.setattr(volumen.pulsectl, "PulseVolumeInfo", lambda valores: SimpleNamespace(values=valores))
    cliente = ClientePulse()

    assert cliente.flujos() == [
        Flujo(7, "Juego.exe", "wine64-preloader", 100, (1.0, 0.5)),
        Flujo(8, "", "", None, (1.0,)),
    ]
    cliente.poner_volumen(7, (0.3, 0.15))
    cliente.poner_volumen(99, (0.3,))  # ya no existe: no falla
    cliente.cerrar()

    pulse = cliente._pulse
    assert pulse.nombre == "vn-audiolibro-volumen"
    assert pulse.puestos == [(7, [0.3, 0.15])]
    assert pulse.cerrado


def test_cliente_pulse_sin_servidor(monkeypatch: pytest.MonkeyPatch) -> None:
    def sin_servidor(nombre: str) -> None:
        raise pulsectl.PulseError("conexión rechazada")

    monkeypatch.setattr(volumen.pulsectl, "Pulse", sin_servidor)
    with pytest.raises(VozFallidaError, match="servidor de sonido"):
        ClientePulse()
