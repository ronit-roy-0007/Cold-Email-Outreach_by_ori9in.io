"""
IntentLead AI — Frontend QA Verification Test Suite
Tests all 9 modules, static assets, responsive templates, and API integrations.
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8000"

def get(path: str) -> tuple[int, str, dict]:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "IntentLead-QA/1.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
            headers = dict(resp.headers)
            return status, body, headers
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body, dict(e.headers)
    except Exception as e:
        return 0, str(e), {}

def post_json(path: str, data: dict) -> tuple[int, str]:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={
            "User-Agent": "IntentLead-QA/1.0",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
            return status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body
    except Exception as e:
        return 0, str(e)

def run_tests():
    print("=" * 70)
    print("INTENTLEAD AI — MASTER FRONTEND QA VERIFICATION SUITE")
    print(f"Target: {BASE_URL}")
    print("=" * 70)

    results = []

    # 1. Static Assets
    print("\n[PHASE 1: STATIC ASSETS]")
    
    # CSS
    st, body, hdrs = get("/static/css/intentlead.css")
    css_ok = st == 200 and "--accent-lime: #C8F560" in body and "--bg-canvas: #F7F5F0" in body
    results.append(("Static CSS (intentlead.css)", css_ok, f"Status: {st}, Size: {len(body)} bytes"))
    print(f"  {'✓ PASS' if css_ok else '✗ FAIL'} Static CSS ({st})")

    # JS
    st, body, hdrs = get("/static/js/intentlead.js")
    js_ok = st == 200 and "handleLeadApproval" in body and "showToast" in body
    results.append(("Static JS (intentlead.js)", js_ok, f"Status: {st}, Size: {len(body)} bytes"))
    print(f"  {'✓ PASS' if js_ok else '✗ FAIL'} Static JS ({st})")

    # 2. Web Routes Verification
    print("\n[PHASE 2: CORE PRODUCT MODULES]")

    # Overview
    st, body, _ = get("/")
    ok = st == 200 and "Autonomous Intelligence" in body and "Pipeline Conversion Architecture" in body
    results.append(("1. Overview Dashboard (/)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Overview Dashboard (/) ({st})")

    st, body, _ = get("/overview")
    ok = st == 200 and "Overview Dashboard" in body
    results.append(("1b. Overview Alias (/overview)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Overview Alias (/overview) ({st})")

    # Leads Directory
    st, body, _ = get("/leads")
    ok = st == 200 and "Multi-Dimensional" in body and "Lead Intelligence" in body
    results.append(("2. Lead Intelligence (/leads)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Lead Intelligence Directory (/leads) ({st})")

    # Leads Filtered
    st, body, _ = get("/leads?status=draft&priority=A")
    ok = st == 200 and "Showing" in body
    results.append(("2b. Leads Filter Query", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Leads Filter Query ({st})")

    # Approvals Center
    st, body, _ = get("/approvals")
    ok = st == 200 and "Operator" in body and "Approval Queue" in body
    results.append(("3. Approval Center (/approvals)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Approval Center (/approvals) ({st})")

    # Campaigns List
    st, body, _ = get("/campaigns")
    ok = st == 200 and "Campaign Matrix" in body
    results.append(("4. Campaign Management (/campaigns)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Campaign Management (/campaigns) ({st})")

    # Campaign New Form
    st, body, _ = get("/campaigns/new")
    ok = st == 200 and "Initialize" in body and "Targeting Matrix" in body
    results.append(("4b. New Campaign Form (/campaigns/new)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} New Campaign Form (/campaigns/new) ({st})")

    # Mailboxes Management
    st, body, _ = get("/mailboxes")
    ok = st == 200 and "Mailbox Rotation" in body and "Quota Plane" in body
    results.append(("5. Mailbox Management (/mailboxes)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Mailbox Management (/mailboxes) ({st})")

    # Analytics
    st, body, _ = get("/analytics")
    ok = st == 200 and "B2B Intelligence" in body and "Analytics" in body
    results.append(("6. Analytics & Intelligence (/analytics)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Analytics & Intelligence (/analytics) ({st})")

    # Suppression List
    st, body, _ = get("/suppression")
    ok = st == 200 and "Suppression" in body and "Opt-Out Registry" in body
    results.append(("7. Suppression Registry (/suppression)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Suppression Registry (/suppression) ({st})")

    # Activity & Audit
    st, body, _ = get("/activity")
    ok = st == 200 and "Audit Trail" in body and "System Activity" in body
    results.append(("8. Activity & Audit Logs (/activity)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Activity & Audit Logs (/activity) ({st})")

    # Settings
    st, body, _ = get("/settings")
    ok = st == 200 and "System Configuration" in body and "Security Integrations" in body
    results.append(("9. Settings & Integrations (/settings)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Settings & Integrations (/settings) ({st})")

    # Unified Inbox
    st, body, _ = get("/inbox")
    ok = st == 200 and "Unified Inbox" in body and "CONVERSATIONS & ENGAGEMENT" in body
    results.append(("10. Unified Inbox (/inbox)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Unified Inbox (/inbox) ({st})")

    # Unified Inbox API
    st, body, _ = get("/api/web/inbox/conversations")
    ok = st == 200 and "conversations" in body
    results.append(("10b. Unified Inbox API (/api/web/inbox/conversations)", ok, f"Status: {st}"))
    print(f"  {'✓ PASS' if ok else '✗ FAIL'} Unified Inbox API (/api/web/inbox/conversations) ({st})")

    # 3. Dynamic Entity Deep-Dives
    print("\n[PHASE 3: DEEP-DIVE INSPECTION & CSV EXPORT]")

    # Find a campaign ID to test /campaigns/{id} and CSV export
    st, body, _ = get("/campaigns")
    camp_id = None
    import re
    match = re.search(r'/campaigns/([0-9a-fA-F-]{36})', body)
    if match:
        camp_id = match.group(1)

    if camp_id:
        st, c_body, _ = get(f"/campaigns/{camp_id}")
        ok = st == 200 and "Scored Leads in Campaign" in c_body
        results.append(("Campaign Detail View", ok, f"ID: {camp_id}, Status: {st}"))
        print(f"  {'✓ PASS' if ok else '✗ FAIL'} Campaign Detail View (/campaigns/{camp_id}) ({st})")

        st, csv_body, hdrs = get(f"/campaigns/{camp_id}/export.csv")
        csv_ok = st == 200 and "overall_score" in csv_body and "recommended_service" in csv_body
        results.append(("Campaign CSV Export", csv_ok, f"Status: {st}, Rows: {len(csv_body.splitlines())}"))
        print(f"  {'✓ PASS' if csv_ok else '✗ FAIL'} Campaign CSV Export ({st}, {len(csv_body.splitlines())} rows)")
    else:
        results.append(("Campaign Detail & CSV", False, "No campaign ID found in list"))
        print("  ✗ SKIP No campaign ID found")

    # Find a lead ID to test /leads/{id}
    st, body, _ = get("/leads")
    lead_id = None
    match = re.search(r'/leads/([0-9a-fA-F-]{36})', body)
    if match:
        lead_id = match.group(1)

    if lead_id:
        st, l_body, _ = get(f"/leads/{lead_id}")
        ok = st == 200 and "Dimension Analysis" in l_body and "Service Fit Rankings" in l_body
        results.append(("Lead Detail View", ok, f"ID: {lead_id}, Status: {st}"))
        print(f"  {'✓ PASS' if ok else '✗ FAIL'} Lead Detail View (/leads/{lead_id}) ({st})")

        # Test web approval action API
        st, app_body = post_json(f"/api/web/approvals/{lead_id}", {
            "user_id": "qa_operator",
            "action": "approve"
        })
        try:
            resp_data = json.loads(app_body)
            app_ok = (st == 200) and (resp_data.get("status") in ("success", "already_processed") or resp_data.get("outreach_status") == "approved")
        except Exception as e:
            app_ok = False
        results.append(("Web Approval API Endpoint", app_ok, f"Status: {st}, Body: {app_body[:60]}"))
        print(f"  {'✓ PASS' if app_ok else '✗ FAIL'} Web Approval API (/api/web/approvals/{lead_id}) ({st})")
    else:
        results.append(("Lead Detail View", False, "No lead ID found in list"))
        print("  ✗ SKIP No lead ID found")

    # 4. Summary Verdict
    print("\n" + "=" * 70)
    total_tests = len(results)
    passed_tests = sum(1 for _, ok, _ in results if ok)
    failed_tests = total_tests - passed_tests

    print(f"VERDICT: {'ALL PASS' if failed_tests == 0 else f'{failed_tests} FAILED'}")
    print(f"Score: {passed_tests} / {total_tests} ({int(passed_tests / total_tests * 100)}%)")
    print("=" * 70)

    if failed_tests > 0:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    run_tests()
