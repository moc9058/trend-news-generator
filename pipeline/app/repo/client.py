from functools import lru_cache

from google.cloud import firestore

from app.config import get_settings


@lru_cache
def db() -> firestore.Client:
    return firestore.Client(project=get_settings().project_id)
