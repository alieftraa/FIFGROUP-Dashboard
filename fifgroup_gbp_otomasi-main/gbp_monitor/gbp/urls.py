"""
urls.py — URL routing untuk GBP app.
"""

from django.urls import path
from . import views

app_name = "gbp"

urlpatterns = [
    # ── Halaman utama ─────────────────────────────────────────────────────────────
    path("", views.OverviewView.as_view(), name="overview"),
    path("data/", views.DataTableView.as_view(), name="data_table"),
    path("map/", views.MapView.as_view(), name="map_view"),
    path("update/", views.UpdateStatusView.as_view(), name="update_status"),
    path("location/<int:pk>/", views.LocationDetailView.as_view(), name="location_detail"),
    path("download/", views.DownloadReportView.as_view(), name="download_report"),

    # ── Export / Download ─────────────────────────────────────────────────────────
    path("export/csv/", views.ExportCSVView.as_view(), name="export_csv"),
    path("export/excel/", views.ExportExcelView.as_view(), name="export_excel"),
    path("reconciliation/<int:job_id>/download/", views.DownloadReconciliationView.as_view(), name="download_reconciliation"),
    path("download/recon/<int:job_id>/", views.DownloadReconDetailView.as_view(), name="download_recon_detail"),

    # ── API internal ─────────────────────────────────────────────────────────────
    path("api/fetch-run/", views.TriggerFetchView.as_view(), name="trigger_fetch"),
    path("api/trend/", views.TrendDataView.as_view(), name="trend_data"),
    path("api/map-data/", views.MapDataAPIView.as_view(), name="map_data_api"),
    path("api/area-coverage/", views.AreaCoverageAPIView.as_view(), name="area_coverage_api"),
    path("api/area-color-map/", views.AreaColorMapAPIView.as_view(), name="area_color_map_api"),
    path("api/branch-boundaries/", views.BranchBoundariesAPIView.as_view(), name="branch_boundaries_api"),
    path("api/branch-performance/", views.BranchPerformanceAPIView.as_view(), name="branch_performance_api"),

    # ── Sales Performance ─────────────────────────────────────────────────────────
    path("upload-sales/", views.UploadSalesView.as_view(), name="upload_sales"),
    path("download-sales-template/", views.DownloadSalesTemplateView.as_view(), name="download_sales_template"),
]
