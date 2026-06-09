LINE_HEAD = "LINESCANNER -TOPO"
MOVER_HEAD = "LINEMOVER -xy"
END = "\r\n"


def set_line_endpoint(name: str, value: float) -> str:
    return f"{LINE_HEAD} -{name} -set={value:g}{END}"


def set_npoints(value: int) -> str:
    return f"{LINE_HEAD} -npoints -set={value:d}{END}"


def set_sample(value: float) -> str:
    return f"{LINE_HEAD} -sample -set={value:g}{END}"


def set_settle(value: float) -> str:
    return f"{LINE_HEAD} -settle -set={value:g}{END}"


def set_idle(value: float) -> str:
    return f"{LINE_HEAD} -idle -set={value:g}{END}"


def set_velocity(value: float) -> str:
    return f"{MOVER_HEAD} -velocity -set={value:g}{END}"


def run() -> str:
    return f"{LINE_HEAD} -ctrl -run{END}"


def pause() -> str:
    return f"{LINE_HEAD} -ctrl -pause{END}"


def unpause() -> str:
    return f"{LINE_HEAD} -ctrl -unpause{END}"


def stop() -> str:
    return f"{LINE_HEAD} -ctrl -stop{END}"
