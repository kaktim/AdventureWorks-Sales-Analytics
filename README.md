# AdventureWorks Sales Analytics

For the complete report guide, see [AdventureWorks Report: End-to-End Documentation](./AdventureWorks_Report_End-to-End_Documentation.md).

An interactive Power BI report for exploring AdventureWorks Internet Sales across revenue, profit,
customers, products, territories, and order fulfillment. This repository also documents an **Azure SQL
Database integration path** and includes a sample T-SQL query that reproduces the report's core sales
aggregations.

> **Data-source note:** The delivered `AdventureWorks Sales.pbix` currently contains an imported model
> built from the supplied AdventureWorks workbook and curated extracts. It is **not currently connected
> to a live Azure SQL Database**. The Azure SQL section below shows how to stage the same source data in
> Azure SQL and connect Power BI for a SQL-backed deployment.

## Project at a glance

| Item | Details |
|---|---|
| Report | Power BI Desktop (`.pbix`) |
| Reporting period | January 2021–December 2022 display timeline |
| Fact grain | One row per sales order line (`SalesOrderNumber` + `SalesOrderLineNumber`) |
| Order lines | 60,398 |
| Units | 631,920 |
| Revenue | **$307,092,945.20** |
| Gross profit | **$126,290,577.65** |
| Gross margin | **41.12%** |
| Orders / customers | 27,659 / 18,484 |
| Azure platform reference | Azure SQL Database → Power BI |

## Report pages

The report has five user-facing analysis pages, plus helper tooltip and drill-through pages.

| Page | What it answers |
|---|---|
| **Overview** | How are revenue and gross profit trending? Which territory groups, countries, and product lines lead? |
| **Profitability** | How do profit, margin, product costs, and freight affect results? Includes a profit bridge. |
| **Customers** | How do repeat behavior, income segments, and customer concentration contribute to sales? Includes Pareto analysis. |
| **Geography** | Which territories and countries contribute revenue and profit? Includes an Azure Maps visual. |
| **Detail** | Which order lines make up the totals? Includes lead-time KPIs and a sortable line-level table. |

Report-wide features include a 2021–2022 date range, period presets, product/territory/customer filters,
reset controls, cross-filtering, branded navigation, and green/red conditional formatting for selected
table metrics.

## Business measures

Amounts in the source workbook are **per unit**, so revenue and cost must be multiplied by quantity.
The semantic model uses the equivalent normalized fields `UnitPrice` and `UnitCost`:

```DAX
Revenue =
    SUMX (
        FactInternetSales,
        FactInternetSales[UnitPrice] * FactInternetSales[OrderQuantity]
    )

Gross Profit =
    SUMX (
        FactInternetSales,
        ( FactInternetSales[UnitPrice] - FactInternetSales[UnitCost] )
            * FactInternetSales[OrderQuantity]
    )

Gross Margin % = DIVIDE ( [Gross Profit], [Revenue] )
```

Do not use `SUM(SalesAmount)` as revenue on the raw workbook: it would omit the quantity multiplier.
The curated model also includes order, customer, unit, freight, lead-time, and year-over-year measures.

## Azure SQL Database integration

### Reference architecture

For a SQL-backed deployment, load the fact and dimension data into an Azure SQL Database, then connect
Power BI using the **Azure SQL Database** connector. Use a least-privilege database identity and keep
credentials in Power BI/Fabric connection settings—not in this repository or in a SQL script.

The query below assumes the workbook has been staged in Azure SQL with these table names:

- `dbo.FactInternetSales`
- `dbo.DimProduct`
- `dbo.DimSalesTerritory`

The workbook's fact sheet is an Excel Table named `Table2`; it can be renamed to
`dbo.FactInternetSales` during staging. The date columns in the fact rows use the report's 2021–2022
display timeline. The legacy numeric date keys point to an older 2005–2010 calendar and should not be
used to join the shifted display dates.

### Azure SQL report query

This Azure SQL (T-SQL) query groups sales by month, territory group, and product line. It computes
line revenue and product cost using the workbook's per-unit amounts and `OrderQuantity`.

```sql
-- Run in the AdventureWorks sales database in Azure SQL Database.
WITH SalesLines AS
(
    SELECT
        CAST(f.OrderDate AS date) AS OrderDate,
        f.SalesOrderNumber,
        f.SalesOrderLineNumber,
        f.OrderQuantity,
        t.TerritoryGroup,
        t.Country AS TerritoryCountry,
        p.ProductLine,
        CAST(f.SalesAmount AS decimal(19, 4))
            * CAST(f.OrderQuantity AS decimal(19, 4)) AS LineRevenue,
        CAST(f.TotalProductCost AS decimal(19, 4))
            * CAST(f.OrderQuantity AS decimal(19, 4)) AS LineProductCost
    FROM dbo.FactInternetSales AS f
    LEFT JOIN dbo.DimProduct AS p
        ON p.ProductKey = f.ProductKey
    LEFT JOIN dbo.DimSalesTerritory AS t
        ON t.SalesTerritoryKey = f.SalesTerritoryKey
    WHERE f.OrderDate >= '2021-01-01'
      AND f.OrderDate <  '2023-01-01'
),
MonthlySales AS
(
    SELECT
        DATEFROMPARTS(YEAR(OrderDate), MONTH(OrderDate), 1) AS SalesMonth,
        TerritoryGroup,
        TerritoryCountry,
        ProductLine,
        SalesOrderNumber,
        SalesOrderLineNumber,
        OrderQuantity,
        LineRevenue,
        LineProductCost
    FROM SalesLines
)
SELECT
    SalesMonth,
    TerritoryGroup,
    TerritoryCountry,
    ProductLine,
    COUNT(DISTINCT SalesOrderNumber) AS Orders,
    COUNT_BIG(*) AS OrderLines,
    SUM(CAST(OrderQuantity AS bigint)) AS Units,
    SUM(LineRevenue) AS Revenue,
    SUM(LineProductCost) AS ProductCost,
    SUM(LineRevenue - LineProductCost) AS GrossProfit,
    CAST(
        SUM(LineRevenue - LineProductCost)
        / NULLIF(SUM(LineRevenue), 0)
        AS decimal(9, 4)
    ) AS GrossMargin
FROM MonthlySales
GROUP BY
    SalesMonth,
    TerritoryGroup,
    TerritoryCountry,
    ProductLine
ORDER BY
    SalesMonth,
    TerritoryGroup,
    TerritoryCountry,
ProductLine;
```

`GrossMargin` is returned as a ratio (for example, `0.4112`); format it as a percentage in Power BI.

**Expected use:** connect Power BI to the Azure SQL server (`<server>.database.windows.net`) and
database, authenticate with an approved identity, and choose Import or DirectQuery according to the
deployment's refresh and latency requirements. The query is an example aggregation; the report's
interactive slicers are normally backed by the underlying fact and dimension tables rather than by a
single pre-aggregated result.

## Data model and important assumptions

The model contains the internet sales fact, date, product, customer, geography, territory, and period
preset tables. Territory reporting uses the fact's `SalesTerritoryKey` path; country analysis uses the
customer/geography path. Avoid combining both territory paths in one visual, which can create ambiguous
filtering.

Important source-data caveats:

- **Two date timelines:** `OrderDate` values are shifted to 2021–2022 for display, while the numeric
  date keys refer to the original 2005–2008 sales dates. Use the display dates for this report's
  2021–2022 analysis; do not relate them to the workbook's legacy `DimDate` dates.
- **Per-unit amounts:** `SalesAmount`, `ExtendedAmount`, `TaxAmt`, `Freight`, and `TotalProductCost`
  are per-unit in the workbook. Multiply by `OrderQuantity` for line-level totals.
- **Missing lookup tables:** the workbook does not include product subcategory, promotion, or currency
  dimensions/exchange rates. Those keys are not given invented labels or conversions.
- **Territory filter paths:** use one territory relationship path per visual to avoid ambiguity.
- **Workbook is read-only:** derived reports and extracts must not be written back into
  `AdventureWorksDW.xlsx`.

## Repository contents

| Path | Purpose |
|---|---|
| `AdventureWorks Sales.pbix` | Primary Power BI deliverable |
| `AdventureWorksDW.xlsx` | Read-only source workbook |
| `build/` | Data-preparation and report/model build scripts |
| `dashboard/` | Static HTML dashboard and generated data |
| `powerbi/model_data/` | Curated CSV extracts |
| `pbi/` | PBIP/TMDL/PBIR editable project source |
| `README.md` / `README.docx` | GitHub and Word documentation |

The `.pbix` is the ready-to-open report. Before refreshing or rebuilding the PBIP project on another
machine, review the local file paths in its Power Query partitions and point them to the repository's
`powerbi/model_data/` files or to the Azure SQL database.

## Open and use

1. Download or clone the repository.
2. Open `AdventureWorks Sales.pbix` in Power BI Desktop.
3. Use the navigation and filter bar to explore dates, customer/product segments, and territories.
4. To use Azure SQL, stage the schema, configure credentials securely, and update the Power BI
   data-source connection.

The optional static dashboard can be served locally from the repository root:

```powershell
python -m http.server 8765 --directory dashboard
```

Then visit `http://localhost:8765/` in a browser. Opening `dashboard/index.html` directly is also
supported.

## Rebuild notes

The repository includes Python build scripts and curated model extracts. Rebuilding or refreshing may
require updating machine-specific paths in the PBIP/TMDL partitions. The Excel workbook remains the
source of truth for the current imported snapshot; Azure SQL is the documented deployment option, not
a connection embedded in the delivered PBIX.

## Data use and attribution

This project uses AdventureWorks sample sales data for analytics and demonstration. Confirm the source
dataset's applicable license and redistribution terms before publishing source data or extracts to a
public GitHub repository. Never commit Azure SQL passwords, tokens, connection strings with secrets, or
personal credentials.
