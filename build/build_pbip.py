"""Generate the Power BI project (semantic model + PBIR report) for the workbook.

The project is opened by Power BI Desktop and then saved as a .pbix. All data is
imported from the curated CSV extracts in powerbi/model_data.

Run:  python build/build_pbip.py
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "pbi"
PROJECT = PBI / "AdventureWorks Internet Sales"
REPORT = PBI / "AdventureWorks Internet Sales.Report"
MODEL = PBI / "AdventureWorks Internet Sales.SemanticModel"
MODEL_DATA = ROOT / "powerbi" / "model_data"

TAB = "\t"


def tag() -> str:
    return str(uuid.uuid4())


def csv_path(name: str) -> str:
    return str(MODEL_DATA / name)


def m_source(filename: str, columns: int, types: list[tuple[str, str]]) -> str:
    type_list = ", ".join(f'{{"{name}", {kind}}}' for name, kind in types)
    return (
        "let\n"
        f'    Source = Csv.Document(File.Contents("{csv_path(filename)}"), [Delimiter = ",", Columns = {columns}, Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),\n'
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),\n"
        f"    Typed = Table.TransformColumnTypes(Promoted, {{{type_list}}})\n"
        "in\n"
        "    Typed"
    )


DATE_M = """let
    StartDate = #date(2021, 1, 1),
    EndDate = #date(2022, 12, 31),
    DayCount = Duration.Days(EndDate - StartDate) + 1,
    DateList = List.Dates(StartDate, DayCount, #duration(1, 0, 0, 0)),
    DateTable = Table.FromList(DateList, Splitter.SplitByNothing(), {"Date"}, null, ExtraValues.Error),
    TypedDate = Table.TransformColumnTypes(DateTable, {{"Date", type date}}),
    AddedYear = Table.AddColumn(TypedDate, "Year", each Date.Year([Date]), Int64.Type),
    AddedQuarterNumber = Table.AddColumn(AddedYear, "QuarterNumber", each Date.QuarterOfYear([Date]), Int64.Type),
    AddedQuarter = Table.AddColumn(AddedQuarterNumber, "Quarter", each "Q" & Text.From(Date.QuarterOfYear([Date])), type text),
    AddedMonthNumber = Table.AddColumn(AddedQuarter, "MonthNumber", each Date.Month([Date]), Int64.Type),
    AddedMonth = Table.AddColumn(AddedMonthNumber, "Month", each Date.ToText([Date], "MMM"), type text),
    AddedMonthKey = Table.AddColumn(AddedMonth, "MonthKey", each Date.Year([Date]) * 100 + Date.Month([Date]), Int64.Type),
    AddedMonthYear = Table.AddColumn(AddedMonthKey, "MonthYear", each Date.ToText([Date], "MMM yyyy"), type text),
    AddedYearMonth = Table.AddColumn(AddedMonthYear, "YearMonth", each Date.ToText([Date], "yyyy-MM"), type text),
    AddedDayOfWeek = Table.AddColumn(AddedYearMonth, "DayOfWeek", each Date.DayOfWeek([Date], Day.Monday) + 1, Int64.Type),
    AddedDayName = Table.AddColumn(AddedDayOfWeek, "DayName", each Date.ToText([Date], "ddd"), type text),
    AddedIsWeekend = Table.AddColumn(AddedDayName, "IsWeekend", each Date.DayOfWeek([Date], Day.Monday) >= 5, type logical)
in
    AddedIsWeekend"""


PRESET_M = """let
    StartDate = #date(2021, 1, 1),
    EndDate = #date(2022, 12, 31),
    DayCount = Duration.Days(EndDate - StartDate) + 1,
    DateList = List.Dates(StartDate, DayCount, #duration(1, 0, 0, 0)),
    AllDates = List.Transform(DateList, each [Preset = "All", PresetOrder = 0, Date = _]),
    YearDates = List.Transform(DateList, each [Preset = Text.From(Date.Year(_)), PresetOrder = Date.Year(_) - 2020, Date = _]),
    HalfDates = List.Transform(List.Select(DateList, each Date.Year(_) = 2022 and Date.Month(_) >= 7), each [Preset = "H2 2022", PresetOrder = 3, Date = _]),
    Combined = Table.FromRecords(AllDates & YearDates & HalfDates),
    Typed = Table.TransformColumnTypes(Combined, {{"Preset", type text}, {"PresetOrder", Int64.Type}, {"Date", type date}})
in
    Typed"""


def column_tmdl(
    name: str,
    dtype: str,
    source: str,
    *,
    summarize: str = "none",
    fmt: str | None = None,
    hidden: bool = False,
    sort_by: str | None = None,
    is_key: bool = False,
) -> str:
    lines = [f"{TAB}column {tmdl_name(name)}"]
    lines.append(f"{TAB * 2}dataType: {dtype}")
    if fmt:
        lines.append(f"{TAB * 2}formatString: {fmt}")
    if is_key:
        lines.append(f"{TAB * 2}isKey")
    if hidden:
        lines.append(f"{TAB * 2}isHidden")
    lines.append(f"{TAB * 2}summarizeBy: {summarize}")
    if sort_by:
        lines.append(f"{TAB * 2}sortByColumn: {sort_by}")
    lines.append(f"{TAB * 2}sourceColumn: {source}")
    lines.append(f"{TAB * 2}lineageTag: {tag()}")
    lines.append("")
    return "\n".join(lines)


def tmdl_name(name: str) -> str:
    """TMDL identifiers must be quoted when they contain spaces/symbols."""
    if name and all(ch.isalnum() or ch == "_" for ch in name):
        return name
    return "'" + name.replace("'", "''") + "'"


def measure_tmdl(name: str, dax: str, fmt: str, folder: str) -> str:
    return (
        f"{TAB}measure {tmdl_name(name)} = {dax}\n"
        f"{TAB * 2}formatString: {fmt}\n"
        f"{TAB * 2}displayFolder: {folder}\n"
        f"{TAB * 2}lineageTag: {tag()}\n"
    )


def money_text(expr: str) -> str:
    """DAX that renders a money measure exactly like dashboard/app.js money()."""
    return (
        f"VAR v = {expr} "
        f"VAR a = ABS(v) "
        'RETURN "$" & SWITCH(TRUE(), '
        'a >= 1000000000, FORMAT(v / 1000000000, "0.00") & "B", '
        'a >= 1000000, FORMAT(v / 1000000, "0.00") & "M", '
        'a >= 1000, FORMAT(v / 1000, "0.0") & "K", '
        'FORMAT(ROUND(v, 0), "#,##0"))'
    )


def table_tmdl(name: str, columns: list[str], partition_m: str, measures: list[str],
               *, data_category: str | None = None, description: str | None = None) -> str:
    out = [f"table {tmdl_name(name)}"]
    if data_category:
        out.append(f"{TAB}dataCategory: {data_category}")
    if description:
        out.append(f"{TAB}description: {description}")
    out.append(f"{TAB}lineageTag: {tag()}")
    out.append("")
    out.extend(columns)
    out.append(f"{TAB}partition {tmdl_name(name)} = m")
    out.append(f"{TAB * 2}mode: import")
    out.append(f"{TAB * 2}source =")
    for line in partition_m.splitlines():
        out.append(f"{TAB * 4}{line}" if line else "")
    out.append("")
    out.append(f"{TAB}annotation PBI_ResultType = Table")
    out.append("")
    if measures:
        out.extend(measures)
        out.append("")
    return "\n".join(out)


def build_model() -> None:
    if (MODEL / "definition").exists():
        shutil.rmtree(MODEL / "definition")
    (MODEL / "definition" / "tables").mkdir(parents=True)
    (MODEL / "definition" / "cultures").mkdir(parents=True)

    (MODEL / "definition" / "database.tmdl").write_text(
        "database\n\tcompatibilityLevel: 1606\n", encoding="utf-8"
    )
    (MODEL / "definition" / "model.tmdl").write_text(
        "model Model\n"
        "\tculture: en-US\n"
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
        "\tsourceQueryCulture: en-US\n"
        "\tvalueFilterBehavior: independent\n"
        "\tdataAccessOptions\n"
        "\t\tlegacyRedirects\n"
        "\t\treturnErrorValuesAsNull\n"
        "\n"
        "annotation __PBI_TimeIntelligenceEnabled = 1\n"
        "\n"
        "annotation PBI_ProTooling = [\"DevMode\"]\n"
        "\n"
        "ref cultureInfo en-US\n",
        encoding="utf-8",
    )
    (MODEL / "definition" / "cultures" / "en-US.tmdl").write_text(
        "cultureInfo en-US\n", encoding="utf-8"
    )

    # ---------- DimDate ----------
    date_cols = [
        column_tmdl("Date", "dateTime", "Date", fmt="yyyy-mm-dd", is_key=True),
        column_tmdl("Year", "int64", "Year", fmt="0"),
        column_tmdl("Quarter", "string", "Quarter"),
        column_tmdl("QuarterNumber", "int64", "QuarterNumber", fmt="0", hidden=True),
        column_tmdl("Month", "string", "Month", sort_by="MonthNumber"),
        column_tmdl("MonthNumber", "int64", "MonthNumber", fmt="0", hidden=True),
        column_tmdl("MonthKey", "int64", "MonthKey", fmt="0", hidden=True),
        column_tmdl("MonthYear", "string", "MonthYear", sort_by="MonthKey"),
        column_tmdl("YearMonth", "string", "YearMonth", sort_by="MonthKey", hidden=True),
        column_tmdl("DayOfWeek", "int64", "DayOfWeek", fmt="0", hidden=True),
        column_tmdl("DayName", "string", "DayName", sort_by="DayOfWeek"),
        column_tmdl("IsWeekend", "boolean", "IsWeekend", hidden=True),
    ]
    (MODEL / "definition" / "tables" / "DimDate.tmdl").write_text(
        table_tmdl("DimDate", date_cols, DATE_M, [], data_category="Time",
                   description=None),
        encoding="utf-8",
    )

    # ---------- DimProduct ----------
    product_cols = [
        column_tmdl("ProductKey", "int64", "ProductKey", fmt="0", hidden=True, is_key=True),
        column_tmdl("ProductAlternateKey", "string", "ProductAlternateKey", hidden=True),
        column_tmdl("ProductName", "string", "ProductName"),
        column_tmdl("ProductLine", "string", "ProductLine"),
        column_tmdl("ModelName", "string", "ModelName"),
        column_tmdl("Color", "string", "Color"),
        column_tmdl("Size", "string", "Size"),
        column_tmdl("SubcategoryKey", "int64", "SubcategoryKey", fmt="0", hidden=True),
        column_tmdl("StandardCost", "double", "StandardCost", fmt="#,0.0000", hidden=True),
        column_tmdl("ListPrice", "double", "ListPrice", fmt="#,0.0000", hidden=True),
        column_tmdl("SellerTier", "string", "SellerTier"),
    ]
    product_m = m_source("DimProductModel.csv", 11, [
        ("ProductKey", "Int64.Type"), ("ProductAlternateKey", "type text"),
        ("ProductName", "type text"), ("ProductLine", "type text"),
        ("ModelName", "type text"), ("Color", "type text"), ("Size", "type text"),
        ("SubcategoryKey", "Int64.Type"), ("StandardCost", "type number"),
        ("ListPrice", "type number"), ("SellerTier", "type text"),
    ])
    (MODEL / "definition" / "tables" / "DimProduct.tmdl").write_text(
        table_tmdl("DimProduct", product_cols, product_m, []), encoding="utf-8"
    )

    # ---------- DimGeography ----------
    geo_cols = [
        column_tmdl("GeographyKey", "int64", "GeographyKey", fmt="0", hidden=True, is_key=True),
        column_tmdl("City", "string", "City"),
        column_tmdl("StateProvince", "string", "StateProvince"),
        column_tmdl("GeographyCountry", "string", "Country"),
    ]
    geo_m = m_source("DimGeographyModel.csv", 4, [
        ("GeographyKey", "Int64.Type"), ("City", "type text"),
        ("StateProvince", "type text"), ("Country", "type text"),
    ])
    (MODEL / "definition" / "tables" / "DimGeography.tmdl").write_text(
        table_tmdl("DimGeography", geo_cols, geo_m, []), encoding="utf-8"
    )

    # ---------- DimCustomer ----------
    customer_cols = [
        column_tmdl("CustomerKey", "int64", "CustomerKey", fmt="0", hidden=True, is_key=True),
        column_tmdl("CustomerAlternateKey", "string", "CustomerAlternateKey", hidden=True),
        column_tmdl("CustomerName", "string", "CustomerName"),
        column_tmdl("Gender", "string", "Gender"),
        column_tmdl("YearlyIncome", "int64", "YearlyIncome", fmt="#,0", hidden=True),
        column_tmdl("IncomeBand", "string", "IncomeBand"),
        column_tmdl("Education", "string", "Education"),
        column_tmdl("GeographyKey", "int64", "GeographyKey", fmt="0", hidden=True),
        column_tmdl("City", "string", "City"),
        column_tmdl("StateProvince", "string", "StateProvince"),
        column_tmdl("Customer Country", "string", "Country"),
        column_tmdl("LifetimeRevenue", "double", "LifetimeRevenue", fmt="#,0.00", hidden=True),
        column_tmdl("LifetimeOrders", "int64", "LifetimeOrders", fmt="0", hidden=True),
        column_tmdl("RepeatCustomer", "string", "RepeatCustomer"),
        column_tmdl("RevenueBand", "string", "RevenueBand"),
        column_tmdl("CustomerTier", "string", "CustomerTier"),
    ]
    customer_m = m_source("DimCustomerModel.csv", 16, [
        ("CustomerKey", "Int64.Type"), ("CustomerAlternateKey", "type text"),
        ("CustomerName", "type text"), ("Gender", "type text"),
        ("YearlyIncome", "Int64.Type"), ("IncomeBand", "type text"),
        ("Education", "type text"), ("GeographyKey", "Int64.Type"),
        ("City", "type text"), ("StateProvince", "type text"), ("Country", "type text"),
        ("LifetimeRevenue", "type number"), ("LifetimeOrders", "Int64.Type"),
        ("RepeatCustomer", "type text"), ("RevenueBand", "type text"), ("CustomerTier", "type text"),
    ])
    (MODEL / "definition" / "tables" / "DimCustomer.tmdl").write_text(
        table_tmdl("DimCustomer", customer_cols, customer_m, []), encoding="utf-8"
    )

    # ---------- DimSalesTerritory ----------
    territory_cols = [
        column_tmdl("SalesTerritoryKey", "int64", "SalesTerritoryKey", fmt="0", hidden=True, is_key=True),
        column_tmdl("TerritoryRegion", "string", "Region"),
        column_tmdl("TerritoryCountry", "string", "Country"),
        column_tmdl("TerritoryGroup", "string", "TerritoryGroup"),
    ]
    territory_m = m_source("DimSalesTerritoryModel.csv", 4, [
        ("SalesTerritoryKey", "Int64.Type"), ("Region", "type text"),
        ("Country", "type text"), ("TerritoryGroup", "type text"),
    ])
    (MODEL / "definition" / "tables" / "DimSalesTerritory.tmdl").write_text(
        table_tmdl("DimSalesTerritory", territory_cols, territory_m, []), encoding="utf-8"
    )

    # ---------- Period Preset (drives the web-style period segmented control) ----------
    preset_cols = [
        column_tmdl("Preset", "string", "Preset", sort_by="PresetOrder"),
        column_tmdl("PresetOrder", "int64", "PresetOrder", fmt="0", hidden=True),
        column_tmdl("Date", "dateTime", "Date", fmt="yyyy-mm-dd", hidden=True),
    ]
    (MODEL / "definition" / "tables" / "Period Preset.tmdl").write_text(
        table_tmdl(
            "Period Preset",
            preset_cols,
            PRESET_M,
            [],
        ),
        encoding="utf-8",
    )

    # ---------- FactInternetSales ----------
    fact_cols = [
        column_tmdl("OrderDate", "dateTime", "OrderDate", fmt="yyyy-mm-dd"),
        column_tmdl("OrderYear", "int64", "OrderYear", fmt="0", hidden=True),
        column_tmdl("ProductKey", "int64", "ProductKey", fmt="0", hidden=True),
        column_tmdl("CustomerKey", "int64", "CustomerKey", fmt="0", hidden=True),
        column_tmdl("SalesTerritoryKey", "int64", "SalesTerritoryKey", fmt="0", hidden=True),
        column_tmdl("SalesOrderNumber", "string", "SalesOrderNumber"),
        column_tmdl("SalesOrderLineNumber", "int64", "SalesOrderLineNumber", fmt="0"),
        column_tmdl("OrderQuantity", "int64", "OrderQuantity", fmt="#,0"),
        column_tmdl("UnitPrice", "double", "UnitPrice", fmt="#,0.0000", hidden=True),
        column_tmdl("UnitCost", "double", "UnitCost", fmt="#,0.0000", hidden=True),
        column_tmdl("LineRevenue", "double", "LineRevenue", fmt="#,0.00", hidden=True),
        column_tmdl("LineProfit", "double", "LineProfit", fmt="#,0.00", hidden=True),
        column_tmdl("LineFreight", "double", "LineFreight", fmt="#,0.00", hidden=True),
        column_tmdl("LeadDays", "int64", "LeadDays", fmt="0"),
        column_tmdl("LateDays", "int64", "LateDays", fmt="0"),
        column_tmdl("LeadBucket", "string", "LeadBucket"),
    ]
    fact_m = m_source("FactInternetSalesModel.csv", 16, [
        ("OrderDate", "type date"), ("OrderYear", "Int64.Type"),
        ("ProductKey", "Int64.Type"), ("CustomerKey", "Int64.Type"),
        ("SalesTerritoryKey", "Int64.Type"), ("SalesOrderNumber", "type text"), ("SalesOrderLineNumber", "Int64.Type"),
        ("OrderQuantity", "Int64.Type"), ("UnitPrice", "type number"),
        ("UnitCost", "type number"), ("LineRevenue", "type number"),
        ("LineProfit", "type number"), ("LineFreight", "type number"),
        ("LeadDays", "Int64.Type"), ("LateDays", "Int64.Type"),
        ("LeadBucket", "type text"),
    ])

    measures = [
        measure_tmdl("Revenue", "SUMX(FactInternetSales, FactInternetSales[UnitPrice] * FactInternetSales[OrderQuantity])", "#,0.00", "01 Core"),
        measure_tmdl("Gross Profit", "SUMX(FactInternetSales, (FactInternetSales[UnitPrice] - FactInternetSales[UnitCost]) * FactInternetSales[OrderQuantity])", "#,0.00", "01 Core"),
        measure_tmdl("Gross Margin %", "DIVIDE([Gross Profit], [Revenue])", "0.00%", "01 Core"),
        measure_tmdl("Orders", "DISTINCTCOUNT(FactInternetSales[SalesOrderNumber])", "#,0", "01 Core"),
        measure_tmdl("Units", "SUM(FactInternetSales[OrderQuantity])", "#,0", "01 Core"),
        measure_tmdl("AOV", "DIVIDE([Revenue], [Orders])", "#,0.00", "01 Core"),
        measure_tmdl("Freight Cost", "SUM(FactInternetSales[LineFreight])", "#,0.00", "01 Core"),
        measure_tmdl("Freight % of Revenue", "DIVIDE([Freight Cost], [Revenue])", "0.00%", "01 Core"),
        measure_tmdl("Customers", "DISTINCTCOUNT(FactInternetSales[CustomerKey])", "#,0", "02 Customers"),
        measure_tmdl("Revenue per Customer", "DIVIDE([Revenue], [Customers])", "#,0.00", "02 Customers"),
        measure_tmdl("Orders per Customer", "DIVIDE([Orders], [Customers])", "0.00", "02 Customers"),
        measure_tmdl("Repeat Customers", "COUNTROWS(FILTER(SUMMARIZE(FactInternetSales, FactInternetSales[CustomerKey], \"OrderCount\", DISTINCTCOUNT(FactInternetSales[SalesOrderNumber])), [OrderCount] >= 2))", "#,0", "02 Customers"),
        measure_tmdl("Repeat Rate", "DIVIDE([Repeat Customers], [Customers])", "0.00%", "02 Customers"),
        measure_tmdl("Lines", "COUNTROWS(FactInternetSales)", "#,0", "03 Fulfillment"),
        measure_tmdl("Avg Lead Days", "AVERAGE(FactInternetSales[LeadDays])", "0.00", "03 Fulfillment"),
        measure_tmdl("Late Lines", "CALCULATE(COUNTROWS(FactInternetSales), KEEPFILTERS(FactInternetSales[LateDays] > 0)) + 0", "#,0", "03 Fulfillment"),
        measure_tmdl("Late Line Rate", "DIVIDE([Late Lines], [Lines], 0)", "0.00%", "03 Fulfillment"),
        measure_tmdl("Revenue PY", "CALCULATE([Revenue], SAMEPERIODLASTYEAR(DimDate[Date]))", "#,0.00", "04 Time intelligence"),
        measure_tmdl("Revenue YoY %", "DIVIDE([Revenue] - [Revenue PY], [Revenue PY])", "0.00%", "04 Time intelligence"),
        measure_tmdl("Gross Profit PY", "CALCULATE([Gross Profit], SAMEPERIODLASTYEAR(DimDate[Date]))", "#,0.00", "04 Time intelligence"),
        measure_tmdl("Margin PY", "CALCULATE([Gross Margin %], SAMEPERIODLASTYEAR(DimDate[Date]))", "0.00%", "04 Time intelligence"),
        measure_tmdl("Margin Change (pp)", "([Gross Margin %] - [Margin PY]) * 100", "0.00", "04 Time intelligence"),
        measure_tmdl("Selected Product", "IF(ISFILTERED(DimProduct[ProductName]), SELECTEDVALUE(DimProduct[ProductName], \"Multiple products\"), \"All products\")", "General", "05 Context"),
        measure_tmdl("Selected Customer", "IF(ISFILTERED(DimCustomer[CustomerName]), SELECTEDVALUE(DimCustomer[CustomerName], \"Multiple customers\"), \"All customers\")", "General", "05 Context"),
        measure_tmdl("Last Refresh (UTC)", "FORMAT(UTCNOW(), \"yyyy-mm-dd HH:mm\") & \" UTC\"", "General", "05 Context"),
        measure_tmdl("Data Through", "FORMAT(MAX(FactInternetSales[OrderDate]), \"yyyy-mm-dd\")", "General", "05 Context"),
        # ---- geography scope measures (dashboard parity) ----
        measure_tmdl("Countries", "COUNTROWS(SUMMARIZE(FactInternetSales, DimCustomer[Customer Country]))", "#,0", "06 Geography"),
        measure_tmdl("Territories", "DISTINCTCOUNT(FactInternetSales[SalesTerritoryKey])", "#,0", "06 Geography"),
        measure_tmdl("Territory Groups", "COUNTROWS(SUMMARIZE(FactInternetSales, DimSalesTerritory[TerritoryGroup]))", "#,0", "06 Geography"),
        # ---- KPI display values (mirror the web dashboard money/pct/int helpers) ----
        measure_tmdl("KPI Revenue", money_text("[Revenue]"), "General", "08 KPI values"),
        measure_tmdl("KPI Gross Profit", money_text("[Gross Profit]"), "General", "08 KPI values"),
        measure_tmdl("KPI Freight Cost", money_text("[Freight Cost]"), "General", "08 KPI values"),
        measure_tmdl("KPI Revenue per Customer", money_text("[Revenue per Customer]"), "General", "08 KPI values"),
        measure_tmdl("KPI Gross Profit per Customer", money_text("DIVIDE([Gross Profit], [Customers])"), "General", "08 KPI values"),
        measure_tmdl("KPI AOV", money_text("[AOV]"), "General", "08 KPI values"),
        measure_tmdl("KPI Gross Margin", "FORMAT([Gross Margin %], \"0.00%\")", "General", "08 KPI values"),
        measure_tmdl("KPI Repeat Rate", "FORMAT([Repeat Rate], \"0.00%\")", "General", "08 KPI values"),
        measure_tmdl("KPI Late Line Rate", "FORMAT([Late Line Rate], \"0.00%\")", "General", "08 KPI values"),
        measure_tmdl("KPI Orders", "FORMAT([Orders], \"#,##0\")", "General", "08 KPI values"),
        measure_tmdl("KPI Customers", "FORMAT([Customers], \"#,##0\")", "General", "08 KPI values"),
        measure_tmdl("KPI Territories", "FORMAT([Territories], \"#,##0\")", "General", "08 KPI values"),
        measure_tmdl("KPI Lines", "FORMAT([Lines], \"#,##0\")", "General", "08 KPI values"),
        measure_tmdl("KPI Units", "FORMAT([Units], \"#,##0\")", "General", "08 KPI values"),
        measure_tmdl("KPI Orders per Customer", "FORMAT([Orders per Customer], \"0.00\")", "General", "08 KPI values"),
        measure_tmdl("KPI Avg Lead", "FORMAT([Avg Lead Days], \"0.00\") & \" d\"", "General", "08 KPI values"),
        # ---- KPI sub-lines (one per card, mirrors the web dashboard) ----
        measure_tmdl("Sub Overview Revenue", "FORMAT([Units], \"#,##0\") & \" units \u00b7 \" & FORMAT([Orders], \"#,##0\") & \" orders\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Overview Gross Profit", "\"Margin \" & FORMAT([Gross Margin %], \"0.00%\")", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Overview Gross Margin", "\"Profit \u00f7 revenue, per-unit \u00d7 quantity\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Overview Orders", "\"AOV \" & [KPI AOV]", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Profitability Gross Profit", "\"Margin \" & FORMAT([Gross Margin %], \"0.00%\") & \" \u00b7 \" & FORMAT([Units], \"#,##0\") & \" units\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Profitability Gross Margin", "\"(Unit price - unit cost) \u00d7 quantity\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Profitability Revenue", "FORMAT([Lines], \"#,##0\") & \" order lines\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Profitability Freight", "FORMAT([Freight % of Revenue], \"0.00%\") & \" of revenue\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Customers Customers", "FORMAT([Customers], \"#,##0\") & \" distinct buyers \u00b7 \" & FORMAT([Orders], \"#,##0\") & \" orders\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Customers Repeat Rate", "FORMAT([Repeat Customers], \"#,##0\") & \" customers with 2+ orders\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Customers Revenue per Customer", "[KPI Gross Profit per Customer] & \" profit per customer\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Customers Orders per Customer", "\"AOV \" & [KPI AOV]", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Geography Revenue", "FORMAT([Lines], \"#,##0\") & \" lines across \" & FORMAT([Countries], \"#,##0\") & \" countries\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Geography Gross Margin", "[KPI Gross Profit] & \" gross profit\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Geography Territories", "FORMAT([Territory Groups], \"#,##0\") & \" territory groups\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Geography Orders", "\"AOV \" & [KPI AOV]", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Detail Lines", "\"Grain: order number + line number\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Detail Units", "\"Sum of OrderQuantity\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Detail Avg Lead", "\"Order date \u2192 ship date\"", "General", "07 KPI sub-lines"),
        measure_tmdl("Sub Detail Late", "FORMAT([Late Lines], \"#,##0\") & \" lines shipped after due date\"", "General", "07 KPI sub-lines"),
    ]
    (MODEL / "definition" / "tables" / "FactInternetSales.tmdl").write_text(
        table_tmdl("FactInternetSales", fact_cols, fact_m, measures), encoding="utf-8"
    )

    # ---------- relationships ----------
    # (name, from, to, cross-filter direction) — single direction always flows
    # from the "one" side to the "many" side, so a bridge table that must filter
    # a dimension (the period preset) has to be bidirectional.
    relationships = [
        ("FactInternetSales_DimDate", "FactInternetSales.OrderDate", "DimDate.Date", "oneDirection"),
        ("FactInternetSales_DimProduct", "FactInternetSales.ProductKey", "DimProduct.ProductKey", "oneDirection"),
        ("FactInternetSales_DimCustomer", "FactInternetSales.CustomerKey", "DimCustomer.CustomerKey", "oneDirection"),
        ("FactInternetSales_DimTerritory", "FactInternetSales.SalesTerritoryKey", "DimSalesTerritory.SalesTerritoryKey", "oneDirection"),
        ("DimCustomer_DimGeography", "DimCustomer.GeographyKey", "DimGeography.GeographyKey", "oneDirection"),
        ("PeriodPreset_DimDate", "'Period Preset'.Date", "DimDate.Date", "bothDirections"),
    ]
    rel_lines = []
    for name, frm, to, direction in relationships:
        rel_lines.extend([
            f"relationship {name}",
            f"{TAB}fromColumn: {frm}",
            f"{TAB}toColumn: {to}",
        ])
        # Only write the direction when it is not the default: touching the
        # other relationships makes Desktop demand a manual model refresh.
        if direction != "oneDirection":
            rel_lines.append(f"{TAB}crossFilteringBehavior: {direction}")
        rel_lines.append("")
    (MODEL / "definition" / "relationships.tmdl").write_text("\n".join(rel_lines), encoding="utf-8")

    # remove stale cache so Desktop rebuilds from TMDL
    cache = MODEL / ".pbi" / "cache.abf"
    if cache.exists():
        cache.unlink()

    print(f"model written: {MODEL / 'definition'}")


def main() -> None:
    build_model()


if __name__ == "__main__":
    main()

