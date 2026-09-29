-- 03_high_risk_by_date.sql
-- Count of HIGH and CRITICAL risk traces grouped by date
SELECT
    date,
    COUNT(*) AS total_traces,
    COUNT(CASE WHEN risk_tier IN ('HIGH', 'CRITICAL') THEN 1 END) AS high_or_critical_traces,
    ROUND(COUNT(CASE WHEN risk_tier IN ('HIGH', 'CRITICAL') THEN 1 END) * 100.0 / COUNT(*), 2) AS high_risk_percentage
FROM audit_analytics
GROUP BY date
ORDER BY date DESC;
