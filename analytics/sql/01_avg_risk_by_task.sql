-- 01_avg_risk_by_task.sql
-- Average risk score and total trace count grouped by task type
SELECT
    task_type,
    COUNT(*) AS total_traces,
    ROUND(AVG(risk_score), 2) AS avg_risk_score,
    MIN(risk_score) AS min_risk_score,
    MAX(risk_score) AS max_risk_score
FROM audit_analytics
GROUP BY task_type
ORDER BY avg_risk_score DESC;
