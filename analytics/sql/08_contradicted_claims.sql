-- 08_contradicted_claims.sql
-- Traces exhibiting explicit contradictions against tool observations
SELECT
    date,
    task_type,
    trace_id,
    risk_score,
    risk_tier,
    contradicted_claims,
    summary
FROM audit_analytics
WHERE contradicted_claims > 0
ORDER BY contradicted_claims DESC, risk_score DESC;
