"""
forms.py — Django forms untuk GBP Monitor.
"""

from django import forms
from .utils import ALL_STATUSES


class DataTableFilterForm(forms.Form):
    """Form filter untuk halaman Data Table."""

    run_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    search = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            "placeholder": "Cari nama bisnis / kode kios / location ID...",
            "id": "search-input",
            "autocomplete": "off",
        }),
        label="Cari",
    )

    STATUS_CHOICES = [(s, s) for s in ALL_STATUSES]
    statuses = forms.MultipleChoiceField(
        required=False,
        choices=STATUS_CHOICES,
        widget=forms.CheckboxSelectMultiple(),
        label="Filter Status",
        initial=ALL_STATUSES,
    )

    SORT_CHOICES = [
        ("business_name", "Nama Bisnis"),
        ("store_code", "Kode Kios"),
        ("status", "Status"),
        ("fetched_at", "Waktu Update"),
    ]
    sort = forms.ChoiceField(
        required=False,
        choices=SORT_CHOICES,
        initial="business_name",
        label="Urutkan",
    )

    ORDER_CHOICES = [
        ("asc", "A → Z"),
        ("desc", "Z → A"),
    ]
    order = forms.ChoiceField(
        required=False,
        choices=ORDER_CHOICES,
        initial="asc",
        label="Urutan",
    )

    page = forms.IntegerField(
        required=False,
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"min": "1", "id": "page-input"}),
        label="Halaman",
    )

    def clean_statuses(self):
        statuses = self.cleaned_data.get("statuses", [])
        if not statuses:
            return ALL_STATUSES
        return statuses

    def clean_page(self):
        return self.cleaned_data.get("page") or 1

    def clean_sort(self):
        return self.cleaned_data.get("sort") or "business_name"

    def clean_order(self):
        return self.cleaned_data.get("order") or "asc"


class UpdateStatusForm(forms.Form):
    """Form untuk halaman Update Status Verifikasi GBP."""

    SOURCE_CSV = "csv"
    SOURCE_SQLITE = "sqlite"
    SOURCE_CHOICES = [
        (SOURCE_CSV, "CSV"),
        (SOURCE_SQLITE, "SQLite"),
    ]

    source_type = forms.ChoiceField(
        choices=SOURCE_CHOICES,
        initial=SOURCE_CSV,
        widget=forms.RadioSelect(attrs={"class": "source-radio"}),
        label="Sumber Master",
    )

    master_file = forms.FileField(
        required=False,
        label="Upload File Master CSV",
        widget=forms.FileInput(attrs={
            "accept": ".csv",
            "id": "master-file-input",
        }),
        help_text="Upload file CSV master data",
    )

    master_path = forms.CharField(
        required=False,
        max_length=500,
        label="Path File Master (di server)",
        widget=forms.TextInput(attrs={
            "placeholder": r"Contoh: D:\path\to\master.csv atau master.db",
            "id": "master-path-input",
        }),
        help_text="Path absolut ke file master di server (opsional jika upload file)",
    )

    sqlite_table = forms.CharField(
        required=False,
        max_length=100,
        initial="kios",
        label="Nama Tabel SQLite",
        widget=forms.TextInput(attrs={
            "placeholder": "kios",
            "id": "sqlite-table-input",
        }),
    )

    account_id = forms.CharField(
        required=False,
        max_length=200,
        label="Account ID GBP (opsional)",
        widget=forms.TextInput(attrs={
            "placeholder": "accounts/123456789",
            "id": "account-id-input",
        }),
        help_text="Kosongkan untuk mengambil dari semua akun",
    )

    save_to_disk = forms.BooleanField(
        required=False,
        initial=False,
        label="Simpan perubahan ke file master di disk",
        widget=forms.CheckboxInput(attrs={"id": "save-to-disk-checkbox"}),
    )

    def clean(self):
        cleaned = super().clean()
        source_type = cleaned.get("source_type")
        master_file = cleaned.get("master_file")
        master_path = cleaned.get("master_path", "").strip()

        if source_type == self.SOURCE_CSV:
            if not master_file and not master_path:
                raise forms.ValidationError(
                    "Upload file CSV master atau isi path file master."
                )
        elif source_type == self.SOURCE_SQLITE:
            if not master_path:
                raise forms.ValidationError(
                    "Isi path file SQLite master."
                )

        return cleaned
