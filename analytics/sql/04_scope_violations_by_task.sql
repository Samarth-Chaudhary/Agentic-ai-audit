-- 04_scope_violations_by_task.sql
-- Scope violations frequency and violation rates by task type
SELECT
    task_type,
    COUNT(*) AS total_traces,
    SUM(scope_violations) AS total_scope_violations,
    COUNT(CASE WHEN scope_violations > 0 THEN 1 END) AS traces_with_violations,
    ROUND(COUNT(CASE WHEN scope_violations > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS violation_rate_percentage
FROM audit_analytics
GROUP BY task_type
ORDER BY total_scope_violations DESC;
