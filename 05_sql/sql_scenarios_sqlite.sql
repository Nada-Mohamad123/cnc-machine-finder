-- READ-ONLY SQL scenarios for the machine tools database (SQLite version).
-- 34 queries. All statements are SELECT / WITH. No tables or records are modified.
-- Rebuilt from the Summary sheet of results_34.xlsx (the exact SQL that ran OK on machines.db).
-- Run:  python run_sql_scenarios_xlsx.py   (from the 05_sql folder, no arguments needed)

-- QUERY: 01 - Overall database and price coverage
SELECT
    COUNT(*) AS total_machines,
    COUNT(DISTINCT URL) AS unique_machine_urls,
    COUNT(price_mid_usd) AS machines_with_recorded_price,
    ROUND(100.0 * COUNT(price_mid_usd) / NULLIF(COUNT(*), 0), 2) AS price_coverage_pct,
    ROUND(AVG(price_mid_usd), 2) AS average_recorded_price_usd,
    MIN(price_mid_usd) AS lowest_recorded_midpoint_usd,
    MAX(price_mid_usd) AS highest_recorded_midpoint_usd
FROM machines;

-- QUERY: 02 - Machine counts and price coverage by category
SELECT
    Category,
    COUNT(*) AS machine_count,
    COUNT(price_mid_usd) AS priced_machine_count,
    ROUND(100.0 * COUNT(price_mid_usd) / NULLIF(COUNT(*), 0), 2) AS price_coverage_pct
FROM machines
GROUP BY Category
ORDER BY machine_count DESC;

-- QUERY: 03 - Price summary by category, including median
WITH priced AS (
    SELECT Category, price_mid_usd AS price_usd
    FROM machines
    WHERE price_mid_usd > 0
), ranked AS (
    SELECT
        Category,
        price_usd,
        ROW_NUMBER() OVER (PARTITION BY Category ORDER BY price_usd) AS rn,
        COUNT(*) OVER (PARTITION BY Category) AS n
    FROM priced
)
SELECT
    Category,
    COUNT(*) AS priced_machine_count,
    ROUND(AVG(price_usd), 2) AS average_price_usd,
    ROUND(AVG(CASE WHEN rn IN ((n + 1) / 2, (n + 2) / 2) THEN price_usd END), 2) AS median_price_usd,
    MIN(price_usd) AS min_price_usd,
    MAX(price_usd) AS max_price_usd
FROM ranked
GROUP BY Category
ORDER BY median_price_usd DESC;

-- QUERY: 04 - Manufacturers with the most machines and their price coverage
SELECT
    Manufacturer,
    COUNT(*) AS machine_count,
    COUNT(price_mid_usd) AS priced_machine_count,
    ROUND(100.0 * COUNT(price_mid_usd) / NULLIF(COUNT(*), 0), 2) AS price_coverage_pct,
    ROUND(AVG(price_mid_usd), 2) AS average_recorded_price_usd
FROM machines
GROUP BY Manufacturer
ORDER BY machine_count DESC
LIMIT 25;

-- QUERY: 05 - Manufacturers with many listings but weak price coverage
SELECT
    Manufacturer,
    COUNT(*) AS machine_count,
    COUNT(price_mid_usd) AS priced_machine_count,
    ROUND(100.0 * COUNT(price_mid_usd) / NULLIF(COUNT(*), 0), 2) AS price_coverage_pct
FROM machines
GROUP BY Manufacturer
HAVING COUNT(*) >= 20
ORDER BY price_coverage_pct ASC, machine_count DESC
LIMIT 30;

-- QUERY: 06 - Specification completeness by category
SELECT
    Category,
    COUNT(*) AS machine_count,
    COUNT(x_travel_mm) AS with_x_travel,
    ROUND(100.0 * COUNT(x_travel_mm) / NULLIF(COUNT(*), 0), 1) AS x_travel_coverage_pct,
    COUNT(y_travel_mm) AS with_y_travel,
    ROUND(100.0 * COUNT(y_travel_mm) / NULLIF(COUNT(*), 0), 1) AS y_travel_coverage_pct,
    COUNT(z_travel_mm) AS with_z_travel,
    ROUND(100.0 * COUNT(z_travel_mm) / NULLIF(COUNT(*), 0), 1) AS z_travel_coverage_pct,
    COUNT(spindle_power_kw) AS with_spindle_power,
    COUNT(max_spindle_rpm) AS with_spindle_rpm,
    COUNT(machine_weight_kg) AS with_machine_weight_kg,
    COUNT(tool_capacity) AS with_tool_capacity
FROM machines
GROUP BY Category
ORDER BY machine_count DESC;

-- QUERY: 07 - Machine finder: example requirements under USD 500,000
SELECT
    `Machine Name`,
    Manufacturer,
    Category,
    price_mid_usd,
    x_travel_mm,
    y_travel_mm,
    z_travel_mm,
    spindle_power_kw,
    max_spindle_rpm,
    tool_capacity
FROM machines
WHERE price_mid_usd > 0
  AND price_mid_usd <= 500000
  AND x_travel_mm >= 1000
  AND z_travel_mm >= 500
  AND max_spindle_rpm >= 10000
ORDER BY price_mid_usd ASC
LIMIT 30;

-- QUERY: 08 - Highest spindle speed among machines with known prices
SELECT
    `Machine Name`,
    Manufacturer,
    Category,
    max_spindle_rpm,
    spindle_power_kw,
    price_mid_usd,
    price_type
FROM machines
WHERE max_spindle_rpm IS NOT NULL
  AND price_mid_usd > 0
ORDER BY max_spindle_rpm DESC, price_mid_usd ASC
LIMIT 25;

-- QUERY: 09 - Price midpoint bands and recorded counts
SELECT
    CASE
        WHEN price_mid_usd < 100000 THEN 'Under $100k'
        WHEN price_mid_usd < 250000 THEN '$100k-$249,999'
        WHEN price_mid_usd < 500000 THEN '$250k-$499,999'
        WHEN price_mid_usd < 1000000 THEN '$500k-$999,999'
        ELSE '$1m and above'
    END AS price_band,
    COUNT(*) AS machine_count,
    ROUND(AVG(price_mid_usd), 2) AS average_price_usd
FROM machines
WHERE price_mid_usd > 0
GROUP BY price_band
ORDER BY MIN(price_mid_usd);

-- QUERY: 10 - Data-quality checks for key standardized fields
SELECT
    COUNT(*) AS total_machines,
    SUM(CASE WHEN URL IS NULL OR TRIM(URL) = '' THEN 1 ELSE 0 END) AS missing_urls,
    SUM(CASE WHEN `Machine Name` IS NULL OR TRIM(`Machine Name`) = '' THEN 1 ELSE 0 END) AS missing_machine_names,
    SUM(CASE WHEN price_low_usd IS NOT NULL AND price_high_usd IS NOT NULL AND price_low_usd > price_high_usd THEN 1 ELSE 0 END) AS invalid_price_ranges,
    SUM(CASE WHEN price_low_usd IS NOT NULL AND price_low_usd <= 0 THEN 1 ELSE 0 END) AS nonpositive_price_lows,
    SUM(CASE WHEN price_high_usd IS NOT NULL AND price_high_usd <= 0 THEN 1 ELSE 0 END) AS nonpositive_price_highs,
    SUM(CASE WHEN spindle_power_kw IS NOT NULL AND spindle_power_kw <= 0 THEN 1 ELSE 0 END) AS nonpositive_spindle_power,
    SUM(CASE WHEN max_spindle_rpm IS NOT NULL AND max_spindle_rpm <= 0 THEN 1 ELSE 0 END) AS nonpositive_rpm,
    SUM(CASE WHEN machine_weight_kg IS NOT NULL AND machine_weight_kg <= 0 THEN 1 ELSE 0 END) AS nonpositive_machine_weight,
    SUM(CASE WHEN max_table_load_kg IS NOT NULL AND max_table_load_kg <= 0 THEN 1 ELSE 0 END) AS nonpositive_table_load,
    SUM(CASE WHEN tool_capacity IS NOT NULL AND tool_capacity <= 0 THEN 1 ELSE 0 END) AS nonpositive_tool_capacity,
    SUM(CASE WHEN x_travel_mm IS NOT NULL AND x_travel_mm <= 0 THEN 1 ELSE 0 END) AS nonpositive_x_travel,
    SUM(CASE WHEN y_travel_mm IS NOT NULL AND y_travel_mm <= 0 THEN 1 ELSE 0 END) AS nonpositive_y_travel,
    SUM(CASE WHEN z_travel_mm IS NOT NULL AND z_travel_mm <= 0 THEN 1 ELSE 0 END) AS nonpositive_z_travel
FROM machines;

-- QUERY: 11 - Price-type coverage
SELECT
    COALESCE(price_type, '(missing)') AS price_type,
    COUNT(*) AS machine_count,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM machines), 2) AS pct_of_all_machines,
    ROUND(AVG(price_mid_usd), 2) AS average_midpoint_usd
FROM machines
GROUP BY COALESCE(price_type, '(missing)')
ORDER BY machine_count DESC;

-- QUERY: 12 - Median price across all machines with recorded prices
WITH priced AS (
    SELECT price_mid_usd AS price_usd
    FROM machines
    WHERE price_mid_usd > 0
), ranked AS (
    SELECT
        price_usd,
        ROW_NUMBER() OVER (ORDER BY price_usd) AS rn,
        COUNT(*) OVER () AS n
    FROM priced
)
SELECT
    COUNT(*) AS priced_machine_count,
    ROUND(AVG(price_usd), 2) AS average_price_usd,
    ROUND(AVG(CASE WHEN rn IN ((n + 1) / 2, (n + 2) / 2) THEN price_usd END), 2) AS median_price_usd
FROM ranked;

-- QUERY: 13 - Median standardized capability by category
WITH measures AS (
   SELECT Category, 'Spindle power (kW)' AS metric, spindle_power_kw AS value
    FROM machines WHERE spindle_power_kw > 0
    UNION ALL
    SELECT Category, 'Spindle speed (RPM)', max_spindle_rpm
    FROM machines WHERE max_spindle_rpm > 0
    UNION ALL
    SELECT Category, 'X travel (mm)', x_travel_mm
    FROM machines WHERE x_travel_mm > 0
    UNION ALL
    SELECT Category, 'Y travel (mm)', y_travel_mm
    FROM machines WHERE y_travel_mm > 0
    UNION ALL
    SELECT Category, 'Z travel (mm)', z_travel_mm
    FROM machines WHERE z_travel_mm > 0
), ranked AS (
    SELECT
        Category,
        metric,
        value,
        ROW_NUMBER() OVER (PARTITION BY Category, metric ORDER BY value) AS rn,
        COUNT(*) OVER (PARTITION BY Category, metric) AS n
    FROM measures
)
SELECT
    Category,
    metric,
    COUNT(*) AS machines_with_value,
    ROUND(AVG(CASE WHEN rn IN ((n + 1) / 2, (n + 2) / 2) THEN value END), 2) AS median_value
FROM ranked
GROUP BY Category, metric
ORDER BY Category, metric;

-- QUERY: 14 - Join validation: specification rows without a known machine URL
SELECT COUNT(*) AS orphan_spec_records
FROM specs_long s
LEFT JOIN machines m ON s.machine_id = m.URL
WHERE m.URL IS NULL;

-- QUERY: 15 - Top 20 highest recorded prices (suspicious-value check)
SELECT
    `Machine Name`,
    Manufacturer,
    Category,
    price_low_usd,
    price_high_usd,
    price_mid_usd,
    price_type,
    URL
FROM machines
WHERE price_mid_usd > 0
ORDER BY price_mid_usd DESC
LIMIT 20;

-- QUERY: 16 - Cheapest recorded price in each category
SELECT
    m.Category,
    m.`Machine Name`,
    m.Manufacturer,
    m.price_mid_usd,
    m.price_type
FROM machines m
JOIN (
    SELECT Category, MIN(price_mid_usd) AS min_price
    FROM machines
    WHERE price_mid_usd > 0
    GROUP BY Category
) x ON x.Category = m.Category AND x.min_price = m.price_mid_usd
ORDER BY m.Category;

-- QUERY: 17 - Average price by category and price type (fair comparison)
SELECT
    Category,
    price_type,
    COUNT(*) AS machine_count,
    ROUND(AVG(price_mid_usd), 2) AS average_price_usd
FROM machines
WHERE price_mid_usd > 0
GROUP BY Category, price_type
ORDER BY Category, price_type;

-- QUERY: 18 - Machines with very wide price ranges
SELECT
    price_type,
    COUNT(*) AS machine_count,
    SUM(CASE WHEN price_high_usd > 3 * price_low_usd THEN 1 ELSE 0 END) AS wide_range_count,
    ROUND(100.0 * SUM(CASE WHEN price_high_usd > 3 * price_low_usd THEN 1 ELSE 0 END) / COUNT(*), 2) AS wide_range_pct
FROM machines
WHERE price_low_usd > 0 AND price_high_usd > 0
GROUP BY price_type;

-- QUERY: 19 - The machines with very wide price ranges (high > 3x low)
SELECT
    `Machine Name`,
    Manufacturer,
    Category,
    price_low_usd,
    price_high_usd,
    price_mid_usd,
    ROUND(price_high_usd / price_low_usd, 1) AS high_to_low_ratio
FROM machines
WHERE price_low_usd > 0
  AND price_high_usd > 3 * price_low_usd
ORDER BY high_to_low_ratio DESC;

-- QUERY: 20 - Suspicious classification: very expensive machines labeled as lathes
SELECT
    `Machine Name`,
    Manufacturer,
    price_mid_usd,
    x_travel_mm,
    z_travel_mm,
    URL
FROM machines
WHERE Category = 'Cnc Lathes'
  AND price_mid_usd >= 1000000
ORDER BY price_mid_usd DESC;

-- QUERY: 21 - Educational (EDU) models and their prices
SELECT
    Category,
    `Machine Name`,
    Manufacturer,
    price_mid_usd,
    price_type
FROM machines
WHERE `Machine Name` LIKE '%EDU%'
ORDER BY Category, price_mid_usd;

-- QUERY: 22 - Average price by manufacturer (at least 10 priced machines)
SELECT
    Manufacturer,
    COUNT(price_mid_usd) AS priced_machine_count,
    ROUND(AVG(price_mid_usd), 2) AS average_price_usd,
    MIN(price_mid_usd) AS min_price_usd,
    MAX(price_mid_usd) AS max_price_usd
FROM machines
WHERE price_mid_usd > 0
GROUP BY Manufacturer
HAVING COUNT(price_mid_usd) >= 10
ORDER BY average_price_usd DESC
LIMIT 20;

-- QUERY: 23 - Custom machine finder
SELECT
    `Machine Name`,
    Manufacturer,
    Category,
    price_mid_usd,
    price_low_usd,
    price_high_usd,
    price_type,
    x_travel_mm,
    y_travel_mm,
    z_travel_mm,
    spindle_power_kw,
    max_spindle_rpm,
    tool_capacity,
    URL
FROM machines
WHERE price_mid_usd > 0
  AND price_mid_usd <= 500000            
  AND Category = '5 Axis Machining Centers'  
  AND x_travel_mm >= 500                 
  AND y_travel_mm >= 400                
  AND z_travel_mm >= 400                 
  AND max_spindle_rpm >= 10000           
  AND `Machine Name` NOT LIKE '%EDU%'
  AND Manufacturer <> 'IPG Photonics'
ORDER BY price_mid_usd ASC
LIMIT 30;

-- QUERY: 24 - How many machines match the filters in total
SELECT COUNT(*) AS matching_machines
FROM machines
WHERE price_mid_usd > 0
  AND price_mid_usd <= 500000
  AND Category = '5 Axis Machining Centers'
  AND x_travel_mm >= 500
  AND y_travel_mm >= 400
  AND z_travel_mm >= 400
  AND max_spindle_rpm >= 10000
  AND `Machine Name` NOT LIKE '%EDU%'
  AND Manufacturer <> 'IPG Photonics';

-- QUERY: 25 - The next 30 matching machines (30 to 60)
SELECT
    `Machine Name`, Manufacturer, price_mid_usd, price_low_usd, price_high_usd,
    price_type, x_travel_mm, y_travel_mm, z_travel_mm,
    spindle_power_kw, max_spindle_rpm, tool_capacity, URL
FROM machines
WHERE price_mid_usd > 0
  AND price_mid_usd <= 500000
  AND Category = '5 Axis Machining Centers'
  AND x_travel_mm >= 500
  AND y_travel_mm >= 400
  AND z_travel_mm >= 400
  AND max_spindle_rpm >= 10000
  AND `Machine Name` NOT LIKE '%EDU%'
  AND Manufacturer <> 'IPG Photonics'
ORDER BY price_mid_usd ASC
LIMIT 30 OFFSET 30;

-- QUERY: 26 - The last 36 matching machines (60 to 96)
SELECT
    `Machine Name`, Manufacturer, price_mid_usd, price_low_usd, price_high_usd,
    price_type, x_travel_mm, y_travel_mm, z_travel_mm,
    spindle_power_kw, max_spindle_rpm, tool_capacity, URL
FROM machines
WHERE price_mid_usd > 0
  AND price_mid_usd <= 500000
  AND Category = '5 Axis Machining Centers'
  AND x_travel_mm >= 500
  AND y_travel_mm >= 400
  AND z_travel_mm >= 400
  AND max_spindle_rpm >= 10000
  AND `Machine Name` NOT LIKE '%EDU%'
  AND Manufacturer <> 'IPG Photonics'
ORDER BY price_mid_usd ASC
LIMIT 40 OFFSET 60;

-- QUERY: 27 - Shortlist: 5-axis machines whose HIGH price is within USD 500,000
SELECT
    `Machine Name`,
    Manufacturer,
    price_low_usd,
    price_mid_usd,
    price_high_usd,
    price_type,
    x_travel_mm,
    y_travel_mm,
    z_travel_mm,
    spindle_power_kw,
    max_spindle_rpm,
    tool_capacity,
    URL
FROM machines
WHERE price_high_usd > 0
  AND price_high_usd <= 500000
  AND Category = '5 Axis Machining Centers'
  AND x_travel_mm >= 500 AND x_travel_mm <= 1600
  AND y_travel_mm >= 400
  AND z_travel_mm >= 400
  AND max_spindle_rpm >= 15000
  AND `Machine Name` NOT LIKE '%EDU%'
ORDER BY max_spindle_rpm DESC, price_mid_usd ASC
LIMIT 40;

-- QUERY: 28 - Count: how many machines match Query 27 in total (no LIMIT)
SELECT
    COUNT(*) AS total_matches
FROM machines
WHERE price_high_usd > 0
  AND price_high_usd <= 500000
  AND Category = '5 Axis Machining Centers'
  AND x_travel_mm >= 500 AND x_travel_mm <= 1600
  AND y_travel_mm >= 400
  AND z_travel_mm >= 400
  AND max_spindle_rpm >= 15000
  AND `Machine Name` NOT LIKE '%EDU%';

-- QUERY: 29 - Shortlist page 2: same filters as Query 27, rows 41 onward
SELECT
    `Machine Name`,
    Manufacturer,
    price_low_usd,
    price_mid_usd,
    price_high_usd,
    price_type,
    x_travel_mm,
    y_travel_mm,
    z_travel_mm,
    spindle_power_kw,
    max_spindle_rpm,
    tool_capacity,
    URL
FROM machines
WHERE price_high_usd > 0
  AND price_high_usd <= 500000
  AND Category = '5 Axis Machining Centers'
  AND x_travel_mm >= 500 AND x_travel_mm <= 1600
  AND y_travel_mm >= 400
  AND z_travel_mm >= 400
  AND max_spindle_rpm >= 15000
  AND `Machine Name` NOT LIKE '%EDU%'
ORDER BY max_spindle_rpm DESC, price_mid_usd ASC, `Machine Name` ASC
LIMIT 40 OFFSET 40;

-- QUERY: 30 - Listed (published) prices only: machines with a guaranteed price within USD 500,000
SELECT
    `Machine Name`,
    Manufacturer,
    price_mid_usd,
    price_type,
    x_travel_mm,
    y_travel_mm,
    z_travel_mm,
    spindle_power_kw,
    max_spindle_rpm,
    tool_capacity,
    URL
FROM machines
WHERE price_type = 'listed'
  AND price_mid_usd <= 500000
  AND Category = '5 Axis Machining Centers'
  AND x_travel_mm >= 500 AND x_travel_mm <= 1600
  AND y_travel_mm >= 400
  AND z_travel_mm >= 400
  AND `Machine Name` NOT LIKE '%EDU%'
ORDER BY price_mid_usd ASC;

-- QUERY: 31 - Market overview: what each RPM tier gives you (price high <= 500k, same filters as Query 27 but RPM >= 8000)
SELECT
    CASE
        WHEN max_spindle_rpm >= 24000 THEN '1) 24,000+ RPM'
        WHEN max_spindle_rpm >= 18000 THEN '2) 18,000-23,999 RPM'
        WHEN max_spindle_rpm >= 15000 THEN '3) 15,000-17,999 RPM'
        WHEN max_spindle_rpm >= 10000 THEN '4) 10,000-14,999 RPM'
        ELSE '5) under 10,000 RPM'
    END AS rpm_tier,
    COUNT(*) AS machines,
    MIN(price_mid_usd) AS cheapest_mid,
    ROUND(AVG(price_mid_usd)) AS avg_mid,
    MAX(price_high_usd) AS max_high,
    MAX(x_travel_mm) AS biggest_x,
    MAX(y_travel_mm) AS biggest_y,
    MAX(z_travel_mm) AS biggest_z,
    SUM(price_type = 'listed') AS listed_price_count
FROM machines
WHERE price_high_usd > 0
  AND price_high_usd <= 500000
  AND Category = '5 Axis Machining Centers'
  AND x_travel_mm >= 500 AND x_travel_mm <= 1600
  AND y_travel_mm >= 400
  AND z_travel_mm >= 400
  AND `Machine Name` NOT LIKE '%EDU%'
GROUP BY rpm_tier
ORDER BY rpm_tier;

-- QUERY: 32 - Shortlist: actual machines in the two recommended RPM tiers
SELECT
    `Machine Name`,
    max_spindle_rpm,
    price_low_usd,
    price_mid_usd,
    price_high_usd,
    price_type,
    x_travel_mm,
    y_travel_mm,
    z_travel_mm,
    CASE
        WHEN max_spindle_rpm >= 18000 THEN 'tier 2 (18k-24k)'
        ELSE 'tier 4 (10k-15k)'
    END AS rpm_tier
FROM machines
WHERE Category = '5 Axis Machining Centers'
  AND price_high_usd > 0
  AND price_mid_usd <= 350000
  AND x_travel_mm >= 500
  AND y_travel_mm >= 500
  AND z_travel_mm >= 400
  AND max_spindle_rpm >= 10000
  AND max_spindle_rpm < 24000
  AND max_spindle_rpm NOT BETWEEN 15000 AND 17999
  AND `Machine Name` NOT LIKE '%EDU%'
ORDER BY rpm_tier DESC, price_mid_usd;

-- QUERY: 33
SELECT `Machine Name`, max_spindle_rpm, price_mid_usd,
       x_travel_mm, y_travel_mm, z_travel_mm
FROM machines
WHERE Category = '5 Axis Machining Centers'
  AND price_high_usd > 0
  AND price_mid_usd <= 350000
  AND max_spindle_rpm >= 10000
  AND (x_travel_mm IS NULL OR y_travel_mm IS NULL OR z_travel_mm IS NULL)
  AND `Machine Name` NOT LIKE '%EDU%';

-- QUERY: 34 - Details of shortlisted machines
SELECT *
FROM machines
WHERE `Machine Name` IN ('Chiron FZ 08 FX', 'Kitamura MedCenter5AX', 'Okuma MU-S600V', 'Mazak VC-Ez 26X', 'Mazak VC-Ez X');
