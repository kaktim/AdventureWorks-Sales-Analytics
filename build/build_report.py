"""Generate the five-page PBIR report definition for the AdventureWorks model.

Visuals are written directly as PBIR JSON (visualContainer 2.14.0) so Power BI
Desktop can open the project and render them. All figures used in the narrative
text boxes are computed from the curated extracts, so the story stays in sync
with the model.

Run:  python build/build_report.py
"""

from __future__ import annotations

import csv
import json
import shutil
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "pbi"
REPORT = PBI / "AdventureWorks Internet Sales.Report"
DEF = REPORT / "definition"
MODEL_DATA = ROOT / "powerbi" / "model_data"

VISUAL_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "visualContainer/2.14.0/schema.json"
)
PAGE_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "page/2.1.0/schema.json"
)
PAGES_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "pagesMetadata/1.1.0/schema.json"
)

NAVY = "#D9D0F0"
TEAL = "#2DD4BF"
AMBER = "#FBBF24"
BODY = "#D9D0F0"
MUTED = "#A294C9"
PAGE_BG = "#0B0718"
SURFACE = "#16102B"

# Web dashboard palette (dashboard/styles.css) used by the KPI cards
CARD_NAVY = "#1D1440"
CARD_INK = "#F4F0FF"
CARD_MUTED = "#B8ABDD"
CARD_LINE = "#2E2352"
TONE_GOLD = "#8B5CF6"
TONES = {
    "teal": "#2DD4BF",
    "gold": "#8B5CF6",
    "coral": "#FB7185",
    "green": "#34D399",
}


# --------------------------------------------------------------------------- #
# JSON literal helpers
# --------------------------------------------------------------------------- #
def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def s_lit(value: str) -> dict:
    return lit("'" + value.replace("'", "''") + "'")


def b_lit(value: bool) -> dict:
    return lit("true" if value else "false")


def n_lit(value: float) -> dict:
    return lit(f"{value}D")


def color(hex_value: str) -> dict:
    return {"solid": {"color": s_lit(hex_value)}}


# --------------------------------------------------------------------------- #
# Field / projection helpers
# --------------------------------------------------------------------------- #
def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def meas(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj_field(field: dict, entity: str, prop: str, *, active: bool = False) -> dict:
    item = {
        "field": field,
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop,
    }
    if active:
        item["active"] = True
    return item


def proj_col(entity: str, prop: str, *, active: bool = False) -> dict:
    return proj_field(col(entity, prop), entity, prop, active=active)


def proj_measure(entity: str, prop: str) -> dict:
    return proj_field(meas(entity, prop), entity, prop)


# --------------------------------------------------------------------------- #
# Visual building blocks
# --------------------------------------------------------------------------- #
def title_objects(text: str, *, size: float = 12, hex_color: str = NAVY,
                  show: bool = True) -> dict:
    return {
        "title": [
            {
                "properties": {
                    "show": b_lit(show),
                    "text": s_lit(text),
                    "fontSize": n_lit(size),
                    "fontColor": color(hex_color),
                }
            }
        ],
        "subTitle": [{"properties": {"show": b_lit(False)}}],
    }


def card_objects(text: str | None = None, *, background: str = SURFACE) -> dict:
    objs: dict = {"background": [{"properties": {"show": b_lit(True), "color": color(background)}}]}
    if text:
        objs.update(title_objects(text, size=12))
    else:
        objs.update(title_objects("", show=False))
    return objs


def add_visual(
    page: dict,
    vtype: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    state: dict | None = None,
    objects: dict | None = None,
    container: dict | None = None,
    filters: list | None = None,
    sort_field: dict | None = None,
    sort_dir: str = "Descending",
    tab_order: int | None = None,
    z: int = 0,
) -> None:
    vid = uuid.uuid4().hex[:20]
    visual: dict = {"visualType": vtype}
    if state is not None:
        visual["query"] = {"queryState": state}
    if sort_field is not None:
        visual.setdefault("query", {})
        visual["query"]["sortDefinition"] = {
            "sort": [{"field": sort_field, "direction": sort_dir}],
            "isDefaultSort": True,
        }
    if objects:
        visual["objects"] = objects
    container = dict(container or {})
    visual["visualContainerObjects"] = container
    visual["drillFilterOtherVisuals"] = True

    position = {"x": x, "y": y, "z": z, "height": h, "width": w}
    if tab_order is not None:
        position["tabOrder"] = tab_order
    entry = {"$schema": VISUAL_SCHEMA, "name": vid, "position": position, "visual": visual}
    if filters:
        entry["filterConfig"] = {"filters": filters}
    page["visuals"].append(entry)


def text_run(text: str, *, size: float, hex_color: str, bold: bool = False) -> dict:
    style: dict = {"fontSize": f"{size}pt", "color": hex_color}
    if bold:
        style["fontWeight"] = "bold"
    return {"value": text, "textStyle": style}


def add_textbox(
    page: dict,
    x: float,
    y: float,
    w: float,
    h: float,
    paragraphs: list[list[dict]],
    *,
    background: str | None = None,
) -> None:
    container: dict = {}
    if background:
        container["background"] = [{"properties": {"show": b_lit(True), "color": color(background)}}]
    add_visual(
        page,
        "textbox",
        x,
        y,
        w,
        h,
        objects={"general": [{"properties": {"paragraphs": [{"textRuns": runs} for runs in paragraphs]}}]},
        container=container,
    )


def header(page: dict, title: str, subtitle: str) -> None:
    add_textbox(
        page,
        0,
        0,
        1920,
        96,
        [
            [text_run(title, size=22, hex_color="#F4F0FF", bold=True)],
            [text_run(subtitle, size=10.5, hex_color="#B8ABDD")],
        ],
        background="#171030",
    )


def footer(page: dict, stamp: str) -> None:
    add_textbox(
        page,
        40,
        1040,
        1840,
        32,
        [[text_run(f"Source: AdventureWorksDW.xlsx (read-only) · Revenue and profit use SUMX(UnitPrice × OrderQuantity) · Display timeline 2021–2022 · Snapshot {stamp} UTC", size=9, hex_color=MUTED)]],
    )


def bar_slicer(page: dict, x: float, y: float, w: float, h: float, entity: str, prop: str,
               label: str, *, mode: str = "Dropdown") -> None:
    """A filter-bar control: white pill card, 9 pt header, dropdown or date range."""
    add_visual(
        page,
        "slicer",
        x,
        y,
        w,
        h,
        state={
            "Values": {
                "projections": [proj_col(entity, prop, active=True)],
            }
        },
        objects={
            "data": [{"properties": {"mode": s_lit(mode)}}],
            # The field-name header fields its own line and squeezes the value
            # box out of a 56 px pill, so it has to go.
            "header": [{"properties": {"show": b_lit(False)}}],
        },
        container={
            "background": [{"properties": {"show": b_lit(True), "color": color(SURFACE),
                                           "transparency": n_lit(0)}}],
            "border": [{"properties": {"show": b_lit(True), "color": color(CARD_LINE),
                                       "radius": n_lit(14)}}],
            "title": [{"properties": {"show": b_lit(True), "text": s_lit(label),
                                      "fontSize": n_lit(9), "fontColor": color(CARD_MUTED)}}],
            "subTitle": [{"properties": {"show": b_lit(False)}}],
            "visualHeader": [{"properties": {"show": b_lit(False)}}],
        },
    )


def reset_button(page: dict, x: float, y: float, w: float, h: float) -> None:
    """Ghost button wired to Desktop's native ClearAllSlicers action."""
    add_visual(
        page,
        "actionButton",
        x,
        y,
        w,
        h,
        objects={
            "text": [
                {"properties": {"show": b_lit(True)}},
                {
                    "properties": {
                        "text": s_lit("Reset filters"),
                        "horizontalAlignment": s_lit("center"),
                        "fontSize": n_lit(10),
                        "fontColor": color(CARD_INK),
                    },
                    "selector": {"id": "default"},
                },
            ],
            "icon": [
                {"properties": {"shapeType": s_lit("clearAllSlicers")}, "selector": {"id": "default"}},
                {"properties": {"show": b_lit(False)}},
            ],
            "fill": [
                {"properties": {"show": b_lit(True)}},
                {
                    "properties": {"fillColor": color(SURFACE), "transparency": n_lit(0)},
                    "selector": {"id": "default"},
                },
            ],
            "outline": [
                {"properties": {"show": b_lit(True)}},
                {
                    "properties": {"color": color(CARD_LINE), "weight": n_lit(1), "radius": n_lit(14)},
                    "selector": {"id": "default"},
                },
            ],
        },
        container={
            "visualLink": [{
                "properties": {
                    "show": b_lit(True),
                    "type": s_lit("ClearAllSlicers"),
                    "tooltipPlaceholderText": s_lit("Clear all slicers on this page"),
                }
            }],
        },
    )


def filter_bar(page: dict, *, lead_band: bool = False) -> None:
    """The web dashboard's filter strip, reproduced across the content width.

    Period range -> period preset -> country -> product line -> region ->
    gender -> income band -> reset. All controls are single, always-visible
    slicers so any page can be narrowed in one click.
    """
    add_textbox(page, 0, 96, 1920, 72, [[text_run(" ", size=1, hex_color=SURFACE)]],
                background=SURFACE)
    bar_slicer(page, 40, 98, 300, 64, "DimDate", "Date", "Period", mode="Between")
    bar_slicer(page, 352, 98, 170, 64, "Period Preset", "Preset", "Preset")
    bar_slicer(page, 534, 98, 190, 64, "DimCustomer", "Customer Country", "Country")
    bar_slicer(page, 736, 98, 190, 64, "DimProduct", "ProductLine", "Product line")
    bar_slicer(page, 938, 98, 200, 64, "DimSalesTerritory", "TerritoryGroup", "Region")
    bar_slicer(page, 1150, 98, 120, 64, "DimCustomer", "Gender", "Gender")
    bar_slicer(page, 1282, 98, 160, 64, "DimCustomer", "IncomeBand", "Income band")
    if lead_band:
        bar_slicer(page, 1454, 98, 160, 64, "FactInternetSales", "LeadBucket", "Lead-time band")
    reset_button(page, 1626, 98, 160, 64)


def kpi(page: dict, x: float, y: float, w: float, h: float, measure: str,
        sub: str, label: str, *, tone: str = "teal", primary: bool = False) -> None:
    """Web-parity KPI card: uppercase label, serif value, muted sub-line.

    Two layered cardVisuals: the first owns the card fill, border, radius and
    accent bar and prints the label + value; the second sits over the bottom
    band and prints the dynamic sub-line in the smaller muted type.
    """
    accent = TONE_GOLD if primary else TONES[tone]
    fill = CARD_NAVY if primary else SURFACE
    edge = "#3A2A63" if primary else CARD_LINE
    value_colour = "#F4F0FF" if primary else CARD_INK
    label_colour = "#B8ABDD" if primary else CARD_MUTED
    sub_colour = "#B8ABDD" if primary else CARD_MUTED

    add_visual(
        page,
        "cardVisual",
        x,
        y,
        w,
        h,
        state={"Data": {"projections": [proj_measure("FactInternetSales", measure)]}},
        objects={
            "label": [{
                "properties": {
                    "show": b_lit(True),
                    "text": s_lit(label.upper()),
                    "position": s_lit("aboveValue"),
                    "fontSize": n_lit(9),
                    "fontColor": color(label_colour),
                },
                "selector": {"id": "default"},
            }],
            "value": [{
                "properties": {
                    "show": b_lit(True),
                    "fontSize": n_lit(26),
                    "fontFamily": s_lit("Georgia"),
                    "fontColor": color(value_colour),
                    "displayUnits": lit("1L"),
                },
                "selector": {"id": "default"},
            }],
            "fillCustom": [{
                "properties": {
                    "show": b_lit(True),
                    "fillColor": color(fill),
                    "transparency": n_lit(0),
                },
                "selector": {"id": "default"},
            }],
            "outline": [{"properties": {"show": b_lit(False)}, "selector": {"id": "default"}}],
            "accentBar": [{
                "properties": {
                    "show": b_lit(True),
                    "position": s_lit("Left"),
                    "width": n_lit(3),
                    "color": color(accent),
                },
                "selector": {"id": "default"},
            }],
            "padding": [{
                "properties": {
                    "paddingSelection": s_lit("Custom"),
                    "topMargin": n_lit(12),
                    "bottomMargin": n_lit(0),
                    "leftMargin": n_lit(15),
                    "rightMargin": n_lit(10),
                },
                "selector": {"id": "default"},
            }],
            "layout": [{"properties": {"paddingUniform": n_lit(0)}, "selector": {"id": "default"}}],
            "spacing": [{"properties": {"verticalSpacing": n_lit(3)}, "selector": {"id": "default"}}],
        },
        container={
            "background": [{"properties": {"show": b_lit(True), "color": color(fill),
                                           "transparency": n_lit(0)}}],
            "border": [{"properties": {"show": b_lit(True), "color": color(edge),
                                       "radius": n_lit(14)}}],
            "title": [{"properties": {"show": b_lit(False)}}],
            "subTitle": [{"properties": {"show": b_lit(False)}}],
        },
    )

    add_visual(
        page,
        "cardVisual",
        x + 15,
        y + h - 34,
        w - 25,
        22,
        state={"Data": {"projections": [proj_measure("FactInternetSales", sub)]}},
        objects={
            "label": [{"properties": {"show": b_lit(False)}, "selector": {"id": "default"}}],
            "value": [{
                "properties": {
                    "show": b_lit(True),
                    "fontSize": n_lit(10.5),
                    "fontColor": color(sub_colour),
                },
                "selector": {"id": "default"},
            }],
            "outline": [{"properties": {"show": b_lit(False)}, "selector": {"id": "default"}}],
            "padding": [{
                "properties": {
                    "paddingSelection": s_lit("Custom"),
                    "topMargin": n_lit(0),
                    "bottomMargin": n_lit(0),
                    "leftMargin": n_lit(0),
                    "rightMargin": n_lit(0),
                },
                "selector": {"id": "default"},
            }],
            "layout": [{"properties": {"paddingUniform": n_lit(0)}, "selector": {"id": "default"}}],
            "spacing": [{"properties": {"verticalSpacing": n_lit(0)}, "selector": {"id": "default"}}],
        },
        z=1,
    )


def kpi_row(page: dict, y: float, h: float, items: list[tuple[str, str, str, str]]) -> None:
    """Lay four KPI cards across the 1840px content column (first one primary)."""
    width = 445
    gap = 20
    for i, (measure, sub, label, tone) in enumerate(items):
        kpi(page, 40 + i * (width + gap), y, width, h, measure, sub, label,
            tone=tone, primary=(i == 0))


def bar_chart(page: dict, x: float, y: float, w: float, h: float, entity: str, category: str,
              measure: str, label: str) -> None:
    add_visual(
        page,
        "barChart",
        x,
        y,
        w,
        h,
        state={
            "Category": {"projections": [proj_col(entity, category, active=True)]},
            "Y": {"projections": [proj_measure("FactInternetSales", measure)]},
        },
        objects={
            "labels": [{"properties": {"show": b_lit(True)}}],
            "legend": [{"properties": {"show": b_lit(False)}}],
        },
        container=title_objects(label, size=12),
        sort_field=meas("FactInternetSales", measure),
    )


def line_chart(page: dict, x: float, y: float, w: float, h: float, measures: list[str],
               label: str, category: str = "MonthYear", category_entity: str = "DimDate") -> None:
    add_visual(
        page,
        "lineChart",
        x,
        y,
        w,
        h,
        state={
            "Category": {"projections": [proj_col(category_entity, category, active=True)]},
            "Y": {"projections": [proj_measure("FactInternetSales", m) for m in measures]},
        },
        objects={
            "labels": [{"properties": {"show": b_lit(False)}}],
            "legend": [{"properties": {"show": b_lit(len(measures) > 1), "position": s_lit("Bottom")}}],
        },
        container=title_objects(label, size=12),
    )


def pie_chart(page: dict, x: float, y: float, w: float, h: float, entity: str, category: str,
              measure: str, label: str) -> None:
    add_visual(
        page,
        "pieChart",
        x,
        y,
        w,
        h,
        state={
            "Category": {"projections": [proj_col(entity, category, active=True)]},
            "Y": {"projections": [proj_measure("FactInternetSales", measure)]},
        },
        objects={
            "labels": [{"properties": {"show": b_lit(True)}}],
            "legend": [{"properties": {"show": b_lit(True), "position": s_lit("Bottom")}}],
        },
        container=title_objects(label, size=12),
        sort_field=meas("FactInternetSales", measure),
    )


def table(page: dict, x: float, y: float, w: float, h: float, fields: list[tuple[str, str, bool]],
          label: str, *, sort_measure: str | None = None, filters: list | None = None) -> None:
    projections = []
    for entity, prop, is_measure in fields:
        if is_measure:
            projections.append(proj_measure(entity, prop))
        else:
            projections.append(proj_col(entity, prop))
    add_visual(
        page,
        "tableEx",
        x,
        y,
        w,
        h,
        state={"Values": {"projections": projections}},
        container=title_objects(label, size=12),
        filters=filters,
        sort_field=meas("FactInternetSales", sort_measure) if sort_measure else None,
    )


def categorical_filter(name: str, entity: str, prop: str, value: str) -> dict:
    return {
        "name": name,
        "field": col(entity, prop),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "f", "Entity": entity, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [
                                {"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": prop}}
                            ],
                            "Values": [[{"Literal": {"Value": "'" + value + "'"}}]],
                        }
                    }
                }
            ],
        },
    }


def insight(page: dict, x: float, y: float, w: float, h: float, heading: str,
            bullets: list[str]) -> None:
    paragraphs = [[text_run(heading, size=13, hex_color=NAVY, bold=True)]]
    for bullet in bullets:
        paragraphs.append([text_run("•  " + bullet, size=10.5, hex_color=BODY)])
    add_textbox(page, x, y, w, h, paragraphs, background=SURFACE)


# --------------------------------------------------------------------------- #
# Facts for the narrative
# --------------------------------------------------------------------------- #
def read_csv(name: str) -> list[dict]:
    with (MODEL_DATA / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def money(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:,.1f}K"
    return f"${value:,.0f}"


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def compute_facts() -> dict:
    fact = read_csv("FactInternetSalesModel.csv")
    products = {r["ProductKey"]: r for r in read_csv("DimProductModel.csv")}
    customers = {r["CustomerKey"]: r for r in read_csv("DimCustomerModel.csv")}
    territories = {r["SalesTerritoryKey"]: r for r in read_csv("DimSalesTerritoryModel.csv")}

    revenue = profit = units = 0.0
    by_year: dict[str, float] = defaultdict(float)
    by_line: dict[str, float] = defaultdict(float)
    profit_by_line: dict[str, float] = defaultdict(float)
    by_territory: dict[str, float] = defaultdict(float)
    by_product: dict[str, float] = defaultdict(float)
    by_customer: dict[str, float] = defaultdict(float)
    by_income: dict[str, float] = defaultdict(float)
    by_value_band: dict[str, float] = defaultdict(float)
    cust_orders: dict[str, set] = defaultdict(set)
    orders: set[str] = set()
    lead_total = 0
    late_lines = 0
    bucket_lines: dict[str, int] = defaultdict(int)

    for row in fact:
        rev = float(row["LineRevenue"])
        prof = float(row["LineProfit"])
        qty = int(row["OrderQuantity"])
        revenue += rev
        profit += prof
        units += qty
        by_year[row["OrderYear"]] += rev
        pid = row["ProductKey"]
        by_product[products[pid]["ProductName"]] += rev
        by_line[products[pid]["ProductLine"]] += rev
        profit_by_line[products[pid]["ProductLine"]] += prof
        by_territory[territories[row["SalesTerritoryKey"]]["Country"]] += rev
        cid = row["CustomerKey"]
        by_customer[cid] += rev
        cust_orders[cid].add(row["SalesOrderNumber"])
        orders.add(row["SalesOrderNumber"])
        by_income[customers[cid]["IncomeBand"]] += rev
        by_value_band[customers[cid]["RevenueBand"]] += rev
        lead_total += int(row["LeadDays"])
        if int(row["LateDays"]) > 0:
            late_lines += 1
        bucket_lines[row["LeadBucket"]] += 1

    repeat_customers = [c for c, os_ in cust_orders.items() if len(os_) >= 2]
    repeat_revenue = sum(by_customer[c] for c in repeat_customers)
    top_products = sorted(by_product.items(), key=lambda kv: kv[1], reverse=True)
    top_customers = sorted(by_customer.items(), key=lambda kv: kv[1], reverse=True)
    top10_customer_rev = sum(v for _, v in top_customers[:10])
    top_line = max(by_line.items(), key=lambda kv: kv[1])
    top_territory = max(by_territory.items(), key=lambda kv: kv[1])
    margin_by_line = {
        line: profit_by_line[line] / by_line[line] for line in by_line
    }
    best_margin_line = max(margin_by_line.items(), key=lambda kv: kv[1])
    top_income = max(by_income.items(), key=lambda kv: kv[1])
    top_band = max(by_value_band.items(), key=lambda kv: kv[1])

    return {
        "revenue": revenue,
        "profit": profit,
        "margin": profit / revenue,
        "orders": len(orders),
        "units": units,
        "customers": len(cust_orders),
        "repeat_customers": len(repeat_customers),
        "repeat_rate": len(repeat_customers) / len(cust_orders),
        "repeat_revenue_share": repeat_revenue / revenue,
        "aov": revenue / len(orders),
        "avg_lead": lead_total / len(fact),
        "late_lines": late_lines,
        "rev2021": by_year["2021"],
        "rev2022": by_year["2022"],
        "growth": by_year["2022"] / by_year["2021"] - 1,
        "top_product": top_products[0],
        "top10_product_share": sum(v for _, v in top_products[:10]) / revenue,
        "top_customer": top_customers[0],
        "top10_customer_share": top10_customer_rev / revenue,
        "top_line": top_line,
        "top_line_share": top_line[1] / revenue,
        "best_margin_line": best_margin_line,
        "top_territory": top_territory,
        "top_territory_share": top_territory[1] / revenue,
        "top_income": top_income,
        "top_band": top_band,
        "customer_names": {c: customers[c]["CustomerName"] for c in customers},
        "bucket_lines": dict(bucket_lines),
        "freight": sum(float(r["LineFreight"]) for r in fact),
    }


# --------------------------------------------------------------------------- #
# Page builders
# --------------------------------------------------------------------------- #
def build_overview(f: dict, stamp: str) -> dict:
    page = make_page("Overview", "Overview")
    header(page, "AdventureWorks Internet Sales",
           "Overview · scale and trajectory · 60,398 order lines, 18,484 customers, 6 markets")
    filter_bar(page)

    kpi_row(page, 176, 136, [
        ("KPI Revenue", "Sub Overview Revenue", "Revenue", "gold"),
        ("KPI Gross Profit", "Sub Overview Gross Profit", "Gross profit", "teal"),
        ("KPI Gross Margin", "Sub Overview Gross Margin", "Gross margin", "gold"),
        ("KPI Orders", "Sub Overview Orders", "Orders", "green"),
    ])

    line_chart(page, 40, 324, 1200, 372, ["Revenue", "Gross Profit"], "Revenue and gross profit by month")
    pie_chart(page, 1256, 324, 624, 372, "DimSalesTerritory", "TerritoryGroup", "Revenue",
              "Revenue by territory group")
    bar_chart(page, 40, 708, 600, 332, "DimProduct", "ProductLine", "Revenue",
              "Revenue by product line")
    bar_chart(page, 656, 708, 600, 332, "DimSalesTerritory", "TerritoryCountry", "Revenue",
              "Revenue by territory country")
    insight(
        page, 1272, 708, 608, 332, "What stands out",
        [
            f"Revenue reached {money(f['revenue'])} across {f['orders']:,} orders (AOV ${f['aov']:,.0f}).",
            f"2022 produced {money(f['rev2022'])} — {pct(f['rev2022'] / f['revenue'])} of the total and {pct(f['growth'])} above 2021.",
            f"{f['top_line'][0]} leads product lines at {pct(f['top_line_share'])} of revenue; {f['top_territory'][0]} leads markets at {pct(f['top_territory_share'])}.",
            f"Gross margin holds at {pct(f['margin'])} ({money(f['profit'])} gross profit).",
        ],
    )
    footer(page, stamp)
    return page


def build_profitability(f: dict, stamp: str) -> dict:
    page = make_page("Profitability", "Profitability")
    header(page, "Profitability",
           "Profitability · margin quality, product concentration and freight drag · amounts net of standard cost")
    filter_bar(page)

    kpi_row(page, 176, 136, [
        ("KPI Gross Profit", "Sub Profitability Gross Profit", "Gross profit", "teal"),
        ("KPI Gross Margin", "Sub Profitability Gross Margin", "Gross margin", "teal"),
        ("KPI Revenue", "Sub Profitability Revenue", "Revenue", "gold"),
        ("KPI Freight Cost", "Sub Profitability Freight", "Freight cost", "coral"),
    ])

    line_chart(page, 40, 324, 920, 372, ["Gross Margin %"], "Gross margin by month")
    bar_chart(page, 976, 324, 904, 372, "DimProduct", "ProductName", "Gross Profit",
              "Top 10 products by gross profit")
    page["visuals"][-1]["filterConfig"] = {
        "filters": [categorical_filter("tier-top10", "DimProduct", "SellerTier", "Top 10")]
    }
    table(
        page, 40, 708, 920, 332,
        [
            ("DimProduct", "ProductName", False),
            ("FactInternetSales", "Revenue", True),
            ("FactInternetSales", "Gross Profit", True),
            ("FactInternetSales", "Gross Margin %", True),
            ("FactInternetSales", "Units", True),
        ],
        "Top 10 products — detail",
        sort_measure="Revenue",
        filters=[categorical_filter("tier-top10-tbl", "DimProduct", "SellerTier", "Top 10")],
    )
    bar_chart(page, 976, 708, 904, 332, "DimProduct", "ProductLine", "Gross Margin %",
              "Gross margin by product line")
    footer(page, stamp)
    return page


def build_customers(f: dict, stamp: str) -> dict:
    page = make_page("Customers", "Customers")
    header(page, "Customers",
           "Customers · value concentration, repeat behaviour and income profile · one row per customer")
    filter_bar(page)

    kpi_row(page, 176, 136, [
        ("KPI Customers", "Sub Customers Customers", "Customers", "teal"),
        ("KPI Repeat Rate", "Sub Customers Repeat Rate", "Repeat rate", "teal"),
        ("KPI Revenue per Customer", "Sub Customers Revenue per Customer", "Revenue per customer", "gold"),
        ("KPI Orders per Customer", "Sub Customers Orders per Customer", "Orders per customer", "green"),
    ])

    bar_chart(page, 40, 324, 600, 340, "DimCustomer", "IncomeBand", "Revenue",
              "Revenue by income band")
    pie_chart(page, 656, 324, 600, 340, "DimCustomer", "Gender", "Customers",
              "Customers by gender")
    bar_chart(page, 1272, 324, 608, 340, "DimCustomer", "RevenueBand", "Revenue",
              "Revenue by customer value band")

    table(
        page, 40, 680, 920, 360,
        [
            ("DimCustomer", "CustomerName", False),
            ("DimCustomer", "Customer Country", False),
            ("FactInternetSales", "Orders", True),
            ("FactInternetSales", "Revenue", True),
            ("FactInternetSales", "Gross Profit", True),
        ],
        "Top 10 customers by revenue",
        sort_measure="Revenue",
        filters=[categorical_filter("tier-top10-cust", "DimCustomer", "CustomerTier", "Top 10")],
    )
    insight(
        page, 976, 680, 904, 360, "What stands out",
        [
            f"{f['repeat_customers']:,} of {f['customers']:,} customers ({pct(f['repeat_rate'])}) placed two or more orders and generate {pct(f['repeat_revenue_share'])} of revenue.",
            f"The top 10 customers contribute {pct(f['top10_customer_share'])} of revenue; the largest is {f['customer_names'][f['top_customer'][0]]} at {money(f['top_customer'][1])}.",
            f"Revenue per customer is ${f['revenue'] / f['customers']:,.0f}, with {f['orders'] / f['customers']:.2f} orders per customer.",
            f"{f['top_income'][0]} is the highest-revenue income band at {money(f['top_income'][1])}.",
        ],
    )
    footer(page, stamp)
    return page


def build_geography(f: dict, stamp: str) -> dict:
    page = make_page("Geography", "Geography")
    header(page, "Geography",
           "Geography · territory performance · fact territory key is the single territory filter path")
    filter_bar(page)

    kpi_row(page, 176, 136, [
        ("KPI Revenue", "Sub Geography Revenue", "Revenue", "gold"),
        ("KPI Gross Margin", "Sub Geography Gross Margin", "Gross margin", "teal"),
        ("KPI Territories", "Sub Geography Territories", "Territories", "gold"),
        ("KPI Orders", "Sub Geography Orders", "Orders", "green"),
    ])

    bar_chart(page, 40, 324, 920, 352, "DimSalesTerritory", "TerritoryCountry", "Revenue",
              "Revenue by territory country")
    pie_chart(page, 976, 324, 904, 352, "DimSalesTerritory", "TerritoryGroup", "Revenue",
              "Revenue by territory group")
    table(
        page, 40, 692, 920, 348,
        [
            ("DimSalesTerritory", "TerritoryRegion", False),
            ("DimSalesTerritory", "TerritoryCountry", False),
            ("DimSalesTerritory", "TerritoryGroup", False),
            ("FactInternetSales", "Revenue", True),
            ("FactInternetSales", "Gross Profit", True),
            ("FactInternetSales", "Gross Margin %", True),
            ("FactInternetSales", "Orders", True),
        ],
        "Territory performance",
        sort_measure="Revenue",
    )
    insight(
        page, 976, 692, 904, 348, "Reading this page",
        [
            f"{f['top_territory'][0]} is the largest market at {money(f['top_territory'][1])} ({pct(f['top_territory_share'])} of revenue).",
            "Territory visuals use FactInternetSales[SalesTerritoryKey]; customer country comes from DimCustomer and is a separate segmentation lens.",
            "Only one territory path is active, so there is no ambiguous filter route; customer geography is reached through DimCustomer → DimGeography.",
            "Currency conversion is not applied: the workbook contains keys but no exchange-rate table.",
        ],
    )
    footer(page, stamp)
    return page


def build_detail(f: dict, stamp: str) -> dict:
    page = make_page("Detail", "Detail")
    header(page, "Detail",
           "Detail · line-level explorer · 60,398 rows, filterable by year, territory, product line and lead-time band")
    filter_bar(page, lead_band=True)

    kpi_row(page, 176, 136, [
        ("KPI Lines", "Sub Detail Lines", "Order lines", "teal"),
        ("KPI Units", "Sub Detail Units", "Units", "teal"),
        ("KPI Avg Lead", "Sub Detail Avg Lead", "Average lead time", "gold"),
        ("KPI Late Line Rate", "Sub Detail Late", "Late line rate", "coral"),
    ])

    table(
        page, 40, 324, 1840, 704,
        [
            ("FactInternetSales", "OrderDate", False),
            ("FactInternetSales", "SalesOrderNumber", False),
            ("FactInternetSales", "SalesOrderLineNumber", False),
            ("DimProduct", "ProductName", False),
            ("DimCustomer", "CustomerName", False),
            ("DimSalesTerritory", "TerritoryRegion", False),
            ("FactInternetSales", "OrderQuantity", False),
            ("FactInternetSales", "Revenue", True),
            ("FactInternetSales", "Gross Profit", True),
            ("FactInternetSales", "LeadDays", False),
            ("FactInternetSales", "LateDays", False),
        ],
        "Order lines",
    )
    footer(page, stamp)
    return page


# --------------------------------------------------------------------------- #
# Page plumbing
# --------------------------------------------------------------------------- #
def make_page(name: str, display: str) -> dict:
    return {
        "id": uuid.uuid4().hex[:20],
        "displayName": display,
        "visuals": [],
        "_name": name,
    }


def write_page(page: dict) -> None:
    page_dir = DEF / "pages" / page["id"]
    (page_dir / "visuals").mkdir(parents=True, exist_ok=True)
    page_json = {
        "$schema": PAGE_SCHEMA,
        "name": page["id"],
        "displayName": page["displayName"],
        "displayOption": "FitToPage",
        "height": 1080,
        "width": 1920,
        "objects": {
            "background": [
                {
                    "properties": {
                        "color": color(PAGE_BG),
                        "transparency": n_lit(0),
                    }
                }
            ]
        },
    }
    (page_dir / "page.json").write_text(
        json.dumps(page_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for visual in page["visuals"]:
        vdir = page_dir / "visuals" / visual["name"]
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "visual.json").write_text(
            json.dumps(visual, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    facts = compute_facts()

    pages_dir = DEF / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True)

    pages = [
        build_overview(facts, stamp),
        build_profitability(facts, stamp),
        build_customers(facts, stamp),
        build_geography(facts, stamp),
        build_detail(facts, stamp),
    ]
    for page in pages:
        write_page(page)

    pages_json = {
        "$schema": PAGES_SCHEMA,
        "pageOrder": [p["id"] for p in pages],
        "activePageName": pages[0]["id"],
    }
    (pages_dir / "pages.json").write_text(
        json.dumps(pages_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"pages written: {len(pages)}  visuals: {sum(len(p['visuals']) for p in pages)}")
    for page in pages:
        print(f"  {page['displayName']:<14} {page['id']}  visuals={len(page['visuals'])}")
    print(f"snapshot: {stamp} UTC")


if __name__ == "__main__":
    main()
