"""
manage.py — Django management utility untuk GBP Monitor.
"""

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gbp_monitor.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Tidak bisa mengimpor Django. Pastikan Django sudah terinstall "
            "dan DJANGO_SETTINGS_MODULE sudah dikonfigurasi."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
