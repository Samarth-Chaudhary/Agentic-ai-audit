-- 02_risk_distribution.sql
-- Distribution of traces across categorical risk tiers with percentage share
SELECT
    risk_tier,
    COUNT(*) AS trace_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS percentage_share
FROM audit_analytics
GROUP BY risk_tier
ORDER BY
    CASE risk_tier
        WHEN 'CRITICAL' THEN 1
        WHEN 'HIGH' THEN 2
        WHEN 'MEDIUM' THEN 3
        WHEN 'LOW' THEN 4
        ELSE 5
    END;
