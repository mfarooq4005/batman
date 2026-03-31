#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from datetime import date, datetime
from typing import Optional, List, Dict, Any

import psycopg2
from fastapi import FastAPI, Query, HTTPException, Header

# =========================================================
# CONFIG
# =========================================================

DB_HOST = os.getenv("DB_HOST", "zk-attendance.cefy4kkume7k.us-east-1.rds.amazonaws.com")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "zk_user")
DB_PASS = os.getenv("DB_PASS", "")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")

API_TOKEN = os.getenv("ATTENDANCE_API_TOKEN", "change-this-token")

app = FastAPI(
    title="Attendance Read-Only API",
    version="1.0.0",
    description="FastAPI service for attendance analytics and OpenClaw integration"
)

# =========================================================
# DB
# =========================================================

def get_db():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        sslmode=DB_SSLMODE
    )

def fetchall_dict(cur) -> List[Dict[str, Any]]:
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in rows]

def fetchone_dict(cur) -> Optional[Dict[str, Any]]:
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))

# =========================================================
# SECURITY
# =========================================================

def verify_token(x_api_token: Optional[str]):
    if not x_api_token or x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# =========================================================
# HELPERS
# =========================================================

def get_scope_ids(
    organization_code: Optional[str] = None,
    campus_code: Optional[str] = None,
    branch_code: Optional[str] = None
):
    conn = get_db()
    cur = conn.cursor()

    org_id = None
    campus_id = None
    branch_id = None

    if organization_code:
        cur.execute(
            "SELECT id FROM organizations WHERE org_code = %s LIMIT 1",
            (organization_code,)
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail=f"Organization not found: {organization_code}")
        org_id = row[0]

    if campus_code:
        if org_id:
            cur.execute("""
                SELECT id
                FROM campuses
                WHERE organization_id = %s AND campus_code = %s
                LIMIT 1
            """, (org_id, campus_code))
        else:
            cur.execute("""
                SELECT id
                FROM campuses
                WHERE campus_code = %s
                LIMIT 1
            """, (campus_code,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail=f"Campus not found: {campus_code}")
        campus_id = row[0]

    if branch_code:
        if campus_id:
            cur.execute("""
                SELECT id
                FROM branches
                WHERE campus_id = %s AND branch_code = %s
                LIMIT 1
            """, (campus_id, branch_code))
        else:
            cur.execute("""
                SELECT id
                FROM branches
                WHERE branch_code = %s
                LIMIT 1
            """, (branch_code,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail=f"Branch not found: {branch_code}")
        branch_id = row[0]

    cur.close()
    conn.close()

    return org_id, campus_id, branch_id

def build_scope_clauses(table_alias: str, org_id, campus_id, branch_id):
    clauses = []
    params = []

    if org_id:
        clauses.append(f"{table_alias}.organization_id = %s")
        params.append(org_id)

    if campus_id:
        clauses.append(f"{table_alias}.campus_id = %s")
        params.append(campus_id)

    if branch_id:
        clauses.append(f"{table_alias}.branch_id = %s")
        params.append(branch_id)

    return clauses, params

# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "attendance-api",
        "version": "1.0.0"
    }

# =========================================================
# TODAY SUMMARY
# =========================================================

@app.get("/api/attendance/summary-today")
def summary_today(
    organization_code: Optional[str] = Query(None),
    campus_code: Optional[str] = Query(None),
    branch_code: Optional[str] = Query(None),
    x_api_token: Optional[str] = Header(None)
):
    verify_token(x_api_token)

    org_id, campus_id, branch_id = get_scope_ids(organization_code, campus_code, branch_code)

    conn = get_db()
    cur = conn.cursor()

    clauses, params = build_scope_clauses("d", org_id, campus_id, branch_id)
    where_sql = " AND ".join(["d.summary_date = CURRENT_DATE"] + clauses)

    cur.execute(f"""
        SELECT
            d.summary_date,
            d.device_sn,
            d.user_id,
            COALESCE(s.staff_name, 'Unknown') AS staff_name,
            COALESCE(s.designation, '') AS designation,
            COALESCE(s.department, '') AS department,
            d.first_in,
            d.last_out,
            d.total_punches,
            d.worked_minutes,
            d.is_late,
            d.late_minutes,
            d.attendance_status,
            COALESCE(o.org_name, '') AS organization_name,
            COALESCE(c.campus_name, '') AS campus_name,
            COALESCE(b.branch_name, '') AS branch_name
        FROM attendance_daily_summary d
        LEFT JOIN device_user_mapping m
            ON m.device_sn = d.device_sn
           AND m.user_id = d.user_id
           AND d.summary_date >= m.valid_from
           AND (m.valid_to IS NULL OR d.summary_date <= m.valid_to)
        LEFT JOIN staff_master s ON s.id = m.staff_id
        LEFT JOIN organizations o ON o.id = d.organization_id
        LEFT JOIN campuses c ON c.id = d.campus_id
        LEFT JOIN branches b ON b.id = d.branch_id
        WHERE {where_sql}
        ORDER BY d.first_in ASC NULLS LAST
    """, params)

    data = fetchall_dict(cur)
    cur.close()
    conn.close()

    return {
        "date": str(date.today()),
        "count": len(data),
        "results": data
    }

# =========================================================
# LATE TODAY
# =========================================================

@app.get("/api/attendance/late-today")
def late_today(
    organization_code: Optional[str] = Query(None),
    campus_code: Optional[str] = Query(None),
    branch_code: Optional[str] = Query(None),
    x_api_token: Optional[str] = Header(None)
):
    verify_token(x_api_token)

    org_id, campus_id, branch_id = get_scope_ids(organization_code, campus_code, branch_code)

    conn = get_db()
    cur = conn.cursor()

    clauses, params = build_scope_clauses("d", org_id, campus_id, branch_id)
    where_sql = " AND ".join(["d.summary_date = CURRENT_DATE", "d.is_late = TRUE"] + clauses)

    cur.execute(f"""
        SELECT
            d.summary_date,
            d.user_id,
            COALESCE(s.staff_name, 'Unknown') AS staff_name,
            COALESCE(s.designation, '') AS designation,
            d.first_in,
            d.late_minutes,
            COALESCE(o.org_name, '') AS organization_name,
            COALESCE(c.campus_name, '') AS campus_name,
            COALESCE(b.branch_name, '') AS branch_name
        FROM attendance_daily_summary d
        LEFT JOIN device_user_mapping m
            ON m.device_sn = d.device_sn
           AND m.user_id = d.user_id
           AND d.summary_date >= m.valid_from
           AND (m.valid_to IS NULL OR d.summary_date <= m.valid_to)
        LEFT JOIN staff_master s ON s.id = m.staff_id
        LEFT JOIN organizations o ON o.id = d.organization_id
        LEFT JOIN campuses c ON c.id = d.campus_id
        LEFT JOIN branches b ON b.id = d.branch_id
        WHERE {where_sql}
        ORDER BY d.first_in ASC
    """, params)

    data = fetchall_dict(cur)
    cur.close()
    conn.close()

    return {
        "date": str(date.today()),
        "count": len(data),
        "results": data
    }

# =========================================================
# MOST LATE
# =========================================================

@app.get("/api/attendance/most-late")
def most_late(
    from_date: str = Query(...),
    to_date: str = Query(...),
    organization_code: Optional[str] = Query(None),
    campus_code: Optional[str] = Query(None),
    branch_code: Optional[str] = Query(None),
    limit: int = Query(10),
    x_api_token: Optional[str] = Header(None)
):
    verify_token(x_api_token)

    org_id, campus_id, branch_id = get_scope_ids(organization_code, campus_code, branch_code)

    conn = get_db()
    cur = conn.cursor()

    clauses, params = build_scope_clauses("d", org_id, campus_id, branch_id)
    where_sql = " AND ".join(["d.summary_date BETWEEN %s AND %s"] + clauses)
    params = [from_date, to_date] + params

    cur.execute(f"""
        SELECT
            d.user_id,
            COALESCE(s.staff_name, 'Unknown') AS staff_name,
            COALESCE(s.designation, '') AS designation,
            COUNT(*) FILTER (WHERE d.is_late = TRUE) AS total_late_days,
            COALESCE(SUM(d.late_minutes), 0) AS total_late_minutes,
            COALESCE(o.org_name, '') AS organization_name,
            COALESCE(c.campus_name, '') AS campus_name,
            COALESCE(b.branch_name, '') AS branch_name
        FROM attendance_daily_summary d
        LEFT JOIN device_user_mapping m
            ON m.device_sn = d.device_sn
           AND m.user_id = d.user_id
           AND d.summary_date >= m.valid_from
           AND (m.valid_to IS NULL OR d.summary_date <= m.valid_to)
        LEFT JOIN staff_master s ON s.id = m.staff_id
        LEFT JOIN organizations o ON o.id = d.organization_id
        LEFT JOIN campuses c ON c.id = d.campus_id
        LEFT JOIN branches b ON b.id = d.branch_id
        WHERE {where_sql}
        GROUP BY d.user_id, s.staff_name, s.designation, o.org_name, c.campus_name, b.branch_name
        ORDER BY total_late_days DESC, total_late_minutes DESC
        LIMIT %s
    """, params + [limit])

    data = fetchall_dict(cur)
    cur.close()
    conn.close()

    return {
        "from_date": from_date,
        "to_date": to_date,
        "count": len(data),
        "results": data
    }

# =========================================================
# MOST ABSENT
# =========================================================

@app.get("/api/attendance/most-absent")
def most_absent(
    summary_month: str = Query(..., description="YYYY-MM-01"),
    organization_code: Optional[str] = Query(None),
    campus_code: Optional[str] = Query(None),
    branch_code: Optional[str] = Query(None),
    limit: int = Query(10),
    x_api_token: Optional[str] = Header(None)
):
    verify_token(x_api_token)

    org_id, campus_id, branch_id = get_scope_ids(organization_code, campus_code, branch_code)

    conn = get_db()
    cur = conn.cursor()

    clauses = ["m.summary_month = %s"]
    params = [summary_month]

    if org_id:
        clauses.append("m.organization_id = %s")
        params.append(org_id)
    if campus_id:
        clauses.append("m.campus_id = %s")
        params.append(campus_id)
    if branch_id:
        clauses.append("m.branch_id = %s")
        params.append(branch_id)

    where_sql = " AND ".join(clauses)

    cur.execute(f"""
        SELECT
            m.user_id,
            COALESCE(s.staff_name, 'Unknown') AS staff_name,
            COALESCE(s.designation, '') AS designation,
            m.total_absent_days,
            m.total_late_days,
            m.total_present_days,
            COALESCE(o.org_name, '') AS organization_name,
            COALESCE(c.campus_name, '') AS campus_name,
            COALESCE(b.branch_name, '') AS branch_name
        FROM attendance_monthly_summary m
        LEFT JOIN staff_master s ON s.id = m.mapped_staff_id
        LEFT JOIN organizations o ON o.id = m.organization_id
        LEFT JOIN campuses c ON c.id = m.campus_id
        LEFT JOIN branches b ON b.id = m.branch_id
        WHERE {where_sql}
        ORDER BY m.total_absent_days DESC, m.total_late_days DESC
        LIMIT %s
    """, params + [limit])

    data = fetchall_dict(cur)
    cur.close()
    conn.close()

    return {
        "summary_month": summary_month,
        "count": len(data),
        "results": data
    }

# =========================================================
# STAFF HISTORY
# =========================================================

@app.get("/api/attendance/staff-history")
def staff_history(
    user_id: str = Query(...),
    from_date: str = Query(...),
    to_date: str = Query(...),
    device_sn: Optional[str] = Query(None),
    x_api_token: Optional[str] = Header(None)
):
    verify_token(x_api_token)

    conn = get_db()
    cur = conn.cursor()

    clauses = ["a.user_id = %s", "a.punch_date BETWEEN %s AND %s"]
    params = [user_id, from_date, to_date]

    if device_sn:
        clauses.append("a.device_sn = %s")
        params.append(device_sn)

    where_sql = " AND ".join(clauses)

    cur.execute(f"""
        SELECT
            a.device_sn,
            a.user_id,
            a.punch_time,
            a.punch_date,
            a.punch_clock,
            a.verify_code,
            a.punch_state,
            a.work_code
        FROM attendance_events a
        WHERE {where_sql}
        ORDER BY a.punch_time ASC
    """, params)

    data = fetchall_dict(cur)
    cur.close()
    conn.close()

    return {
        "user_id": user_id,
        "from_date": from_date,
        "to_date": to_date,
        "count": len(data),
        "results": data
    }

# =========================================================
# BRANCH SUMMARY TODAY
# =========================================================

@app.get("/api/attendance/branch-summary-today")
def branch_summary_today(
    organization_code: Optional[str] = Query(None),
    x_api_token: Optional[str] = Header(None)
):
    verify_token(x_api_token)

    org_id, _, _ = get_scope_ids(organization_code, None, None)

    conn = get_db()
    cur = conn.cursor()

    clauses = ["d.summary_date = CURRENT_DATE"]
    params = []

    if org_id:
        clauses.append("d.organization_id = %s")
        params.append(org_id)

    where_sql = " AND ".join(clauses)

    cur.execute(f"""
        SELECT
            COALESCE(o.org_name, '') AS organization_name,
            COALESCE(c.campus_name, '') AS campus_name,
            COALESCE(b.branch_name, '') AS branch_name,
            COUNT(*) AS total_present,
            COUNT(*) FILTER (WHERE d.is_late = TRUE) AS total_late
        FROM attendance_daily_summary d
        LEFT JOIN organizations o ON o.id = d.organization_id
        LEFT JOIN campuses c ON c.id = d.campus_id
        LEFT JOIN branches b ON b.id = d.branch_id
        WHERE {where_sql}
        GROUP BY o.org_name, c.campus_name, b.branch_name
        ORDER BY o.org_name, c.campus_name, b.branch_name
    """, params)

    data = fetchall_dict(cur)
    cur.close()
    conn.close()

    return {
        "date": str(date.today()),
        "count": len(data),
        "results": data
    }

# =========================================================
# STAFF SEARCH
# =========================================================

@app.get("/api/staff/search")
def staff_search(
    q: str = Query(...),
    x_api_token: Optional[str] = Header(None)
):
    verify_token(x_api_token)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            employee_code,
            staff_name,
            designation,
            department,
            mobile,
            email,
            is_active
        FROM staff_master
        WHERE LOWER(staff_name) LIKE LOWER(%s)
           OR LOWER(COALESCE(employee_code, '')) LIKE LOWER(%s)
        ORDER BY staff_name ASC
        LIMIT 50
    """, (f"%{q}%", f"%{q}%"))

    data = fetchall_dict(cur)
    cur.close()
    conn.close()

    return {
        "query": q,
        "count": len(data),
        "results": data
    }

# =========================================================
# CONTACT CHECK
# =========================================================

@app.get("/api/security/check-contact")
def check_contact(
    phone_number: str = Query(...),
    x_api_token: Optional[str] = Header(None)
):
    verify_token(x_api_token)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            contact_name,
            phone_number,
            role_name,
            is_active,
            can_access_attendance,
            can_access_reports,
            can_receive_alerts,
            can_use_assistant,
            can_chat_normally,
            block_help_messages,
            can_manage_timing,
            is_super_admin
        FROM authorized_contacts
        WHERE phone_number = %s
        LIMIT 1
    """, (phone_number,))

    row = fetchone_dict(cur)
    cur.close()
    conn.close()

    if not row:
        return {"authorized": False, "detail": "Contact not found"}

    return {
        "authorized": bool(row["is_active"] and row["can_use_assistant"]),
        "contact": row
    }

# =========================================================
# CURRENT TIMING
# =========================================================

@app.get("/api/timing/current")
def current_timing(
    organization_code: str = Query(...),
    campus_code: str = Query(...),
    branch_code: str = Query(...),
    target_date: Optional[str] = Query(None),
    x_api_token: Optional[str] = Header(None)
):
    verify_token(x_api_token)

    tdate = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    org_id, campus_id, branch_id = get_scope_ids(organization_code, campus_code, branch_code)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            policy_name,
            effective_from,
            effective_to,
            institution_start,
            teacher_report_offset_minutes,
            head_report_offset_minutes,
            grace_minutes,
            teacher_start,
            teacher_late_after,
            head_start,
            head_late_after,
            absent_after,
            half_day_after,
            shift_end,
            policy_source,
            change_reason,
            is_active
        FROM timing_policies
        WHERE organization_id = %s
          AND campus_id = %s
          AND branch_id = %s
          AND is_active = TRUE
          AND effective_from <= %s
          AND (effective_to IS NULL OR effective_to >= %s)
        ORDER BY effective_from DESC
        LIMIT 1
    """, (org_id, campus_id, branch_id, tdate, tdate))

    row = fetchone_dict(cur)
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="No active timing policy found")

    return {
        "target_date": str(tdate),
        "timing_policy": row
    }