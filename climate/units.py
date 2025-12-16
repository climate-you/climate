

# -----------------------------------------------------------
# Helpers to convert temperatures
# -----------------------------------------------------------

FAHRENHEIT_COUNTRIES = {"US", "BS", "BZ", "KY", "PW", "FM", "MH", "LR"}  # common °F users

def default_unit_for_country(country_code: str | None) -> str:
    return "°F" if (country_code or "").upper() in FAHRENHEIT_COUNTRIES else "°C"

def c_to_f(x: float) -> float:
    return x * 9.0 / 5.0 + 32.0

def convert_temp(x_c: float, unit: str) -> float:
    return c_to_f(x_c) if unit == "°F" else x_c

def convert_delta(delta_c: float, unit: str) -> float:
    # differences scale but do not shift
    return delta_c * 9.0 / 5.0 if unit == "°F" else delta_c

def fmt_temp(x_c: float, unit: str, decimals: int = 1) -> str:
    v = convert_temp(float(x_c), unit)
    return f"{v:.{decimals}f}{unit}"

def fmt_delta(delta_c: float, unit: str, decimals: int = 1, sign = True) -> str:
    v = convert_delta(float(delta_c), unit)
    if sign:
        return f"{v:+.{decimals}f}{unit}"
    else:
        return f"{v:.{decimals}f}{unit}"
