# Base44 build guide: Deal Desk front end

Paste the prompts below into Base44 **one at a time**, checking each result before the next. Building in stages is more reliable than one giant prompt, and easier to fix.

The app reads everything live from the API, so there is no data to import. A backup CSV (`data/scored/base44_import.csv`) exists only in case live calls do not work.

API base URL: `https://metro-deal-desk-api.onrender.com`

Before starting a session, open https://metro-deal-desk-api.onrender.com/health in a browser tab to wake the server (free tier sleeps after about 15 minutes).

---

## Prompt 1: app shell and the broker portal

```
Build a web app called "Deal Desk" for triaging vehicle and equipment finance applications. It is a portfolio demo that runs on synthetic data. It must not use any company's logo. Style: clean internal-tool look, white background, one dark navy accent colour, a left sidebar, plenty of whitespace, no emojis.

Sidebar pages (build the first now, placeholders for the rest): Broker Portal, Credit Dashboard, Application Detail (reached by clicking an application, not in the sidebar), Data Quality, About.

All data comes from an external REST API. Put the base URL in one constant: https://metro-deal-desk-api.onrender.com
The API allows cross-origin requests from the browser, so call it directly with fetch. No authentication.

The server sleeps when idle and the first request can take up to 60 seconds. On every page, while the first request is loading, show a small message: "Waking up the API (free tier servers sleep when idle). This can take up to a minute." Use a 90 second timeout and a Retry button if it fails.

BROKER PORTAL page:
On load, GET /reference/options. It returns lists for dropdowns: industry, asset_category, state, condition, channel, entity_type, term_months, and asset_models (an object mapping each asset_category to a list of model names).

Show a form a finance broker would fill in, in three groups:
1. Business: broker_id (text, default "BRK-012"), channel (dropdown), abn (text, 11 digits), entity_type (dropdown), abn_age_months (number, label "Months trading"), industry (dropdown), state (dropdown), postcode (text), credit_score (number 0 to 1200, label "Director credit score").
2. Asset: asset_category (dropdown), asset model (dropdown filtered by the chosen asset_category using asset_models), asset_year (number), condition (New or Used), asset_price (number, dollars).
3. Loan: loan_amount (number), term_months (dropdown), balloon_amount (number, default 0), interest_rate (number shown as a percentage, e.g. 8.9, sent to the API as 0.089).

Build asset_description as asset_year + " " + model, e.g. "2025 Toyota HiLux SR5".

Add three buttons above the form that fill it with examples:
- "Clean deal": BRK-012, Broker, abn 25892415116, Company, 96 months, Health care, NSW, postcode 2541, credit score 850, Car / SUV, Toyota RAV4 Hybrid, 2026, New, price 55000, loan 50000, 48 months, balloon 10000, rate 7.9
- "Needs review": BRK-012, Broker, abn 25892415116, Company, 14 months, Construction & trades, NSW, 2541, credit score 690, Ute / van, Toyota HiLux SR5, 2025, Used, price 62000, loan 60000, 60 months, balloon 25000, rate 9.5
- "Data error": same as Clean deal but postcode 3000 (a Victorian postcode on a NSW application)

On submit, POST /applications with a JSON body using exactly these field names: broker_id, channel, abn, entity_type, abn_age_months, industry, state, postcode, credit_score, asset_category, asset_description, condition, asset_year, asset_price, loan_amount, term_months, balloon_amount, interest_rate. Numbers must be sent as numbers.

The response looks like this:
{
 "application_id": "API-28B99A07",
 "dq_status": "Pass",               // Pass, Warning or Rejected
 "dq_issues": [ {"rule": "...", "severity": "reject", "field": "...", "message": "..."} ],
 "decision": "Refer",               // Approve, Refer, Decline or Returned
 "pd": 0.0509,                      // probability of default, null if Returned
 "risk_grade": "C",                 // A to E, null if Returned
 "reasons": {
   "raises_risk": [ {"feature": "credit_score", "reason": "Director credit score of 690", "impact": 0.227} ],
   "lowers_risk": [ {"feature": "lvr", "reason": "Loan is 97% of the asset price", "impact": -0.129} ]
 },
 "policy": [ {"rule": "balloon_limit", "outcome": "refer", "message": "Balloon is 40% of the asset price; the limit for ute / van is 35%.", "fix": "Reduce the balloon to $21,700 or less."} ],
 "indicative_rate": 0.095,
 "monthly_repayment": 932.98,
 "broker_note": "API-28B99A07 ($60,000 over 60 months) has been referred to a credit officer..."
}

Show the result in a card beside or below the form:
- A large decision badge: Approve (green), Refer (amber), Decline (red), Returned (grey). Always show the word as well as the colour.
- Risk: pd as a percentage with one decimal, and the risk grade. Hide both if decision is Returned.
- Monthly repayment, formatted as dollars.
- "What raised the risk" and "What lowered the risk": list each reason with a small horizontal bar whose length is proportional to the absolute impact.
- "Policy checks": each policy item with its message and, underneath, its fix in a softer style.
- "Data issues": each dq_issues message, shown prominently if decision is Returned.
- "Note for the broker": the broker_note text in a quoted box.
- A link "Open full detail" to the Application Detail page for this application_id.

If the API returns HTTP 422, show "Some fields have the wrong format" and list the field names from the response's detail array.
```

**Check before moving on:** click each example button and submit. Clean deal should approve, Needs review should refer with two policy checks, Data error should come back Returned with a postcode message.

Submitting the same example a second time comes back as Returned with "looks like a resubmission". That is the duplicate check working, not a bug. Change the loan amount by a dollar to submit it as a new deal.

---

## Prompt 2: credit dashboard

```
Build the Credit Dashboard page. It is the internal view for the credit team.

Data:
- GET /portfolio/summary returns:
  decision_mix: [{decision, applications, share_pct}]
  by_industry: [{industry, applications, approval_rate_pct, avg_pd_pct}]
  broker_scorecard: [{broker_id, applications, returned_for_fixes_pct, approval_rate_pct, avg_pd_pct}]
  dq_by_rule: [{rule, severity, occurrences}]
  weekly_volume: [{week, applications, approved, referred, declined, returned}]
- GET /applications?limit=5000 returns a list of applications, newest first, each with: application_id, submitted_date, source, broker_id, channel, state, industry, asset_category, asset_description, loan_amount, term_months, balloon_amount, dq_status, decision, pd (may be null), risk_grade (may be null).

Layout, top to bottom:
1. Four KPI tiles: Total applications; Approval rate (Approve / all, as %); Referred to credit officers (count and %); Average probability of default (mean of non-null pd, as %).
2. Two charts side by side: "Decisions" as a horizontal bar chart from decision_mix (Approve green, Refer amber, Decline red, Returned grey; labels on bars). "Average risk by industry" as a horizontal bar chart of avg_pd_pct sorted highest first, single colour.
3. "Weekly volume" as a stacked column chart from weekly_volume using approved, referred, declined, returned with the same four colours and a legend.
4. "Application queue" table from /applications: columns Date, ID, Broker, Industry, Asset, Loan ($), PD (%), Grade, Decision (coloured badge with text). Filters in one row above it: Decision (All / Approve / Refer / Decline / Returned), Industry, Asset type, and a search box that matches ID, broker or asset. Paginate 25 rows per page. Clicking a row opens Application Detail for that application_id.

Label all charts with plain titles and axis labels. Numbers: dollars with thousands separators, percentages with one decimal.
```

**Check:** tiles should show about 2,004 applications and an approval rate near 49%.

---

## Prompt 3: application detail and AI-polished broker note

```
Build the Application Detail page. It receives an application_id.

GET /applications/{application_id} returns the stored row (application_id, submitted_date, broker_id, channel, state, industry, asset_category, asset_description, abn, loan_amount, term_months, balloon_amount, dq_status, decision, pd, risk_grade, broker_note) plus a "result" object with the same shape as the POST /applications response (dq_issues, reasons, policy, monthly_repayment, broker_note).

Show:
1. Header: application ID, asset description, decision badge (colour plus word), submitted date, broker.
2. Deal summary: industry, state, loan amount, term, balloon, monthly repayment.
3. Risk: pd as a percentage, risk grade, and a "Why this score" chart: a horizontal diverging bar chart of every reason in result.reasons.raises_risk (bars to the right, red) and result.reasons.lowers_risk (bars to the left, green), bar length = impact. Caption: "SHAP values from the credit model: how much each factor moved this application's risk up or down."
4. Policy checks and data issues, as on the Broker Portal result card. If none, say "All policy checks passed" / "No data issues".
5. Broker note, with two tabs: "System note" (broker_note exactly as returned) and "Polished for sending".

For "Polished for sending": add a button "Polish with AI". When clicked, call the built-in Base44 LLM integration (InvokeLLM) with this prompt, inserting the system note:

"You are helping a lender's credit team write to a finance broker. Rewrite the note below so it reads warmly and professionally, as a short message from the credit team. Rules: keep every fact, number, reason, decision and suggested fix exactly as given; do not add any new reason, promise, figure or advice; do not change the decision; no em dashes; no emojis; under 130 words. Note: <system note>"

Show the result in the tab, with a small caption: "Reworded by AI from the system note. The decision and reasons come from the model and policy rules, not from the AI." Keep the System note tab as the default view. If the AI call fails, show the system note and a short error message.

Add a "Back to dashboard" link.
```

**Check:** open a Refer from the dashboard, press Polish with AI, and compare the two tabs. The polished version must not add or drop any reason.

---

## Prompt 4: data quality and about pages

```
Build the remaining two pages.

DATA QUALITY page, using GET /portfolio/summary and GET /applications?decision=Returned&limit=500:
1. Intro line: "Every submission is checked before it is scored. Serious problems send it back to the broker with a clear message; minor ones are flagged for credit staff."
2. Bar chart "Issues found, by rule" from dq_by_rule, colour by severity (reject dark grey, warn amber) with a legend. Turn rule names into readable labels, e.g. postcode_state_mismatch -> "Postcode not in state", abn_checksum_fail -> "Invalid ABN", missing_abn -> "Missing ABN", balloon_exceeds_loan -> "Balloon larger than loan", new_asset_too_old -> "'New' asset is old", invalid_term -> "Term not offered", loan_far_above_asset_value -> "Loan far above asset value", unrecognised_asset -> "Unrecognised asset (possible typo)", duplicate_submission -> "Duplicate submission".
3. "Broker scorecard" table from broker_scorecard: Broker, Applications, Returned for fixes (%), Approval rate (%), Average PD (%). Sortable columns. Caption: "Helps broker account managers see who might need help with submissions."
4. "Returned applications" table: ID, Date, Broker, Asset, Loan; clicking a row opens Application Detail.

ABOUT page, plain text, no marketing language:
Title: "About this project"
- "Deal Desk is a portfolio project built to show how a non-bank lender could triage broker applications for vehicle and equipment finance: data quality checks, an explainable credit risk model, fixed policy rules, and a plain-English note back to the broker."
- "All data is synthetic. Risk patterns are calibrated against 273,000 real US Small Business Administration loans, and levels against Australian public sources. No real customer, broker or lender data is used."
- "This is an independent project. It is not affiliated with or endorsed by any lender."
- "How a decision is made" as four numbered steps: 1. Data quality rules check the submission. 2. A LightGBM model estimates the probability of default and explains its top reasons (SHAP). 3. Credit policy rules can refer or decline whatever the score. 4. The system writes a note for the broker; AI may reword it for tone but never changes its content.
- Links: "API documentation" -> https://metro-deal-desk-api.onrender.com/docs, "Source code" -> https://github.com/PaneerChilliDry/metro_deal_desk
- "Built by Parva Teli-Shah."
```

---

## Visual pass (after Prompt 4)

Run once every page exists, so one prompt styles the whole app. Colours come from Metro's public brand palette. Attach the white logo file (kept outside the repo, in the project folder's `brand/` folder) in the same message. Metro's site uses Euclid Circular, a licensed font that Base44 cannot load, so Outfit (a free Google Font with a similar geometric, rounded feel) stands in.

```
Visual refresh across the whole app. Keep all functionality, data and page structure exactly as they are.

Logo: use the attached white logo image at the top of the sidebar, about 28px tall. Directly beside it, show a small pill-shaped label reading "Concept" (white text, 1px white outline). Under the logo, show the line "A concept project for a Metro Finance application" in small, light text. Do not use the logo anywhere else.

Font: use "Outfit" from Google Fonts for all text. Headings semi-bold, body regular.

Colours:
- Primary: #5164FF (buttons, links, active sidebar item, main chart colour)
- Dark navy: #3A3F76 (sidebar background, headings)
- Coral #FF563C and warm yellow #FFC976, used sparingly as accents (for example a thin top border on KPI cards)
- White page background; white cards with soft shadows and 12px rounded corners.
Keep the decision badge colours (Approve green, Refer amber, Decline red, Returned grey) so decisions never clash with the theme.

Footer on every page, small grey text, centred:
"Independent portfolio project by Parva Teli-Shah, created for an application to the Metro Finance AI & Software Engineering Graduate Program. Not affiliated with, endorsed by or produced by Metro Finance. All data is synthetic; no real customer, broker or lender data is used."
```

---

## If something goes wrong

- **Everything shows "failed to fetch" at once:** the API is probably still waking up. Open /health in a tab, wait for it to answer, then press Retry.
- **Base44 cannot call external URLs from the page:** ask it to "move the API calls into a backend function that fetches the same URLs and returns the JSON", or fall back to importing `data/scored/base44_import.csv` as an entity for the dashboard.
- **A chart looks wrong:** paste the exact JSON the endpoint returns (open the URL in a browser) and ask Base44 to use those field names.
