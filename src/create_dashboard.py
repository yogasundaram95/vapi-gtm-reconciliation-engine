"""
create_dashboard.py
Vapi GTM Reconciliation Engine

Generates vapi_reconciliation_dashboard.xlsx from the output CSVs.
Run reconcile.py first to produce the source files.

Run:
    pip3 install openpyxl
    python3 src/create_dashboard.py
"""

import os
import csv
from collections import Counter

from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.series import DataPoint
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "output")
DASHBOARD_PATH = os.path.join(BASE_DIR, "dashboard", "vapi_reconciliation_dashboard.xlsx")
os.makedirs(os.path.dirname(DASHBOARD_PATH), exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_csv(filename: str) -> list[dict]:
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def safe_int(v, default=0) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------

BLUE_DARK   = "1F4E79"
BLUE_MID    = "2E75B6"
BLUE_LIGHT  = "D6E4F0"
RED         = "C00000"
ORANGE      = "E36C09"
YELLOW_SOFT = "FFC000"
GREEN       = "375623"
GREEN_LIGHT = "E2EFDA"
GREY_LIGHT  = "F2F2F2"
WHITE       = "FFFFFF"

SEV_COLORS = {
    "Critical": "FFCCCC",
    "High":     "FFE0CC",
    "Medium":   "FFF2CC",
    "Low":      "EBF1DE",
    "Healthy":  "EBF1DE",
}

def h_font(bold=True, size=11, color=WHITE):
    return Font(name="Calibri", bold=bold, size=size, color=color)

def b_font(bold=True, size=11, color="000000"):
    return Font(name="Calibri", bold=bold, size=size, color=color)

def r_font(size=10, color="000000"):
    return Font(name="Calibri", size=size, color=color)

def fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)

def center(wrap=False) -> Alignment:
    return Alignment(horizontal="center", vertical="center", wrap_text=wrap)

def left(wrap=False) -> Alignment:
    return Alignment(horizontal="left", vertical="center", wrap_text=wrap)

def thin_border() -> Border:
    s = Side(style="thin", color="BFBFBF")
    return Border(left=s, right=s, top=s, bottom=s)

def header_row(ws, row: int, headers: list[str], col_start=1):
    for i, h in enumerate(headers):
        c = ws.cell(row=row, column=col_start + i, value=h)
        c.font    = h_font()
        c.fill    = fill(BLUE_DARK)
        c.alignment = center(wrap=True)
        c.border  = thin_border()

def data_cell(ws, row: int, col: int, value, number=False, alt_row=False):
    c = ws.cell(row=row, column=col, value=value)
    c.font      = r_font()
    c.fill      = fill(GREY_LIGHT if alt_row else WHITE)
    c.alignment = left(wrap=True)
    c.border    = thin_border()
    return c

def kpi_block(ws, row: int, col: int, label: str, value, color=BLUE_MID):
    """Write a two-row KPI card: label on top, value below."""
    lc = ws.cell(row=row,   column=col, value=label)
    lc.font      = Font(name="Calibri", bold=True, size=9, color=WHITE)
    lc.fill      = fill(color)
    lc.alignment = center(wrap=True)
    lc.border    = thin_border()

    vc = ws.cell(row=row+1, column=col, value=value)
    vc.font      = Font(name="Calibri", bold=True, size=22, color=color)
    vc.fill      = fill(WHITE)
    vc.alignment = center()
    vc.border    = thin_border()


# ---------------------------------------------------------------------------
# Tab 1 — Executive Summary
# ---------------------------------------------------------------------------

def tab_executive_summary(wb: Workbook, summary: list[dict], issues: list[dict], scored: list[dict]):
    ws = wb.active
    ws.title = "Executive Summary"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 45
    ws.column_dimensions["B"].width = 12

    # Title
    ws.row_dimensions[1].height = 28
    t = ws.cell(row=1, column=1, value="Vapi GTM Reconciliation Engine — Executive Summary")
    t.font      = Font(name="Calibri", bold=True, size=16, color=BLUE_DARK)
    t.alignment = left()
    ws.merge_cells("A1:B1")

    ws.cell(row=2, column=1, value="Revenue leakage detection report — mock data demonstration").font = r_font(size=9, color="595959")

    # KPI cards (row 4–5, columns D–G)
    summary_map = {r["metric"]: safe_int(r["value"]) for r in summary}

    ws.column_dimensions["D"].width = 22
    ws.column_dimensions["E"].width = 22
    ws.column_dimensions["F"].width = 22
    ws.column_dimensions["G"].width = 22

    ws.row_dimensions[4].height = 22
    ws.row_dimensions[5].height = 38

    kpi_block(ws, 4, 4, "Critical Leakage Records",
              summary_map.get("Critical revenue leakage records", 0), RED)
    kpi_block(ws, 4, 5, "High-Intent Not in Salesforce",
              summary_map.get("High-intent leads not in Salesforce", 0), ORANGE)
    kpi_block(ws, 4, 6, "Missing Salesforce Owner",
              summary_map.get("Salesforce leads missing owner", 0), BLUE_MID)
    kpi_block(ws, 4, 7, "Healthy Records",
              summary_map.get("Healthy records", 0), "375623")

    # Summary table
    ws.row_dimensions[7].height = 20
    header_row(ws, 7, ["Metric", "Value"])
    for i, r in enumerate(summary):
        alt = i % 2 == 1
        data_cell(ws, 8 + i, 1, r["metric"], alt_row=alt)
        vc = data_cell(ws, 8 + i, 2, safe_int(r["value"]), alt_row=alt)
        vc.alignment = center()
        vc.font = Font(name="Calibri", size=10, bold=True)

    # Issues by severity chart (data in cols D–E, rows 8–13)
    sev_counts = Counter(r.get("severity", "") for r in issues)
    sev_order  = ["Critical", "High", "Medium", "Low"]
    chart_start_row = 8

    ws.cell(row=chart_start_row,     column=4, value="Severity")
    ws.cell(row=chart_start_row,     column=5, value="Count")
    ws.cell(row=chart_start_row, column=4).font = b_font(size=9)
    ws.cell(row=chart_start_row, column=5).font = b_font(size=9)

    for i, sev in enumerate(sev_order):
        ws.cell(row=chart_start_row + 1 + i, column=4, value=sev)
        ws.cell(row=chart_start_row + 1 + i, column=5, value=sev_counts.get(sev, 0))

    chart = BarChart()
    chart.type    = "col"
    chart.title   = "Sync Issues by Severity"
    chart.y_axis.title = "Issue Count"
    chart.x_axis.title = ""
    chart.style   = 10
    chart.width   = 12
    chart.height  = 10
    chart.legend  = None

    data = Reference(ws, min_col=5, min_row=chart_start_row,
                     max_row=chart_start_row + len(sev_order))
    cats = Reference(ws, min_col=4, min_row=chart_start_row + 1,
                     max_row=chart_start_row + len(sev_order))
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    ws.add_chart(chart, "D14")

    # Lead score distribution (cols F–G, rows 8–13)
    buckets = {"<40": 0, "40–59": 0, "60–79": 0, "80+": 0}
    for r in scored:
        s = safe_int(r.get("lead_score", 0))
        if s >= 80:    buckets["80+"] += 1
        elif s >= 60:  buckets["60–79"] += 1
        elif s >= 40:  buckets["40–59"] += 1
        else:          buckets["<40"] += 1

    ws.cell(row=chart_start_row,     column=6, value="Score Range")
    ws.cell(row=chart_start_row,     column=7, value="Leads")
    ws.cell(row=chart_start_row, column=6).font = b_font(size=9)
    ws.cell(row=chart_start_row, column=7).font = b_font(size=9)

    for i, (bucket, count) in enumerate(buckets.items()):
        ws.cell(row=chart_start_row + 1 + i, column=6, value=bucket)
        ws.cell(row=chart_start_row + 1 + i, column=7, value=count)

    chart2 = BarChart()
    chart2.type   = "col"
    chart2.title  = "Lead Score Distribution"
    chart2.y_axis.title = "Leads"
    chart2.style  = 10
    chart2.width  = 12
    chart2.height = 10
    chart2.legend = None

    data2 = Reference(ws, min_col=7, min_row=chart_start_row,
                      max_row=chart_start_row + 4)
    cats2 = Reference(ws, min_col=6, min_row=chart_start_row + 1,
                      max_row=chart_start_row + 4)
    chart2.add_data(data2, titles_from_data=True)
    chart2.set_categories(cats2)
    ws.add_chart(chart2, "F14")


# ---------------------------------------------------------------------------
# Tab 2 — High Intent Not Synced (hero tab)
# ---------------------------------------------------------------------------

def tab_high_intent(wb: Workbook, rows: list[dict]):
    ws = wb.create_sheet("High Intent Not Synced")
    ws.sheet_view.showGridLines = False

    ws.row_dimensions[1].height = 28
    t = ws.cell(row=1, column=1,
                value="High-Intent Leads NOT in Salesforce — Revenue Leakage Queue")
    t.font      = Font(name="Calibri", bold=True, size=14, color=RED)
    t.alignment = left()

    ws.cell(row=2, column=1,
            value="Lead Score >= 80 with no Salesforce record. Sales has zero visibility on these leads.").font = r_font(size=9, color="595959")

    cols = ["email", "company", "domain", "lead_score", "data_quality_score",
            "industry", "active_job_signal", "intent_summary",
            "business_risk", "recommended_fix"]
    labels = ["Email", "Company", "Domain", "Lead Score", "DQ Score",
              "Industry", "Active Job Signal", "Intent Summary",
              "Business Risk", "Recommended Fix"]
    widths = [32, 22, 20, 11, 9, 22, 30, 40, 45, 42]

    for i, (col, w) in enumerate(zip(cols, widths)):
        ws.column_dimensions[get_column_letter(i + 1)].width = w

    header_row(ws, 4, labels)

    for i, r in enumerate(rows):
        alt = i % 2 == 1
        for j, col in enumerate(cols):
            c = data_cell(ws, 5 + i, j + 1, r.get(col, ""), alt_row=alt)
            if col == "lead_score":
                c.font      = Font(name="Calibri", bold=True, size=10, color=RED)
                c.alignment = center()
            elif col == "data_quality_score":
                c.alignment = center()


# ---------------------------------------------------------------------------
# Tab 3 — Missing Owner Queue
# ---------------------------------------------------------------------------

def tab_missing_owner(wb: Workbook, rows: list[dict]):
    ws = wb.create_sheet("Missing Owner Queue")
    ws.sheet_view.showGridLines = False

    ws.row_dimensions[1].height = 28
    t = ws.cell(row=1, column=1, value="Missing Salesforce Owner — Routing Gap Queue")
    t.font      = Font(name="Calibri", bold=True, size=14, color=BLUE_DARK)
    t.alignment = left()

    ws.cell(row=2, column=1,
            value="These leads have no Salesforce owner assigned. No one is working them.").font = r_font(size=9, color="595959")

    cols   = ["email", "company", "domain", "lead_score", "data_quality_score",
              "revenue_leakage_risk", "action_required",
              "owner_assignment_basis", "suggested_routing_segment"]
    labels = ["Email", "Company", "Domain", "Lead Score", "DQ Score",
              "Leakage Risk", "Action Required",
              "Owner Assignment Basis", "Routing Segment"]
    widths = [32, 22, 20, 11, 9, 14, 22, 38, 28]

    for i, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = w

    header_row(ws, 4, labels)

    for i, r in enumerate(rows):
        alt = i % 2 == 1
        for j, col in enumerate(cols):
            c = data_cell(ws, 5 + i, j + 1, r.get(col, ""), alt_row=alt)
            if col == "lead_score":
                c.alignment = center()
                c.font = Font(name="Calibri", bold=True, size=10)
            elif col == "revenue_leakage_risk":
                risk = r.get("revenue_leakage_risk", "")
                c.fill = fill(SEV_COLORS.get(risk, WHITE))
                c.alignment = center()
                c.font = Font(name="Calibri", bold=True, size=10)


# ---------------------------------------------------------------------------
# Tab 4 — Sync Issues
# ---------------------------------------------------------------------------

def tab_sync_issues(wb: Workbook, rows: list[dict]):
    ws = wb.create_sheet("Sync Issues")
    ws.sheet_view.showGridLines = False

    ws.row_dimensions[1].height = 28
    t = ws.cell(row=1, column=1, value="Sync Issues — Master QA Table")
    t.font      = Font(name="Calibri", bold=True, size=14, color=BLUE_DARK)
    t.alignment = left()

    ws.cell(row=2, column=1,
            value="One row per issue per contact. A single contact may appear multiple times.").font = r_font(size=9, color="595959")

    cols   = ["issue_id", "email", "company", "issue_type", "severity",
              "lead_score", "data_quality_score", "revenue_leakage_risk", "recommended_fix"]
    labels = ["Issue ID", "Email", "Company", "Issue Type", "Severity",
              "Lead Score", "DQ Score", "Leakage Risk", "Recommended Fix"]
    widths = [10, 32, 22, 38, 10, 11, 9, 14, 45]

    for i, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = w

    header_row(ws, 4, labels)

    for i, r in enumerate(rows):
        alt = i % 2 == 1
        for j, col in enumerate(cols):
            c = data_cell(ws, 5 + i, j + 1, r.get(col, ""), alt_row=alt)
            if col == "severity":
                sev = r.get("severity", "")
                c.fill      = fill(SEV_COLORS.get(sev, WHITE))
                c.alignment = center()
                c.font      = Font(name="Calibri", bold=True, size=10)
            elif col in ("lead_score", "data_quality_score"):
                c.alignment = center()
            elif col == "revenue_leakage_risk":
                risk = r.get("revenue_leakage_risk", "")
                c.fill = fill(SEV_COLORS.get(risk, WHITE))
                c.alignment = center()
                c.font = Font(name="Calibri", bold=True, size=10)


# ---------------------------------------------------------------------------
# Tab 5 — Routing Recommendations
# ---------------------------------------------------------------------------

def tab_routing(wb: Workbook, rows: list[dict]):
    ws = wb.create_sheet("Routing Recommendations")
    ws.sheet_view.showGridLines = False

    ws.row_dimensions[1].height = 28
    t = ws.cell(row=1, column=1, value="Routing Recommendations — Prioritized Action Queue")
    t.font      = Font(name="Calibri", bold=True, size=14, color=BLUE_DARK)
    t.alignment = left()

    ws.cell(row=2, column=1,
            value="Sorted by Lead Score descending. Lead Score >= 80 requires immediate action.").font = r_font(size=9, color="595959")

    # Routing breakdown summary (small table, cols H–I)
    rec_counts = Counter(r.get("routing_recommendation", "") for r in rows)
    ws.cell(row=4, column=8, value="Routing Tier").font = b_font(size=10, color=BLUE_DARK)
    ws.cell(row=4, column=9, value="Count").font        = b_font(size=10, color=BLUE_DARK)
    ws.column_dimensions["H"].width = 42
    ws.column_dimensions["I"].width = 8
    for i, (rec, cnt) in enumerate(rec_counts.most_common()):
        ws.cell(row=5 + i, column=8, value=rec).font  = r_font(size=9)
        ws.cell(row=5 + i, column=9, value=cnt).font  = r_font(size=9)

    cols   = ["email", "company", "domain", "lead_score", "data_quality_score",
              "revenue_leakage_risk", "routing_recommendation", "next_best_action"]
    labels = ["Email", "Company", "Domain", "Lead Score", "DQ Score",
              "Leakage Risk", "Routing Recommendation", "Next Best Action"]
    widths = [32, 22, 20, 11, 9, 14, 38, 45]

    for i, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = w

    header_row(ws, 4, labels)

    ROUTE_COLORS = {
        "AE Priority":                                        "C6EFCE",
        "RevOps Critical Fix — Add to Salesforce before Sales outreach": "FFCCCC",
        "Assign Owner Immediately":                           "FFE0CC",
        "Fix Lifecycle Stage Before Routing":                 "FFF2CC",
        "SDR Priority":                                       "DDEBF7",
        "Nurture":                                            "EBF1DE",
        "Hold / Enrich Further":                              "F2F2F2",
    }

    for i, r in enumerate(rows):
        alt = i % 2 == 1
        for j, col in enumerate(cols):
            c = data_cell(ws, 5 + i, j + 1, r.get(col, ""), alt_row=alt)
            if col == "lead_score":
                c.alignment = center()
                c.font = Font(name="Calibri", bold=True, size=10)
            elif col == "data_quality_score":
                c.alignment = center()
            elif col == "revenue_leakage_risk":
                risk = r.get("revenue_leakage_risk", "")
                c.fill = fill(SEV_COLORS.get(risk, WHITE))
                c.alignment = center()
                c.font = Font(name="Calibri", bold=True, size=10)
            elif col == "routing_recommendation":
                rec = r.get("routing_recommendation", "")
                c.fill = fill(ROUTE_COLORS.get(rec, WHITE))
                c.font = Font(name="Calibri", bold=True, size=10)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\nBuilding Excel dashboard...")

    summary  = read_csv("reconciliation_summary.csv")
    issues   = read_csv("sync_issues.csv")
    hi_leads = read_csv("high_intent_not_synced_to_salesforce.csv")
    m_owner  = read_csv("missing_owner_queue.csv")
    routing  = read_csv("routing_recommendations.csv")
    scored   = read_csv("scored_leads.csv")

    wb = Workbook()

    tab_executive_summary(wb, summary, issues, scored)
    tab_high_intent(wb, hi_leads)
    tab_missing_owner(wb, m_owner)
    tab_sync_issues(wb, issues)
    tab_routing(wb, routing)

    wb.save(DASHBOARD_PATH)
    print(f"  Saved: {DASHBOARD_PATH}")
    print(f"\n  Tabs created:")
    for ws in wb.worksheets:
        print(f"    • {ws.title}")
    print()


if __name__ == "__main__":
    main()
