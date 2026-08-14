"""
apps.py — Konfigurasi Django app untuk GBP Monitor.
"""

from django.apps import AppConfig


class GbpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gbp"
    verbose_name = "GBP Monitor"
