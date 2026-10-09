from flask import request
from werkzeug.exceptions import BadRequest, ServiceUnavailable

CATALOG_LIMIT = 500
DATA_LIMIT = 50000


def catalog_page():
    values = []
    for name, default in (("limit", CATALOG_LIMIT), ("offset", 0)):
        raw = request.args.get(name, str(default))
        if not raw.isascii() or not raw.isdigit() or len(raw) > 9:
            raise BadRequest("La paginación debe usar números enteros válidos.")
        values.append(int(raw))
    if not 1 <= values[0] <= CATALOG_LIMIT or values[1] > 1000000:
        raise BadRequest("El límite debe estar entre 1 y 500 y el desplazamiento entre 0 y 1000000.")
    return tuple(values)


def checked_rows(rows):
    if len(rows) > DATA_LIMIT:
        raise ServiceUnavailable("La competición supera el límite de consulta. Contacta con la administración.")
    return rows
