"""Procesos del sistema: en Linux se leen de `/proc`; en Windows, con Toolhelp32."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Proceso:
    pid: int
    padre: int
    nombre: str
    """En Linux, el de `/proc/<pid>/stat` (recortado a 15 caracteres); en Windows, el ejecutable."""


def listar_procesos(proc: Path = Path("/proc")) -> dict[int, Proceso]:
    """Todos los procesos del sistema, por PID."""
    if sys.platform == "win32":
        return _procesos_windows()
    return _procesos_linux(proc)


def _procesos_linux(proc: Path) -> dict[int, Proceso]:
    procesos = {}
    try:
        carpetas = list(proc.iterdir())
    except OSError:
        return {}
    for carpeta in carpetas:
        if not carpeta.name.isdigit():
            continue
        try:
            estado = (carpeta / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # el proceso ha terminado mientras se leía
        # El nombre va entre paréntesis y puede contener espacios y paréntesis: el PPID es el
        # segundo campo tras el último ")".
        nombre, resto = estado.split("(", 1)[1].rsplit(")", 1)
        pid = int(carpeta.name)
        procesos[pid] = Proceso(pid, int(resto.split()[1]), nombre)
    return procesos


def _procesos_windows() -> dict[int, Proceso]:
    if sys.platform != "win32":  # para mypy: solo se llama en Windows
        raise NotImplementedError
    import ctypes
    from ctypes import wintypes

    class Entrada(ctypes.Structure):  # PROCESSENTRY32W
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for funcion in (kernel32.Process32FirstW, kernel32.Process32NextW):
        funcion.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entrada))
        funcion.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    th32cs_snapprocess = 0x2
    instantanea = kernel32.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    if instantanea in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    procesos = {}
    try:
        entrada = Entrada()
        entrada.dwSize = ctypes.sizeof(Entrada)
        hay = kernel32.Process32FirstW(instantanea, ctypes.byref(entrada))
        while hay:
            pid = int(entrada.th32ProcessID)
            procesos[pid] = Proceso(pid, int(entrada.th32ParentProcessID), entrada.szExeFile)
            hay = kernel32.Process32NextW(instantanea, ctypes.byref(entrada))
    finally:
        kernel32.CloseHandle(instantanea)
    return procesos


def pids_propios(proc: Path = Path("/proc")) -> frozenset[int]:
    """PID de este proceso y de todos sus antecesores (terminal, shell…)."""
    procesos = listar_procesos(proc)
    pids = set()
    pid = os.getpid()
    # Se para en init (1) y en el PID 0; en Windows los PID son múltiplos de 4 y nunca valen 1.
    # En Windows el PID del padre puede estar reutilizado por otro proceso: el conjunto evita ciclos.
    while pid > 1 and pid not in pids:
        pids.add(pid)
        proceso = procesos.get(pid)
        if proceso is None:
            break
        pid = proceso.padre
    return frozenset(pids)


def descendientes(pid: int, procesos: dict[int, Proceso]) -> frozenset[int]:
    """El proceso y todos los que cuelgan de él."""
    hijos: dict[int, list[int]] = {}
    for proceso in procesos.values():
        if proceso.padre != proceso.pid:
            hijos.setdefault(proceso.padre, []).append(proceso.pid)
    pids = {pid}
    pendientes = [pid]
    while pendientes:
        for hijo in hijos.get(pendientes.pop(), []):
            if hijo not in pids:
                pids.add(hijo)
                pendientes.append(hijo)
    return frozenset(pids)
