"""Build the dashboard dataset and Power BI-ready CSV extracts from the workbook.

No third-party dependencies: reads the XLSX package with zipfile + ElementTree.
Run from the repo root:  python build/prepare_data.py
"""

from __future__ import annotations

import csv
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "AdventureWorksDW.xlsx"
DASHBOARD = ROOT / "dashboard"
POWERBI = ROOT / "powerbi"
DATA_DIR = POWERBI / "data"
MODEL_DATA = POWERBI / "model_data"

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
EXCEL_EPOCH = datetime(1899, 12, 30)
PERIOD_START = date(2021, 1, 1)
PERIOD_END = date(2022, 12, 31)

PRODUCT_LINE_NAMES = {"R": "Road", "M": "Mountain", "T": "Touring", "S": "Standard"}


def income_band(income: int) -> str:
    if income < 40000:
        return "Under 40K"
    if income < 70000:
        return "40K-70K"
    if income < 100000:
        return "70K-100K"
    return "100K+"


def revenue_band(revenue: float) -> str:
    if revenue < 1000:
        return "Under 1K"
    if revenue < 5000:
        return "1K-5K"
    if revenue < 10000:
        return "5K-10K"
    if revenue < 50000:
        return "10K-50K"
    return "50K+"


def lead_bucket(days: int) -> str:
    if days <= 2:
        return "0-2 days"
    if days <= 5:
        return "3-5 days"
    if days <= 8:
        return "6-8 days"
    if days <= 11:
        return "9-11 days"
    return "12+ days"


def clean(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def number(value: str | None) -> float | None:
    text = clean(value)
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def integer(value: str | None) -> int | None:
    n = number(value)
    return None if n is None else int(n)


def serial_to_date(value: str | None) -> date | None:
    n = number(value)
    if n is None:
        return None
    return (EXCEL_EPOCH + timedelta(days=n)).date()


def key_to_date(value: str | None) -> date | None:
    """Convert a YYYYMMDD date key (e.g. 20050701) to a date."""
    text = clean(value)
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def sheet_targets(z: zipfile.ZipFile) -> dict[str, str]:
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {r.get("Id"): r.get("Target") for r in rels}
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    out: dict[str, str] = {}
    for sheet in wb.iter(NS + "sheet"):
        target = relmap[sheet.get(RELNS + "id")]
        out[sheet.get("name")] = "xl/" + target.lstrip("/")
    return out


def iter_rows(z: zipfile.ZipFile, target: str, shared: list[str]):
    with z.open(target) as fh:
        headers: dict[str, str] | None = None
        for _, el in ET.iterparse(fh, events=("end",)):
            if el.tag != NS + "row":
                continue
            row: dict[str, str | None] = {}
            for cell in el.iter(NS + "c"):
                col = re.match(r"[A-Z]+", cell.get("r")).group(0)
                ctype = cell.get("t")
                v = cell.find(NS + "v")
                if ctype == "s" and v is not None:
                    value = shared[int(v.text)]
                elif ctype == "inlineStr":
                    value = "".join(t.text or "" for t in cell.iter(NS + "t"))
                else:
                    value = v.text if v is not None else None
                if headers is not None and col in headers:
                    row[headers[col]] = value
                elif headers is None:
                    row[col] = value
            if headers is None:
                headers = {col: (clean(value) or col) for col, value in row.items()}
            else:
                yield {headers.get(col, col): value for col, value in row.items()}
            el.clear()


def main() -> None:
    if not XLSX.exists():
        raise SystemExit(f"Missing source workbook: {XLSX}")

    DASHBOARD.mkdir(exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(XLSX) as z:
        targets = sheet_targets(z)

        shared: list[str] = []
        with z.open("xl/sharedStrings.xml") as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                if el.tag == NS + "si":
                    shared.append("".join(t.text or "" for t in el.iter(NS + "t")))
                    el.clear()

        # ---------------- dimensions ----------------
        products: list[dict] = []
        with (DATA_DIR / "DimProduct.csv").open("w", newline="", encoding="utf-8-sig") as out:
            writer = None
            for raw in iter_rows(z, targets["DimProduct"], shared):
                if writer is None:
                    writer = csv.DictWriter(out, fieldnames=list(raw.keys()))
                    writer.writeheader()
                writer.writerow(raw)
                key = integer(raw.get("ProductKey"))
                if key is None:
                    continue
                line_code = clean(raw.get("ProductLine"))
                products.append({
                    "k": key,
                    "alt": clean(raw.get("ProductAlternateKey")),
                    "n": clean(raw.get("EnglishProductName")) or f"Product {key}",
                    "line": PRODUCT_LINE_NAMES.get(line_code, line_code or "Unspecified"),
                    "model": clean(raw.get("ModelName")) or "Unspecified",
                    "color": clean(raw.get("Color")) or "Unspecified",
                    "size": clean(raw.get("Size")) or "Unspecified",
                    "sub": integer(raw.get("ProductSubcategoryKey")),
                    "cost": number(raw.get("StandardCost")) or 0.0,
                    "price": number(raw.get("ListPrice")) or 0.0,
                })
        products.sort(key=lambda p: p["k"])

        geos: list[dict] = []
        with (DATA_DIR / "DimGeography.csv").open("w", newline="", encoding="utf-8-sig") as out:
            writer = None
            for raw in iter_rows(z, targets["DimGeography"], shared):
                if writer is None:
                    writer = csv.DictWriter(out, fieldnames=list(raw.keys()))
                    writer.writeheader()
                writer.writerow(raw)
                key = integer(raw.get("GeographyKey"))
                if key is None:
                    continue
                geos.append({
                    "k": key,
                    "city": clean(raw.get("City")),
                    "state": clean(raw.get("StateProvinceName")),
                    "country": clean(raw.get("EnglishCountryRegionName")),
                })
        geos.sort(key=lambda g: g["k"])

        customers: list[dict] = []
        with (DATA_DIR / "DimCustomer.csv").open("w", newline="", encoding="utf-8-sig") as out:
            writer = None
            for raw in iter_rows(z, targets["DimCustomer"], shared):
                if writer is None:
                    writer = csv.DictWriter(out, fieldnames=list(raw.keys()))
                    writer.writeheader()
                writer.writerow(raw)
                key = integer(raw.get("CustomerKey"))
                if key is None:
                    continue
                first = clean(raw.get("FirstName"))
                last = clean(raw.get("LastName"))
                customers.append({
                    "k": key,
                    "alt": clean(raw.get("CustomerAlternateKey")),
                    "n": f"{first} {last}".strip() or clean(raw.get("CustomerAlternateKey")),
                    "gender": clean(raw.get("Gender")),
                    "income": integer(raw.get("YearlyIncome")) or 0,
                    "education": clean(raw.get("EnglishEducation")) or "Unspecified",
                    "geo": integer(raw.get("GeographyKey")),
                })
        customers.sort(key=lambda c: c["k"])

        territories: list[dict] = []
        with (DATA_DIR / "DimSalesTerritory.csv").open("w", newline="", encoding="utf-8-sig") as out:
            writer = None
            for raw in iter_rows(z, targets["DimSalesTerritory"], shared):
                if writer is None:
                    writer = csv.DictWriter(out, fieldnames=list(raw.keys()))
                    writer.writeheader()
                writer.writerow(raw)
                key = integer(raw.get("SalesTerritoryKey"))
                if key is None:
                    continue
                group = clean(raw.get("SalesTerritoryGroup"))
                territories.append({
                    "k": key,
                    "region": clean(raw.get("SalesTerritoryRegion")),
                    "country": clean(raw.get("SalesTerritoryCountry")),
                    "group": "North America" if group == "NA" else group,
                })
        territories.sort(key=lambda t: t["k"])

        # DimDate is exported for validation only; v1 uses a generated date table.
        with (DATA_DIR / "DimDate.csv").open("w", newline="", encoding="utf-8-sig") as out:
            writer = None
            for raw in iter_rows(z, targets["DimDate"], shared):
                if writer is None:
                    writer = csv.DictWriter(out, fieldnames=list(raw.keys()))
                    writer.writeheader()
                writer.writerow(raw)

        # ---------------- fact ----------------
        prod_idx = {p["k"]: i for i, p in enumerate(products)}
        cust_idx = {c["k"]: i for i, c in enumerate(customers)}
        terr_idx = {t["k"]: i for i, t in enumerate(territories)}
        order_idx: dict[str, int] = {}
        orders: list[str] = []
        fact: list[list] = []

        with (DATA_DIR / "FactInternetSales.csv").open("w", newline="", encoding="utf-8-sig") as out:
            writer = None
            for raw in iter_rows(z, targets["FactInternetSales"], shared):
                if writer is None:
                    writer = csv.DictWriter(out, fieldnames=list(raw.keys()))
                    writer.writeheader()
                writer.writerow(raw)

                order_date = serial_to_date(raw.get("OrderDate"))
                if order_date is None:
                    continue
                d = (order_date - PERIOD_START).days
                if not 0 <= d <= (PERIOD_END - PERIOD_START).days:
                    raise SystemExit(f"OrderDate outside 2021-2022: {order_date}")

                product_key = integer(raw.get("ProductKey"))
                customer_key = integer(raw.get("CustomerKey"))
                territory_key = integer(raw.get("SalesTerritoryKey"))
                if product_key not in prod_idx or customer_key not in cust_idx or territory_key not in terr_idx:
                    raise SystemExit(
                        f"Unresolved key: product={product_key} customer={customer_key} territory={territory_key}"
                    )

                qty = number(raw.get("OrderQuantity")) or 0.0
                price = number(raw.get("SalesAmount")) or 0.0
                cost = number(raw.get("TotalProductCost")) or 0.0
                freight = (number(raw.get("Freight")) or 0.0) * qty
                order_no = clean(raw.get("SalesOrderNumber"))
                if order_no not in order_idx:
                    order_idx[order_no] = len(orders)
                    orders.append(order_no)

                # Fulfillment uses the *key* timeline (2005-2008); the display
                # dates are re-based and distort shipping intervals.
                key_order = key_to_date(raw.get("OrderDateKey"))
                key_due = key_to_date(raw.get("DueDateKey"))
                key_ship = key_to_date(raw.get("ShipDateKey"))
                lead_days = (key_ship - key_order).days if key_order and key_ship else 0
                late_days = max(0, (key_ship - key_due).days) if key_due and key_ship else 0

                fact.append([
                    d,
                    prod_idx[product_key],
                    cust_idx[customer_key],
                    terr_idx[territory_key],
                    order_idx[order_no],
                    qty,
                    price,
                    cost,
                    price * qty,
                    (price - cost) * qty,
                    freight,
                    lead_days,
                    late_days,
                    int(raw.get("SalesOrderLineNumber") or 0),
                ])

    fact.sort(key=lambda r: (r[0], r[4]))
    dates = [(PERIOD_START + timedelta(days=i)).isoformat() for i in range((PERIOD_END - PERIOD_START).days + 1)]

    months = []
    cursor = PERIOD_START.replace(day=1)
    while cursor <= PERIOD_END:
        nxt = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        months.append({
            "key": cursor.strftime("%Y-%m"),
            "label": cursor.strftime("%b %Y"),
            "short": cursor.strftime("%b %y"),
            "start": (cursor - PERIOD_START).days,
            "end": (min(nxt, PERIOD_END + timedelta(days=1)) - PERIOD_START).days - 1,
        })
        cursor = nxt

    revenue = sum(r[8] for r in fact)
    profit = sum(r[9] for r in fact)
    units = sum(r[5] for r in fact)
    freight_total = sum(r[10] for r in fact)
    order_count = len({r[4] for r in fact})
    customer_orders: dict[int, set[int]] = {}
    for r in fact:
        customer_orders.setdefault(r[2], set()).add(r[4])
    repeat = sum(1 for s in customer_orders.values() if len(s) >= 2)
    sold_products = len({r[1] for r in fact})
    avg_lead = sum(r[11] for r in fact) / len(fact)
    late_lines = sum(1 for r in fact if r[12] > 0)

    payload = {
        "meta": {
            "source": XLSX.name,
            "generatedUtc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "periodStart": PERIOD_START.isoformat(),
            "periodEnd": PERIOD_END.isoformat(),
            "rows": len(fact),
            "orders": order_count,
            "customers": len(customers),
            "products": len(products),
            "soldProducts": sold_products,
            "revenue": round(revenue, 2),
            "profit": round(profit, 2),
            "units": round(units, 2),
            "freight": round(freight_total, 2),
            "repeatCustomers": repeat,
            "avgLeadDays": round(avg_lead, 2),
            "lateLines": late_lines,
        },
        "dates": dates,
        "months": months,
        "products": products,
        "customers": customers,
        "geos": geos,
        "territories": territories,
        "orders": orders,
        "fact": fact,
    }

    with (DASHBOARD / "data.js").open("w", encoding="utf-8") as fh:
        fh.write("window.AW=")
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")

    write_model_extracts(products, customers, geos, territories, orders, fact, dates)

    print(f"fact rows       {len(fact):,}")
    print(f"orders          {order_count:,}")
    print(f"customers       {len(customers):,}")
    print(f"products        {len(products):,} ({sold_products:,} sold)")
    print(f"revenue         {revenue:,.2f}")
    print(f"gross profit    {profit:,.2f}  ({profit / revenue * 100:.4f}%)")
    print(f"units           {units:,.0f}")
    print(f"repeat          {repeat:,}  ({repeat / len(customer_orders) * 100:.4f}%)")
    print(f"avg lead time   {avg_lead:.2f} days, late lines {late_lines:,}")
    print(f"data.js         {(DASHBOARD / 'data.js').stat().st_size / 1_048_576:.1f} MB")
    print(f"csv extracts    {DATA_DIR}")


def write_model_extracts(products, customers, geos, territories, orders, fact, dates) -> None:
    """Write curated, Power BI-ready extracts (derived from the read-only workbook)."""
    MODEL_DATA.mkdir(parents=True, exist_ok=True)
    geo_by_key = {g["k"]: g for g in geos}

    cust_revenue: dict[int, float] = {}
    cust_orders: dict[int, set[int]] = {}
    for row in fact:
        ci = row[2]
        cust_revenue[ci] = cust_revenue.get(ci, 0.0) + row[8]
        cust_orders.setdefault(ci, set()).add(row[4])

    with (MODEL_DATA / "FactInternetSalesModel.csv").open("w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow([
            "OrderDate", "OrderYear", "ProductKey", "CustomerKey", "SalesTerritoryKey",
            "SalesOrderNumber", "SalesOrderLineNumber", "OrderQuantity", "UnitPrice", "UnitCost", "LineRevenue",
            "LineProfit", "LineFreight", "LeadDays", "LateDays", "LeadBucket",
        ])
        for row in fact:
            order_date = dates[row[0]]
            w.writerow([
                order_date, order_date[:4], products[row[1]]["k"], customers[row[2]]["k"],
                territories[row[3]]["k"], orders[row[4]], int(row[13]), int(row[5]),
                f"{row[6]:.4f}", f"{row[7]:.4f}", f"{row[8]:.4f}", f"{row[9]:.4f}",
                f"{row[10]:.4f}", int(row[11]), int(row[12]), lead_bucket(int(row[11])),
            ])

    prod_revenue: dict[int, float] = {}
    for row in fact:
        prod_revenue[row[1]] = prod_revenue.get(row[1], 0.0) + row[8]
    prod_order = sorted(prod_revenue, key=lambda i: prod_revenue[i], reverse=True)
    prod_tier: dict[int, str] = {
        pi: ("Top 10" if rank <= 10 else ("Top 25" if rank <= 25 else "Other"))
        for rank, pi in enumerate(prod_order, 1)
    }

    cust_order = sorted(cust_revenue, key=lambda i: cust_revenue[i], reverse=True)
    cust_tier: dict[int, str] = {
        ci: ("Top 10" if rank <= 10 else ("Top 50" if rank <= 50 else "Other"))
        for rank, ci in enumerate(cust_order, 1)
    }

    with (MODEL_DATA / "DimProductModel.csv").open("w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow([
            "ProductKey", "ProductAlternateKey", "ProductName", "ProductLine", "ModelName",
            "Color", "Size", "SubcategoryKey", "StandardCost", "ListPrice", "SellerTier",
        ])
        for pi, p in enumerate(products):
            w.writerow([
                p["k"], p["alt"], p["n"], p["line"], p["model"], p["color"], p["size"],
                "" if p["sub"] is None else p["sub"], f"{p['cost']:.4f}", f"{p['price']:.4f}",
                prod_tier.get(pi, "No sales"),
            ])

    with (MODEL_DATA / "DimCustomerModel.csv").open("w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow([
            "CustomerKey", "CustomerAlternateKey", "CustomerName", "Gender", "YearlyIncome",
            "IncomeBand", "Education", "GeographyKey", "City", "StateProvince", "Country",
            "LifetimeRevenue", "LifetimeOrders", "RepeatCustomer", "RevenueBand", "CustomerTier",
        ])
        for ci, c in enumerate(customers):
            g = geo_by_key.get(c["geo"], {})
            revenue = cust_revenue.get(ci, 0.0)
            order_count = len(cust_orders.get(ci, set()))
            w.writerow([
                c["k"], c["alt"], c["n"], c["gender"], c["income"], income_band(c["income"]),
                c["education"], c["geo"], g.get("city", ""), g.get("state", ""),
                g.get("country", ""), f"{revenue:.4f}", order_count,
                "Yes" if order_count >= 2 else "No", revenue_band(revenue),
                cust_tier.get(ci, "Other"),
            ])

    with (MODEL_DATA / "DimGeographyModel.csv").open("w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["GeographyKey", "City", "StateProvince", "Country"])
        for g in geos:
            w.writerow([g["k"], g["city"], g["state"], g["country"]])

    with (MODEL_DATA / "DimSalesTerritoryModel.csv").open("w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["SalesTerritoryKey", "Region", "Country", "TerritoryGroup"])
        for t in territories:
            w.writerow([t["k"], t["region"], t["country"], t["group"]])

    print(f"model extracts  {MODEL_DATA}")


if __name__ == "__main__":
    main()
