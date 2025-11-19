import multiprocessing
multiprocessing.freeze_support()

from celery import Celery
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery = Celery(
    "app",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks"],   # <-- force Celery to load tasks
)

celery.conf.task_track_started = True
celery.conf.worker_max_tasks_per_child = 100
