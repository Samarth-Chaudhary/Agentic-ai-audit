-- 07_unsupported_claims.sql
-- Unsupported claim occurrences grouped by date and task type
SELECT
    date,
    task_type,
    COUNT(*) AS total_traces,
    SUM(unsupported_claims) AS total_unsupported_claims,
    ROUND(AVG(unsupported_claims), 2) AS avg_unsupported_claims_per_trace
FROM audit_analytics
WHERE unsupported_claims > 0
GROUP BY date, task_type
ORDER BY date DESC, total_unsupported_claims DESC;
