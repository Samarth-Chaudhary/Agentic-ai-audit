-- 09_daily_risk_trend.sql
-- Daily average risk score and high-risk ratio over time
SELECT
    date,
    COUNT(*) AS daily_trace_count,
    ROUND(AVG(risk_score), 2) AS daily_avg_risk,
    SUM(scope_violations) AS daily_scope_violations,
    SUM(pii_count) AS daily_pii_detections,
    SUM(groundedness_failures) AS daily_groundedness_failures,
    ROUND(COUNT(CASE WHEN risk_tier IN ('HIGH', 'CRITICAL') THEN 1 END) * 100.0 / COUNT(*), 2) AS daily_high_risk_ratio
FROM audit_analytics
GROUP BY date
ORDER BY date ASC;
