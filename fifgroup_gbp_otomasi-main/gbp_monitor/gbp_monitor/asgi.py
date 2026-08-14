"""
asgi.py — ASGI config untuk GBP Monitor.
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gbp_monitor.settings")
application = get_asgi_application()
