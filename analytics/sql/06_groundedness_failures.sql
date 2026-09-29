-- 06_groundedness_failures.sql
-- Groundedness failure rates and breakdown by task type
SELECT
    task_type,
    COUNT(*) AS total_traces,
    SUM(groundedness_failures) AS total_groundedness_failures,
    SUM(unsupported_claims) AS total_unsupported_claims,
    SUM(contradicted_claims) AS total_contradicted_claims,
    COUNT(CASE WHEN groundedness_failures > 0 THEN 1 END) AS traces_with_hallucinations,
    ROUND(COUNT(CASE WHEN groundedness_failures > 0 THEN 1 END) * 100.0 / COUNT(*), 2) AS hallucination_rate_percentage
FROM audit_analytics
GROUP BY task_type
ORDER BY total_groundedness_failures DESC;
