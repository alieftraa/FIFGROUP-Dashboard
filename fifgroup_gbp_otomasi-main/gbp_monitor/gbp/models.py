"""
models.py — Django ORM models untuk GBP Monitor.
Semua data disimpan ke Supabase PostgreSQL via DATABASE_URL.

Models:
  FetchRun           → metadata setiap eksekusi fetch GBP API
  LocationSnapshot   → status per lokasi untuk setiap run
  MasterLocation     → data master network/outlet
  ReconciliationJob  → metadata proses pencocokan
  ReconciliationResult → detail hasil pencocokan per baris
"""

from django.db import models
from django.utils import timezone


# ══════════════════════════════════════════════════════════════════════
# FETCH RUN & SNAPSHOT
# ══════════════════════════════════════════════════════════════════════

class FetchRun(models.Model):
    """
    Metadata setiap eksekusi fetch GBP API.
    Menggantikan tabel `runs` di gbp_history.db.
    """

    run_date = models.DateField(
        verbose_name="Tanggal Run",
        db_index=True,
    )
    run_timestamp = models.DateTimeField(
        verbose_name="Timestamp Run",
        default=timezone.now,
    )
    total = models.IntegerField(verbose_name="Total Lokasi", default=0)
    verified = models.IntegerField(verbose_name="Verified", default=0)
    duplicate = models.IntegerField(verbose_name="Duplicate", default=0)
    suspended = models.IntegerField(verbose_name="Suspended", default=0)
    # Field ini tetap bernama `unverified` untuk backward compatibility
    # dengan data yang sudah ada, tapi dicatat sebagai "Verification Required"
    unverified = models.IntegerField(verbose_name="Verification Required", default=0)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        verbose_name = "Fetch Run"
        verbose_name_plural = "Fetch Runs"
        ordering = ["-id"]
        db_table = "gbp_fetchrun"

    def __str__(self) -> str:
        return f"Run #{self.pk} — {self.run_date} ({self.total:,} lokasi)"

    @property
    def verification_required(self) -> int:
        """Alias backward-compatible untuk field unverified."""
        return self.unverified

    @property
    def verified_pct(self) -> float:
        total = self.total or 1
        return round(self.verified / total * 100, 1)

    @property
    def duplicate_pct(self) -> float:
        total = self.total or 1
        return round(self.duplicate / total * 100, 1)

    @property
    def suspended_pct(self) -> float:
        total = self.total or 1
        return round(self.suspended / total * 100, 1)

    @property
    def unverified_pct(self) -> float:
        total = self.total or 1
        return round(self.unverified / total * 100, 1)


class LocationSnapshot(models.Model):
    """
    Status satu lokasi GBP untuk satu run tertentu.
    Menggantikan tabel `snapshots` di gbp_history.db.
    """

    STATUS_VERIFIED = "Verified"
    STATUS_DUPLICATE = "Duplicate"
    STATUS_SUSPENDED = "Suspended"
    STATUS_NEED_VERIFICATION = "Need Verification"
    STATUS_UNVERIFIED = "Unverified"

    STATUS_CHOICES = [
        (STATUS_VERIFIED, "Verified"),
        (STATUS_DUPLICATE, "Duplicate"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_NEED_VERIFICATION, "Need Verification"),
        (STATUS_UNVERIFIED, "Unverified"),
    ]

    COORD_OK = "OK"
    COORD_MISSING = "MISSING"
    COORD_PARSE_ERROR = "PARSE_ERROR"
    COORD_OUT_OF_RANGE = "OUT_OF_RANGE"

    COORD_STATUS_CHOICES = [
        (COORD_OK, "OK"),
        (COORD_MISSING, "Missing"),
        (COORD_PARSE_ERROR, "Parse Error"),
        (COORD_OUT_OF_RANGE, "Out of Range"),
    ]

    run = models.ForeignKey(
        FetchRun,
        on_delete=models.CASCADE,
        related_name="snapshots",
        verbose_name="Run",
        db_index=True,
    )
    store_code = models.CharField(
        max_length=100, blank=True, null=True,
        verbose_name="Kode Kios", db_index=True,
    )
    location_name = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name="Location ID",
    )
    business_name = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name="Nama Bisnis",
    )
    account_name = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name="Account Name",
    )
    address = models.TextField(blank=True, null=True, verbose_name="Alamat")
    latitude = models.FloatField(null=True, blank=True, verbose_name="Latitude")
    longitude = models.FloatField(null=True, blank=True, verbose_name="Longitude")
    coord_status = models.CharField(
        max_length=20,
        choices=COORD_STATUS_CHOICES,
        default=COORD_MISSING,
        verbose_name="Status Koordinat",
    )
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        verbose_name="Status Verifikasi",
        db_index=True,
    )
    has_vom = models.BooleanField(default=False, verbose_name="Has Voice of Merchant")
    is_duplicate = models.BooleanField(default=False, verbose_name="Is Duplicate")
    is_suspended = models.BooleanField(default=False, verbose_name="Is Suspended")
    has_pending_edits = models.BooleanField(default=False, verbose_name="Has Pending Edits")
    maps_uri = models.TextField(blank=True, null=True, verbose_name="Google Maps URI")
    fetched_at = models.DateTimeField(null=True, blank=True, verbose_name="Waktu Fetch")
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        verbose_name = "Location Snapshot"
        verbose_name_plural = "Location Snapshots"
        db_table = "gbp_locationsnapshot"
        indexes = [
            models.Index(fields=["run", "status"]),
            models.Index(fields=["store_code"]),
            models.Index(fields=["location_name"]),
            models.Index(fields=["business_name"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.business_name} ({self.store_code}) — {self.status}"

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


# ══════════════════════════════════════════════════════════════════════
# MASTER LOCATION
# ══════════════════════════════════════════════════════════════════════

class MasterLocation(models.Model):
    """
    Data master outlet/network. Sumber kebenaran untuk pencocokan.
    Import dari CSV master menggunakan command: import_master_locations
    """

    store_code = models.CharField(
        max_length=100, unique=True, blank=True, null=True,
        verbose_name="Kode Kios / Store Code", db_index=True,
    )
    location_name = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name="Location ID / Nama Lokasi", db_index=True,
    )
    business_name = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name="Nama Bisnis", db_index=True,
    )
    network_name = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name="Nama Network",
    )
    area = models.CharField(
        max_length=150, blank=True, null=True,
        verbose_name="Area",
    )
    network = models.CharField(
        max_length=100, blank=True, null=True,
        verbose_name="Jenis Network",
    )
    account_name = models.CharField(
        max_length=255, blank=True, null=True,
        verbose_name="Account Name",
    )
    verification_status = models.CharField(
        max_length=50, blank=True, null=True,
        verbose_name="Status Verifikasi", db_index=True,
    )
    # Koordinat manual — digunakan sebagai fallback jika GBP API tidak punya koordinat
    latitude = models.FloatField(
        null=True, blank=True,
        verbose_name="Latitude (Manual)",
        help_text="Isi jika lokasi tidak terdeteksi oleh GBP API. Format: -6.200000",
    )
    longitude = models.FloatField(
        null=True, blank=True,
        verbose_name="Longitude (Manual)",
        help_text="Isi jika lokasi tidak terdeteksi oleh GBP API. Format: 106.816666",
    )
    last_synced_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Terakhir Disinkronkan",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Master Location"
        verbose_name_plural = "Master Locations"
        db_table = "gbp_masterlocation"
        indexes = [
            models.Index(fields=["verification_status"]),
            models.Index(fields=["network_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.business_name} [{self.store_code}] — {self.verification_status}"


class MasterDataHistory(models.Model):
    """
    Menyimpan history jumlah total network setiap kali ada update master data.
    Digunakan untuk data chart efisiensi penyimpanan.
    """
    total_network = models.IntegerField(default=0, verbose_name="Total Network")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Master Data History"
        verbose_name_plural = "Master Data Histories"
        db_table = "gbp_masterdatahistory"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at.strftime('%Y-%m-%d %H:%M:%S')} - {self.total_network} networks"


# ══════════════════════════════════════════════════════════════════════
# RECONCILIATION JOB & RESULTS
# ══════════════════════════════════════════════════════════════════════

class ReconciliationJob(models.Model):
    """
    Metadata satu proses rekonsiliasi status verifikasi.
    Dibuat setiap kali user menjalankan Update Status Verifikasi.
    """

    job_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Nama Job")
    source_type = models.CharField(max_length=100, blank=True, null=True, verbose_name="Tipe Sumber")
    source_label = models.CharField(max_length=500, blank=True, null=True, verbose_name="Label Sumber")

    total_master = models.IntegerField(default=0, verbose_name="Total Master")
    total_api = models.IntegerField(default=0, verbose_name="Total API")
    total_matched = models.IntegerField(default=0, verbose_name="Total Matched")
    total_updated = models.IntegerField(default=0, verbose_name="Total Updated")
    total_unchanged = models.IntegerField(default=0, verbose_name="Total Unchanged")
    total_not_found_master = models.IntegerField(default=0, verbose_name="Tidak Ditemukan di Master")
    total_not_found_api = models.IntegerField(default=0, verbose_name="Tidak Ditemukan di API")
    total_invalid = models.IntegerField(default=0, verbose_name="Total Invalid")
    total_manual_review = models.IntegerField(default=0, verbose_name="Total Manual Review")
    total_error = models.IntegerField(default=0, verbose_name="Total Error")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Reconciliation Job"
        verbose_name_plural = "Reconciliation Jobs"
        db_table = "gbp_reconciliationjob"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Job #{self.pk} — {self.job_name} ({self.created_at})"


class ReconciliationResult(models.Model):
    """
    Satu baris hasil pencocokan dalam satu ReconciliationJob.
    """

    PROCESS_STATUS_CHOICES = [
        ("Updated", "Updated"),
        ("Unchanged", "Unchanged"),
        ("Not Found in Master", "Not Found in Master"),
        ("Not Found in API", "Not Found in API"),
        ("Invalid", "Invalid"),
        ("Manual Review", "Manual Review"),
        ("Error", "Error"),
        # Legacy compatibility
        ("Matched", "Matched"),
        ("Not Found", "Not Found"),
    ]

    job = models.ForeignKey(
        ReconciliationJob,
        on_delete=models.CASCADE,
        related_name="results",
        verbose_name="Job",
    )
    store_code = models.CharField(max_length=100, blank=True, null=True, verbose_name="Store Code", db_index=True)
    network_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Network Name")
    business_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Nama Bisnis", db_index=True)
    location_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Location Name", db_index=True)
    identifier_value = models.CharField(max_length=255, blank=True, null=True, verbose_name="Nilai Identifier")
    match_rule = models.CharField(max_length=100, blank=True, null=True, verbose_name="Aturan Matching")
    old_status = models.CharField(max_length=100, blank=True, null=True, verbose_name="Status Lama")
    new_status = models.CharField(max_length=100, blank=True, null=True, verbose_name="Status Baru")
    process_status = models.CharField(
        max_length=100,
        choices=PROCESS_STATUS_CHOICES,
        verbose_name="Status Proses",
        db_index=True,
    )
    status_changed = models.BooleanField(default=False, verbose_name="Status Berubah?", db_index=True)
    change_note = models.TextField(blank=True, null=True, verbose_name="Catatan Perubahan")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Reconciliation Result"
        verbose_name_plural = "Reconciliation Results"
        db_table = "gbp_reconciliationresult"
        indexes = [
            models.Index(fields=["job", "process_status"]),
            models.Index(fields=["job", "status_changed"]),
            models.Index(fields=["store_code"]),
            models.Index(fields=["business_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.identifier_value} — {self.process_status}"


# ══════════════════════════════════════════════════════════════════════
# BRANCH SALES RECORD
# ══════════════════════════════════════════════════════════════════════

class BranchSalesRecord(models.Model):
    """
    Data performa penjualan per cabang per periode.
    Diupload via CSV dari halaman Update Data.
    Ditampilkan di popup peta Branch Coverage dan Performance Report.

    Kolom utama Performance Report:
      nsa    → Nett Service Asset (Rupiah, CharField agar bisa terima format asli)
      osa    → NSA dalam Unit (jumlah kontrak)
      cd     → Cycle Delinquent (%)
      profit → Profit cabang (Rupiah, float)
      nl     → Nett Losses (Rupiah / persentase, float)
    """

    branch_prefix = models.CharField(
        max_length=10,
        verbose_name="Prefix Cabang (3 digit)",
        db_index=True,
        help_text="3 digit pertama store code cabang. Contoh: 101",
    )
    branch_name = models.CharField(
        max_length=255,
        verbose_name="Nama Cabang",
    )
    area = models.CharField(
        max_length=150,
        blank=True, null=True,
        verbose_name="Area",
    )
    period = models.CharField(
        max_length=7,
        verbose_name="Periode (YYYY-MM)",
        db_index=True,
        help_text="Format: YYYY-MM. Contoh: 2026-06",
    )
    nsa = models.CharField(
        max_length=100,
        blank=True, null=True,
        verbose_name="NSA",
        help_text="Nett Service Asset (Rupiah). Contoh: 333.115.001.111",
    )
    osa = models.FloatField(
        null=True, blank=True,
        verbose_name="OSA (Unit)",
        help_text="NSA dalam Unit. Jumlah kontrak/kendaraan yang dibiayai.",
    )
    cd = models.FloatField(
        null=True, blank=True,
        verbose_name="CD (%)",
        help_text="Cycle Delinquent dalam persen. Contoh: 95.20",
    )
    profit = models.FloatField(
        null=True, blank=True,
        verbose_name="Profit (Rupiah)",
        help_text="Profit cabang dalam Rupiah. Bisa positif atau negatif.",
    )
    bp = models.FloatField(
        null=True, blank=True,
        verbose_name="BP (%)",
        help_text="Bisa positif atau negatif. Contoh: 31.59 atau -9.89",
    )
    mscp = models.FloatField(
        null=True, blank=True,
        verbose_name="MSCP (%)",
        help_text="Bisa positif atau negatif.",
    )
    nl = models.FloatField(
        null=True, blank=True,
        verbose_name="NL (Nett Losses)",
        help_text="Nett Losses. Bisa dalam Rupiah atau persentase tergantung konteks upload.",
    )
    uploaded_at = models.DateTimeField(auto_now=True, verbose_name="Terakhir Diupload")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Branch Sales Record"
        verbose_name_plural = "Branch Sales Records"
        db_table = "gbp_branchsalesrecord"
        # Satu record per cabang per periode (upsert)
        unique_together = [("branch_prefix", "period")]
        ordering = ["-period", "branch_prefix"]
        indexes = [
            models.Index(fields=["branch_prefix", "period"]),
        ]

    def __str__(self) -> str:
        return f"{self.branch_name} ({self.branch_prefix}) — {self.period}"

    @property
    def osa_display(self) -> str:
        if self.osa is None:
            return "—"
        return f"{int(self.osa):,} Unit"

    @property
    def cd_display(self) -> str:
        if self.cd is None:
            return "—"
        return f"{self.cd:.2f}%"

    @property
    def profit_display(self) -> str:
        if self.profit is None:
            return "—"
        sign = "+" if self.profit >= 0 else ""
        return f"{sign}Rp {abs(self.profit):,.0f}"

    @property
    def bp_display(self) -> str:
        """Format tampilan BP dengan tanda + atau -."""
        if self.bp is None:
            return "—"
        sign = "+" if self.bp >= 0 else ""
        return f"{sign}{self.bp:.2f}%"

    @property
    def mscp_display(self) -> str:
        if self.mscp is None:
            return "—"
        sign = "+" if self.mscp >= 0 else ""
        return f"{sign}{self.mscp:.2f}%"

    @property
    def nl_display(self) -> str:
        if self.nl is None:
            return "—"
        sign = "+" if self.nl >= 0 else ""
        return f"{sign}{self.nl:.2f}"
