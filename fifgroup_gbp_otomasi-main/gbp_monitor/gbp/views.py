"""
views.py — Django views untuk GBP Monitor.
Semua business logic didelegasikan ke services layer.

Views:
  OverviewView              → GET /
  DataTableView             → GET /data/
  MapView                   → GET /map/
  UpdateStatusView          → GET + POST /update/
  LocationDetailView        → GET /location/<int:pk>/
  DownloadReportView        → GET /download/
  ExportCSVView             → GET /export/csv/
  ExportExcelView           → GET /export/excel/
  DownloadReconciliationView→ GET /reconciliation/<job_id>/download/
  DownloadReconDetailView   → GET /download/recon/<job_id>/
  TriggerFetchView          → POST /api/fetch-run/
  TrendDataView             → GET /api/trend/
  UploadSalesView           → POST /upload-sales/
  DownloadSalesTemplateView → GET /download-sales-template/
"""

import json
import logging
from datetime import datetime

import pandas as pd
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from gbp.forms import DataTableFilterForm, UpdateStatusForm
from gbp.models import FetchRun, LocationSnapshot, MasterLocation, ReconciliationJob, ReconciliationResult, BranchSalesRecord
from gbp.services import export_service, history_service, reconciliation_service, dashboard_service
from gbp.utils import ALL_STATUSES, PAGE_SIZE, STATUS_META, get_status_meta

log = logging.getLogger("gbp.views")


# ── Helper ─────────────────────────────────────────────────────────────

def _get_run_context(request: HttpRequest) -> dict:
    """Ambil context umum: semua runs, run yang dipilih, run_id dari query param."""
    all_runs = history_service.get_all_runs()
    run_id = request.GET.get("run_id") or (all_runs[0]["run_id"] if all_runs else None)

    try:
        run_id = int(run_id) if run_id else None
    except (ValueError, TypeError):
        run_id = all_runs[0]["run_id"] if all_runs else None

    sel_run = history_service.get_run_by_id(run_id) if run_id else None

    return {
        "all_runs": all_runs,
        "sel_run": sel_run,
        "sel_run_id": run_id,
        "status_meta": STATUS_META,
        "all_statuses": ALL_STATUSES,
    }


# ══════════════════════════════════════════════════════════════════════
# PAGE 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════

class OverviewView(View):
    template_name = "gbp/overview.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        ctx = _get_run_context(request)

        if not ctx["all_runs"]:
            return render(request, self.template_name, {**ctx, "no_data": True})

        run_id = ctx["sel_run_id"]
        
        summary = dashboard_service.get_overview_summary(run_id)
        verified_growth = dashboard_service.get_verified_growth_timeseries(days=30)
        top_areas = dashboard_service.get_top_areas(run_id, limit=10)
        bottom_areas = dashboard_service.get_bottom_areas(run_id, limit=10)
        status_by_network = dashboard_service.get_status_by_network_type(run_id)
        attention_summary = dashboard_service.get_attention_status_summary(run_id)
        
        # Gauge chart data — progress verifikasi
        gauge_total = summary.get("total", 0)
        gauge_verified = summary.get("verified", 0)
        gauge_pct = round((gauge_verified / gauge_total * 100) if gauge_total else 0, 1)
        gauge_unverified = max(0, gauge_total - gauge_verified)

        ctx.update({
            "summary": summary,
            "verified_growth_json": json.dumps(verified_growth),
            "top_areas": top_areas,
            "bottom_areas": bottom_areas,
            "status_by_network": status_by_network,
            "status_by_network_json": json.dumps(status_by_network),
            "attention_summary": attention_summary,
            "gauge_total": gauge_total,
            "gauge_verified": gauge_verified,
            "gauge_unverified": gauge_unverified,
            "gauge_pct": gauge_pct,
        })

        return render(request, self.template_name, ctx)


# ══════════════════════════════════════════════════════════════════════
# PAGE 2 — DATA TABLE
# ══════════════════════════════════════════════════════════════════════

class DataTableView(View):
    template_name = "gbp/data_table.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        ctx = _get_run_context(request)

        if not ctx["all_runs"]:
            return render(request, self.template_name, {**ctx, "no_data": True})

        run_id = ctx["sel_run_id"]
        form = DataTableFilterForm(request.GET or None)

        statuses = ALL_STATUSES
        search = ""
        sort_col = "business_name"
        sort_order = "asc"
        page_num = 1

        if form.is_valid():
            statuses = form.cleaned_data["statuses"] or ALL_STATUSES
            search = form.cleaned_data["search"] or ""
            sort_col = form.cleaned_data["sort"] or "business_name"
            sort_order = form.cleaned_data["order"] or "asc"
            page_num = form.cleaned_data["page"] or 1

        snapshots = history_service.get_snapshots(
            run_id=run_id,
            status_filter=list(statuses),
            search=search or None,
        )

        reverse = sort_order == "desc"
        snapshots.sort(
            key=lambda x: str(x.get(sort_col, "") or "").lower(),
            reverse=reverse,
        )

        paginator = Paginator(snapshots, PAGE_SIZE)
        page_obj = paginator.get_page(page_num)

        ctx.update({
            "form": form,
            "page_obj": page_obj,
            "paginator": paginator,
            "total_count": len(snapshots),
            "search": search,
            "statuses": statuses,
            "sort_col": sort_col,
            "sort_order": sort_order,
            "get_status_meta": get_status_meta,
        })
        return render(request, self.template_name, ctx)


# ══════════════════════════════════════════════════════════════════════
# PAGE 3 — MAP VIEW
# ══════════════════════════════════════════════════════════════════════

class MapView(View):
    template_name = "gbp/map_view.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        ctx = _get_run_context(request)

        if not ctx["all_runs"]:
            return render(request, self.template_name, {**ctx, "no_data": True})

        run_id = ctx["sel_run_id"]
        # Ambil mode peta: status, network, atau coverage
        selected_mode = request.GET.get("mode", "status")

        # ══════════════════════════════════════════════════════════
        # MODE: BRANCH COVERAGE
        # ══════════════════════════════════════════════════════════
        if selected_mode == "coverage":
            return self._handle_coverage_mode(request, ctx, run_id)

        # ══════════════════════════════════════════════════════════
        # MODE: STATUS / NETWORK — Data dikirim via JSON API ke Leaflet
        # Folium tidak lagi digunakan untuk mode ini.
        # ══════════════════════════════════════════════════════════

        # Ambil semua snapshot untuk statistik sidebar
        all_snapshots = history_service.get_snapshots(run_id=run_id)

        with_coords_count = sum(
            1 for s in all_snapshots
            if s.get("latitude") is not None and s.get("longitude") is not None
        )
        without_coords_count = len(all_snapshots) - with_coords_count

        # Koordinat bermasalah
        coord_issues = [
            s for s in all_snapshots
            if s.get("coord_status") and s.get("coord_status") != "OK"
        ]

        ctx.update({
            "with_coords_count": with_coords_count,
            "without_coords_count": without_coords_count,
            "total_count": len(all_snapshots),
            "selected_mode": selected_mode,
            "coord_issues": coord_issues,
            "coord_issues_json": json.dumps([
                {
                    "store_code": s.get("store_code") or "—",
                    "business_name": s.get("business_name") or "—",
                    "address": (s.get("address") or "")[:80],
                    "coord_status": s.get("coord_status") or "UNKNOWN",
                }
                for s in coord_issues
            ], ensure_ascii=False),
        })
        return render(request, self.template_name, ctx)

    # ── Coverage Mode Handler ──────────────────────────────────────
    def _handle_coverage_mode(self, request, ctx, run_id):
        """Handle Branch Coverage Mode: grouping, map, summary, detail."""
        from gbp.services import map_coverage_service as cov_svc

        branch_prefix = request.GET.get("branch_prefix", "").strip()

        try:
            result = cov_svc.build_branch_coverage_groups(run_id)
            coverage_map_html = cov_svc.build_branch_coverage_map(result, selected_branch_prefix=branch_prefix or None)
            coverage_summary = cov_svc.calculate_branch_coverage_summary(result)

            # Build branch list for dropdown
            branch_list = []
            for g in result.get("groups", []):
                b = g["branch"]
                branch_list.append({
                    "prefix": b["prefix"],
                    "name": b["name"],
                    "area": b["area"],
                    "total_covered": g["summary"]["total"],
                    "color": g["color"],
                })

            # Selected branch detail
            selected_branch_detail = None
            if branch_prefix:
                selected_branch_detail = cov_svc.get_selected_branch_detail(result, branch_prefix)

            # Warnings
            coverage_warnings = {
                "duplicate_prefixes": result.get("duplicate_prefixes", []),
                "unmapped": result.get("unmapped", []),
                "invalid_store_codes": result.get("invalid_store_codes", []),
                "no_coord_networks": result.get("no_coord_networks", []),
                "has_warnings": bool(
                    result.get("duplicate_prefixes")
                    or result.get("unmapped")
                    or result.get("invalid_store_codes")
                    or result.get("no_coord_networks")
                ),
            }

        except Exception as exc:
            log.exception("Error building branch coverage data")
            coverage_map_html = ""
            coverage_summary = {}
            branch_list = []
            selected_branch_detail = None
            coverage_warnings = {"has_warnings": False}
            messages.error(request, f"Gagal membangun data coverage: {exc}")

        ctx.update({
            "selected_mode": "coverage",
            "coverage_map_html": coverage_map_html,
            "coverage_summary": coverage_summary,
            "branch_list": branch_list,
            "selected_branch_prefix": branch_prefix,
            "selected_branch_detail": selected_branch_detail,
            "coverage_warnings": coverage_warnings,
        })
        return render(request, self.template_name, ctx)


# ══════════════════════════════════════════════════════════════════════
# API — MAP DATA (JSON untuk Leaflet client-side map)
# ══════════════════════════════════════════════════════════════════════

class MapDataAPIView(View):
    """
    Endpoint JSON yang menyediakan semua data lokasi untuk Leaflet map.
    Menggabungkan LocationSnapshot (koordinat & status) dengan MasterLocation
    (jenis network, nama network, area, dsb.).

    GET /api/map-data/?run_id=<id>
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        run_id = request.GET.get("run_id")

        try:
            run_id = int(run_id) if run_id else None
        except (ValueError, TypeError):
            run_id = None

        if not run_id:
            all_runs = history_service.get_all_runs()
            run_id = all_runs[0]["run_id"] if all_runs else None

        if not run_id:
            return JsonResponse({"locations": [], "stats": {"with_coords": 0, "without_coords": 0, "total": 0}})

        snapshots = history_service.get_snapshots(run_id=run_id)

        # Ambil semua store_code untuk join ke MasterLocation
        store_codes = [s["store_code"] for s in snapshots if s.get("store_code")]

        # Data dari MasterLocation: network type, network_name, area
        master_qs = MasterLocation.objects.filter(
            store_code__in=store_codes
        ).values("store_code", "network", "network_name", "area")

        # Build lookup dict
        master_map = {}
        for m in master_qs:
            master_map[m["store_code"]] = {
                "raw_network": m["network"] or "",
                "network_name": m["network_name"] or "",
                "area": m["area"] or "",
            }

        def normalize_network_type(raw, business_name="", store_code=""):
            """Normalisasi tipe network ke: Cabang, Pos, Kios, Subkios, Lainnya."""
            if raw:
                v = str(raw).strip().lower()
                if v in ("cabang", "branch") or "cabang" in v:
                    return "Cabang"
                if v == "pos" or "pos" in v:
                    return "Pos"
                if "subkios" in v or "sub kios" in v or "sub_kios" in v:
                    return "Subkios"
                if "kios" in v:
                    return "Kios"

            # Infer dari nama bisnis
            bn = (business_name or "").lower()
            if "cabang" in bn or "branch" in bn:
                return "Cabang"
            if "subkios" in bn or "sub kios" in bn:
                return "Subkios"
            if "kios" in bn:
                return "Kios"
            if " pos " in f" {bn} " or bn.startswith("pos ") or bn.endswith(" pos"):
                return "Pos"

            # Infer dari konvensi store_code 5 digit FIFGROUP (2 digit terakhir)
            sc_str = str(store_code).strip().split(".")[0]
            if len(sc_str) == 5 and sc_str.isdigit():
                suffix = int(sc_str[3:5])
                if suffix in (0, 1, 2, 3, 4):
                    return "Cabang"
                elif 50 <= suffix <= 69:
                    return "Pos"
                elif 70 <= suffix <= 79:
                    return "Kios"
                elif 80 <= suffix <= 89:
                    return "Subkios"

            return "Lainnya"

        def normalize_status(raw):
            """Normalisasi status verifikasi ke nilai kanonik."""
            if not raw:
                return "Need Verification"
            v = str(raw).strip().lower()
            if v == "verified":
                return "Verified"
            if v in ("duplicate",):
                return "Duplicate"
            if v == "suspended":
                return "Suspended"
            if v in ("need verification", "need reverification",
                     "unverified", "verification required", "processing"):
                return "Need Verification"
            return "Need Verification"

        import re

        def extract_zipcode(address_str):
            """Ekstrak 5-digit kode pos Indonesia dari string alamat."""
            if not address_str:
                return ""
            m = re.search(r"\b(\d{5})\b", str(address_str))
            return m.group(1) if m else ""

        def extract_branch_prefix(sc_str):
            """Ambil 3 digit prefix cabang dari store code yang dinormalisasi."""
            if not sc_str:
                return ""
            s = str(sc_str).strip().split(".")[0]
            clean = re.sub(r"[^\d]", "", s)
            return clean[:3] if len(clean) >= 3 else ""

        locations = []
        with_coords = 0
        without_coords = 0

        for s in snapshots:
            has_coord = (
                s.get("latitude") is not None
                and s.get("longitude") is not None
            )

            if has_coord:
                with_coords += 1
            else:
                without_coords += 1
                # Jangan masukkan lokasi tanpa koordinat ke markers
                continue

            sc = s.get("store_code") or ""
            master_info = master_map.get(sc, {})

            raw_network = master_info.get("raw_network", "")
            b_name = s.get("business_name") or ""
            network_type = normalize_network_type(raw_network, business_name=b_name, store_code=sc)

            status_normalized = normalize_status(s.get("status", ""))
            addr = s.get("address") or ""
            zipcode = extract_zipcode(addr)
            prefix = extract_branch_prefix(sc)

            locations.append({
                "id": s["id"],
                "store_code": sc,
                "branch_prefix": prefix,
                "zipcode": zipcode,
                "business_name": s.get("business_name") or "",
                "address": addr[:150],
                "latitude": s["latitude"],
                "longitude": s["longitude"],
                "status": status_normalized,
                "status_raw": s.get("status") or "",
                "coord_status": s.get("coord_status") or "OK",
                "network_type": network_type,
                "network_raw": raw_network,
                "network_name": master_info.get("network_name", ""),
                "area": master_info.get("area", ""),
                "maps_uri": s.get("maps_uri") or "",
                "has_vom": bool(s.get("has_vom")),
            })

        return JsonResponse({
            "locations": locations,
            "stats": {
                "with_coords": with_coords,
                "without_coords": without_coords,
                "total": len(snapshots),
            },
        })


_BOUNDARIES_CACHE = None

class BranchBoundariesAPIView(View):
    """
    Endpoint JSON yang menyajikan data GeoJSON batas administratif asli
    (administrative boundaries) untuk setiap cabang / wilayah cakupan.

    GET /api/branch-boundaries/
    """
    def get(self, request: HttpRequest) -> JsonResponse:
        global _BOUNDARIES_CACHE
        if _BOUNDARIES_CACHE is not None:
            return JsonResponse(_BOUNDARIES_CACHE)

        import os, json
        base_dir = os.path.dirname(os.path.abspath(__file__))
        geojson_path = os.path.join(base_dir, "static", "gbp", "data", "geojson", "branch_boundaries.geojson")

        if os.path.exists(geojson_path):
            try:
                with open(geojson_path, "r", encoding="utf-8") as f:
                    _BOUNDARIES_CACHE = json.load(f)
                return JsonResponse(_BOUNDARIES_CACHE)
            except Exception as e:
                return JsonResponse({"type": "FeatureCollection", "features": [], "error": str(e)})

        return JsonResponse({"type": "FeatureCollection", "features": []})


# ══════════════════════════════════════════════════════════════════════
# PAGE 4 — UPDATE STATUS VERIFIKASI
# ══════════════════════════════════════════════════════════════════════

class UpdateStatusView(View):
    template_name = "gbp/update_status.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        form = UpdateStatusForm()
        return render(request, self.template_name, {
            "form": form,
            "status_meta": STATUS_META,
        })

    def post(self, request: HttpRequest) -> HttpResponse:
        form = UpdateStatusForm(request.POST, request.FILES)
        context = {"form": form, "status_meta": STATUS_META}

        if not form.is_valid():
            return render(request, self.template_name, context)

        try:
            # 0. Periksa OAuth siap sebelum mulai (hindari request menggantung)
            from gbp.services.gbp_api import fetch_records, check_oauth_ready
            oauth_ready, oauth_msg = check_oauth_ready()
            if not oauth_ready:
                messages.error(request, f"OAuth belum siap:\n{oauth_msg}")
                return render(request, self.template_name, context)

            # 1. Ambil data dari GBP API
            account_id = form.cleaned_data["account_id"].strip() or None
            api_records = fetch_records(account_id=account_id)

            if not api_records:
                messages.error(request, "Data API kosong. Tidak ada baris yang bisa dibandingkan.")
                return render(request, self.template_name, context)

            api_df = pd.DataFrame(api_records)

            # 2. Baca master data
            source_type = form.cleaned_data["source_type"]
            master_source_label = ""

            if source_type == UpdateStatusForm.SOURCE_CSV:
                master_file = form.cleaned_data.get("master_file")
                master_path = form.cleaned_data.get("master_path", "").strip()

                if master_file:
                    master_df = pd.read_csv(master_file, dtype=str, keep_default_na=False)
                    master_source_label = f"Upload: {master_file.name}"
                else:
                    master_df = pd.read_csv(master_path, dtype=str, keep_default_na=False)
                    master_source_label = master_path
            else:
                master_path = form.cleaned_data.get("master_path", "").strip()
                sqlite_table = form.cleaned_data.get("sqlite_table", "kios").strip()
                import sqlite3
                with sqlite3.connect(master_path) as conn:
                    master_df = pd.read_sql_query(f'SELECT * FROM "{sqlite_table}"', conn)
                master_source_label = f"{master_path} :: {sqlite_table}"

            if master_df.empty:
                messages.warning(request, "Master data kosong, tidak ada yang bisa diupdate.")
                return render(request, self.template_name, context)

            # 3. Rekonsiliasi
            master_status_col = reconciliation_service.detect_status_column(list(master_df.columns))
            api_status_col = reconciliation_service.detect_status_column(list(api_df.columns))

            updated_master_df, comparison_df, summary = reconciliation_service.compare_master_to_api(
                master_df, api_df,
                master_status_col=master_status_col,
                api_status_col=api_status_col,
            )

            comparison_rows = comparison_df.to_dict("records") if not comparison_df.empty else []

            # 4. Simpan ReconciliationJob + Results ke Supabase
            job = reconciliation_service.save_reconciliation_job(
                summary=summary,
                source_type=source_type,
                source_label=master_source_label,
                total_master=len(master_df),
                total_api=len(api_df),
            )
            reconciliation_service.save_reconciliation_results(job, comparison_rows)

            # 5. Update MasterLocation di Supabase jika ada di DB
            reconciliation_service.update_master_statuses(comparison_rows)

            # 6. Simpan ke disk jika diminta
            save_result_msg = None
            if form.cleaned_data.get("save_to_disk"):
                master_path_disk = form.cleaned_data.get("master_path", "").strip()
                if master_path_disk and source_type == UpdateStatusForm.SOURCE_CSV:
                    updated_master_df.to_csv(master_path_disk, index=False, encoding="utf-8")
                    save_result_msg = "✅ CSV master berhasil diperbarui."

            # 7. Data untuk template
            show_cols = [
                "match_status", "match_rule", "identifier_value",
                "old_status", "new_status", "status_changed", "change_note",
            ]
            available_cols = [c for c in show_cols if c in comparison_df.columns]
            comparison_rows_display = comparison_df[available_cols].to_dict("records") if not comparison_df.empty else []

            changed_rows = reconciliation_service.generate_changed_networks(comparison_rows)

            context.update({
                "result": True,
                "job": job,
                "summary": summary,
                "comparison_rows": comparison_rows_display,
                "changed_rows": changed_rows,
                "master_source_label": master_source_label,
                "master_row_count": len(master_df),
                "api_row_count": len(api_df),
                "save_result_msg": save_result_msg,
            })

            if summary.get("updated", 0) > 0:
                messages.success(
                    request,
                    f"✅ Rekonsiliasi selesai. {summary['updated']} status berubah, "
                    f"{summary['matched'] - summary['updated']} tidak berubah."
                )
            else:
                messages.info(request, "ℹ️ Rekonsiliasi selesai. Tidak ada status yang berubah.")

        except FileNotFoundError as exc:
            log.error("Credentials tidak ditemukan saat update status")
            messages.error(request, str(exc))
        except PermissionError as exc:
            log.error("Google API permission/auth error saat update status")
            messages.error(request, str(exc))
        except Exception as exc:
            log.exception("Error saat update status verifikasi")
            messages.error(request, f"Gagal menjalankan update status: {exc}")

        return render(request, self.template_name, context)



# ══════════════════════════════════════════════════════════════════════
# PAGE 5 — LOCATION DETAIL
# ══════════════════════════════════════════════════════════════════════

class LocationDetailView(View):
    template_name = "gbp/location_detail.html"

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        snapshot = get_object_or_404(LocationSnapshot, pk=pk)
        ctx = _get_run_context(request)
        ctx.update({
            "snapshot": snapshot,
            "status_meta": get_status_meta(snapshot.status),
        })
        return render(request, self.template_name, ctx)


# ══════════════════════════════════════════════════════════════════════
# EXPORT — CSV & EXCEL
# ══════════════════════════════════════════════════════════════════════

class ExportCSVView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        run_id = request.GET.get("run_id")
        statuses = request.GET.getlist("status") or ALL_STATUSES
        search = request.GET.get("search", "") or None

        try:
            run_id = int(run_id)
        except (TypeError, ValueError):
            run_id = history_service.get_latest_run_id()
            if not run_id:
                return HttpResponse("Tidak ada data.", status=404)

        snapshots = history_service.get_snapshots(run_id=run_id, status_filter=statuses, search=search)
        df = export_service.snapshots_to_dataframe(snapshots)
        csv_bytes = export_service.to_csv_bytes(df)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        response = HttpResponse(csv_bytes, content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = f'attachment; filename="gbp_export_{ts}.csv"'
        return response


class ExportExcelView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        run_id = request.GET.get("run_id")
        statuses = request.GET.getlist("status") or ALL_STATUSES
        search = request.GET.get("search", "") or None

        try:
            run_id = int(run_id)
        except (TypeError, ValueError):
            run_id = history_service.get_latest_run_id()
            if not run_id:
                return HttpResponse("Tidak ada data.", status=404)

        snapshots = history_service.get_snapshots(run_id=run_id, status_filter=statuses, search=search)
        df = export_service.snapshots_to_dataframe(snapshots)
        xlsx_bytes = export_service.to_excel_bytes(df)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        response = HttpResponse(
            xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="gbp_export_{ts}.xlsx"'
        return response


class DownloadReconciliationView(View):
    """Download hasil rekonsiliasi dari database berdasarkan job_id."""

    def get(self, request: HttpRequest, job_id: int) -> HttpResponse:
        job = get_object_or_404(ReconciliationJob, pk=job_id)
        results = ReconciliationResult.objects.filter(job=job).values(
            "store_code", "network_name", "business_name", "location_name",
            "identifier_value", "match_rule", "old_status", "new_status",
            "process_status", "status_changed", "change_note",
        )

        rows = list(results)
        if not rows:
            messages.error(request, "Tidak ada hasil rekonsiliasi untuk didownload.")
            return redirect("gbp:update_status")

        df = pd.DataFrame(rows)
        df.columns = [
            "Store Code", "Network Name", "Nama Bisnis", "Location Name",
            "Identifier", "Aturan Matching", "Status Lama", "Status Baru",
            "Status Proses", "Status Berubah?", "Catatan",
        ]

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hasil_pencocokan_status_verifikasi_gbp_{ts}.csv"
        csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

        response = HttpResponse(csv_bytes, content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# ══════════════════════════════════════════════════════════════════════
# PAGE 6 — DOWNLOAD REPORT
# ══════════════════════════════════════════════════════════════════════

class DownloadReportView(View):
    """Halaman daftar rekonsiliasi yang bisa didownload."""
    template_name = "gbp/download_report.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        ctx = _get_run_context(request)
        jobs = ReconciliationJob.objects.order_by("-created_at")[:20]
        ctx["recon_jobs"] = jobs

        return render(request, self.template_name, ctx)


class DownloadReconDetailView(View):
    """Download CSV rekonsiliasi tertentu dengan kolom: network_name, status lama, baru, latlong."""

    def get(self, request: HttpRequest, job_id: int) -> HttpResponse:
        job = get_object_or_404(ReconciliationJob, pk=job_id)
        results = ReconciliationResult.objects.filter(job=job).select_related()

        rows = []
        for r in results:
            # Ambil latlong dari snapshot terbaru
            lat, lng = None, None
            snap = None
            if r.store_code:
                snap = LocationSnapshot.objects.filter(store_code=r.store_code).order_by("-created_at").first()
            if not snap and r.business_name:
                snap = LocationSnapshot.objects.filter(business_name=r.business_name).order_by("-created_at").first()
            if not snap and r.identifier_value:
                # Fallback untuk job lama yang belum save store_code
                snap = LocationSnapshot.objects.filter(store_code=r.identifier_value).order_by("-created_at").first()
                if not snap:
                    snap = LocationSnapshot.objects.filter(business_name=r.identifier_value).order_by("-created_at").first()

            latlong_str = ""
            maps_uri_str = ""
            if snap and snap.latitude is not None and snap.longitude is not None:
                latlong_str = f"{snap.latitude},{snap.longitude}"
            if snap and snap.maps_uri:
                maps_uri_str = snap.maps_uri

            # Penyesuaian retroaktif untuk file CSV lama:
            # Jika old_status = "Need Reverification" dan new_status = "Need Verification"
            old_s = str(r.old_status or "").strip()
            new_s = str(r.new_status or "").strip()
            is_changed = r.status_changed
            catatan = r.change_note or ""

            if old_s.lower() == "need reverification" and new_s.lower() in ["need verification", "verification required"]:
                new_s = old_s
                is_changed = False
                catatan = "Tidak ada perubahan"

            rows.append({
                "Nama Network": r.network_name or r.business_name or r.identifier_value or "—",
                "Store Code": r.store_code or r.identifier_value or "—",
                "Status Lama": old_s or "—",
                "Status Baru": new_s or "—",
                "Status Berubah": "Ya" if is_changed else "Tidak",
                "Latlong": latlong_str,
                "URL Maps": maps_uri_str,
                "Catatan": catatan,
            })

        if not rows:
            messages.error(request, "Tidak ada data untuk didownload.")
            return redirect("gbp:download_report")

        df = pd.DataFrame(rows)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rekonsiliasi_status_gbp_{ts}.csv"
        csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

        response = HttpResponse(csv_bytes, content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# ══════════════════════════════════════════════════════════════════════
# API — FETCH TRIGGER & TREND DATA
# ══════════════════════════════════════════════════════════════════════

class TriggerFetchView(View):
    """Trigger fetch GBP API dan simpan ke database."""

    def post(self, request: HttpRequest):
        try:
            from gbp.services.gbp_api import fetch_records
            account_id = request.POST.get("account_id") or None
            records = fetch_records(account_id=account_id)

            if not records:
                messages.error(request, "Data API kosong.")
                return redirect("gbp:overview")

            run_id = history_service.save_run(records)
            messages.success(request, f"✅ Fetch selesai! {len(records)} lokasi disimpan.")
            return redirect("gbp:overview")
        except Exception as exc:
            log.exception("Error saat trigger fetch GBP")
            messages.error(request, f"Gagal menjalankan fetch: {exc}")
            return redirect("gbp:overview")


class TrendDataView(View):
    """Endpoint JSON untuk data tren 30 hari (dipakai oleh Chart.js)."""

    def get(self, request: HttpRequest) -> JsonResponse:
        days = int(request.GET.get("days", 30))
        trend = history_service.get_status_trend(days=days)
        return JsonResponse({"data": trend})


# ══════════════════════════════════════════════════════════════════════
# SALES PERFORMANCE
# ══════════════════════════════════════════════════════════════════════

_SALES_REQUIRED_COLS = {"branch_prefix", "branch_name", "period", "nsa", "bp", "mscp", "nl"}
_SALES_OPTIONAL_COLS = {"osa", "cd", "profit", "area"}


# ══════════════════════════════════════════════════════════════════════
# API — BRANCH PERFORMANCE (Y vs Y-1)
# ══════════════════════════════════════════════════════════════════════

import re as _re


class BranchPerformanceAPIView(View):
    """
    GET /api/branch-performance/?store_code=<sc>&month=<1-12>&year=<YYYY>

    Mengembalikan data performance cabang untuk periode yang dipilih
    dan periode yang sama tahun sebelumnya (Y vs Y-1).

    Response:
    {
      "ok": true,
      "branch_prefix": "101",
      "branch_name": "...",
      "area": "...",
      "period": "2026-08",
      "prev_period": "2025-08",
      "current": { nsa, osa, cd, profit, nl },
      "previous": { nsa, osa, cd, profit, nl },
      "has_current": bool,
      "has_previous": bool
    }
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        store_code = request.GET.get("store_code", "").strip()
        month_raw  = request.GET.get("month", "")
        year_raw   = request.GET.get("year", "")

        # ── Validate inputs ──────────────────────────────────────────
        if not store_code:
            return JsonResponse({"ok": False, "error": "store_code diperlukan."}, status=400)

        try:
            month = int(month_raw)
            year  = int(year_raw)
            if not (1 <= month <= 12):
                raise ValueError
            if not (2000 <= year <= 2100):
                raise ValueError
        except (ValueError, TypeError):
            return JsonResponse({"ok": False, "error": "month/year tidak valid."}, status=400)

        # ── Extract branch_prefix from store_code ────────────────────
        # Normalisasi: ambil digit saja, hapus trailing .0
        sc = str(store_code).strip()
        if sc.endswith(".0"):
            sc = sc[:-2]
        digits = _re.sub(r"[^\d]", "", sc)
        if not digits:
            return JsonResponse({"ok": False, "error": "store_code tidak valid."}, status=400)
        branch_prefix = digits[:3].zfill(3)

        # ── Build period strings ─────────────────────────────────────
        period      = f"{year}-{month:02d}"
        prev_period = f"{year - 1}-{month:02d}"

        # ── Query database ───────────────────────────────────────────
        def record_to_dict(rec):
            """Convert BranchSalesRecord to serializable dict."""
            if rec is None:
                return None

            # Parse NSA string to float for comparison
            nsa_float = None
            if rec.nsa:
                nsa_clean = _re.sub(r"[^\d]", "", str(rec.nsa))
                try:
                    nsa_float = float(nsa_clean) if nsa_clean else None
                except ValueError:
                    nsa_float = None

            return {
                "nsa":        nsa_float,
                "nsa_raw":    rec.nsa or None,
                "osa":        rec.osa,
                "cd":         rec.cd,
                "profit":     rec.profit,
                "nl":         rec.nl,
                "bp":         rec.bp,
                "mscp":       rec.mscp,
            }

        try:
            curr_rec = BranchSalesRecord.objects.filter(
                branch_prefix=branch_prefix, period=period
            ).first()
            prev_rec = BranchSalesRecord.objects.filter(
                branch_prefix=branch_prefix, period=prev_period
            ).first()
        except Exception as exc:
            log.exception("Error querying branch performance")
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

        # ── Build response ───────────────────────────────────────────
        branch_name = ""
        area        = ""
        if curr_rec:
            branch_name = curr_rec.branch_name
            area        = curr_rec.area or ""
        elif prev_rec:
            branch_name = prev_rec.branch_name
            area        = prev_rec.area or ""

        # Fallback jika belum ada sales record untuk branch ini
        if not branch_name:
            master = MasterLocation.objects.filter(store_code=store_code).first()
            if not master:
                master = MasterLocation.objects.filter(store_code__startswith=branch_prefix).first()
            if master:
                branch_name = master.business_name or master.network_name or ""
                area = master.area or ""
            else:
                snap = LocationSnapshot.objects.filter(store_code=store_code).first()
                if snap:
                    branch_name = snap.business_name or ""

        return JsonResponse({
            "ok":            True,
            "branch_prefix": branch_prefix,
            "branch_name":   branch_name,
            "area":          area,
            "period":        period,
            "prev_period":   prev_period,
            "current":       record_to_dict(curr_rec),
            "previous":      record_to_dict(prev_rec),
            "has_current":   curr_rec is not None,
            "has_previous":  prev_rec is not None,
        })




class UploadSalesView(View):
    """
    POST /upload-sales/
    Menerima file CSV berisi data performa penjualan cabang.
    Melakukan upsert ke tabel BranchSalesRecord.
    """

    def post(self, request: HttpRequest) -> JsonResponse:
        csv_file = request.FILES.get("sales_csv")
        if not csv_file:
            return JsonResponse({"ok": False, "error": "File CSV tidak ditemukan."}, status=400)

        try:
            import io
            df = pd.read_csv(io.BytesIO(csv_file.read()), dtype=str)
            df.columns = [c.strip().lower() for c in df.columns]
        except Exception as exc:
            return JsonResponse({"ok": False, "error": f"Gagal membaca CSV: {exc}"}, status=400)

        missing = _SALES_REQUIRED_COLS - set(df.columns)
        if missing:
            return JsonResponse({
                "ok": False,
                "error": f"Kolom berikut tidak ada di CSV: {', '.join(sorted(missing))}"
            }, status=400)

        success, errors = 0, []
        for i, row in df.iterrows():
            try:
                prefix = str(row["branch_prefix"]).strip().zfill(3)

                def parse_pct(val):
                    """Parse persentase: '31.59', '+31.59', '-9.89' → float."""
                    v = str(val).strip().replace("%", "").replace(",", ".")
                    return float(v) if v not in ("", "nan", "None", "-") else None

                def parse_float_or_none(val):
                    """Parse nilai float umum, return None jika kosong."""
                    v = str(val).strip().replace(",", ".")
                    # Hapus karakter non-numeric kecuali . dan -
                    v = _re.sub(r"[^\d\.\-]", "", v)
                    return float(v) if v not in ("", "nan") else None

                # Optional columns — default to None if not in CSV
                osa_val    = parse_float_or_none(row.get("osa", "")) if "osa" in df.columns else None
                cd_val     = parse_pct(row.get("cd", ""))             if "cd" in df.columns else None
                profit_val = parse_float_or_none(row.get("profit", "")) if "profit" in df.columns else None

                BranchSalesRecord.objects.update_or_create(
                    branch_prefix=prefix,
                    period=str(row["period"]).strip(),
                    defaults={
                        "branch_name": str(row["branch_name"]).strip(),
                        "area":   str(row.get("area", "")).strip() or None,
                        "nsa":    str(row["nsa"]).strip() if str(row["nsa"]).strip() not in ("", "nan") else None,
                        "osa":    osa_val,
                        "cd":     cd_val,
                        "profit": profit_val,
                        "bp":     parse_pct(row["bp"]),
                        "mscp":   parse_pct(row["mscp"]),
                        "nl":     parse_pct(row["nl"]),
                    }
                )
                success += 1
            except Exception as exc:
                errors.append(f"Baris {i + 2}: {exc}")

        return JsonResponse({
            "ok": True,
            "success": success,
            "errors": errors,
            "message": f"{success} data berhasil disimpan." + (f" {len(errors)} baris gagal." if errors else "")
        })


class DownloadSalesTemplateView(View):
    """GET /download-sales-template/ — Unduh template CSV kosong."""

    def get(self, request: HttpRequest) -> HttpResponse:
        import csv as csv_module
        import io

        output = io.StringIO()
        writer = csv_module.writer(output)
        # Kolom wajib + opsional (osa, cd, profit)
        writer.writerow(["branch_prefix", "branch_name", "area", "period", "nsa", "osa", "cd", "profit", "bp", "mscp", "nl"])
        # Contoh baris
        writer.writerow(["101", "JAKARTA PUSAT 2", "JABODETABEK", "2026-06",
                         "333115001111", "1250", "95.20", "2500000000",
                         "31.59", "89.36", "-9890000"])
        writer.writerow(["102", "SERANG", "JABODETABEK", "2026-06",
                         "150000000", "850", "92.50", "1200000000",
                         "-5.20", "75.00", "1250000"])

        response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="template_sales_performance.csv"'
        return response
