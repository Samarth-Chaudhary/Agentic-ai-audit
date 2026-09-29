-- 05_pii_by_task.sql
-- PII leakage metrics and entity counts by task type
SELECT
    task_type,
    COUNT(*) AS total_traces,
    SUM(pii_count) AS total_pii_entities,
    COUNT(CASE WHEN pii_count > 0 THEN 1 END) AS traces_with_pii,
    ROUND(COUNT(CASE WHEN pii_count > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS pii_leakage_rate_percentage
FROM audit_analytics
GROUP BY task_type
ORDER BY total_pii_entities DESC;
