"""
Server-side PDF report generator.

Runs synchronously inside asyncio.run_in_executor so the event loop is never
blocked.  All async work (DB queries, Claude call) is done in the calling
coroutine; this module only receives plain Python objects and bytes.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless — must precede pyplot import
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ─── Colour palette ────────────────────────────────────────────────────────────
_NAVY   = colors.HexColor("#1e3a5f")
_TEAL   = colors.HexColor("#0d9488")
_AMBER  = colors.HexColor("#d97706")
_RED    = colors.HexColor("#dc2626")
_ORANGE = colors.HexColor("#ea580c")
_BLUE   = colors.HexColor("#2563eb")
_GREEN  = colors.HexColor("#16a34a")
_LGRAY  = colors.HexColor("#f8fafc")
_MGRAY  = colors.HexColor("#e2e8f0")
_DKGRAY = colors.HexColor("#64748b")
_WHITE  = colors.white
_SLATE  = colors.HexColor("#0f172a")

_CONTENT_W = 17.4 * cm   # A4 − 2 × 1.8 cm margin

# Sensor display metadata: column → (human label, unit string)
_SENSORS: list[tuple[str, str, str]] = [
    ("water_level_m",      "Water Level",    "m"),
    ("flow_rate_lpm",      "Flow Rate",      "L/min"),
    ("pump_pressure_bar",  "Pump Pressure",  "bar"),
    ("turbidity_ntu",      "Turbidity",      "NTU"),
    ("conductivity_us_cm", "Conductivity",   "µS/cm"),
    ("temperature_c",      "Temperature",    "°C"),
]

_SEV_COLORS = {
    "critical": "#dc2626",
    "high":     "#d97706",
    "medium":   "#ea580c",
    "low":      "#2563eb",
}


# ─── Styles ────────────────────────────────────────────────────────────────────

def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title":   ParagraphStyle("title",   fontName="Helvetica-Bold", fontSize=20, textColor=_NAVY,   spaceAfter=2),
        "h1":      ParagraphStyle("h1",       fontName="Helvetica-Bold", fontSize=12, textColor=_NAVY,   spaceBefore=16, spaceAfter=3),
        "body":    ParagraphStyle("body",     fontName="Helvetica",      fontSize=9,  textColor=_SLATE,  leading=13),
        "small":   ParagraphStyle("small",    fontName="Helvetica",      fontSize=7.5,textColor=_DKGRAY, leading=11),
        "summary": ParagraphStyle("summary",  fontName="Helvetica",      fontSize=9,  textColor=_SLATE,  leading=15, alignment=TA_JUSTIFY),
        "center":  ParagraphStyle("center",   fontName="Helvetica",      fontSize=8,  textColor=_DKGRAY, alignment=TA_CENTER),
        "label":   ParagraphStyle("label",    fontName="Helvetica-Bold", fontSize=8,  textColor=_DKGRAY),
    }


# ─── Header banner ─────────────────────────────────────────────────────────────

def _header_banner(
    site_name: str,
    location: str | None,
    start: datetime,
    end: datetime,
) -> Table:
    fmt = lambda d: d.strftime("%d %b %Y  %H:%M UTC")

    left = Paragraph(
        '<font color="white" size="17"><b>Groundwater Monitor</b></font><br/>'
        '<font color="#7dd3fc" size="9">Automated Site Report</font>',
        ParagraphStyle("hl", fontName="Helvetica-Bold", textColor=_WHITE),
    )
    right_lines = [f"<b>{site_name}</b>"]
    if location:
        right_lines.append(location)
    right_lines += [f"Period: {fmt(start)}", f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; to {fmt(end)}"]
    right = Paragraph(
        "<br/>".join(right_lines),
        ParagraphStyle("hr", fontName="Helvetica", textColor=_WHITE, fontSize=8.5),
    )

    t = Table([[left, right]], colWidths=[_CONTENT_W * 0.42, _CONTENT_W * 0.58])
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), _NAVY),
        ("PADDING",     (0, 0), (-1, -1), 14),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE",   (0, 0), (-1, 0),  3, _TEAL),
    ]))
    return t


# ─── Overview KPI cards ────────────────────────────────────────────────────────

def _overview_table(
    total_readings: int,
    total_alerts: int,
    active_alerts: int,
    health_vals: list[float],
    start: datetime,
    end: datetime,
    s: dict,
) -> Table:
    days = (end - start).days
    hours = ((end - start).seconds) // 3600

    avg_health = f"{np.mean(health_vals):.0f} / 100" if health_vals else "—"
    latest_health = f"{health_vals[-1]:.0f} / 100" if health_vals else "—"
    span = f"{days}d {hours}h" if days else f"{hours}h"

    rows = [
        [_kv("Total Readings", str(total_readings), s),
         _kv("Total Alerts", str(total_alerts), s),
         _kv("Active Alerts", str(active_alerts), s)],
        [_kv("Avg Health Score", avg_health, s),
         _kv("Latest Health", latest_health, s),
         _kv("Report Span", span, s)],
    ]
    col_w = [_CONTENT_W / 3] * 3
    t = Table(rows, colWidths=col_w)
    t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [_LGRAY, _WHITE]),
        ("GRID",           (0, 0), (-1, -1), 0.4, _MGRAY),
        ("TOPPADDING",     (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
        ("LEFTPADDING",    (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 10),
    ]))
    return t


def _kv(label: str, value: str, s: dict) -> Paragraph:
    return Paragraph(
        f'<font color="{_DKGRAY.hexval()}" size="8">{label}</font><br/>'
        f'<font color="{_NAVY.hexval()}" size="12"><b>{value}</b></font>',
        s["body"],
    )


# ─── Stats table ───────────────────────────────────────────────────────────────

def _stats_table(df: pd.DataFrame, s: dict) -> Table | None:
    if df.empty:
        return None

    header_row = [
        Paragraph("<b>Sensor</b>",   s["label"]),
        Paragraph("<b>Unit</b>",     s["label"]),
        Paragraph("<b>Mean</b>",     s["label"]),
        Paragraph("<b>Min</b>",      s["label"]),
        Paragraph("<b>Max</b>",      s["label"]),
        Paragraph("<b>Std Dev</b>",  s["label"]),
        Paragraph("<b>Readings</b>", s["label"]),
    ]
    rows = [header_row]

    for col, label, unit in _SENSORS:
        if col not in df.columns or df[col].isna().all():
            continue
        ser = df[col].dropna()
        rows.append([
            Paragraph(label, s["body"]),
            unit,
            f"{ser.mean():.3f}",
            f"{ser.min():.3f}",
            f"{ser.max():.3f}",
            f"{ser.std():.3f}",
            str(len(ser)),
        ])

    if len(rows) <= 1:
        return None

    col_w = [3.8*cm, 1.7*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.0*cm, 1.9*cm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  _NAVY),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  _WHITE),
        ("FONTSIZE",       (0, 0), (-1, -1), 8.5),
        ("ALIGN",          (2, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _LGRAY]),
        ("GRID",           (0, 0), (-1, -1), 0.3, _MGRAY),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
    ]))
    return t


# ─── Water level + health chart ────────────────────────────────────────────────

def _render_chart(df: pd.DataFrame, health_scores: list[dict]) -> io.BytesIO:
    has_health = bool(health_scores) and not all(
        h.get("score") is None for h in health_scores
    )
    chart_h_cm = 9.5 if has_health else 6.5
    fig = Figure(figsize=(_CONTENT_W / cm / 2.54, chart_h_cm / 2.54), dpi=150)

    if df.empty or "water_level_m" not in df.columns or df["water_level_m"].isna().all():
        ax = fig.add_subplot(1, 1, 1)
        ax.text(0.5, 0.5, "No water level data available for this period.",
                ha="center", va="center", color="#94a3b8", fontsize=9)
        ax.set_facecolor("white")
        fig.patch.set_facecolor("white")
    else:
        ts = pd.to_datetime(df["timestamp"])
        wl = df["water_level_m"].values

        if has_health:
            (ax_wl, ax_hp) = fig.subplots(
                2, 1, sharex=True,
                gridspec_kw={"height_ratios": [2.2, 1], "hspace": 0.06},
            )
        else:
            ax_wl = fig.add_subplot(1, 1, 1)

        # ── Water level subplot ──────────────────────────────────────────────
        ax_wl.plot(ts, wl, color="#0d9488", linewidth=1.3, zorder=3)
        ax_wl.fill_between(ts, wl, wl.min() - 0.5, alpha=0.10, color="#0d9488")
        # Mean reference line
        mean_wl = wl.mean()
        ax_wl.axhline(mean_wl, color="#64748b", linewidth=0.8,
                      linestyle="--", alpha=0.6, label=f"Mean {mean_wl:.2f} m")
        ax_wl.set_ylabel("Water Level (m)", fontsize=7.5, color="#374151")
        ax_wl.tick_params(axis="both", labelsize=7, colors="#6b7280")
        ax_wl.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.4, color="#d1d5db")
        ax_wl.set_facecolor("white")
        ax_wl.legend(fontsize=7, framealpha=0.7, loc="upper right")
        for sp in ax_wl.spines.values():
            sp.set_linewidth(0.4)
            sp.set_color("#e5e7eb")

        # ── Health score subplot ─────────────────────────────────────────────
        if has_health:
            hdf = pd.DataFrame(health_scores).sort_values("timestamp")
            hdf = hdf.dropna(subset=["score"])
            h_ts = pd.to_datetime(hdf["timestamp"])
            h_sc = hdf["score"].values

            ax_hp.plot(h_ts, h_sc, color="#d97706", linewidth=1.3,
                       marker="o", markersize=2.5, zorder=3)
            ax_hp.fill_between(h_ts, h_sc, 0, alpha=0.08, color="#d97706")
            ax_hp.axhline(75, color="#16a34a", linewidth=0.7,
                          linestyle="--", alpha=0.5, label="Good (75)")
            ax_hp.axhline(50, color="#dc2626", linewidth=0.7,
                          linestyle="--", alpha=0.4, label="Fair (50)")
            ax_hp.set_ylim(0, 108)
            ax_hp.set_ylabel("Health Score", fontsize=7.5, color="#374151")
            ax_hp.tick_params(axis="both", labelsize=7, colors="#6b7280")
            ax_hp.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.4, color="#d1d5db")
            ax_hp.set_facecolor("white")
            ax_hp.legend(fontsize=6.5, framealpha=0.7, loc="upper right")
            for sp in ax_hp.spines.values():
                sp.set_linewidth(0.4)
                sp.set_color("#e5e7eb")
            ax_hp.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        else:
            ax_wl.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))

        fig.patch.set_facecolor("white")
        fig.autofmt_xdate(rotation=25, ha="right")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white", dpi=150)
    buf.seek(0)
    return buf


# ─── Anomaly table ─────────────────────────────────────────────────────────────

def _anomaly_table(alerts: list[dict], s: dict) -> Table | None:
    if not alerts:
        return None

    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    shown = sorted(
        alerts,
        key=lambda a: (sev_order.get(a["severity"], 9),
                       a["triggered_at"] if isinstance(a["triggered_at"], datetime)
                       else datetime.fromisoformat(str(a["triggered_at"]))),
    )[:50]

    hdr = [
        Paragraph("<b>Timestamp</b>",  s["label"]),
        Paragraph("<b>Severity</b>",   s["label"]),
        Paragraph("<b>Type</b>",       s["label"]),
        Paragraph("<b>Message</b>",    s["label"]),
        Paragraph("<b>Resolved</b>",   s["label"]),
    ]
    rows = [hdr]
    for a in shown:
        ts = a["triggered_at"]
        ts_str = (ts.strftime("%d %b %H:%M") if isinstance(ts, datetime)
                  else str(ts)[:16].replace("T", " "))
        sev = a["severity"]
        hex_c = _SEV_COLORS.get(sev, "#64748b")
        sev_para = Paragraph(
            f'<font color="{hex_c}"><b>{sev.upper()}</b></font>', s["body"]
        )
        res = a.get("resolved_at")
        res_str = "Yes" if res else "—"
        rows.append([
            ts_str,
            sev_para,
            Paragraph(a.get("alert_type", ""), s["small"]),
            Paragraph(a.get("message", ""), s["small"]),
            res_str,
        ])

    col_w = [2.3*cm, 1.8*cm, 2.6*cm, 9.2*cm, 1.5*cm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  _NAVY),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  _WHITE),
        ("FONTSIZE",       (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _LGRAY]),
        ("GRID",           (0, 0), (-1, -1), 0.3, _MGRAY),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ("LEFTPADDING",    (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 5),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
    ]))
    return t


# ─── Section heading helper ────────────────────────────────────────────────────

def _section(title: str, s: dict) -> list:
    return [
        Paragraph(title, s["h1"]),
        HRFlowable(width="100%", thickness=1, color=_TEAL, spaceAfter=5),
    ]


# ─── Public entry point ────────────────────────────────────────────────────────

def generate_pdf(
    *,
    site_name: str,
    site_location: str | None,
    date_range_start: datetime,
    date_range_end: datetime,
    readings_df: pd.DataFrame,
    alerts: list[dict],
    health_scores: list[dict],
    executive_summary: str,
    output_path: Path,
) -> None:
    """Assemble and write a PDF report to *output_path*."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    s = _styles()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"Groundwater Report — {site_name}",
        author="Groundwater Monitor v2.0",
    )

    story: list = []

    # ── Page header ────────────────────────────────────────────────────────────
    story.append(_header_banner(site_name, site_location, date_range_start, date_range_end))
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph(
        f"Generated {datetime.utcnow().strftime('%d %b %Y  %H:%M UTC')}"
        f"  ·  Groundwater Monitor v2.0",
        s["center"],
    ))
    story.append(Spacer(1, 0.5 * cm))

    # ── Overview KPIs ──────────────────────────────────────────────────────────
    story += _section("Overview", s)
    health_vals = [h["score"] for h in health_scores if h.get("score") is not None]
    active_alert_count = sum(1 for a in alerts if not a.get("resolved_at"))
    story.append(_overview_table(
        total_readings=len(readings_df),
        total_alerts=len(alerts),
        active_alerts=active_alert_count,
        health_vals=health_vals,
        start=date_range_start,
        end=date_range_end,
        s=s,
    ))

    # ── AI Executive Summary ───────────────────────────────────────────────────
    story += _section("Executive Summary (AI-Generated)", s)
    box = Table(
        [[Paragraph(executive_summary, s["summary"])]],
        colWidths=[_CONTENT_W],
    )
    box.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), _LGRAY),
        ("LINEAFTER",    (0, 0), (0, -1),  3, _TEAL),
        ("TOPPADDING",   (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
        ("LEFTPADDING",  (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(box)
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(
        "<i>Generated by Claude claude-sonnet-4-6 · Groundwater Monitor AI</i>",
        s["small"],
    ))

    # ── Sensor Statistics ──────────────────────────────────────────────────────
    story += _section("Sensor Statistics", s)
    stats_t = _stats_table(readings_df, s)
    if stats_t:
        story.append(stats_t)
    else:
        story.append(Paragraph("No sensor data available for the selected period.", s["body"]))

    # ── Water Level Trend ──────────────────────────────────────────────────────
    story += _section("Water Level Trend" + (" & Pump Health History" if health_scores else ""), s)
    chart_buf = _render_chart(readings_df, health_scores)
    chart_h_cm = 9.5 if health_scores else 6.5
    story.append(Image(chart_buf, width=_CONTENT_W, height=chart_h_cm * cm, kind="bound"))

    # ── Anomaly Log ────────────────────────────────────────────────────────────
    story += _section(f"Anomaly Log  ({len(alerts)} events)", s)
    if alerts:
        if len(alerts) > 50:
            story.append(Paragraph(
                f"Showing top 50 of {len(alerts)} alerts, sorted by severity.",
                s["small"],
            ))
            story.append(Spacer(1, 0.15 * cm))
        at = _anomaly_table(alerts, s)
        if at:
            story.append(at)
    else:
        story.append(Paragraph("No anomalies detected during this period.", s["body"]))

    # ── Footer ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.9 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_MGRAY))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        f"Groundwater Monitor  ·  Confidential  ·  "
        f"{date_range_start.strftime('%Y-%m-%d')} to {date_range_end.strftime('%Y-%m-%d')}",
        s["center"],
    ))

    doc.build(story)
