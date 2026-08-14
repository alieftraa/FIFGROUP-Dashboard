"""
wsgi.py — WSGI config untuk GBP Monitor.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gbp_monitor.settings")
application = get_wsgi_application()
