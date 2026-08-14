"""
admin.py — Django Admin untuk GBP Monitor.
"""

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from .models import FetchRun, LocationSnapshot, MasterLocation, BranchSalesRecord


# ══════════════════════════════════════════════════════════════════════
# CUSTOM FORM: MasterLocation dengan field koordinat gabungan
# ══════════════════════════════════════════════════════════════════════

class MasterLocationAdminForm(forms.ModelForm):
    """
    Form kustom agar kolom latitude & longitude tampil sebagai satu field
    'lat, lng' di halaman admin. Parsing dilakukan secara otomatis.
    """
    coordinates = forms.CharField(
        required=False,
        label="Koordinat Manual (lat, lng)",
        widget=forms.TextInput(attrs={
            "placeholder": "Contoh: -6.200000, 106.816666",
            "style": "width: 300px; font-family: monospace;",
        }),
        help_text=(
            "Isi dalam format: <b>latitude, longitude</b> "
            "(pisahkan dengan koma). Kosongkan jika ingin menggunakan koordinat dari GBP API. "
            "Contoh: <code>-6.200000, 106.816666</code>"
        ),
    )

    class Meta:
        model = MasterLocation
        # Sertakan semua field kecuali latitude & longitude (digantikan oleh 'coordinates')
        exclude = ["latitude", "longitude"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Jika data sudah ada, isi field 'coordinates' dengan nilai yang ada
        instance = kwargs.get("instance")
        if instance and instance.latitude is not None and instance.longitude is not None:
            self.fields["coordinates"].initial = f"{instance.latitude}, {instance.longitude}"

    def clean_coordinates(self):
        """Parse dan validasi nilai koordinat gabungan."""
        value = self.cleaned_data.get("coordinates", "").strip()
        if not value:
            return None  # Boleh kosong

        try:
            parts = [p.strip() for p in value.split(",")]
            if len(parts) != 2:
                raise ValueError
            lat = float(parts[0])
            lng = float(parts[1])
        except (ValueError, TypeError):
            raise ValidationError(
                "Format koordinat tidak valid. Gunakan format: lat, lng "
                "(contoh: -6.200000, 106.816666)"
            )

        if not (-90 <= lat <= 90):
            raise ValidationError("Latitude harus antara -90 dan 90.")
        if not (-180 <= lng <= 180):
            raise ValidationError("Longitude harus antara -180 dan 180.")

        return f"{lat}, {lng}"

    def save(self, commit=True):
        """Pisahkan field 'coordinates' kembali ke latitude & longitude sebelum disimpan."""
        instance = super().save(commit=False)
        coords = self.cleaned_data.get("coordinates")
        if coords:
            lat_str, lng_str = coords.split(",")
            instance.latitude = float(lat_str.strip())
            instance.longitude = float(lng_str.strip())
        else:
            instance.latitude = None
            instance.longitude = None
        if commit:
            instance.save()
        return instance


# ══════════════════════════════════════════════════════════════════════
# ADMIN: MasterLocation
# ══════════════════════════════════════════════════════════════════════

def coordinates_display(obj):
    """Kolom tampilan koordinat gabungan untuk list view."""
    if obj.latitude is not None and obj.longitude is not None:
        return f"{obj.latitude}, {obj.longitude}"
    return "—"
coordinates_display.short_description = "Koordinat (Manual)"


@admin.register(MasterLocation)
class MasterLocationAdmin(admin.ModelAdmin):
    form = MasterLocationAdminForm
    list_display = [
        "store_code", "network_name", "network", "business_name",
        "area", "verification_status", coordinates_display,
    ]
    list_display_links = ["store_code", "network_name", "business_name"]
    list_filter = ["network", "area", "verification_status"]
    search_fields = ["store_code", "network_name", "business_name"]
    ordering = ["store_code"]
    fieldsets = [
        (None, {
            "fields": ["store_code", "business_name", "network_name", "network", "area", "account_name", "verification_status"]
        }),
        ("Koordinat Manual (Fallback)", {
            "fields": ["coordinates"],
            "description": (
                "Isi hanya jika lokasi tidak memiliki koordinat dari GBP API. "
                "Koordinat ini akan digunakan sebagai cadangan untuk peta."
            ),
        }),
    ]


# ══════════════════════════════════════════════════════════════════════
# ADMIN: FetchRun & LocationSnapshot
# ══════════════════════════════════════════════════════════════════════

@admin.register(FetchRun)
class FetchRunAdmin(admin.ModelAdmin):
    list_display = [
        "id", "run_date", "run_timestamp",
        "total", "verified", "duplicate", "suspended", "unverified",
    ]
    list_filter = ["run_date"]
    ordering = ["-id"]
    readonly_fields = ["run_timestamp"]


@admin.register(LocationSnapshot)
class LocationSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        "id", "run", "store_code", "business_name",
        "status", "coord_status", "fetched_at",
    ]
    list_filter = ["status", "coord_status", "run"]
    search_fields = ["store_code", "business_name", "location_name"]
    raw_id_fields = ["run"]
    ordering = ["-id"]


@admin.register(BranchSalesRecord)
class BranchSalesRecordAdmin(admin.ModelAdmin):
    list_display = [
        "branch_prefix", "branch_name", "area", "period",
        "nsa", "bp", "mscp", "nl", "uploaded_at",
    ]
    list_display_links = ["branch_prefix", "branch_name"]
    list_filter = ["period", "area"]
    search_fields = ["branch_prefix", "branch_name"]
    ordering = ["-period", "branch_prefix"]
