-- 10_tool_violation_analysis.sql
-- Frequency of violations broken down by specific tool name using UNNEST
SELECT
    t.tool_name,
    COUNT(*) AS violation_count,
    COUNT(DISTINCT a.trace_id) AS impacted_traces,
    ROUND(AVG(a.risk_score), 2) AS avg_risk_when_violated
FROM audit_analytics a
CROSS JOIN UNNEST(a.violated_tools) AS t(tool_name)
GROUP BY t.tool_name
ORDER BY violation_count DESC;
