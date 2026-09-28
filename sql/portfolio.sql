-- Portfolio analytics queries used by GET /portfolio/summary.
-- Each query starts with a "-- name:" line so db.py can load it by name.

-- name: decision_mix
SELECT decision,
       COUNT(*) AS applications,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM applications), 1) AS share_pct
FROM applications
GROUP BY decision
ORDER BY applications DESC;

-- name: by_industry
SELECT industry,
       COUNT(*) AS applications,
       ROUND(100.0 * SUM(decision = 'Approve') / COUNT(*), 1) AS approval_rate_pct,
       ROUND(100.0 * AVG(pd), 2) AS avg_pd_pct
FROM applications
WHERE decision <> 'Returned'
GROUP BY industry
ORDER BY avg_pd_pct DESC;

-- name: broker_scorecard
-- Brokers with the most submissions: how often their deals come back for
-- data fixes, and how risky the rest are. Useful for broker account managers.
SELECT broker_id,
       COUNT(*) AS applications,
       ROUND(100.0 * SUM(decision = 'Returned') / COUNT(*), 1) AS returned_for_fixes_pct,
       ROUND(100.0 * SUM(decision = 'Approve') / COUNT(*), 1) AS approval_rate_pct,
       ROUND(100.0 * AVG(pd), 2) AS avg_pd_pct
FROM applications
GROUP BY broker_id
ORDER BY applications DESC
LIMIT 15;

-- name: dq_by_rule
SELECT rule, severity, COUNT(*) AS occurrences
FROM dq_issues
GROUP BY rule, severity
ORDER BY occurrences DESC;

-- name: weekly_volume
SELECT strftime('%Y-%W', submitted_date) AS week,
       COUNT(*) AS applications,
       SUM(decision = 'Approve') AS approved,
       SUM(decision = 'Refer') AS referred,
       SUM(decision = 'Decline') AS declined,
       SUM(decision = 'Returned') AS returned
FROM applications
GROUP BY week
ORDER BY week;
