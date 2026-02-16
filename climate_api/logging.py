import logging
import sys

ACCESS_LOGGER_NAME = "climate_api.access"


def configure_access_logger() -> logging.Logger:
    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.INFO)
    logger.propagate = False

    h = logging.StreamHandler(sys.stdout)
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(h)
    return logger


def _color(s: str, code: str, use_colors: bool = True) -> str:
    if not use_colors:
        return s
    return f"\x1b[{code}m{s}\x1b[0m"


def _bold(s: str, use_colors: bool = True) -> str:
    if not use_colors:
        return s
    return f"\x1b[1m{s}\x1b[0m"


def format_access_line(
    client_addr: str,
    request_line: str,
    status_code: int,
    duration_ms: float,
    use_colors: bool = True,
) -> str:
    # Uvicorn-ish status phrase
    phrase = "OK" if 200 <= status_code < 300 else ""
    if 300 <= status_code < 400:
        phrase = "REDIRECT"
    elif 400 <= status_code < 500:
        phrase = "CLIENT ERROR"
    elif status_code >= 500:
        phrase = "SERVER ERROR"

    # Colors similar to uvicorn:
    # - INFO in green
    # - 2xx green, 3xx cyan, 4xx red, 5xx bright red
    info = _color("INFO", "32", use_colors)
    if 200 <= status_code < 300:
        status = _color(f"{status_code} {phrase}".rstrip(), "32", use_colors)
    elif 300 <= status_code < 400:
        status = _color(f"{status_code} {phrase}".rstrip(), "36", use_colors)
    elif 400 <= status_code < 500:
        status = _color(f"{status_code} {phrase}".rstrip(), "31", use_colors)
    else:
        status = _color(f"{status_code} {phrase}".rstrip(), "91", use_colors)

    request_line = _bold(request_line, use_colors)

    # match uvicorn spacing: `INFO:     ... - "..." 200 OK`
    return (
        f'{info}:     {client_addr} - "{request_line}" {status} ({duration_ms:.1f} ms)'
    )
