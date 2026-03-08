# core/charts/__init__.py

from . import general, technologist, workshop, paint, film
from .general import get_data as general_get_data

HANDLERS = {
    "general": general_get_data,
    "technologist": technologist.get_data,
    "workshop": workshop.get_data,
    "paint": paint.get_data,
    "film": film.get_data,
}
