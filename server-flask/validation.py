import re
import unicodedata


def positive_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or len(str(value)) > 10 or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError(f"{label} debe ser un número entero positivo.")
    number = int(value)
    if not 1 <= number <= 2147483647:
        raise ValueError(f"{label} debe ser un número entero positivo válido.")
    return number


def validate_name(value):
    if not isinstance(value, str):
        raise ValueError("Introduce el nombre del equipo.")
    name = " ".join(unicodedata.normalize("NFC", value).split())
    if not name:
        raise ValueError("Introduce el nombre del equipo.")
    if len(name) > 100:
        raise ValueError("El nombre del equipo no puede superar los 100 caracteres.")
    if any(unicodedata.category(character).startswith("C") for character in name):
        raise ValueError("El nombre contiene caracteres no permitidos.")
    return name
