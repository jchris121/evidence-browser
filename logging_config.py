import logging
import logging.handlers
import os
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)


class CompactFormatter(logging.Formatter):
    def format(self, record):
        return f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [{record.levelname}] {record.name}: {record.getMessage()}"


def setup_logging():
    fmt = CompactFormatter()

    # App logger - general application events
    app = logging.getLogger('app')
    app.setLevel(logging.INFO)
    h = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, 'app.log'), maxBytes=5*1024*1024, backupCount=3
    )
    h.setFormatter(fmt)
    app.addHandler(h)

    # Auth logger - security events
    auth = logging.getLogger('auth')
    auth.setLevel(logging.INFO)
    h2 = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, 'auth.log'), maxBytes=5*1024*1024, backupCount=5
    )
    h2.setFormatter(fmt)
    auth.addHandler(h2)

    # Access logger - only errors and slow requests
    access = logging.getLogger('access')
    access.setLevel(logging.WARNING)
    h3 = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, 'access.log'), maxBytes=5*1024*1024, backupCount=2
    )
    h3.setFormatter(fmt)
    access.addHandler(h3)

    # Stderr for errors only
    stderr = logging.StreamHandler()
    stderr.setLevel(logging.WARNING)
    stderr.setFormatter(fmt)
    app.addHandler(stderr)
    auth.addHandler(stderr)
