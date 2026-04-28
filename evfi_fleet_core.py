from flask import Flask, jsonify, redirect, request, send_from_directory, url_for
import json
import secrets
import requests
import urllib.parse
import time
import sqlite3
import os
import subprocess
from datetime import datetime, timedelta
from html import escape

app = Flask(__name__)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env_file(path=".env"):
    env_path = path if os.path.isabs(path) else os.path.join(APP_ROOT, path)
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


load_env_file()

# =========================================================
# CONFIG
# =========================================================
DEFAULT_PORT = int(os.getenv("PORT", "8091"))
CLIENT_ID = os.getenv("TESLA_CLIENT_ID", "ec3c3c77-bb9b-4b8b-95cd-86443e2bfc7f")
CLIENT_SECRET = os.getenv("TESLA_CLIENT_SECRET", "ta-secret.O&@kYvSF7aPdg$CB")
REDIRECT_URI = os.getenv("TESLA_REDIRECT_URI", f"http://localhost:{DEFAULT_PORT}/auth/callback")

SCOPES = "openid offline_access vehicle_device_data vehicle_cmds vehicle_charging_cmds"

APP_USER_NAME = os.getenv("APP_USER_NAME", "David")
DEFAULT_WALLET_ADDRESS = os.getenv("DEFAULT_WALLET_ADDRESS", "0x57F81ae3B61725D5506899A46bD9442F8F01c889")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change-this-for-local-demo")
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL", "")
EVFI_TOKEN_ADDRESS = os.getenv("EVFI_TOKEN_ADDRESS", "")
EVFI_REWARDS_ADDRESS = os.getenv("EVFI_REWARDS_ADDRESS", "")
WEEKLY_REWARD_POOL = os.getenv("WEEKLY_REWARD_POOL", "10000")
MAX_WEEKLY_EVFI = float(os.getenv("MAX_WEEKLY_EVFI", "1000"))
ONBOARDING_AIRDROP_EVFI = float(os.getenv("ONBOARDING_AIRDROP_EVFI", "100"))
WEEKLY_SCORE_BOOTSTRAP_FLOOR = float(os.getenv("WEEKLY_SCORE_BOOTSTRAP_FLOOR", "10000"))
MISSION_BONUS_CAP_SHARE = float(os.getenv("MISSION_BONUS_CAP_SHARE", "0.25"))
EVFI_ASSIGN_SCRIPT = os.getenv("EVFI_ASSIGN_SCRIPT", "evfi_assign_rewards.mjs")

MINIMUM_TRIP_DISTANCE = 2.0
MINIMUM_TRIP_DURATION_SECONDS = 5 * 60
MINIMUM_AVERAGE_SPEED = 12.0
MAX_AVERAGE_SPEED = 95.0
MAX_DAILY_MILES = 300.0
DUPLICATE_SYNC_WINDOW_SECONDS = 10 * 60
MIN_SYNC_INTERVAL_SECONDS = 60
SPORT_MODE_DURATION_SECONDS = 15 * 60
SPORT_MODE_USES_PER_DAY = 1
SPORT_MODE_COOLDOWN_SECONDS = 24 * 60 * 60
CHALLENGE_TARGET_DRIVE_25 = 25.0
CHALLENGE_TARGET_SYNC_3_DAY_STREAK = 3.0
CHALLENGE_TARGET_EARN_250_EVFI = 250.0
SYNC_PARTICIPATION_POINTS = 5.0
SYNC_PARTICIPATION_CAP = 20.0
HEALTHY_CHARGE_SESSION_POINTS = 10.0
HEALTHY_CHARGE_SCORE_CAP = 30.0
HIGH_SOC_CHARGE_PENALTY = 12.5
OFFPEAK_CHARGE_SESSION_POINTS = 6.0
OFFPEAK_CHARGE_SCORE_CAP = 18.0
AC_CHARGE_SESSION_POINTS = 4.0
AC_CHARGE_SCORE_CAP = 12.0
FAST_CHARGE_SESSION_PENALTY = 8.0
FAST_CHARGE_PENALTY_CAP = 24.0
EFFICIENCY_BONUS_CAP = 35.0
EFFICIENCY_PENALTY_CAP = 20.0
TELEMETRY_REJECTION_PENALTY = 15.0
OFFPEAK_START_HOUR = int(os.getenv("OFFPEAK_START_HOUR", "22"))
OFFPEAK_END_HOUR = int(os.getenv("OFFPEAK_END_HOUR", "6"))
CHARGE_SESSION_GAP_SECONDS = int(os.getenv("CHARGE_SESSION_GAP_SECONDS", str(3 * 60 * 60)))
HEALTHY_CHARGE_MIN_SOC = float(os.getenv("HEALTHY_CHARGE_MIN_SOC", "15"))
HEALTHY_CHARGE_MAX_SOC = float(os.getenv("HEALTHY_CHARGE_MAX_SOC", "80"))
HIGH_SOC_THRESHOLD = float(os.getenv("HIGH_SOC_THRESHOLD", "95"))
AC_CHARGE_MAX_KW = float(os.getenv("AC_CHARGE_MAX_KW", "19.5"))
FAST_CHARGE_MIN_KW = float(os.getenv("FAST_CHARGE_MIN_KW", "45"))

CHALLENGE_DEFS = {
    "drive_25_miles_weekly": {
        "label": "Drive 25 Miles This Week",
        "target": CHALLENGE_TARGET_DRIVE_25,
        "window": "weekly",
    },
    "sync_3_days_in_a_row": {
        "label": "Sync 3 Days In A Row",
        "target": CHALLENGE_TARGET_SYNC_3_DAY_STREAK,
        "window": "weekly",
    },
    "earn_250_evfi": {
        "label": "Earn 250 EVFi",
        "target": CHALLENGE_TARGET_EARN_250_EVFI,
        "window": "monthly",
    },
}

BADGE_DEFS = {
    "first_sync": "First Sync Badge",
    "streak_7_days": "7-Day Streak Badge",
    "miles_100": "100 Miles Synced Badge",
    "miles_500": "500 Miles Synced Badge",
    "first_evfi_claim": "First EVFi Claim Badge",
}

STATE = secrets.token_urlsafe(32)
LEGACY_DB_PATH = "drivetoken.db"
DB_PATH = os.getenv("EVFI_DB_PATH", "evfi_demo.db")
if not os.path.exists(DB_PATH) and os.path.exists(LEGACY_DB_PATH):
    DB_PATH = LEGACY_DB_PATH

# Put your mock vehicle image here:
# static/car-avatar.jpg
LOCAL_CAR_IMAGE_PATH = "static/car-avatar.jpg"


# =========================================================
# DATABASE HELPERS
# =========================================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_ts():
    return int(time.time())


def current_week_bounds(ts=None):
    current = datetime.fromtimestamp(ts or now_ts())
    week_start_dt = current - timedelta(days=current.weekday())
    week_start_dt = week_start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end_dt = week_start_dt + timedelta(days=7) - timedelta(seconds=1)
    return int(week_start_dt.timestamp()), int(week_end_dt.timestamp())


def calendar_day(ts=None):
    return datetime.fromtimestamp(ts or now_ts()).strftime("%Y-%m-%d")


def parse_calendar_day(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def challenge_window_bounds(window_type, ts=None):
    current_ts = int(ts or now_ts())
    current = datetime.fromtimestamp(current_ts)
    if window_type == "weekly":
        start, end = current_week_bounds(current_ts)
        return ("weekly", start, end, f"week:{start}")
    if window_type == "monthly":
        month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        month_end = int(next_month.timestamp()) - 1
        start = int(month_start.timestamp())
        return ("monthly", start, month_end, f"month:{month_start.year:04d}-{month_start.month:02d}")
    return ("all_time", 0, 4102444799, "all_time")


def fmt2(value):
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def fmt2_grouped(value):
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def value_tone(value):
    try:
        return "positive" if float(value) > 0 else "negative"
    except (TypeError, ValueError):
        return "negative"


def fmt_ts(value):
    return time.strftime("%b %d, %Y %I:%M %p", time.localtime(int(value))) if value else "Never"


def log_v2_event(event_name, **payload):
    app.logger.info("[evfi-v2] %s %s", event_name, json.dumps(payload, sort_keys=True, default=str))


def log_rule_violation(rule_name, **payload):
    app.logger.warning("[evfi-v2-rule] %s %s", rule_name, json.dumps(payload, sort_keys=True, default=str))


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def parse_json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def is_offpeak_hour(local_hour):
    hour = int(local_hour or 0)
    if OFFPEAK_START_HOUR == OFFPEAK_END_HOUR:
        return True
    if OFFPEAK_START_HOUR < OFFPEAK_END_HOUR:
        return OFFPEAK_START_HOUR <= hour < OFFPEAK_END_HOUR
    return hour >= OFFPEAK_START_HOUR or hour < OFFPEAK_END_HOUR


def build_charge_policy_summary():
    return {
        "offpeakStartHour": OFFPEAK_START_HOUR,
        "offpeakEndHour": OFFPEAK_END_HOUR,
        "sessionGapSeconds": CHARGE_SESSION_GAP_SECONDS,
        "healthyChargeMinSoc": round(HEALTHY_CHARGE_MIN_SOC, 2),
        "healthyChargeMaxSoc": round(HEALTHY_CHARGE_MAX_SOC, 2),
        "highSocThreshold": round(HIGH_SOC_THRESHOLD, 2),
        "acChargeMaxKw": round(AC_CHARGE_MAX_KW, 2),
        "fastChargeMinKw": round(FAST_CHARGE_MIN_KW, 2),
    }


def classify_charge_session(session):
    session["healthy"] = session["start_battery"] >= HEALTHY_CHARGE_MIN_SOC and session["max_battery"] <= HEALTHY_CHARGE_MAX_SOC
    session["high_soc"] = session["max_battery"] >= HIGH_SOC_THRESHOLD
    session["ac_charge"] = session["max_charge_rate"] > 0 and session["max_charge_rate"] <= AC_CHARGE_MAX_KW
    session["fast_charge"] = session["max_charge_rate"] >= FAST_CHARGE_MIN_KW
    session["session_hours"] = round(max(0.0, (session["session_end_ts"] - session["session_start_ts"]) / 3600), 2)
    return session


def append_charge_session_record(cur, user_id, session, status="closed"):
    session = classify_charge_session(dict(session))
    cur.execute(
        """
        INSERT INTO charge_sessions
        (user_id, session_start_ts, session_end_ts, last_synced_at, start_battery, end_battery, max_battery, snapshot_count, avg_charge_rate, max_charge_rate, offpeak, healthy, high_soc, ac_charge, fast_charge, status, details_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            int(session["session_start_ts"]),
            int(session["session_end_ts"]),
            int(session["last_synced_at"]),
            as_float(session["start_battery"], 0.0),
            as_float(session["end_battery"], 0.0),
            as_float(session["max_battery"], 0.0),
            int(session["snapshot_count"]),
            as_float(session["avg_charge_rate"], 0.0),
            as_float(session["max_charge_rate"], 0.0),
            1 if session.get("offpeak") else 0,
            1 if session.get("healthy") else 0,
            1 if session.get("high_soc") else 0,
            1 if session.get("ac_charge") else 0,
            1 if session.get("fast_charge") else 0,
            status,
            json.dumps({"sessionHours": session["session_hours"]}, sort_keys=True),
            now_ts(),
            now_ts(),
        ),
    )


def rebuild_charge_sessions(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS total FROM charge_sessions")
    if int(cur.fetchone()["total"] or 0) > 0:
        return

    cur.execute(
        """
        SELECT user_id, synced_at, battery_level, charging_state, charge_rate
        FROM gamification_sync_history
        WHERE user_id IS NOT NULL
          AND charging_state IS NOT NULL
          AND lower(charging_state) IN ('charging', 'complete')
        ORDER BY user_id ASC, synced_at ASC, id ASC
        """
    )
    rows = cur.fetchall()
    current_user_id = None
    current_session = None
    for row in rows:
        user_id = int(row["user_id"])
        synced_at = int(row["synced_at"] or 0)
        battery_level = as_float(row["battery_level"], 0.0)
        charge_rate = as_float(row["charge_rate"], 0.0)
        charging_state = str(row["charging_state"] or "").lower()
        local_hour = datetime.fromtimestamp(synced_at).hour
        needs_new = (
            current_session is None
            or current_user_id != user_id
            or (synced_at - current_session["last_synced_at"]) > CHARGE_SESSION_GAP_SECONDS
        )
        if needs_new:
            if current_session is not None:
                append_charge_session_record(cur, current_user_id, current_session, status="closed")
            current_user_id = user_id
            current_session = {
                "session_start_ts": synced_at,
                "session_end_ts": synced_at,
                "last_synced_at": synced_at,
                "start_battery": battery_level,
                "end_battery": battery_level,
                "max_battery": battery_level,
                "snapshot_count": 1,
                "avg_charge_rate": charge_rate,
                "max_charge_rate": charge_rate,
                "offpeak": is_offpeak_hour(local_hour),
            }
        else:
            current_session["session_end_ts"] = synced_at
            current_session["last_synced_at"] = synced_at
            current_session["end_battery"] = battery_level
            current_session["max_battery"] = max(current_session["max_battery"], battery_level)
            current_session["snapshot_count"] += 1
            current_session["avg_charge_rate"] = ((current_session["avg_charge_rate"] * (current_session["snapshot_count"] - 1)) + charge_rate) / current_session["snapshot_count"]
            current_session["max_charge_rate"] = max(current_session["max_charge_rate"], charge_rate)
            current_session["offpeak"] = current_session["offpeak"] or is_offpeak_hour(local_hour)

        if charging_state == "complete":
            append_charge_session_record(cur, current_user_id, current_session, status="closed")
            current_session = None
            current_user_id = None

    if current_session is not None and current_user_id is not None:
        append_charge_session_record(cur, current_user_id, current_session, status="closed")


def update_or_close_charge_session(user_id, synced_at, battery_level, charging_state, charge_rate):
    state = str(charging_state or "").lower()
    is_charging = state in ("charging", "complete")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM charge_sessions
        WHERE user_id = ? AND status = 'open'
        ORDER BY session_start_ts DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    active = cur.fetchone()
    active_id = int(active["id"]) if active else None

    if active and (int(synced_at) - int(active["last_synced_at"] or active["session_end_ts"] or 0)) > CHARGE_SESSION_GAP_SECONDS:
        cur.execute(
            "UPDATE charge_sessions SET status = 'closed', updated_at = ? WHERE id = ?",
            (now_ts(), active_id),
        )
        active = None
        active_id = None

    if not is_charging:
        if active_id is not None:
            cur.execute(
                "UPDATE charge_sessions SET status = 'closed', updated_at = ? WHERE id = ?",
                (now_ts(), active_id),
            )
        conn.commit()
        conn.close()
        return

    local_hour = datetime.fromtimestamp(int(synced_at)).hour
    if active is None:
        session = classify_charge_session(
            {
                "session_start_ts": int(synced_at),
                "session_end_ts": int(synced_at),
                "last_synced_at": int(synced_at),
                "start_battery": as_float(battery_level, 0.0),
                "end_battery": as_float(battery_level, 0.0),
                "max_battery": as_float(battery_level, 0.0),
                "snapshot_count": 1,
                "avg_charge_rate": as_float(charge_rate, 0.0),
                "max_charge_rate": as_float(charge_rate, 0.0),
                "offpeak": is_offpeak_hour(local_hour),
            }
        )
        cur.execute(
            """
            INSERT INTO charge_sessions
            (user_id, session_start_ts, session_end_ts, last_synced_at, start_battery, end_battery, max_battery, snapshot_count, avg_charge_rate, max_charge_rate, offpeak, healthy, high_soc, ac_charge, fast_charge, status, details_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                session["session_start_ts"],
                session["session_end_ts"],
                session["last_synced_at"],
                session["start_battery"],
                session["end_battery"],
                session["max_battery"],
                session["snapshot_count"],
                session["avg_charge_rate"],
                session["max_charge_rate"],
                1 if session["offpeak"] else 0,
                1 if session["healthy"] else 0,
                1 if session["high_soc"] else 0,
                1 if session["ac_charge"] else 0,
                1 if session["fast_charge"] else 0,
                "open" if state == "charging" else "closed",
                json.dumps({"sessionHours": session["session_hours"]}, sort_keys=True),
                now_ts(),
                now_ts(),
            ),
        )
    else:
        snapshot_count = int(active["snapshot_count"] or 0) + 1
        avg_charge_rate = (
            (as_float(active["avg_charge_rate"], 0.0) * int(active["snapshot_count"] or 0)) + as_float(charge_rate, 0.0)
        ) / max(snapshot_count, 1)
        session = classify_charge_session(
            {
                "session_start_ts": int(active["session_start_ts"] or synced_at),
                "session_end_ts": int(synced_at),
                "last_synced_at": int(synced_at),
                "start_battery": as_float(active["start_battery"], battery_level),
                "end_battery": as_float(battery_level, 0.0),
                "max_battery": max(as_float(active["max_battery"], 0.0), as_float(battery_level, 0.0)),
                "snapshot_count": snapshot_count,
                "avg_charge_rate": avg_charge_rate,
                "max_charge_rate": max(as_float(active["max_charge_rate"], 0.0), as_float(charge_rate, 0.0)),
                "offpeak": bool(int(active["offpeak"] or 0)) or is_offpeak_hour(local_hour),
            }
        )
        cur.execute(
            """
            UPDATE charge_sessions
            SET session_end_ts = ?,
                last_synced_at = ?,
                end_battery = ?,
                max_battery = ?,
                snapshot_count = ?,
                avg_charge_rate = ?,
                max_charge_rate = ?,
                offpeak = ?,
                healthy = ?,
                high_soc = ?,
                ac_charge = ?,
                fast_charge = ?,
                status = ?,
                details_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                session["session_end_ts"],
                session["last_synced_at"],
                session["end_battery"],
                session["max_battery"],
                session["snapshot_count"],
                session["avg_charge_rate"],
                session["max_charge_rate"],
                1 if session["offpeak"] else 0,
                1 if session["healthy"] else 0,
                1 if session["high_soc"] else 0,
                1 if session["ac_charge"] else 0,
                1 if session["fast_charge"] else 0,
                "open" if state == "charging" else "closed",
                json.dumps({"sessionHours": session["session_hours"]}, sort_keys=True),
                now_ts(),
                active_id,
            ),
        )
    conn.commit()
    conn.close()


def repair_reward_event_history(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, tesla_vehicle_id, odometer_reading, miles_added, drv_earned, verified_miles
        FROM reward_events
        ORDER BY tesla_vehicle_id ASC, synced_at ASC, id ASC
        """
    )
    rows = cur.fetchall()

    previous_odometer_by_vehicle = {}
    updates = []
    for row in rows:
        vehicle_id = str(row["tesla_vehicle_id"] or "")
        odometer = as_float(row["odometer_reading"], 0.0)
        previous_odometer = previous_odometer_by_vehicle.get(vehicle_id)
        calculated_miles = 0.0 if previous_odometer is None else max(0.0, odometer - previous_odometer)
        current_miles = max(0.0, as_float(row["miles_added"], 0.0))
        verified_miles = row["verified_miles"]
        if verified_miles is None:
            verified_miles = row["drv_earned"]
        if verified_miles is None:
            verified_miles = row["miles_added"]
        verified_miles = max(0.0, as_float(verified_miles, 0.0))
        current_score = max(0.0, as_float(row["drv_earned"], 0.0))
        if abs(current_miles - calculated_miles) > 1e-6 or row["verified_miles"] is None or abs(current_score - verified_miles) > 1e-6:
            updates.append((calculated_miles, verified_miles, verified_miles, int(row["id"])))
        previous_odometer_by_vehicle[vehicle_id] = odometer

    if updates:
        cur.executemany(
            """
            UPDATE reward_events
            SET miles_added = ?,
                verified_miles = ?,
                drv_earned = ?
            WHERE id = ?
            """,
            updates,
        )
        log_v2_event("reward_event_history_repaired", updated_rows=len(updates))


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicle_rewards (
        tesla_vehicle_id TEXT PRIMARY KEY,
        display_name TEXT,
        vin TEXT,
        baseline_odometer REAL,
        latest_odometer REAL,
        total_miles REAL DEFAULT 0,
        drv_balance REAL DEFAULT 0,
        last_synced_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reward_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tesla_vehicle_id TEXT,
        odometer_reading REAL,
        miles_added REAL,
        drv_earned REAL,
        synced_at INTEGER
    )
    """)

    try:
        cur.execute("ALTER TABLE reward_events ADD COLUMN user_id INTEGER")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE reward_events ADD COLUMN verified_miles REAL")
    except sqlite3.OperationalError:
        pass

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wallet_address TEXT UNIQUE,
        created_at INTEGER,
        sport_mode_active INTEGER DEFAULT 0,
        sport_mode_start_time INTEGER,
        sport_mode_end_time INTEGER,
        sport_mode_uses_today INTEGER DEFAULT 0,
        sport_mode_last_used INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicles (
        vin TEXT PRIMARY KEY,
        user_id INTEGER,
        odometer_last REAL,
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS weekly_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        vin TEXT,
        week_start INTEGER,
        week_end INTEGER,
        verified_miles REAL,
        active_days INTEGER,
        charge_health_score REAL,
        streak_multiplier REAL,
        mission_bonus REAL,
        total_score REAL,
        created_at INTEGER,
        UNIQUE(user_id, vin, week_start)
    )
    """)

    try:
        cur.execute("ALTER TABLE weekly_scores ADD COLUMN score_breakdown_json TEXT")
    except sqlite3.OperationalError:
        pass

    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        mission_type TEXT,
        progress REAL DEFAULT 0,
        completed INTEGER DEFAULT 0,
        completed_at INTEGER,
        UNIQUE(user_id, mission_type)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        week_start INTEGER,
        week_end INTEGER,
        score REAL,
        evfi_allocated REAL,
        claimed INTEGER DEFAULT 0,
        claimed_at INTEGER,
        UNIQUE(user_id, week_start, week_end)
    )
    """)

    try:
        cur.execute("ALTER TABLE claims ADD COLUMN reward_type TEXT DEFAULT 'weekly'")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE claims ADD COLUMN allocation_context_json TEXT")
    except sqlite3.OperationalError:
        pass

    cur.execute("""
    CREATE TABLE IF NOT EXISTS mission_badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        mission_type TEXT,
        week_start INTEGER,
        badge_asset TEXT,
        created_at INTEGER,
        UNIQUE(user_id, mission_type, week_start)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS weekly_resets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        week_start INTEGER,
        reset_at INTEGER,
        UNIQUE(user_id, week_start)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gamification_state (
        user_id INTEGER PRIMARY KEY,
        last_activity_date TEXT,
        last_login_date TEXT,
        last_sync_date TEXT,
        last_reward_check_date TEXT,
        current_streak INTEGER DEFAULT 0,
        longest_streak INTEGER DEFAULT 0,
        completed_challenges_count INTEGER DEFAULT 0,
        total_miles_synced REAL DEFAULT 0,
        lifetime_evfi_earned REAL DEFAULT 0,
        last_known_odometer REAL,
        total_sync_events INTEGER DEFAULT 0,
        telemetry_sync_count INTEGER DEFAULT 0,
        last_sync_at INTEGER,
        updated_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gamification_challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        challenge_key TEXT,
        progress REAL DEFAULT 0,
        target REAL DEFAULT 0,
        completed INTEGER DEFAULT 0,
        completed_at INTEGER,
        last_updated INTEGER,
        UNIQUE(user_id, challenge_key)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gamification_challenge_windows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        challenge_key TEXT,
        window_key TEXT,
        window_start INTEGER,
        window_end INTEGER,
        progress REAL DEFAULT 0,
        target REAL DEFAULT 0,
        completed INTEGER DEFAULT 0,
        completed_at INTEGER,
        active INTEGER DEFAULT 1,
        last_updated INTEGER,
        UNIQUE(user_id, challenge_key, window_key)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gamification_badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        badge_key TEXT,
        badge_name TEXT,
        badge_asset TEXT,
        awarded_at INTEGER,
        UNIQUE(user_id, badge_key)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gamification_evfi_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        event_key TEXT,
        source TEXT,
        amount REAL DEFAULT 0,
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(user_id, event_key)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gamification_sync_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        synced_at INTEGER,
        odometer REAL,
        miles_delta REAL DEFAULT 0,
        verified_miles REAL DEFAULT 0,
        battery_level REAL,
        charging_state TEXT,
        charge_rate REAL,
        efficiency_whmi REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gamification_activity_feed (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        event_type TEXT,
        source TEXT,
        details_json TEXT,
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS utility_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action_key TEXT,
        action_type TEXT,
        amount_evfi REAL DEFAULT 0,
        status TEXT DEFAULT 'completed',
        details_json TEXT,
        created_at INTEGER,
        completed_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS staking_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tier_key TEXT,
        stake_evfi REAL DEFAULT 0,
        reward_boost_pct REAL DEFAULT 0,
        status TEXT DEFAULT 'active',
        details_json TEXT,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS charge_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        session_start_ts INTEGER,
        session_end_ts INTEGER,
        last_synced_at INTEGER,
        start_battery REAL,
        end_battery REAL,
        max_battery REAL,
        snapshot_count INTEGER DEFAULT 0,
        avg_charge_rate REAL,
        max_charge_rate REAL,
        offpeak INTEGER DEFAULT 0,
        healthy INTEGER DEFAULT 0,
        high_soc INTEGER DEFAULT 0,
        ac_charge INTEGER DEFAULT 0,
        fast_charge INTEGER DEFAULT 0,
        status TEXT DEFAULT 'open',
        details_json TEXT,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    repair_reward_event_history(conn)
    rebuild_charge_sessions(conn)
    conn.commit()
    conn.close()


# =========================================================
# TESLA API
# =========================================================
class TeslaAPI:
    def __init__(self, client_id, client_secret, redirect_uri, scopes):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.tokens = {}
        self.state = STATE

    def valid(self):
        return self.tokens and (
            int(time.time()) - self.tokens["obtained_at"] < self.tokens["expires_in"] - 60
        )

    def refresh(self):
        r = requests.post(
            "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.tokens["refresh_token"]
            },
            timeout=30
        ).json()

        r["obtained_at"] = int(time.time())
        self.tokens.update(r)

    def api_get(self, path):
        if not self.valid():
            self.refresh()

        return requests.get(
            f"https://fleet-api.prd.na.vn.cloud.tesla.com{path}",
            headers={"Authorization": f"Bearer {self.tokens['access_token']}"},
            timeout=30
        )

    def api_post(self, path):
        if not self.valid():
            self.refresh()

        return requests.post(
            f"https://fleet-api.prd.na.vn.cloud.tesla.com{path}",
            headers={"Authorization": f"Bearer {self.tokens['access_token']}"},
            timeout=30
        )

    def get_vehicles(self):
        resp = self.api_get("/api/1/vehicles")
        try:
            return resp.json().get("response", [])
        except Exception:
            return []

    def get_vehicle_state(self, vid):
        vehicles = self.get_vehicles()
        vehicle = next((v for v in vehicles if str(v.get("id")) == str(vid)), None)
        return vehicle.get("state") if vehicle else None

    def wake_up_vehicle(self, vid):
        return self.api_post(f"/api/1/vehicles/{vid}/wake_up")

    def get_vehicle_data(self, vid):
        return self.api_get(f"/api/1/vehicles/{vid}/vehicle_data")


tesla_api = TeslaAPI(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPES)


# =========================================================
# UI HELPERS
# =========================================================
BASE_CSS = """
<style>
    :root{
        --bg:#06070b;
        --bg2:#0b1020;
        --panel:#111318;
        --panel2:#151922;
        --stroke:rgba(255,255,255,.07);
        --text:#f5f7fb;
        --muted:#9ca3af;
        --red:#ff2d46;
        --green:#20e37c;
        --blue:#69a7ff;
        --shadow:0 24px 70px rgba(0,0,0,.48);
    }

    *{ box-sizing:border-box; }

    body{
        margin:0;
        color:var(--text);
        background:
            radial-gradient(circle at top left, rgba(255,45,70,.08), transparent 26%),
            radial-gradient(circle at top right, rgba(105,167,255,.08), transparent 28%),
            linear-gradient(180deg, #050608 0%, #080a10 100%);
        font-family:'Inter', sans-serif;
        min-height:100vh;
    }

    body::before{
        content:"";
        position:fixed;
        inset:0;
        pointer-events:none;
        background-image:
          linear-gradient(rgba(255,255,255,.022) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,.022) 1px, transparent 1px);
        background-size:32px 32px;
        opacity:.22;
    }

    .shell{
        width:min(1320px, 94vw);
        margin:26px auto;
        position:relative;
        z-index:1;
    }

    .dashboard-brand-banner{
        width:min(980px, 92vw);
        min-height:88px;
        border-radius:18px;
        border:1px solid rgba(110,188,255,.22);
        background:
            linear-gradient(90deg, rgba(4,8,18,.86) 0%, rgba(4,8,18,.34) 42%, rgba(4,8,18,.82) 100%),
            url('/static/EVFi-banner-dark.png') center center / contain no-repeat;
        box-shadow:0 18px 54px rgba(0,0,0,.38);
        margin:0 auto 16px;
        position:relative;
        overflow:hidden;
    }

    .dashboard-brand-banner::after{
        content:"";
        position:absolute;
        inset:auto 28px 18px 28px;
        height:1px;
        background:linear-gradient(90deg, transparent, rgba(32,227,124,.45), rgba(65,189,255,.45), transparent);
    }

    .hero{
        display:flex;
        justify-content:space-between;
        align-items:center;
        gap:18px;
        background:linear-gradient(180deg, rgba(18,20,27,.96), rgba(14,17,24,.98));
        border:1px solid var(--stroke);
        border-radius:24px;
        box-shadow:var(--shadow);
        padding:28px;
        margin-bottom:22px;
        position:relative;
        overflow:hidden;
    }

    .hero-auth{
        min-height:176px;
        align-items:center;
        justify-content:flex-end;
        gap:0;
        margin-bottom:14px;
        background:
            linear-gradient(108deg, rgba(3,7,18,.92) 0%, rgba(4,11,24,.88) 42%, rgba(4,10,20,.24) 100%),
            url('/static/EVFi-banner-dark.png') center center / cover no-repeat;
        border-color:rgba(110,188,255,.28);
        box-shadow:0 26px 80px rgba(2,7,20,.62);
    }

    .hero-auth::before{
        content:"";
        position:absolute;
        inset:0;
        background:
            radial-gradient(circle at 8% 10%, rgba(123,45,255,.34), transparent 44%),
            radial-gradient(circle at 26% 84%, rgba(0,200,255,.22), transparent 50%),
            linear-gradient(180deg, rgba(2,6,15,.2), rgba(2,6,15,.62));
        pointer-events:none;
    }

    .hero-auth::after{
        content:"";
        position:absolute;
        inset:0;
        background:
            linear-gradient(90deg, rgba(3,8,18,.34) 0%, rgba(3,8,18,.16) 34%, rgba(3,8,18,.22) 72%, rgba(3,8,18,.5) 100%),
            linear-gradient(180deg, rgba(2,6,16,.18), rgba(2,6,16,.48));
        pointer-events:none;
    }

    .pre-auth-info{
        min-height:220px;
        align-items:flex-end;
        justify-content:space-between;
        gap:20px;
        background:linear-gradient(180deg, rgba(16,20,31,.95), rgba(12,16,26,.98));
        border-color:rgba(127,180,255,.24);
        box-shadow:0 20px 48px rgba(2,8,20,.46);
    }

    .pre-auth-copy{
        position:relative;
        z-index:1;
        max-width:760px;
    }

    .pre-auth-actions{
        display:flex;
        align-items:center;
        justify-content:flex-end;
        min-width:220px;
    }

    .pre-auth-info h1{
        margin:0;
        font-size:50px;
        line-height:.98;
        letter-spacing:-.035em;
    }

    .pre-auth-info p{
        margin-top:14px;
        max-width:56ch;
        color:#b9c7da;
    }

    .hero h1{
        margin:0;
        font-family:'Oxanium', sans-serif;
        font-size:48px;
        line-height:1;
        letter-spacing:-.03em;
        font-weight:700;
    }

    .hero p{
        margin:12px 0 0;
        color:var(--muted);
        font-size:18px;
        line-height:1.5;
    }

    .badge{
        display:inline-block;
        padding:10px 14px;
        border-radius:999px;
        background:rgba(255,45,70,.12);
        border:1px solid rgba(255,45,70,.18);
        color:#ffd9df;
        font-size:12px;
        letter-spacing:.08em;
        text-transform:uppercase;
        font-weight:700;
        margin-bottom:14px;
        font-family:'Oxanium', sans-serif;
    }

    .btn, .wallet-btn, .soft-link{
        text-decoration:none;
        cursor:pointer;
    }

    .btn{
        display:inline-flex;
        align-items:center;
        justify-content:center;
        gap:10px;
        color:white;
        padding:14px 20px;
        border-radius:16px;
        border:1px solid rgba(255,255,255,.08);
        font-family:'Oxanium', sans-serif;
        font-size:16px;
        font-weight:700;
        min-width:150px;
    }

    .btn-primary{
        color:#06111f;
        background:linear-gradient(135deg, #1fe37c 0%, #44d9ff 100%);
        border-color:rgba(127,238,255,.56);
        box-shadow:
            0 8px 0 rgba(8, 70, 96, .95),
            0 16px 28px rgba(1, 10, 24, .42),
            inset 0 1px 0 rgba(255,255,255,.48);
    }

    .btn-primary:active{
        transform:translateY(4px);
        box-shadow:
            0 3px 0 rgba(8, 70, 96, .95),
            0 8px 16px rgba(1, 10, 24, .34),
            inset 0 1px 0 rgba(255,255,255,.38);
    }

    .btn-secondary{
        color:#d8e8ff;
        border-color:rgba(110,188,255,.3);
        background:linear-gradient(180deg, rgba(20,31,52,.78), rgba(12,20,36,.82));
        box-shadow:
            0 8px 0 rgba(12, 20, 36, .95),
            0 16px 28px rgba(2, 9, 20, .36),
            inset 0 1px 0 rgba(170, 220, 255, .1);
    }

    .btn-secondary:hover{
        border-color:rgba(138,212,255,.52);
        background:linear-gradient(180deg, rgba(26,41,67,.86), rgba(14,24,42,.88));
    }

    .btn-secondary:active{
        transform:translateY(4px);
        box-shadow:
            0 3px 0 rgba(12, 20, 36, .95),
            0 8px 16px rgba(2, 9, 20, .3),
            inset 0 1px 0 rgba(170, 220, 255, .08);
    }

    .vehicle-list{
        display:grid;
        grid-template-columns:repeat(auto-fit, minmax(300px,1fr));
        gap:16px;
    }

    .vehicle-card,
    .panel, .stat-card, .vehicle-panel, .history-panel{
        background:linear-gradient(180deg, rgba(18,20,27,.96), rgba(14,17,24,.98));
        border:1px solid var(--stroke);
        border-radius:16px;
        box-shadow:var(--shadow);
    }

    .vehicle-card{
        padding:20px;
    }

    .vehicle-card h3{
        margin:0 0 8px;
        font-family:'Oxanium', sans-serif;
        font-size:26px;
    }

    .vehicle-meta{
        color:var(--muted);
        font-size:15px;
        line-height:1.6;
        margin-bottom:16px;
    }

    .vehicle-actions{
        display:flex;
        gap:10px;
        flex-wrap:wrap;
    }

    .topbar{
        display:grid;
        grid-template-columns:minmax(0, 1.16fr) minmax(360px, .84fr);
        gap:16px;
        margin-bottom:16px;
        align-items:stretch;
    }

    .hero-copy, .hero-vehicle{
        padding:28px;
        position:relative;
        overflow:hidden;
    }

    .hero-copy::before, .hero-vehicle::before{
        content:"";
        position:absolute;
        inset:auto -40px -70px auto;
        width:240px;
        height:240px;
        border-radius:50%;
        background:radial-gradient(circle, rgba(105,167,255,.15), transparent 72%);
        pointer-events:none;
    }

    .eyebrow{
        display:inline-flex;
        align-items:center;
        gap:10px;
        padding:10px 14px;
        border-radius:999px;
        border:1px solid rgba(255,255,255,.08);
        background:rgba(255,255,255,.03);
        color:#c8d0de;
        font-size:12px;
        text-transform:uppercase;
        letter-spacing:.14em;
        font-weight:700;
        margin-bottom:18px;
    }

    .hero-vehicle{
        display:grid;
        grid-template-columns:minmax(0, 1.1fr) 220px;
        gap:16px;
        align-items:center;
        background:
            radial-gradient(circle at 18% 16%, rgba(255,45,70,.16), transparent 26%),
            radial-gradient(circle at 84% 22%, rgba(105,167,255,.18), transparent 24%),
            linear-gradient(135deg, rgba(17,19,27,.98), rgba(11,13,19,.98));
    }

    .vehicle-hero-meta{
        position:relative;
        z-index:1;
    }

    .vehicle-hero-copy{
        max-width:720px;
    }

    .vehicle-hero-title{
        margin:0;
        font-size:40px;
        line-height:1;
        font-family:'Oxanium', sans-serif;
        font-weight:700;
        letter-spacing:-.04em;
    }

    .vehicle-hero-sub{
        margin-top:10px;
        color:#c7cfdb;
        font-size:15px;
        line-height:1.6;
    }

    .vehicle-hero-topline{
        display:flex;
        align-items:center;
        gap:10px;
        flex-wrap:wrap;
        margin-bottom:16px;
    }

    .vehicle-state-pill{
        display:inline-flex;
        align-items:center;
        gap:8px;
        padding:9px 12px;
        border-radius:999px;
        border:1px solid rgba(255,255,255,.08);
        background:rgba(255,255,255,.04);
        color:#eef3fb;
        font-size:12px;
        font-weight:700;
        letter-spacing:.12em;
        text-transform:uppercase;
    }

    .vehicle-state-pill::before{
        content:"";
        width:8px;
        height:8px;
        border-radius:50%;
        background:var(--green);
        box-shadow:0 0 0 6px rgba(32,227,124,.1);
    }

    .vehicle-hero-data{
        display:grid;
        grid-template-columns:minmax(0, 1.2fr) repeat(2, minmax(120px, .4fr));
        gap:12px;
        margin-top:18px;
    }

    .vehicle-data-card{
        padding:14px 16px;
        border-radius:18px;
        background:rgba(255,255,255,.04);
        border:1px solid rgba(255,255,255,.06);
        min-height:78px;
    }

    .vehicle-data-label{
        color:#b7becd;
        text-transform:uppercase;
        letter-spacing:.1em;
        font-size:11px;
        margin-bottom:8px;
    }

    .vehicle-data-value{
        color:#f4f7fc;
        font-size:14px;
        line-height:1.55;
        word-break:break-word;
    }

    .vehicle-hero-grid{
        display:grid;
        grid-template-columns:repeat(3, minmax(0,1fr));
        gap:12px;
        margin-top:14px;
    }

    .vehicle-hero-stat{
        padding:14px 16px;
        border-radius:20px;
        background:linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.025));
        border:1px solid rgba(255,255,255,.07);
        box-shadow:inset 0 1px 0 rgba(255,255,255,.04);
    }

    .vehicle-hero-label{
        color:#b7becd;
        text-transform:uppercase;
        letter-spacing:.1em;
        font-size:11px;
        margin-bottom:8px;
    }

    .vehicle-hero-value{
        font-size:30px;
        font-family:'Oxanium', sans-serif;
        font-weight:700;
        line-height:1;
    }

    .vehicle-hero-art{
        min-height:210px;
        min-width:0;
        border-radius:28px;
        border:1px solid rgba(255,255,255,.08);
        background:
            radial-gradient(circle at 50% 22%, rgba(255,255,255,.12), transparent 28%),
            linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.015));
        display:flex;
        align-items:center;
        justify-content:center;
        padding:22px;
        position:relative;
        z-index:1;
        overflow:hidden;
        aspect-ratio:1 / 1;
    }

    .vehicle-hero-art::before{
        content:"";
        position:absolute;
        inset:auto auto -58px -24px;
        width:180px;
        height:180px;
        border-radius:50%;
        background:radial-gradient(circle, rgba(255,45,70,.16), transparent 68%);
        pointer-events:none;
    }

    .vehicle-hero-art::after{
        content:"";
        position:absolute;
        inset:-40px -40px auto auto;
        width:160px;
        height:160px;
        border-radius:50%;
        background:radial-gradient(circle, rgba(105,167,255,.14), transparent 68%);
        pointer-events:none;
    }

    .vehicle-hero-art img{
        width:100%;
        height:100%;
        max-width:none;
        max-height:none;
        object-fit:contain;
        filter:drop-shadow(0 22px 34px rgba(0,0,0,.34));
        position:relative;
        z-index:1;
    }

    .welcome h1{
        margin:0;
        font-family:'Oxanium', sans-serif;
        font-size:56px;
        line-height:1;
        letter-spacing:-.03em;
        font-weight:700;
    }

    .welcome p{
        margin:10px 0 0;
        color:var(--muted);
        font-size:22px;
    }

    .wallet-panel{
        padding:20px;
        position:relative;
        overflow:hidden;
        background:
            radial-gradient(circle at top right, rgba(255,45,70,.14), transparent 36%),
            linear-gradient(180deg, rgba(16,18,26,.98), rgba(10,12,18,.98));
        backdrop-filter:blur(18px);
    }

    .wallet-panel::before{
        content:"";
        position:absolute;
        left:-60px;
        bottom:-90px;
        width:230px;
        height:230px;
        border-radius:50%;
        background:radial-gradient(circle, rgba(105,167,255,.16), transparent 72%);
        pointer-events:none;
    }

    .wallet-panel-header{
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:16px;
        margin-bottom:18px;
        position:relative;
        z-index:1;
    }

    .wallet-panel-title{
        margin:0;
        font-size:24px;
        font-family:'Oxanium', sans-serif;
        font-weight:700;
    }

    .wallet-panel-copy{
        margin:8px 0 0;
        color:var(--muted);
        font-size:15px;
        line-height:1.6;
    }

    .wallet-badge{
        display:inline-flex;
        align-items:center;
        gap:8px;
        padding:10px 14px;
        border-radius:999px;
        border:1px solid rgba(255,255,255,.08);
        background:rgba(255,255,255,.04);
        color:#c9d0dc;
        font-size:12px;
        font-weight:700;
        text-transform:uppercase;
        letter-spacing:.12em;
        white-space:nowrap;
    }

    .wallet-badge::before{
        content:"";
        width:9px;
        height:9px;
        border-radius:50%;
        background:#7f8794;
        box-shadow:0 0 0 0 rgba(127,135,148,.55);
    }

    .wallet-badge[data-state="connecting"]{
        color:#f3f6fc;
        border-color:rgba(105,167,255,.28);
        background:rgba(105,167,255,.08);
    }

    .wallet-badge[data-state="connecting"]::before{
        background:var(--blue);
        animation:pulse 1.2s infinite;
    }

    .wallet-badge[data-state="connected"]{
        color:#dff9ec;
        border-color:rgba(32,227,124,.24);
        background:rgba(32,227,124,.1);
        box-shadow:0 0 24px rgba(32,227,124,.14);
    }

    .wallet-badge[data-state="connected"]::before{
        background:var(--green);
        box-shadow:0 0 0 6px rgba(32,227,124,.12);
    }

    .wallet-badge[data-state="error"]{
        color:#ffd4da;
        border-color:rgba(255,45,70,.22);
        background:rgba(255,45,70,.1);
    }

    .wallet-badge[data-state="error"]::before{
        background:var(--red);
    }

    .wallet-btn{
        display:inline-flex;
        align-items:center;
        justify-content:center;
        gap:12px;
        width:100%;
        color:white;
        background:
            linear-gradient(135deg, rgba(255,45,70,.96), rgba(224,48,127,.92) 54%, rgba(105,167,255,.92));
        padding:17px 22px;
        border-radius:20px;
        border:1px solid rgba(255,255,255,.14);
        box-shadow:0 18px 32px rgba(5,8,14,.45), inset 0 1px 0 rgba(255,255,255,.16);
        font-family:'Oxanium', sans-serif;
        font-size:17px;
        font-weight:700;
        letter-spacing:.02em;
        position:relative;
        overflow:hidden;
        transition:transform .18s ease, box-shadow .18s ease, opacity .18s ease, filter .18s ease;
    }

    .wallet-btn::before{
        content:"";
        position:absolute;
        inset:1px;
        border-radius:19px;
        background:linear-gradient(180deg, rgba(255,255,255,.16), rgba(255,255,255,0));
        opacity:.55;
        pointer-events:none;
    }

    .wallet-btn:hover{
        transform:translateY(-1px);
        box-shadow:0 22px 38px rgba(5,8,14,.5), 0 0 0 1px rgba(255,255,255,.05), 0 0 38px rgba(255,45,70,.24);
        filter:saturate(1.06);
    }

    .wallet-btn:active{
        transform:translateY(1px);
    }

    .wallet-btn[disabled]{
        cursor:wait;
        opacity:.92;
    }

    .wallet-btn[data-state="connecting"]{
        box-shadow:0 22px 38px rgba(5,8,14,.5), 0 0 34px rgba(105,167,255,.22);
    }

    .wallet-btn[data-state="connected"]{
        background:linear-gradient(135deg, rgba(25,217,111,.92), rgba(54,219,168,.9), rgba(105,167,255,.88));
        box-shadow:0 20px 34px rgba(5,8,14,.45), 0 0 34px rgba(32,227,124,.22);
    }

    .wallet-btn-icon{
        width:22px;
        height:22px;
        display:inline-flex;
        align-items:center;
        justify-content:center;
        position:relative;
        z-index:1;
    }

    .wallet-btn-icon::before{
        content:"";
        width:12px;
        height:12px;
        border-radius:50%;
        background:currentColor;
        box-shadow:0 0 0 6px rgba(255,255,255,.14);
        transition:transform .18s ease, box-shadow .18s ease;
    }

    .wallet-btn[data-state="connecting"] .wallet-btn-icon::before{
        animation:pulse 1s infinite;
    }

    .wallet-btn[data-state="connected"] .wallet-btn-icon::before{
        width:14px;
        height:14px;
        box-shadow:0 0 0 7px rgba(255,255,255,.12), 0 0 24px rgba(255,255,255,.2);
    }

    .wallet-btn-label{
        position:relative;
        z-index:1;
    }

    .wallet-grid{
        display:grid;
        grid-template-columns:1fr 1fr;
        gap:14px;
        margin:18px 0 16px;
        position:relative;
        z-index:1;
    }

    .wallet-stat{
        padding:16px 18px;
        border-radius:18px;
        background:rgba(255,255,255,.04);
        border:1px solid rgba(255,255,255,.06);
        backdrop-filter:blur(14px);
    }

    .wallet-stat-label{
        color:#b7becd;
        text-transform:uppercase;
        letter-spacing:.1em;
        font-size:12px;
        margin-bottom:8px;
    }

    .wallet-stat-value{
        font-family:'Oxanium', sans-serif;
        font-size:32px;
        line-height:1;
        letter-spacing:-.04em;
        font-weight:700;
    }

    .wallet-sub{
        margin-top:10px;
        color:var(--muted);
        font-size:13px;
        letter-spacing:.02em;
        word-break:break-all;
        position:relative;
        z-index:1;
    }

    .wallet-address{
        margin-top:16px;
        padding:16px 18px;
        border-radius:18px;
        border:1px solid rgba(255,255,255,.07);
        background:rgba(255,255,255,.035);
        position:relative;
        z-index:1;
    }

    .wallet-address-label{
        color:#b7becd;
        text-transform:uppercase;
        letter-spacing:.1em;
        font-size:12px;
        margin-bottom:8px;
    }

    .wallet-address-value{
        font-size:14px;
        color:#f5f7fb;
        line-height:1.6;
        word-break:break-all;
    }

    .wallet-links{
        display:flex;
        gap:10px;
        flex-wrap:wrap;
        margin-top:16px;
        position:relative;
        z-index:1;
    }

    .wallet-actions{
        display:grid;
        grid-template-columns:minmax(0,1fr) auto;
        gap:12px;
        align-items:center;
        position:relative;
        z-index:1;
    }

    .admin-stack{
        display:grid;
        gap:12px;
        margin-top:14px;
    }

    .admin-input{
        width:100%;
        padding:12px 14px;
        border-radius:12px;
        border:1px solid rgba(255,255,255,.1);
        background:#0f131c;
        color:white;
    }

    .wallet-link{
        display:inline-flex;
        align-items:center;
        gap:8px;
        padding:10px 14px;
        border-radius:999px;
        border:1px solid rgba(255,255,255,.08);
        background:rgba(255,255,255,.04);
        color:#edf2fc;
        font-size:13px;
        font-weight:600;
    }

    .wallet-link:hover{
        background:rgba(255,255,255,.08);
    }

    .wallet-link-button{
        appearance:none;
        cursor:pointer;
        font-family:inherit;
    }

    .wallet-hint{
        margin-top:14px;
        color:var(--muted);
        font-size:13px;
        line-height:1.5;
        position:relative;
        z-index:1;
    }

    .inline-toast{
        margin-top:14px;
        padding:12px 14px;
        border-radius:16px;
        border:1px solid rgba(255,255,255,.08);
        background:rgba(255,255,255,.04);
        color:#dbe2ef;
        font-size:13px;
        line-height:1.5;
        opacity:0;
        transform:translateY(6px);
        transition:opacity .2s ease, transform .2s ease;
        pointer-events:none;
        position:relative;
        z-index:1;
    }

    .inline-toast.is-visible{
        opacity:1;
        transform:translateY(0);
    }

    .inline-toast[data-tone="success"]{
        color:#e2fff0;
        border-color:rgba(32,227,124,.24);
        background:rgba(32,227,124,.08);
    }

    .inline-toast[data-tone="error"]{
        color:#ffd6dc;
        border-color:rgba(255,45,70,.24);
        background:rgba(255,45,70,.08);
    }

    .dashboard-grid{
        display:grid;
        grid-template-columns:1.05fr .95fr;
        gap:16px;
    }

    .stack{
        display:grid;
        gap:16px;
    }

    .stats-grid{
        display:grid;
        grid-template-columns:repeat(2, minmax(0,1fr));
        gap:16px;
    }

    .secondary-card{
        padding:20px;
        border-radius:16px;
        overflow:hidden;
    }

    .secondary-card-title{
        margin:0;
        font-size:24px;
        font-family:'Oxanium', sans-serif;
        font-weight:700;
    }

    .secondary-card-copy{
        margin:10px 0 0;
        color:var(--muted);
        font-size:15px;
        line-height:1.6;
    }

    .summary-grid{
        display:grid;
        grid-template-columns:repeat(2, minmax(0,1fr));
        gap:12px;
        margin-top:18px;
    }

    .summary-item{
        padding:14px 16px;
        border-radius:18px;
        background:rgba(255,255,255,.035);
        border:1px solid rgba(255,255,255,.06);
    }

    .summary-item.wide{
        grid-column:1 / -1;
    }

    .summary-label{
        color:#b7becd;
        text-transform:uppercase;
        letter-spacing:.1em;
        font-size:11px;
        margin-bottom:8px;
    }

    .summary-value{
        color:#f4f7fc;
        font-size:14px;
        line-height:1.55;
        word-break:break-word;
    }

    .distribution-grid{
        display:grid;
        grid-template-columns:repeat(3, minmax(0,1fr));
        gap:12px;
        margin-top:18px;
    }

    .distribution-stat{
        padding:16px 18px;
        border-radius:18px;
        background:rgba(255,255,255,.04);
        border:1px solid rgba(255,255,255,.06);
    }

    .distribution-label{
        color:#b7becd;
        text-transform:uppercase;
        letter-spacing:.1em;
        font-size:11px;
        margin-bottom:8px;
    }

    .distribution-value{
        font-family:'Oxanium', sans-serif;
        font-size:28px;
        line-height:1;
        font-weight:700;
    }

    .reward-engine-grid{
        margin-top:16px;
    }

    .reward-engine-card{
        grid-column:1 / -1;
    }

    .v2-score-grid{
        margin-top:16px;
        grid-template-columns:repeat(4, minmax(0,1fr));
        align-items:start;
    }

    .score-breakdown-card{
        grid-column:span 3;
    }

    .score-explain-card{
        grid-column:span 2;
    }

    .score-card{
        border-color:rgba(32,227,124,.18);
        box-shadow:0 0 32px rgba(32,227,124,.08);
        background:linear-gradient(180deg, rgba(32,227,124,.06), rgba(255,255,255,.02));
    }

    .streak-card{
        border-color:rgba(105,167,255,.18);
        box-shadow:0 0 32px rgba(105,167,255,.08);
        background:linear-gradient(180deg, rgba(105,167,255,.06), rgba(255,255,255,.02));
    }

    .missions-card{
        border-color:rgba(181,104,255,.18);
        box-shadow:0 0 32px rgba(181,104,255,.08);
        background:linear-gradient(180deg, rgba(181,104,255,.06), rgba(255,255,255,.02));
    }

    .distribution-card{
        border-color:rgba(255,205,92,.2);
        box-shadow:0 0 32px rgba(255,205,92,.09);
        background:linear-gradient(180deg, rgba(255,205,92,.07), rgba(255,255,255,.02));
        position:relative;
        grid-column:span 2;
    }

    .distribution-card::after{
        content:"";
        position:absolute;
        right:18px;
        top:18px;
        width:8px;
        height:8px;
        border-radius:50%;
        background:#ffcd5c;
        box-shadow:0 0 0 0 rgba(255,205,92,.45);
        animation:sparkle .3s ease-out;
    }

    .value-tone-positive{
        color:var(--green);
    }

    .value-tone-negative{
        color:var(--red);
    }

    .mission-list{
        margin-top:14px;
        display:grid;
        gap:10px;
    }

    .mission-row{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        padding:12px 14px;
        border-radius:16px;
        background:rgba(255,255,255,.035);
        border:1px solid rgba(255,255,255,.06);
    }

    .mission-pill{
        border-radius:999px;
        padding:6px 12px;
        color:#dfe7f6;
        font-weight:600;
        font-size:12px;
        white-space:nowrap;
    }

    .mission-pill[data-state="active"]{
        background:rgba(105,167,255,.14);
        border:1px solid rgba(105,167,255,.28);
        color:#b9d6ff;
    }

    .mission-pill[data-state="complete"]{
        background:rgba(32,227,124,.14);
        border:1px solid rgba(32,227,124,.3);
        color:#c9ffdf;
    }

    .mission-pill[data-state="expired"]{
        background:rgba(255,45,70,.13);
        border:1px solid rgba(255,45,70,.3);
        color:#ffc4cb;
    }

    .status-pill{
        display:inline-flex;
        align-items:center;
        border-radius:999px;
        padding:6px 12px;
        font-weight:600;
        font-size:12px;
        margin-top:10px;
    }

    .status-pill[data-state="sport-active"]{
        color:#ffe7c4;
        background:rgba(255,145,66,.16);
        border:1px solid rgba(255,145,66,.32);
    }

    .status-pill[data-state="sport-inactive"]{
        color:#d2d8e4;
        background:rgba(255,255,255,.05);
        border:1px solid rgba(255,255,255,.08);
    }

    .token-metrics-panel{
        margin-top:24px;
        padding-top:20px;
        border-top:1px solid rgba(255,255,255,.08);
    }

    .token-metrics-grid{
        display:grid;
        grid-template-columns:repeat(2, minmax(0,1fr));
        gap:10px;
        margin-top:14px;
    }

    .token-metrics-grid div{
        padding:12px;
        border-radius:14px;
        background:rgba(255,255,255,.035);
        border:1px solid rgba(255,255,255,.06);
    }

    .token-metrics-grid span{
        display:block;
        color:var(--muted);
        font-size:12px;
        margin-bottom:6px;
    }

    .token-metrics-grid strong{
        font-family:'Oxanium', sans-serif;
        font-size:18px;
    }

    .mock-chart{
        height:188px;
        margin-top:14px;
        border-radius:18px;
        background:linear-gradient(180deg, rgba(12,20,30,.92), rgba(4,8,13,.92));
        border:1px solid rgba(255,255,255,.06);
        padding:0;
        overflow:hidden;
        position:relative;
    }

    .line-chart{
        width:100%;
        height:100%;
        display:block;
    }

    .badge-display{
        display:flex;
        align-items:center;
        gap:14px;
        margin-top:16px;
        padding:14px;
        border-radius:18px;
        background:rgba(255,255,255,.035);
        border:1px solid rgba(255,255,255,.06);
    }

    .nft-badge{
        width:72px;
        height:72px;
        border-radius:18px;
        box-shadow:0 18px 40px rgba(32,227,124,.18);
    }

    .mission-badge{
        width:42px;
        height:42px;
        border-radius:12px;
        margin-right:10px;
        filter:drop-shadow(0 0 12px rgba(32,227,124,.38));
        animation:badgePop .3s ease-out;
    }

    .mission-copy{
        display:flex;
        align-items:center;
        min-width:0;
    }

    .badge-label{
        font-family:'Oxanium', sans-serif;
        font-size:18px;
        color:#f4f7fc;
    }

    .achievement-strip{
        display:grid;
        gap:10px;
        margin-top:14px;
    }

    .achievement-badge{
        display:flex;
        align-items:center;
        gap:12px;
        padding:12px;
        border-radius:16px;
        background:rgba(255,255,255,.035);
        border:1px solid rgba(255,255,255,.07);
    }

    .achievement-badge img{
        width:46px;
        height:46px;
        border-radius:12px;
        box-shadow:0 12px 24px rgba(105,167,255,.16);
    }

    .achievement-badge strong{
        display:block;
        color:#f4f7fc;
        font-family:'Oxanium', sans-serif;
        font-size:15px;
    }

    .score-card-metrics,
    .streak-metrics{
        display:grid;
        grid-template-columns:repeat(2,minmax(0,1fr));
        gap:10px;
        margin-top:16px;
    }

    .score-mini-metric,
    .streak-mini-metric{
        padding:12px;
        border-radius:14px;
        background:rgba(255,255,255,.035);
        border:1px solid rgba(255,255,255,.06);
    }

    .score-mini-metric span,
    .streak-mini-metric span{
        display:block;
        color:rgba(255,255,255,.58);
        font-size:10px;
        letter-spacing:.08em;
        text-transform:uppercase;
        margin-bottom:6px;
    }

    .score-mini-metric strong,
    .streak-mini-metric strong{
        font-family:'Oxanium', sans-serif;
        font-size:18px;
    }

    .tesla-logo{
        width:44px;
        height:44px;
        color:#fff;
    }

    .stat-card{
        padding:22px 22px 20px;
        position:relative;
        overflow:hidden;
        min-height:160px;
    }

    .stat-card::after{
        content:"";
        position:absolute;
        right:-20px;
        top:-16px;
        width:90px;
        height:90px;
        border-radius:50%;
        background:radial-gradient(circle, rgba(255,45,70,.14), transparent 70%);
    }

    .stat-top{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        margin-bottom:22px;
    }

    .label{
        color:#b7becd;
        letter-spacing:.08em;
        text-transform:uppercase;
        font-size:13px;
    }

    .icon-chip{
        width:44px;
        height:44px;
        border-radius:14px;
        display:flex;
        align-items:center;
        justify-content:center;
        background:rgba(255,255,255,.04);
        color:#fff;
        font-size:18px;
    }

    .value{
        font-size:58px;
        font-weight:700;
        line-height:1;
        letter-spacing:-.04em;
        font-family:'Oxanium', sans-serif;
    }

    .value.small{
        font-size:26px;
    }

    .sub{
        margin-top:10px;
        color:var(--muted);
        font-size:14px;
    }

    .sub strong{
        color:#f3f6fc;
        font-weight:700;
    }

    .vehicle-panel{
        padding:28px;
        min-height:560px;
        position:relative;
        overflow:hidden;
    }

    .vehicle-panel::before{
        content:"";
        position:absolute;
        right:-80px;
        top:-80px;
        width:240px;
        height:240px;
        border-radius:50%;
        background:radial-gradient(circle, rgba(255,45,70,.12), transparent 70%);
        pointer-events:none;
    }

    .vehicle-header{
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:18px;
        margin-bottom:22px;
    }

    .vehicle-title{
        margin:0;
        font-size:24px;
        font-weight:600;
        font-family:'Oxanium', sans-serif;
    }

    .vehicle-sub{
        color:var(--muted);
        margin-top:8px;
        font-size:15px;
    }

    .tesla-mark{
        width:104px;
        height:104px;
        padding:6px;
        border-radius:50%;
        background:transparent;
        border:2px solid rgba(128,204,255,.34);
        box-shadow:
            0 0 0 1px rgba(123,196,255,.18),
            0 16px 30px rgba(0,0,0,.42),
            0 0 34px rgba(66,211,255,.18);
        display:flex;
        align-items:center;
        justify-content:center;
        color:#fff;
        overflow:hidden;
    }

    .vehicle-brand-logo{
        width:100%;
        height:100%;
        display:block;
        object-fit:contain;
        border-radius:50%;
        transform:none;
        filter:drop-shadow(0 5px 11px rgba(0,0,0,.42));
    }

    .soc-row{
        display:flex;
        align-items:center;
        gap:14px;
        margin-bottom:10px;
    }

    .battery-icon{
        width:38px;
        height:22px;
        border:2px solid var(--green);
        border-radius:5px;
        position:relative;
    }

    .battery-icon::after{
        content:"";
        position:absolute;
        right:-6px;
        top:5px;
        width:4px;
        height:8px;
        background:var(--green);
        border-radius:2px;
    }

    .battery-icon-fill{
        height:100%;
        background:linear-gradient(90deg, #18d36d, #23f08c);
        border-radius:2px;
    }

    .soc-percent{
        font-size:28px;
        font-family:'Oxanium', sans-serif;
        font-weight:700;
        color:var(--green);
    }

    .soc-meta{
        color:#a3aab8;
        font-size:15px;
        margin-bottom:22px;
    }

    .car-photo-wrap{
        margin:28px 0 18px;
        min-height:260px;
        display:flex;
        align-items:center;
        justify-content:center;
        border-radius:22px;
        background:linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,.01));
        border:1px solid rgba(255,255,255,.05);
        padding:20px;
        overflow:hidden;
    }

    .car-photo{
        max-width:100%;
        max-height:320px;
        object-fit:contain;
        display:block;
        filter:drop-shadow(0 18px 30px rgba(0,0,0,.35));
    }

    .car-photo-fallback{
        display:flex;
        align-items:center;
        justify-content:center;
        width:100%;
        min-height:180px;
        color:rgba(255,255,255,.55);
        font-family:'Oxanium', sans-serif;
        font-size:18px;
        letter-spacing:.04em;
    }

    .quick-actions{
        display:grid;
        grid-template-columns:repeat(4, minmax(0,1fr));
        gap:12px;
        margin:18px 0 26px;
    }

    .quick-btn{
        border:none;
        outline:none;
        cursor:pointer;
        color:#d9dee7;
        background:rgba(255,255,255,.03);
        border:1px solid rgba(255,255,255,.06);
        border-radius:18px;
        padding:16px 12px;
        font-family:'Oxanium', sans-serif;
        font-size:14px;
        font-weight:600;
    }

    .quick-btn:hover{
        background:rgba(255,255,255,.05);
    }

    .quick-btn.sport-active{
        color:#08100b;
        background:linear-gradient(135deg, #20e37c, #b8ffca);
        border-color:rgba(32,227,124,.7);
    }

    .charge-card{
        margin-top:10px;
        background:rgba(255,255,255,.03);
        border:1px solid rgba(255,255,255,.05);
        border-radius:22px;
        padding:20px;
    }

    .charge-head{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        margin-bottom:8px;
        font-size:18px;
        font-weight:600;
    }

    .charge-meta{
        color:var(--muted);
        font-size:15px;
        margin-bottom:18px;
    }

    .charge-bar-wrap{
        position:relative;
        height:12px;
        border-radius:999px;
        background:#232833;
        overflow:visible;
        margin:16px 0 20px;
    }

    .charge-bar{
        position:absolute;
        left:0;
        top:0;
        height:12px;
        border-radius:999px;
        background:linear-gradient(90deg, #1ad56f, #2bf09e);
    }

    .charge-limit-knob{
        position:absolute;
        top:50%;
        width:22px;
        height:22px;
        border-radius:50%;
        background:#fff;
        transform:translate(-50%, -50%);
        box-shadow:0 4px 14px rgba(0,0,0,.3);
    }

    .tip-box{
        display:flex;
        gap:14px;
        align-items:flex-start;
        margin-top:8px;
    }

    .tip-icon{
        width:36px;
        height:36px;
        border-radius:999px;
        background:#19d96f;
        color:#0b0f12;
        display:flex;
        align-items:center;
        justify-content:center;
        font-weight:700;
        font-size:20px;
        flex-shrink:0;
    }

    .tip-title{
        color:#27eb85;
        font-weight:700;
        font-size:18px;
        margin-bottom:4px;
    }

    .tip-copy{
        color:var(--muted);
        font-size:15px;
    }

    .history-panel{
        padding:24px;
        min-height:520px;
    }

    .details-panel{
        padding:24px;
        min-height:520px;
    }

    .activity-panel{
        margin-top:16px;
        padding:24px;
    }

    .activity-list{
        display:grid;
        gap:10px;
        margin-top:14px;
    }

    .activity-item{
        display:grid;
        gap:6px;
        padding:12px 14px;
        border-radius:14px;
        border:1px solid rgba(255,255,255,.08);
        background:rgba(255,255,255,.03);
    }

    .activity-head{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
    }

    .activity-type{
        font-family:'Oxanium', sans-serif;
        font-size:15px;
        color:#f4f7fc;
    }

    .activity-time{
        color:#a8b5c9;
        font-size:12px;
        white-space:nowrap;
    }

    .activity-source{
        display:inline-flex;
        width:max-content;
        border-radius:999px;
        padding:4px 10px;
        font-size:11px;
        letter-spacing:.06em;
        text-transform:uppercase;
        color:#c8d7ef;
        background:rgba(105,167,255,.12);
        border:1px solid rgba(105,167,255,.26);
    }

    .activity-details{
        color:#d3dced;
        font-size:13px;
        line-height:1.45;
        word-break:break-word;
    }

    .history-title{
        margin:0 0 18px;
        font-size:20px;
        font-weight:700;
        font-family:'Oxanium', sans-serif;
    }

    table{
        width:100%;
        border-collapse:collapse;
    }

    th, td{
        text-align:left;
        padding:16px 10px;
        border-bottom:1px solid rgba(255,255,255,.05);
    }

    th{
        color:#a6adba;
        text-transform:uppercase;
        letter-spacing:.08em;
        font-size:12px;
    }

    td{
        font-size:15px;
        color:#f3f6fc;
    }

    .gain{
        color:#ff3e57;
        font-weight:700;
        font-family:'Oxanium', sans-serif;
    }

    .muted{
        color:var(--muted);
    }

    .header-links{
        display:flex;
        gap:10px;
        margin-top:16px;
        flex-wrap:wrap;
    }

    .soft-link{
        color:#e9edf6;
        background:rgba(255,255,255,.03);
        border:1px solid rgba(255,255,255,.06);
        border-radius:14px;
        padding:12px 14px;
        font-weight:600;
        font-size:14px;
    }

    pre.error-box{
        white-space:pre-wrap;
        word-break:break-word;
        background:rgba(255,255,255,.03);
        padding:18px;
        border-radius:16px;
        border:1px solid rgba(255,255,255,.06);
        color:#f7d7dd;
    }

    .is-hidden{
        display:none !important;
    }

    @keyframes pulse{
        0%{
            transform:scale(1);
            box-shadow:0 0 0 0 rgba(105,167,255,.35);
        }
        70%{
            transform:scale(1.04);
            box-shadow:0 0 0 10px rgba(105,167,255,0);
        }
        100%{
            transform:scale(1);
            box-shadow:0 0 0 0 rgba(105,167,255,0);
        }
    }

    @keyframes badgePop{
        0%{ transform:scale(.82); opacity:.45; }
        72%{ transform:scale(1.08); opacity:1; }
        100%{ transform:scale(1); opacity:1; }
    }

    @keyframes sparkle{
        0%{ transform:scale(.7); box-shadow:0 0 0 0 rgba(255,205,92,.45); opacity:.4; }
        100%{ transform:scale(1); box-shadow:0 0 0 14px rgba(255,205,92,0); opacity:1; }
    }

    @media (max-width: 1120px){
        .topbar{
            grid-template-columns:1fr;
        }

        .hero-vehicle{
            grid-template-columns:1fr;
        }

        .hero-auth{
            min-height:154px;
            background-position:center;
        }

        .pre-auth-copy{
            max-width:100%;
        }

        .pre-auth-actions{
            justify-content:flex-start;
            min-width:0;
        }

        .dashboard-grid{
            grid-template-columns:1fr;
        }

        .stats-grid{
            grid-template-columns:repeat(2, minmax(0,1fr));
        }

        .v2-score-grid{
            grid-template-columns:repeat(2, minmax(0,1fr));
        }
    }

    @media (max-width: 720px){
        .topbar{
            grid-template-columns:1fr;
        }

        .stats-grid{
            grid-template-columns:1fr;
        }

        .v2-score-grid{
            grid-template-columns:1fr;
        }

        .wallet-grid{
            grid-template-columns:1fr;
        }

        .vehicle-hero-grid{
            grid-template-columns:1fr;
        }

        .vehicle-hero-data{
            grid-template-columns:1fr;
        }

        .summary-grid{
            grid-template-columns:1fr;
        }

        .distribution-grid{
            grid-template-columns:1fr;
        }

        .quick-actions{
            grid-template-columns:repeat(2, minmax(0,1fr));
        }

        .welcome h1{
            font-size:40px;
        }

        .hero h1{
            font-size:38px;
        }

        .pre-auth-info h1{
            font-size:42px;
        }

        .pre-auth-info p{
            font-size:16px;
            line-height:1.55;
        }

        .pre-auth-info{
            min-height:200px;
            align-items:flex-start;
        }

        .pre-auth-actions{
            width:100%;
            justify-content:flex-start;
        }

        .pre-auth-actions .btn{
            min-width:190px;
        }
    }
    .score-breakdown-grid{
        display:grid;
        grid-template-columns:repeat(5,minmax(116px,1fr));
        gap:10px;
        margin-top:16px;
    }
    .score-breakdown-item{
        border:1px solid rgba(255,255,255,.08);
        border-radius:12px;
        padding:11px 12px;
        background:rgba(255,255,255,.03);
        min-height:72px;
    }
    .score-breakdown-label{
        font-size:10px;
        text-transform:uppercase;
        letter-spacing:.07em;
        color:rgba(255,255,255,.55);
        margin-bottom:6px;
    }
    .score-breakdown-value{
        font-size:20px;
        font-weight:700;
        color:#f5f7fb;
        word-break:normal;
        overflow-wrap:anywhere;
        line-height:1.05;
    }
    .score-explanation-list{
        margin:16px 0 0;
        padding-left:18px;
        display:grid;
        gap:10px;
        color:rgba(245,247,251,.88);
    }
    .score-explanation-item{
        line-height:1.55;
    }
    .utility-grid{
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:14px;
        margin-top:16px;
    }
    .utility-summary-grid{
        display:grid;
        grid-template-columns:repeat(2,minmax(0,1fr));
        gap:14px;
        margin-top:16px;
    }
    .utility-summary-card{
        border:1px solid rgba(255,255,255,.08);
        border-radius:18px;
        padding:16px;
        background:rgba(255,255,255,.04);
    }
    .utility-card{
        border:1px solid rgba(255,255,255,.08);
        border-radius:16px;
        padding:18px;
        background:linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.02));
    }
    .utility-card-label{
        font-size:12px;
        letter-spacing:.08em;
        text-transform:uppercase;
        color:rgba(255,255,255,.58);
        margin-bottom:8px;
    }
    .utility-card-value{
        font-family:'Oxanium', sans-serif;
        font-size:28px;
        font-weight:800;
        color:#f5f7fb;
        margin-bottom:8px;
    }
    .utility-card-copy{
        color:rgba(245,247,251,.78);
        line-height:1.5;
        font-size:14px;
    }
    .utility-action-button{
        margin-top:14px;
        border:none;
        border-radius:999px;
        padding:14px 18px;
        font-weight:700;
        font-family:'Oxanium', sans-serif;
        background:linear-gradient(135deg,#20e37c,#0ba5ec);
        color:#071018;
        cursor:pointer;
        width:100%;
        box-shadow:0 10px 24px rgba(13,181,183,.18), inset 0 1px 0 rgba(255,255,255,.42);
    }
    .utility-action-button:disabled{
        opacity:.45;
        cursor:not-allowed;
    }
    .utility-action-button-secondary{
        background:rgba(255,255,255,.08);
        color:#f5f7fb;
        border:1px solid rgba(255,255,255,.12);
    }
    .history-panel{
        overflow-x:auto;
    }
    .history-panel table{
        min-width:560px;
    }

    .contracts-panel{
        padding:24px 28px;
    }

    .contracts-grid{
        display:grid;
        grid-template-columns:repeat(2,minmax(0,1fr));
        gap:12px;
        margin-top:16px;
    }

    .contract-item{
        padding:14px 16px;
        border-radius:14px;
        background:rgba(255,255,255,.035);
        border:1px solid rgba(255,255,255,.06);
    }

    .contract-label{
        color:rgba(255,255,255,.56);
        font-size:11px;
        letter-spacing:.08em;
        text-transform:uppercase;
        margin-bottom:8px;
    }

    .contract-value{
        color:#f4f7fc;
        font-family:'Oxanium', sans-serif;
        font-size:14px;
        overflow-wrap:anywhere;
    }

    .onchain-staking-card{
        margin-top:18px;
        padding:22px;
        border:1px solid rgba(85,205,255,.18);
        border-radius:18px;
        background:
            radial-gradient(circle at 12% 0%, rgba(32,227,124,.12), transparent 34%),
            linear-gradient(180deg, rgba(20,25,35,.88), rgba(13,16,23,.96));
        box-shadow:0 18px 42px rgba(0,0,0,.28);
    }

    .staking-panel-header{
        display:flex;
        justify-content:space-between;
        align-items:flex-start;
        gap:12px;
        flex-wrap:wrap;
    }

    .staking-panel-header h3{
        margin:0 0 6px;
        font-family:'Oxanium', sans-serif;
        font-size:26px;
    }

    .staking-panel-header p,
    .staking-status{
        margin:0;
        color:rgba(245,247,251,.74);
        line-height:1.45;
    }

    .staking-refresh-button,
    .onchain-unstake-button{
        border:1px solid rgba(255,255,255,.12);
        border-radius:999px;
        background:rgba(255,255,255,.07);
        color:#f5f7fb;
        font-weight:700;
        padding:10px 14px;
        cursor:pointer;
    }

    .staking-summary-grid{
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:12px;
        margin-top:16px;
    }

    .staking-summary-stat{
        padding:14px;
        border-radius:14px;
        background:rgba(255,255,255,.04);
        border:1px solid rgba(255,255,255,.07);
    }

    .staking-summary-stat strong{
        display:block;
        color:rgba(255,255,255,.58);
        text-transform:uppercase;
        letter-spacing:.08em;
        font-size:10px;
        margin-bottom:6px;
    }

    .staking-summary-stat div{
        font-family:'Oxanium', sans-serif;
        font-size:22px;
        color:#f5f7fb;
    }

    .staking-source{
        margin-top:8px;
        color:rgba(255,255,255,.48);
        font-size:12px;
    }

    .staking-form{
        display:grid;
        grid-template-columns:1.1fr .9fr auto;
        gap:14px;
        align-items:end;
        margin-top:18px;
    }

    .staking-form label{
        display:grid;
        gap:8px;
        color:#e8edf7;
        font-weight:700;
    }

    .staking-form input,
    .staking-form select{
        width:100%;
        min-height:48px;
        border-radius:12px;
        border:1px solid rgba(255,255,255,.12);
        background:rgba(3,7,13,.72);
        color:#f5f7fb;
        padding:0 14px;
        font-size:18px;
        font-family:'Oxanium', sans-serif;
    }

    .stake-onchain-button{
        min-height:48px;
        border:none;
        border-radius:999px;
        padding:0 26px;
        background:linear-gradient(135deg,#20e37c,#44d9ff);
        color:#051019;
        font-family:'Oxanium', sans-serif;
        font-weight:800;
        box-shadow:0 12px 28px rgba(32,227,124,.18), inset 0 1px 0 rgba(255,255,255,.45);
        cursor:pointer;
    }

    .staking-position-card{
        margin-top:12px;
        padding:16px;
        border:1px solid rgba(255,255,255,.08);
        border-radius:16px;
        background:rgba(255,255,255,.035);
    }
    @media (max-width: 1080px){
        .score-breakdown-grid{
            grid-template-columns:repeat(3,minmax(0,1fr));
        }
        .utility-grid{
            grid-template-columns:repeat(2,minmax(0,1fr));
        }
        .utility-summary-grid{
            grid-template-columns:1fr;
        }
        .score-breakdown-card,
        .score-explain-card,
        .distribution-card{
            grid-column:auto;
        }
        .staking-summary-grid{
            grid-template-columns:repeat(2,minmax(0,1fr));
        }
        .staking-form,
        .contracts-grid{
            grid-template-columns:1fr;
        }
    }
    @media (max-width: 900px){
        .topbar,
        .stats-grid,
        .dashboard-grid,
        .v2-score-grid{
            grid-template-columns:1fr !important;
        }
        .quick-actions,
        .wallet-grid,
        .distribution-grid,
        .summary-grid,
        .score-breakdown-grid,
        .utility-grid,
        .utility-summary-grid,
        .staking-summary-grid,
        .score-card-metrics,
        .streak-metrics{
            grid-template-columns:repeat(2,minmax(0,1fr));
        }
        .wallet-actions,
        .header-links{
            flex-wrap:wrap;
        }
    }
    @media (max-width: 640px){
        .shell{
            padding:14px;
        }
        .dashboard-brand-banner{
            width:100%;
            min-height:72px;
            border-radius:14px;
        }
        .quick-actions,
        .wallet-grid,
        .distribution-grid,
        .summary-grid,
        .score-breakdown-grid,
        .utility-grid,
        .utility-summary-grid,
        .staking-summary-grid,
        .score-card-metrics,
        .streak-metrics{
            grid-template-columns:1fr;
        }
        .wallet-actions{
            flex-direction:column;
            align-items:stretch;
        }
        .wallet-btn,
        .wallet-link-button{
            width:100%;
            justify-content:center;
        }
        .history-panel table{
            min-width:480px;
        }
    }
        </style>
"""


def render_page(title, body_html):
    web3_config = {
        "chainId": 11155111,
        "chainName": "Sepolia",
        "rpcUrlConfigured": bool(SEPOLIA_RPC_URL),
        "tokenAddress": EVFI_TOKEN_ADDRESS,
        "rewardsAddress": EVFI_REWARDS_ADDRESS,
        "weeklyRewardPool": WEEKLY_REWARD_POOL,
        "defaultWalletAddress": DEFAULT_WALLET_ADDRESS,
        "adminConfigured": bool(ADMIN_API_KEY),
    }
    return f"""
    <html>
    <head>
        <title>{escape(title)}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Oxanium:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        {BASE_CSS}
        <script src="https://cdn.jsdelivr.net/npm/ethers@6.16.0/dist/ethers.umd.min.js"></script>
    </head>
    <body>
        <div class="shell">
            {body_html}
        </div>
        <script>
            window.EVFI_WEB3_CONFIG = {json.dumps(web3_config)};
        </script>
        <script src="/static/evfi-wallet.js"></script>
        <script src="/static/evfi-staking.js"></script>
    </body>
    </html>
    """


# =========================================================
# DATA / REWARD HELPERS
# =========================================================
def extract_odometer(vehicle_response):
    try:
        return float(vehicle_response.get("vehicle_state", {}).get("odometer", 0))
    except Exception:
        return 0.0


def format_wallet(addr):
    if not addr or len(addr) < 12:
        return addr
    return f"{addr[:6]}...{addr[-4:]}"


def is_valid_evm_address(value):
    return isinstance(value, str) and value.startswith("0x") and len(value) == 42


def verify_admin_or_wallet_signature(expected_wallet=None, expected_action=None, expected_vehicle_id=None):
    if request.headers.get("x-admin-key") == ADMIN_API_KEY:
        return True, None

    wallet = str(request.headers.get("x-wallet-address") or "").strip()
    message = str(request.headers.get("x-wallet-message") or "")
    signature = str(request.headers.get("x-wallet-signature") or "").strip()
    if not is_valid_evm_address(wallet) or not message or not signature:
        return False, "Connect your wallet and approve the EVFi action signature."

    if expected_wallet and wallet.lower() != str(expected_wallet).strip().lower():
        return False, "Connected wallet does not match the requested recipient wallet."

    expected_lines = [
        "EVFi wallet action",
        f"Action: {expected_action}",
        f"Vehicle: {expected_vehicle_id}",
        f"Wallet: {wallet}",
    ]
    for expected_line in expected_lines:
        if expected_line not in message:
            return False, "Wallet signature message does not match this EVFi action."

    message_parts = [part.strip() for part in message.replace("\n", "|").split("|")]
    timestamp_line = next((line for line in message_parts if line.startswith("Timestamp: ")), "")
    try:
        signed_at_ms = int(timestamp_line.split(":", 1)[1].strip())
    except Exception:
        return False, "Wallet signature timestamp is missing."
    if abs((time.time() * 1000) - signed_at_ms) > 15 * 60 * 1000:
        return False, "Wallet signature expired. Try the action again."

    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct

        recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
    except Exception as exc:
        try:
            script = "import('ethers').then(({verifyMessage})=>console.log(verifyMessage(process.argv[1],process.argv[2]))).catch((error)=>{console.error(error.message||error);process.exit(1);})"
            result = subprocess.run(
                ["node", "-e", script, message, signature],
                cwd=APP_ROOT,
                capture_output=True,
                text=True,
                timeout=8,
            )
            if result.returncode != 0:
                return False, f"Wallet signature verification failed: {result.stderr.strip() or exc}"
            recovered = result.stdout.strip()
        except Exception as fallback_exc:
            return False, f"Wallet signature verification failed: {fallback_exc}"

    if recovered.lower() != wallet.lower():
        return False, "Wallet signature does not match the connected wallet."
    return True, None


def build_weekly_reward_preview(user_id, vin, event_vehicle_id):
    weekly_score = get_current_week_score(user_id, vin) or calculate_weekly_score(user_id, vin, event_vehicle_id)
    reward_context = estimate_weekly_reward(float(weekly_score["total_score"] or 0.0), weekly_score["week_start"], weekly_score["week_end"])
    return {
        "weeklyScore": round(float(weekly_score["total_score"] or 0.0), 2),
        "estimatedEvfi": round(float(reward_context["estimated_evfi"] or 0.0), 2),
        "emissionFactor": round(float(reward_context["emission_factor"] or 0.0), 8),
        "actualNetworkScore": round(float(reward_context["actual_network_score"] or 0.0), 2),
        "effectiveNetworkScore": round(float(reward_context["effective_network_score"] or 0.0), 2),
        "weeklyPool": round(float(reward_context["weekly_pool"] or 0.0), 2),
        "weekStart": int(weekly_score["week_start"] or 0),
        "weekEnd": int(weekly_score["week_end"] or 0),
    }


def extract_weekly_score_breakdown(weekly_score):
    breakdown = parse_json_object(weekly_score["score_breakdown_json"] if weekly_score and "score_breakdown_json" in weekly_score.keys() else {})
    return {
        "verifiedMiles": round(as_float(breakdown.get("verified_miles"), 0.0), 2),
        "activeDays": int(breakdown.get("active_days") or 0),
        "activeDayScore": round(as_float(breakdown.get("active_day_score"), 0.0), 2),
        "participationBonus": round(as_float(breakdown.get("participation_bonus"), 0.0), 2),
        "efficiencyScore": round(as_float(breakdown.get("efficiency_score"), 0.0), 2),
        "chargingScore": round(as_float(breakdown.get("charging_score"), 0.0), 2),
        "penaltyScore": round(as_float(breakdown.get("penalty_score"), 0.0), 2),
        "missionBonus": round(as_float(breakdown.get("mission_bonus_applied"), 0.0), 2),
        "streakMultiplier": round(as_float(breakdown.get("streak_multiplier"), 1.0), 2),
        "avgEfficiencyWhmi": round(as_float(breakdown.get("avg_efficiency_whmi"), 0.0), 2),
        "baselineEfficiencyWhmi": round(as_float(breakdown.get("baseline_efficiency_whmi"), 0.0), 2),
        "healthyChargeSessions": int(breakdown.get("healthy_charge_sessions") or 0),
        "highSocChargeSessions": int(breakdown.get("high_soc_charge_sessions") or 0),
        "offpeakChargeSessions": int(breakdown.get("offpeak_charge_sessions") or 0),
        "acChargeSessions": int(breakdown.get("ac_charge_sessions") or 0),
        "fastChargeSessions": int(breakdown.get("fast_charge_sessions") or 0),
        "chargeSessions": int(breakdown.get("charge_sessions") or 0),
        "preBonusScore": round(as_float(breakdown.get("pre_bonus_score"), 0.0), 2),
        "stakingBoostPct": round(as_float(breakdown.get("staking_boost_pct"), 0.0), 2),
        "stakingBonus": round(as_float(breakdown.get("staking_bonus"), 0.0), 2),
        "totalScore": round(as_float(breakdown.get("total_score"), weekly_score["total_score"] if weekly_score else 0.0), 2),
    }


def build_token_utility_catalog():
    return {
        "analyticsUnlocks": [
            {"key": "premium_weekly_insights", "actionType": "analytics_unlock", "label": "Premium Weekly Insights", "costEvfi": 25, "description": "Unlock expanded efficiency, charging, and streak analysis for the current week."},
            {"key": "battery_health_report", "actionType": "analytics_unlock", "label": "Battery Health Report", "costEvfi": 40, "description": "Generate a deeper battery stewardship and charging-discipline report."},
        ],
        "partnerRewards": [
            {"key": "charging_credit_pass", "actionType": "partner_reward", "label": "Charging Credit Pass", "costEvfi": 60, "description": "Unlock a digital charging-credit pass preview in your EVFi wallet profile."},
            {"key": "telemetry_export_pack", "actionType": "partner_reward", "label": "Telemetry Export Pack", "costEvfi": 45, "description": "Unlock digital CSV and PDF export previews for your weekly EVFi telemetry summary."},
        ],
        "stakingTiers": [
            {"key": "bronze", "actionType": "onchain_stake_hint", "label": "Bronze Stake", "stakeEvfi": 100, "rewardBoostPct": 5, "description": "Stake at least 100 EVFi on Sepolia for the Bronze weekly reward boost."},
            {"key": "silver", "actionType": "onchain_stake_hint", "label": "Silver Stake", "stakeEvfi": 500, "rewardBoostPct": 10, "description": "Stake at least 500 EVFi on Sepolia for the Silver weekly reward boost."},
            {"key": "gold", "actionType": "onchain_stake_hint", "label": "Gold Stake", "stakeEvfi": 1000, "rewardBoostPct": 15, "description": "Stake at least 1,000 EVFi on Sepolia for the Gold weekly reward boost."},
        ],
    }


def get_token_utility_entry(action_key):
    catalog = build_token_utility_catalog()
    for group in ("analyticsUnlocks", "partnerRewards", "stakingTiers"):
        for entry in catalog[group]:
            if entry["key"] == action_key:
                return dict(entry)
    return None


def get_active_stake_position(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM staking_positions
        WHERE user_id = ? AND status = 'active'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_user_utility_balance(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM gamification_evfi_events
        WHERE user_id = ?
          AND source != 'airdrop_claim'
        """,
        (user_id,),
    )
    total_earned = as_float(cur.fetchone()["total"], 0.0)
    cur.execute(
        """
        SELECT COALESCE(SUM(amount_evfi), 0) AS total
        FROM utility_actions
        WHERE user_id = ? AND status = 'completed'
        """,
        (user_id,),
    )
    total_spent = as_float(cur.fetchone()["total"], 0.0)
    cur.execute(
        """
        SELECT COALESCE(SUM(stake_evfi), 0) AS total
        FROM staking_positions
        WHERE user_id = ? AND status = 'active'
        """,
        (user_id,),
    )
    total_staked = as_float(cur.fetchone()["total"], 0.0)
    conn.close()
    available = max(0.0, round(total_earned - total_spent - total_staked, 2))
    return {
        "totalEarned": round(total_earned, 2),
        "totalSpent": round(total_spent, 2),
        "totalStaked": round(total_staked, 2),
        "available": available,
    }


def get_user_utility_state(user_id):
    balance = get_user_utility_balance(user_id)
    active_stake = get_active_stake_position(user_id)
    return {
        "balance": balance,
        "activeStake": {
            "tierKey": active_stake["tier_key"],
            "stakeEvfi": round(as_float(active_stake["stake_evfi"], 0.0), 2),
            "rewardBoostPct": round(as_float(active_stake["reward_boost_pct"], 0.0), 2),
            "updatedAt": int(active_stake["updated_at"] or active_stake["created_at"] or 0),
        } if active_stake else None,
        "catalog": build_token_utility_catalog(),
    }


def get_active_stake_boost_pct(user_id):
    active_stake = get_active_stake_position(user_id)
    if not active_stake:
        return 0.0
    return round(as_float(active_stake["reward_boost_pct"], 0.0), 2)


def redeem_token_utility(user_id, action_key):
    entry = get_token_utility_entry(action_key)
    if not entry or entry.get("actionType") not in ("analytics_unlock", "partner_reward"):
        raise ValueError("Unknown utility action.")
    balance = get_user_utility_balance(user_id)
    cost_evfi = round(as_float(entry.get("costEvfi"), 0.0), 2)
    if balance["available"] < cost_evfi:
        raise ValueError("Not enough EVFi utility balance.")

    conn = get_db_connection()
    cur = conn.cursor()
    created_at = now_ts()
    cur.execute(
        """
        INSERT INTO utility_actions
        (user_id, action_key, action_type, amount_evfi, status, details_json, created_at, completed_at)
        VALUES (?, ?, ?, ?, 'completed', ?, ?, ?)
        """,
        (
            user_id,
            action_key,
            entry["actionType"],
            cost_evfi,
            json.dumps(entry, sort_keys=True),
            created_at,
            created_at,
        ),
    )
    conn.commit()
    action_id = cur.lastrowid
    conn.close()
    log_v2_event("utility_redeemed", user_id=user_id, action_key=action_key, amount_evfi=cost_evfi)
    return {
        "actionId": int(action_id),
        "entry": entry,
        "amountEvfi": cost_evfi,
        "utilityState": get_user_utility_state(user_id),
    }


def stake_evfi_tier(user_id, tier_key):
    entry = get_token_utility_entry(tier_key)
    if not entry or entry.get("actionType") != "stake":
        raise ValueError("Unknown staking tier.")
    if get_active_stake_position(user_id):
        raise ValueError("Unstake the current position before staking a new tier.")

    stake_evfi = round(as_float(entry.get("stakeEvfi"), 0.0), 2)
    balance = get_user_utility_balance(user_id)
    if balance["available"] < stake_evfi:
        raise ValueError("Not enough EVFi utility balance to stake this tier.")

    conn = get_db_connection()
    cur = conn.cursor()
    created_at = now_ts()
    cur.execute(
        """
        INSERT INTO staking_positions
        (user_id, tier_key, stake_evfi, reward_boost_pct, status, details_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            user_id,
            tier_key,
            stake_evfi,
            round(as_float(entry.get("rewardBoostPct"), 0.0), 2),
            json.dumps(entry, sort_keys=True),
            created_at,
            created_at,
        ),
    )
    conn.commit()
    position_id = cur.lastrowid
    conn.close()
    log_v2_event("stake_activated", user_id=user_id, tier_key=tier_key, stake_evfi=stake_evfi)
    return {
        "positionId": int(position_id),
        "entry": entry,
        "utilityState": get_user_utility_state(user_id),
    }


def unstake_evfi(user_id):
    active_stake = get_active_stake_position(user_id)
    if not active_stake:
        raise ValueError("No active stake to unstake.")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE staking_positions
        SET status = 'unstaked',
            updated_at = ?
        WHERE id = ?
        """,
        (now_ts(), int(active_stake["id"])),
    )
    conn.commit()
    conn.close()
    log_v2_event("stake_released", user_id=user_id, tier_key=active_stake["tier_key"], stake_evfi=active_stake["stake_evfi"])
    return {
        "tierKey": active_stake["tier_key"],
        "stakeEvfi": round(as_float(active_stake["stake_evfi"], 0.0), 2),
        "utilityState": get_user_utility_state(user_id),
    }


def build_distribution_batch_id(vid, action="demo"):
    return f"{vid}-{action}-{int(time.time())}"


def normalize_assignment_exception(exc):
    raw = str(exc)
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    return {
        "ok": False,
        "error": {
            "message": raw,
            "reason": raw,
            "code": "ASSIGNMENT_ERROR",
        },
    }


def get_or_create_user(wallet_address=None):
    wallet = wallet_address if is_valid_evm_address(wallet_address or "") else DEFAULT_WALLET_ADDRESS
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE wallet_address = ?", (wallet,))
    user = cur.fetchone()
    if user is None:
        cur.execute(
            """
            INSERT INTO users
            (wallet_address, created_at, sport_mode_active, sport_mode_uses_today)
            VALUES (?, ?, 0, 0)
            """,
            (wallet, now_ts()),
        )
        conn.commit()
        cur.execute("SELECT * FROM users WHERE wallet_address = ?", (wallet,))
        user = cur.fetchone()
        log_v2_event("user_created", wallet=wallet)
    conn.close()
    return user


def get_or_create_gamification_state(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM gamification_state WHERE user_id = ?", (user_id,))
    state = cur.fetchone()
    if state is None:
        cur.execute(
            """
            INSERT INTO gamification_state
            (user_id, current_streak, longest_streak, completed_challenges_count, total_miles_synced, lifetime_evfi_earned, total_sync_events, telemetry_sync_count, updated_at)
            VALUES (?, 0, 0, 0, 0, 0, 0, 0, ?)
            """,
            (user_id, now_ts()),
        )
        conn.commit()
        cur.execute("SELECT * FROM gamification_state WHERE user_id = ?", (user_id,))
        state = cur.fetchone()
    conn.close()
    return state


def append_gamification_activity(user_id, event_type, source, details=None, event_ts=None):
    payload = details or {}
    created_at = int(event_ts or now_ts())
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gamification_activity_feed (user_id, event_type, source, details_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, str(event_type), str(source), json.dumps(payload, sort_keys=True, default=str), created_at),
    )
    conn.commit()
    conn.close()


def updateStreak(user_id, activity_date):
    state = get_or_create_gamification_state(user_id)
    last_date = parse_calendar_day(state["last_activity_date"])
    current_date = parse_calendar_day(activity_date) or datetime.fromtimestamp(now_ts()).date()
    current_streak = int(state["current_streak"] or 0)
    longest_streak = int(state["longest_streak"] or 0)

    streak_increased = False
    streak_reset = False
    if last_date is None:
        current_streak = 1
        streak_increased = True
    elif current_date > last_date:
        delta_days = (current_date - last_date).days
        if delta_days == 1:
            current_streak += 1
            streak_increased = True
        elif delta_days > 1:
            current_streak = 1
            streak_increased = True
            streak_reset = True

    if current_streak > longest_streak:
        longest_streak = current_streak

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE gamification_state
        SET last_activity_date = ?, current_streak = ?, longest_streak = ?, updated_at = ?
        WHERE user_id = ?
        """,
        (current_date.strftime("%Y-%m-%d"), current_streak, longest_streak, now_ts(), user_id),
    )
    conn.commit()
    conn.close()
    return {
        "currentStreak": current_streak,
        "longestStreak": longest_streak,
        "streakIncreased": streak_increased,
        "streakReset": streak_reset,
    }


def updateDailyActivity(user_id, activityDate=None, activity_type="activity"):
    day = activityDate or calendar_day()
    streak = updateStreak(user_id, day)
    conn = get_db_connection()
    cur = conn.cursor()
    field = {
        "login": "last_login_date",
        "sync": "last_sync_date",
        "reward_check": "last_reward_check_date",
        "claim": "last_reward_check_date",
    }.get(activity_type)
    if field:
        cur.execute(
            f"UPDATE gamification_state SET {field} = ?, updated_at = ? WHERE user_id = ?",
            (day, now_ts(), user_id),
        )
    conn.commit()
    conn.close()

    events = []
    if streak["streakIncreased"]:
        message = f"Streak is now {streak['currentStreak']} day{'s' if streak['currentStreak'] != 1 else ''}."
        events.append(message)
        append_gamification_activity(
            user_id,
            "streak_increased",
            activity_type,
            {"currentStreak": streak["currentStreak"], "longestStreak": streak["longestStreak"], "activityDate": day},
        )
    if streak["streakReset"]:
        message = "Streak reset after a missed day."
        events.append(message)
        append_gamification_activity(
            user_id,
            "streak_reset",
            activity_type,
            {"currentStreak": streak["currentStreak"], "activityDate": day},
        )
    append_gamification_activity(
        user_id,
        "daily_activity",
        activity_type,
        {"activityDate": day, "streak": streak["currentStreak"]},
    )
    return {"activityDate": day, "streak": streak, "events": events}


def record_app_activity(user_id, activity_type, activity_ts=None):
    day = calendar_day(activity_ts)
    activity = updateDailyActivity(user_id, day, activity_type)
    challenges = updateChallengeProgress(user_id, {"verified_miles": 0.0})
    badges = awardEligibleBadges(user_id)
    events = []
    events.extend(activity["events"])
    events.extend(challenges["events"])
    events.extend(badges["events"])
    # Keep response events concise and unique in order.
    events = list(dict.fromkeys(events))
    return {
        "activity": activity,
        "challenges": challenges,
        "badges": badges,
        "events": events,
    }


def calculateMileageDelta(previousOdometer, currentOdometer):
    try:
        previous = float(previousOdometer or 0)
        current = float(currentOdometer or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, current - previous)


def record_evfi_earning(user_id, event_key, amount, source):
    get_or_create_gamification_state(user_id)
    event_amount = round(max(0.0, float(amount or 0.0)), 2)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT amount FROM gamification_evfi_events WHERE user_id = ? AND event_key = ?",
        (user_id, event_key),
    )
    existing = cur.fetchone()
    previous_amount = float(existing["amount"] or 0.0) if existing else 0.0
    delta = round(event_amount - previous_amount, 2)

    if existing is None:
        cur.execute(
            """
            INSERT INTO gamification_evfi_events (user_id, event_key, source, amount, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, event_key, source, event_amount, now_ts(), now_ts()),
        )
    else:
        cur.execute(
            """
            UPDATE gamification_evfi_events
            SET source = ?, amount = ?, updated_at = ?
            WHERE user_id = ? AND event_key = ?
            """,
            (source, event_amount, now_ts(), user_id, event_key),
        )

    should_log_event = abs(delta) > 0
    if should_log_event:
        cur.execute(
            """
            UPDATE gamification_state
            SET lifetime_evfi_earned = MAX(0, COALESCE(lifetime_evfi_earned, 0) + ?),
                updated_at = ?
            WHERE user_id = ?
            """,
            (delta, now_ts(), user_id),
        )
    conn.commit()
    conn.close()
    if should_log_event:
        append_gamification_activity(
            user_id,
            "evfi_earned",
            source,
            {"eventKey": event_key, "delta": delta, "totalEventAmount": event_amount},
        )
    return delta


def upsert_challenge(user_id, challenge_key, progress):
    definition = CHALLENGE_DEFS[challenge_key]
    target = float(definition["target"])
    next_progress = max(0.0, min(float(progress or 0.0), target))
    window_type = definition.get("window", "all_time")
    _, window_start, window_end, window_key = challenge_window_bounds(window_type)

    conn = get_db_connection()
    cur = conn.cursor()
    # Archive prior active windows for this challenge if they are not current.
    cur.execute(
        """
        UPDATE gamification_challenge_windows
        SET active = 0, last_updated = ?
        WHERE user_id = ? AND challenge_key = ? AND active = 1 AND window_key != ?
        """,
        (now_ts(), user_id, challenge_key, window_key),
    )
    cur.execute(
        """
        SELECT completed, progress
        FROM gamification_challenge_windows
        WHERE user_id = ? AND challenge_key = ? AND window_key = ?
        """,
        (user_id, challenge_key, window_key),
    )
    row = cur.fetchone()
    was_completed = bool(row["completed"]) if row else False
    is_completed = next_progress >= target
    completed_at = now_ts() if (is_completed and not was_completed) else None

    cur.execute(
        """
        INSERT INTO gamification_challenge_windows
        (user_id, challenge_key, window_key, window_start, window_end, progress, target, completed, completed_at, active, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(user_id, challenge_key, window_key) DO UPDATE SET
            window_start = excluded.window_start,
            window_end = excluded.window_end,
            progress = excluded.progress,
            target = excluded.target,
            completed = CASE WHEN gamification_challenge_windows.completed = 1 THEN 1 ELSE excluded.completed END,
            completed_at = CASE
                WHEN gamification_challenge_windows.completed = 1 THEN gamification_challenge_windows.completed_at
                WHEN excluded.completed = 1 THEN excluded.completed_at
                ELSE gamification_challenge_windows.completed_at
            END,
            active = 1,
            last_updated = excluded.last_updated
        """,
        (
            user_id,
            challenge_key,
            window_key,
            window_start,
            window_end,
            next_progress,
            target,
            1 if is_completed else 0,
            completed_at,
            now_ts(),
        ),
    )

    # Mirror active window into legacy table used by existing dashboard hooks.
    cur.execute(
        """
        INSERT INTO gamification_challenges
        (user_id, challenge_key, progress, target, completed, completed_at, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, challenge_key) DO UPDATE SET
            progress = excluded.progress,
            target = excluded.target,
            completed = excluded.completed,
            completed_at = excluded.completed_at,
            last_updated = excluded.last_updated
        """,
        (user_id, challenge_key, next_progress, target, 1 if is_completed else 0, completed_at, now_ts()),
    )
    conn.commit()
    conn.close()
    return {
        "challengeKey": challenge_key,
        "windowKey": window_key,
        "windowStart": window_start,
        "windowEnd": window_end,
        "progress": next_progress,
        "target": target,
        "completedNow": is_completed and not was_completed,
        "completed": is_completed,
    }


def updateChallengeProgress(user_id, telemetryDelta):
    ensure_challenge_windows_maintenance(user_id)
    state = get_or_create_gamification_state(user_id)
    week_start, week_end = current_week_bounds()
    month_start_key = challenge_window_bounds("monthly")
    month_start = month_start_key[1]
    month_end = month_start_key[2]
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(miles_delta), 0) AS miles
        FROM gamification_sync_history
        WHERE user_id = ?
          AND synced_at BETWEEN ? AND ?
          AND miles_delta > 0
        """,
        (user_id, week_start, week_end),
    )
    weekly_miles = float(cur.fetchone()["miles"] or 0.0)
    cur.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS earned
        FROM gamification_evfi_events
        WHERE user_id = ? AND updated_at BETWEEN ? AND ?
        """,
        (user_id, month_start, month_end),
    )
    monthly_earned = float(cur.fetchone()["earned"] or 0.0)
    conn.close()

    challenge_updates = [
        upsert_challenge(user_id, "drive_25_miles_weekly", weekly_miles),
        upsert_challenge(user_id, "sync_3_days_in_a_row", min(float(state["current_streak"] or 0), CHALLENGE_TARGET_SYNC_3_DAY_STREAK)),
        upsert_challenge(user_id, "earn_250_evfi", monthly_earned),
    ]

    newly_completed = [item for item in challenge_updates if item["completedNow"]]
    for item in challenge_updates:
        append_gamification_activity(
            user_id,
            "challenge_progress",
            "challenge_engine",
            {
                "challengeKey": item["challengeKey"],
                "windowKey": item.get("windowKey"),
                "progress": item["progress"],
                "target": item["target"],
                "completed": item["completed"],
            },
        )
    for item in newly_completed:
        append_gamification_activity(
            user_id,
            "challenge_completed",
            "challenge_engine",
            {"challengeKey": item["challengeKey"], "windowKey": item.get("windowKey")},
        )
    return {
        "all": challenge_updates,
        "completedNow": newly_completed,
        "events": [f"Challenge completed: {CHALLENGE_DEFS[item['challengeKey']]['label']}" for item in newly_completed],
    }


def ensure_challenge_windows_maintenance(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    archived_count = 0
    for challenge_key, definition in CHALLENGE_DEFS.items():
        window_type = definition.get("window", "all_time")
        _, _, _, expected_window_key = challenge_window_bounds(window_type)
        cur.execute(
            """
            UPDATE gamification_challenge_windows
            SET active = 0, last_updated = ?
            WHERE user_id = ? AND challenge_key = ? AND active = 1 AND window_key != ?
            """,
            (now_ts(), user_id, challenge_key, expected_window_key),
        )
        archived_count += int(cur.rowcount or 0)
    conn.commit()
    conn.close()
    if archived_count > 0:
        append_gamification_activity(
            user_id,
            "challenge_window_rollover",
            "challenge_engine",
            {"archivedWindows": archived_count},
        )


def awardEligibleBadges(user_id):
    state = get_or_create_gamification_state(user_id)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT badge_key FROM gamification_badges WHERE user_id = ?", (user_id,))
    existing = {row["badge_key"] for row in cur.fetchall()}
    cur.execute("SELECT COUNT(*) AS count FROM claims WHERE user_id = ? AND claimed = 1", (user_id,))
    claimed_count = int(cur.fetchone()["count"] or 0)

    candidates = set()
    if int(state["total_sync_events"] or 0) >= 1:
        candidates.add("first_sync")
    if int(state["current_streak"] or 0) >= 7:
        candidates.add("streak_7_days")
    if float(state["total_miles_synced"] or 0.0) >= 100:
        candidates.add("miles_100")
    if float(state["total_miles_synced"] or 0.0) >= 500:
        candidates.add("miles_500")
    if claimed_count > 0:
        candidates.add("first_evfi_claim")

    awarded_now = []
    for badge_key in sorted(candidates):
        if badge_key in existing:
            continue
        cur.execute(
            """
            INSERT INTO gamification_badges (user_id, badge_key, badge_name, badge_asset, awarded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, badge_key, BADGE_DEFS[badge_key], "/static/evfi-badge-genesis.svg", now_ts()),
        )
        awarded_now.append({"badgeKey": badge_key, "badgeName": BADGE_DEFS[badge_key]})

    if awarded_now:
        cur.execute(
            """
            UPDATE gamification_state
            SET completed_challenges_count = (
                SELECT COUNT(*) FROM gamification_challenge_windows WHERE user_id = ? AND active = 1 AND completed = 1
            ),
                updated_at = ?
            WHERE user_id = ?
            """,
            (user_id, now_ts(), user_id),
        )
    conn.commit()
    conn.close()
    for badge in awarded_now:
        append_gamification_activity(
            user_id,
            "badge_awarded",
            "badge_engine",
            {"badgeKey": badge["badgeKey"], "badgeName": badge["badgeName"]},
        )
    return {
        "awardedNow": awarded_now,
        "events": [f"Badge earned: {item['badgeName']}" for item in awarded_now],
    }


def processTelemetrySync(user_id, telemetryData):
    state = get_or_create_gamification_state(user_id)
    synced_at = int(telemetryData.get("synced_at") or now_ts())
    day = calendar_day(synced_at)
    odometer = float(telemetryData.get("odometer") or 0.0)
    verified_miles = max(0.0, float(telemetryData.get("verified_miles") or 0.0))
    telemetry_miles = max(0.0, float(telemetryData.get("miles_delta") or 0.0))
    previous_odometer = state["last_known_odometer"]
    odometer_delta = calculateMileageDelta(previous_odometer, odometer)
    miles_delta = max(telemetry_miles, odometer_delta)
    battery_level = telemetryData.get("battery_level")
    charge_rate = telemetryData.get("charge_rate")
    charging_state = telemetryData.get("charging_state")
    efficiency_whmi = telemetryData.get("efficiency_whmi")

    log_v2_event(
        "telemetry_sync_received",
        user_id=user_id,
        previous_odometer=previous_odometer,
        current_odometer=odometer,
        telemetry_miles=telemetry_miles,
        odometer_delta=odometer_delta,
        miles_added=miles_delta,
        verified_miles=verified_miles,
        reward_added=verified_miles,
    )

    activity = updateDailyActivity(user_id, day, "sync")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE gamification_state
        SET total_miles_synced = COALESCE(total_miles_synced, 0) + ?,
            last_known_odometer = ?,
            last_sync_at = ?,
            last_sync_date = ?,
            total_sync_events = COALESCE(total_sync_events, 0) + 1,
            telemetry_sync_count = COALESCE(telemetry_sync_count, 0) + 1,
            updated_at = ?
        WHERE user_id = ?
        """,
        (miles_delta, odometer, synced_at, day, now_ts(), user_id),
    )
    cur.execute(
        """
        INSERT INTO gamification_sync_history
        (user_id, synced_at, odometer, miles_delta, verified_miles, battery_level, charging_state, charge_rate, efficiency_whmi)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            synced_at,
            odometer,
            miles_delta,
            verified_miles,
            battery_level if battery_level is None else float(battery_level),
            str(charging_state) if charging_state is not None else None,
            charge_rate if charge_rate is None else float(charge_rate),
            efficiency_whmi if efficiency_whmi is None else float(efficiency_whmi),
        ),
    )
    conn.commit()
    conn.close()
    append_gamification_activity(
        user_id,
        "telemetry_sync",
        "telemetry",
        {
            "synced_at": synced_at,
            "odometer": odometer,
            "miles_delta": miles_delta,
            "verified_miles": verified_miles,
            "battery_level": battery_level,
            "charging_state": charging_state,
            "charge_rate": charge_rate,
            "efficiency_whmi": efficiency_whmi,
        },
        event_ts=synced_at,
    )
    log_v2_event(
        "telemetry_sync_persisted",
        user_id=user_id,
        previous_odometer=previous_odometer,
        current_odometer=odometer,
        miles_added=miles_delta,
        verified_miles=verified_miles,
        reward_added=verified_miles,
    )

    challenges = updateChallengeProgress(user_id, {"verified_miles": verified_miles})
    badges = awardEligibleBadges(user_id)
    state_after = get_or_create_gamification_state(user_id)
    events = []
    events.extend(activity["events"])
    events.extend(challenges["events"])
    events.extend(badges["events"])
    return {
        "state": dict(state_after),
        "events": events,
        "streak": activity["streak"],
        "challenges": challenges,
        "badges": badges,
    }


def getGamificationState(user_id):
    state = get_or_create_gamification_state(user_id)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT challenge_key, window_key, window_start, window_end, progress, target, completed, completed_at
        FROM gamification_challenge_windows
        WHERE user_id = ?
          AND active = 1
        ORDER BY challenge_key ASC, window_start DESC
        """,
        (user_id,),
    )
    challenges = [dict(row) for row in cur.fetchall()]

    cur.execute(
        """
        SELECT badge_key, badge_name, badge_asset, awarded_at
        FROM gamification_badges
        WHERE user_id = ?
        ORDER BY awarded_at DESC
        """,
        (user_id,),
    )
    badges = [dict(row) for row in cur.fetchall()]

    cur.execute(
        """
        SELECT event_type, source, details_json, created_at
        FROM gamification_activity_feed
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 100
        """,
        (user_id,),
    )
    feed_rows = []
    for row in cur.fetchall():
        row_dict = dict(row)
        try:
            row_dict["details"] = json.loads(row_dict.get("details_json") or "{}")
        except json.JSONDecodeError:
            row_dict["details"] = {}
        feed_rows.append(row_dict)

    cur.execute(
        """
        SELECT synced_at, odometer, miles_delta, verified_miles, battery_level, charging_state, charge_rate, efficiency_whmi
        FROM gamification_sync_history
        WHERE user_id = ?
        ORDER BY synced_at DESC
        LIMIT 100
        """
        ,
        (user_id,),
    )
    telemetry_history = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {
        "state": dict(state),
        "challenges": challenges,
        "badges": badges,
        "activityFeed": feed_rows,
        "telemetrySyncHistory": telemetry_history,
    }


def expire_sport_mode(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    if user and user["sport_mode_active"] and user["sport_mode_end_time"] and now_ts() >= user["sport_mode_end_time"]:
        cur.execute("UPDATE users SET sport_mode_active = 0 WHERE id = ?", (user_id,))
        conn.commit()
        log_v2_event("sport_mode_expired", user_id=user_id)
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    updated = cur.fetchone()
    conn.close()
    return updated


def bind_vehicle_to_user(vin, user_id, odometer):
    if not vin or vin == "Unknown VIN":
        return True

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM vehicles WHERE vin = ?", (vin,))
    existing = cur.fetchone()
    if existing and int(existing["user_id"]) != int(user_id):
        log_rule_violation("vin_wallet_conflict", vin=vin, existing_user=existing["user_id"], requested_user=user_id)
        conn.close()
        return False

    if existing is None:
        cur.execute(
            "INSERT INTO vehicles (vin, user_id, odometer_last, created_at) VALUES (?, ?, ?, ?)",
            (vin, user_id, odometer, now_ts()),
        )
        log_v2_event("vehicle_bound", vin=vin, user_id=user_id)
    else:
        cur.execute("UPDATE vehicles SET odometer_last = ? WHERE vin = ?", (odometer, vin))

    conn.commit()
    conn.close()
    return True


def get_daily_verified_miles(user_id, event_vehicle_id, day_start):
    day_end = day_start + 86400
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(COALESCE(verified_miles, miles_added)), 0) AS miles
        FROM reward_events
        WHERE user_id = ?
          AND tesla_vehicle_id = ?
          AND synced_at >= ?
          AND synced_at < ?
          AND COALESCE(verified_miles, miles_added) >= ?
        """,
        (user_id, event_vehicle_id, day_start, day_end, MINIMUM_TRIP_DISTANCE),
    )
    miles = float(cur.fetchone()["miles"] or 0)
    conn.close()
    return miles


def get_last_reward_event(user_id, event_vehicle_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, odometer_reading, miles_added, synced_at
        FROM reward_events
        WHERE user_id = ? AND tesla_vehicle_id = ?
        ORDER BY synced_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, event_vehicle_id),
    )
    row = cur.fetchone()
    conn.close()
    return row


def validate_trip_for_scoring(user_id, event_vehicle_id, miles_added, previous_synced_at, synced_at):
    if miles_added <= 0:
        return 0.0
    if miles_added < MINIMUM_TRIP_DISTANCE:
        log_rule_violation("minimum_trip_distance", user_id=user_id, vehicle_id=event_vehicle_id, miles=miles_added)
        append_gamification_activity(user_id, "telemetry_rejected", "anti_abuse", {"reason": "minimum_trip_distance", "vehicleId": event_vehicle_id, "miles": miles_added})
        return 0.0

    duration = synced_at - previous_synced_at if previous_synced_at else None
    if duration is not None and duration < MIN_SYNC_INTERVAL_SECONDS:
        log_rule_violation("minimum_sync_interval", user_id=user_id, vehicle_id=event_vehicle_id, duration=duration)
        append_gamification_activity(user_id, "telemetry_rejected", "anti_abuse", {"reason": "minimum_sync_interval", "vehicleId": event_vehicle_id, "duration": duration})
        return 0.0

    # Sync cadence is not trip duration, so only enforce an upper-bound speed check here.
    effective_duration = duration if duration and duration > 0 else MINIMUM_TRIP_DURATION_SECONDS
    average_speed = miles_added / max(effective_duration / 3600, 0.01)
    if average_speed > MAX_AVERAGE_SPEED:
        log_rule_violation("max_average_speed", user_id=user_id, vehicle_id=event_vehicle_id, average_speed=average_speed)
        append_gamification_activity(user_id, "telemetry_rejected", "anti_abuse", {"reason": "max_average_speed", "vehicleId": event_vehicle_id, "average_speed": round(average_speed, 2)})
        return 0.0

    day_start = current_week_bounds(synced_at)[0] + ((datetime.fromtimestamp(synced_at).weekday()) * 86400)
    counted_today = get_daily_verified_miles(user_id, event_vehicle_id, day_start)
    remaining = max(0.0, MAX_DAILY_MILES - counted_today)
    if miles_added > remaining:
        log_rule_violation("max_daily_miles", user_id=user_id, vehicle_id=event_vehicle_id, miles=miles_added, remaining=remaining)
        append_gamification_activity(user_id, "telemetry_capped", "anti_abuse", {"reason": "max_daily_miles", "vehicleId": event_vehicle_id, "miles": miles_added, "remaining": remaining})
    return min(miles_added, remaining)


def get_week_verified_miles(user_id, event_vehicle_id, week_start, week_end):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(COALESCE(verified_miles, miles_added)), 0) AS miles
        FROM reward_events
        WHERE user_id = ?
          AND tesla_vehicle_id = ?
          AND synced_at BETWEEN ? AND ?
          AND COALESCE(verified_miles, miles_added) >= ?
        """,
        (user_id, event_vehicle_id, week_start, week_end, MINIMUM_TRIP_DISTANCE),
    )
    miles = float(cur.fetchone()["miles"] or 0)
    conn.close()
    return miles


def mission_points(mission_type):
    return {
        "sync_vehicle": 25,
        "drive_once_today": 50,
        "efficient_trip": 75,
        "drive_on_5_days": 200,
        "complete_3_healthy_charges": 150,
        "stay_active_all_week": 150,
    }.get(mission_type, 0)


def upsert_mission(user_id, mission_type, progress, completed):
    conn = get_db_connection()
    cur = conn.cursor()
    week_start, _ = current_week_bounds()
    completed_at = now_ts() if completed else None
    cur.execute(
        """
        INSERT INTO missions (user_id, mission_type, progress, completed, completed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, mission_type) DO UPDATE SET
            progress = excluded.progress,
            completed = CASE WHEN missions.completed = 1 THEN 1 ELSE excluded.completed END,
            completed_at = CASE
                WHEN missions.completed = 1 THEN missions.completed_at
                WHEN excluded.completed = 1 THEN excluded.completed_at
                ELSE missions.completed_at
            END
        """,
        (user_id, mission_type, progress, 1 if completed else 0, completed_at),
    )
    if completed:
        cur.execute(
            """
            INSERT OR IGNORE INTO mission_badges
            (user_id, mission_type, week_start, badge_asset, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, mission_type, week_start, "/static/evfi-badge-genesis.svg", now_ts()),
        )
    conn.commit()
    if completed:
        log_v2_event("badge_generated", user_id=user_id, mission_type=mission_type, week_start=week_start)
        log_v2_event("mission_completion", user_id=user_id, mission_type=mission_type, progress=progress)
    conn.close()


def ensure_weekly_reset(user_id):
    week_start, _ = current_week_bounds()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM weekly_resets WHERE user_id = ? AND week_start = ?", (user_id, week_start))
    already_reset = cur.fetchone()
    if already_reset:
        conn.close()
        return

    cur.execute("SELECT COUNT(*) AS count FROM weekly_resets WHERE user_id = ?", (user_id,))
    has_prior_reset = int(cur.fetchone()["count"] or 0) > 0
    cur.execute(
        "INSERT OR IGNORE INTO weekly_resets (user_id, week_start, reset_at) VALUES (?, ?, ?)",
        (user_id, week_start, now_ts()),
    )
    if has_prior_reset:
        cur.execute(
            "UPDATE missions SET progress = 0, completed = 0, completed_at = NULL WHERE user_id = ?",
            (user_id,),
        )
        cur.execute("DELETE FROM mission_badges WHERE user_id = ?", (user_id,))
        log_v2_event("mission_reset", user_id=user_id, week_start=week_start)
        log_v2_event("weekly_reset_triggered", user_id=user_id, week_start=week_start)
    conn.commit()
    conn.close()


def get_completed_mission_bonus(user_id):
    ensure_weekly_reset(user_id)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT mission_type FROM missions WHERE user_id = ? AND completed = 1", (user_id,))
    bonus = sum(mission_points(row["mission_type"]) for row in cur.fetchall())
    conn.close()
    return float(bonus)


def calculate_active_days(user_id, event_vehicle_id, week_start, week_end):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT synced_at, COALESCE(verified_miles, miles_added) AS verified_miles
        FROM reward_events
        WHERE user_id = ?
          AND tesla_vehicle_id = ?
          AND synced_at BETWEEN ? AND ?
          AND COALESCE(verified_miles, miles_added) >= ?
        """,
        (user_id, event_vehicle_id, week_start, week_end, MINIMUM_TRIP_DISTANCE),
    )
    days = {time.strftime("%Y-%m-%d", time.localtime(row["synced_at"])) for row in cur.fetchall()}
    conn.close()
    return len(days)


def calculate_streak_multiplier(active_days):
    if active_days >= 30:
        return 1.25
    if active_days >= 14:
        return 1.15
    if active_days >= 7:
        return 1.10
    if active_days >= 3:
        return 1.05
    return 1.0


def get_week_sync_metrics(user_id, week_start, week_end):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*) AS sync_events,
            COUNT(DISTINCT strftime('%Y-%m-%d', synced_at, 'unixepoch', 'localtime')) AS sync_days,
            AVG(CASE WHEN efficiency_whmi IS NOT NULL AND efficiency_whmi > 0 THEN efficiency_whmi END) AS avg_efficiency_whmi,
            SUM(CASE WHEN charging_state IS NOT NULL AND lower(charging_state) IN ('charging', 'complete') THEN 1 ELSE 0 END) AS charging_events,
            SUM(CASE WHEN charging_state IS NOT NULL AND lower(charging_state) = 'charging' AND battery_level BETWEEN 20 AND 80 THEN 1 ELSE 0 END) AS healthy_charge_sessions,
            SUM(CASE WHEN charging_state IS NOT NULL AND lower(charging_state) IN ('charging', 'complete') AND battery_level >= 95 THEN 1 ELSE 0 END) AS high_soc_charge_sessions,
            SUM(CASE WHEN charging_state IS NOT NULL AND lower(charging_state) = 'charging' AND (CAST(strftime('%H', synced_at, 'unixepoch', 'localtime') AS INTEGER) >= 22 OR CAST(strftime('%H', synced_at, 'unixepoch', 'localtime') AS INTEGER) < 6) THEN 1 ELSE 0 END) AS offpeak_charge_sessions,
            SUM(CASE WHEN charging_state IS NOT NULL AND lower(charging_state) = 'charging' AND charge_rate IS NOT NULL AND charge_rate > 0 AND charge_rate <= 19.5 THEN 1 ELSE 0 END) AS ac_charge_sessions,
            SUM(CASE WHEN charging_state IS NOT NULL AND lower(charging_state) = 'charging' AND charge_rate IS NOT NULL AND charge_rate >= 45 THEN 1 ELSE 0 END) AS fast_charge_sessions
        FROM gamification_sync_history
        WHERE user_id = ?
          AND synced_at BETWEEN ? AND ?
        """,
        (user_id, week_start, week_end),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {
        "sync_events": 0,
        "sync_days": 0,
        "avg_efficiency_whmi": None,
        "charging_events": 0,
        "healthy_charge_sessions": 0,
        "high_soc_charge_sessions": 0,
        "offpeak_charge_sessions": 0,
        "ac_charge_sessions": 0,
        "fast_charge_sessions": 0,
    }


def infer_week_charge_sessions(user_id, week_start, week_end):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM charge_sessions
        WHERE user_id = ?
          AND session_end_ts >= ?
          AND session_start_ts <= ?
        ORDER BY session_start_ts ASC, id ASC
        """,
        (user_id, week_start, week_end),
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "startTs": int(row["session_start_ts"] or 0),
            "endTs": int(row["session_end_ts"] or 0),
            "lastSyncedAt": int(row["last_synced_at"] or row["session_end_ts"] or 0),
            "startBattery": as_float(row["start_battery"], 0.0),
            "endBattery": as_float(row["end_battery"], 0.0),
            "maxBattery": as_float(row["max_battery"], 0.0),
            "snapshotCount": int(row["snapshot_count"] or 0),
            "avgChargeRate": as_float(row["avg_charge_rate"], 0.0),
            "maxChargeRate": as_float(row["max_charge_rate"], 0.0),
            "offpeak": bool(int(row["offpeak"] or 0)),
            "healthy": bool(int(row["healthy"] or 0)),
            "highSoc": bool(int(row["high_soc"] or 0)),
            "acCharge": bool(int(row["ac_charge"] or 0)),
            "fastCharge": bool(int(row["fast_charge"] or 0)),
            "sessionHours": round(max(0.0, (int(row["session_end_ts"] or 0) - int(row["session_start_ts"] or 0)) / 3600), 2),
        }
        for row in rows
    ]


def get_efficiency_baseline(user_id, before_ts):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT AVG(efficiency_whmi) AS baseline_efficiency
        FROM gamification_sync_history
        WHERE user_id = ?
          AND synced_at < ?
          AND efficiency_whmi IS NOT NULL
          AND efficiency_whmi > 0
        """,
        (user_id, before_ts),
    )
    row = cur.fetchone()
    conn.close()
    return as_float(row["baseline_efficiency"] if row else 0.0, 0.0)


def get_week_penalty_points(user_id, week_start, week_end):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS total
        FROM gamification_activity_feed
        WHERE user_id = ?
          AND created_at BETWEEN ? AND ?
          AND event_type IN ('telemetry_rejected', 'telemetry_capped')
        """,
        (user_id, week_start, week_end),
    )
    count = int(cur.fetchone()["total"] or 0)
    conn.close()
    return round(count * TELEMETRY_REJECTION_PENALTY, 2)


def compute_efficiency_score(avg_efficiency_whmi, baseline_efficiency_whmi):
    avg_efficiency = as_float(avg_efficiency_whmi, 0.0)
    baseline_efficiency = as_float(baseline_efficiency_whmi, 0.0)
    if avg_efficiency <= 0 or baseline_efficiency <= 0:
        return 0.0
    improvement_ratio = (baseline_efficiency - avg_efficiency) / baseline_efficiency
    raw_score = improvement_ratio * 200.0
    return round(max(-EFFICIENCY_PENALTY_CAP, min(EFFICIENCY_BONUS_CAP, raw_score)), 2)


def summarize_charge_sessions(charge_sessions):
    healthy_charge_sessions = sum(1 for session in charge_sessions if session.get("healthy"))
    high_soc_charge_sessions = sum(1 for session in charge_sessions if session.get("highSoc"))
    offpeak_charge_sessions = sum(1 for session in charge_sessions if session.get("offpeak"))
    ac_charge_sessions = sum(1 for session in charge_sessions if session.get("acCharge"))
    fast_charge_sessions = sum(1 for session in charge_sessions if session.get("fastCharge"))
    return {
        "session_count": len(charge_sessions),
        "healthy_charge_sessions": healthy_charge_sessions,
        "high_soc_charge_sessions": high_soc_charge_sessions,
        "offpeak_charge_sessions": offpeak_charge_sessions,
        "ac_charge_sessions": ac_charge_sessions,
        "fast_charge_sessions": fast_charge_sessions,
    }


def compute_charging_score(charge_session_summary):
    healthy_charge_sessions = int(charge_session_summary.get("healthy_charge_sessions") or 0)
    high_soc_charge_sessions = int(charge_session_summary.get("high_soc_charge_sessions") or 0)
    offpeak_charge_sessions = int(charge_session_summary.get("offpeak_charge_sessions") or 0)
    ac_charge_sessions = int(charge_session_summary.get("ac_charge_sessions") or 0)
    fast_charge_sessions = int(charge_session_summary.get("fast_charge_sessions") or 0)
    healthy_points = min(HEALTHY_CHARGE_SCORE_CAP, healthy_charge_sessions * HEALTHY_CHARGE_SESSION_POINTS)
    offpeak_points = min(OFFPEAK_CHARGE_SCORE_CAP, offpeak_charge_sessions * OFFPEAK_CHARGE_SESSION_POINTS)
    ac_points = min(AC_CHARGE_SCORE_CAP, ac_charge_sessions * AC_CHARGE_SESSION_POINTS)
    high_soc_penalty = high_soc_charge_sessions * HIGH_SOC_CHARGE_PENALTY
    fast_charge_penalty = min(FAST_CHARGE_PENALTY_CAP, fast_charge_sessions * FAST_CHARGE_SESSION_PENALTY)
    total = healthy_points + offpeak_points + ac_points - high_soc_penalty - fast_charge_penalty
    return round(max(0.0, total), 2)


def compute_participation_bonus(sync_metrics):
    sync_events = int(sync_metrics.get("sync_events") or 0)
    return round(min(SYNC_PARTICIPATION_CAP, sync_events * SYNC_PARTICIPATION_POINTS), 2)


def build_weekly_score_breakdown(user_id, event_vehicle_id, week_start, week_end):
    verified_miles = get_week_verified_miles(user_id, event_vehicle_id, week_start, week_end)
    active_days = calculate_active_days(user_id, event_vehicle_id, week_start, week_end)
    streak_multiplier = calculate_streak_multiplier(active_days)
    sync_metrics = get_week_sync_metrics(user_id, week_start, week_end)
    charge_sessions = infer_week_charge_sessions(user_id, week_start, week_end)
    charge_session_summary = summarize_charge_sessions(charge_sessions)
    baseline_efficiency = get_efficiency_baseline(user_id, week_start)
    avg_efficiency = as_float(sync_metrics.get("avg_efficiency_whmi"), 0.0)
    efficiency_score = compute_efficiency_score(avg_efficiency, baseline_efficiency)
    charging_score = compute_charging_score(charge_session_summary)
    participation_bonus = compute_participation_bonus(sync_metrics)
    penalty_score = get_week_penalty_points(user_id, week_start, week_end)
    active_day_score = float(active_days * 25)
    pre_multiplier_score = verified_miles + active_day_score + efficiency_score + charging_score + participation_bonus
    post_multiplier_score = max(0.0, round(pre_multiplier_score * streak_multiplier, 2))
    pre_bonus_score = max(0.0, round(post_multiplier_score - penalty_score, 2))
    return {
        "verified_miles": round(float(verified_miles), 2),
        "active_days": int(active_days),
        "active_day_score": round(active_day_score, 2),
        "streak_multiplier": float(streak_multiplier),
        "sync_events": int(sync_metrics.get("sync_events") or 0),
        "sync_days": int(sync_metrics.get("sync_days") or 0),
        "participation_bonus": participation_bonus,
        "avg_efficiency_whmi": round(avg_efficiency, 2) if avg_efficiency > 0 else 0.0,
        "baseline_efficiency_whmi": round(baseline_efficiency, 2) if baseline_efficiency > 0 else 0.0,
        "efficiency_score": efficiency_score,
        "charging_events": int(sync_metrics.get("charging_events") or 0),
        "charge_sessions": int(charge_session_summary.get("session_count") or 0),
        "healthy_charge_sessions": int(charge_session_summary.get("healthy_charge_sessions") or 0),
        "high_soc_charge_sessions": int(charge_session_summary.get("high_soc_charge_sessions") or 0),
        "offpeak_charge_sessions": int(charge_session_summary.get("offpeak_charge_sessions") or 0),
        "ac_charge_sessions": int(charge_session_summary.get("ac_charge_sessions") or 0),
        "fast_charge_sessions": int(charge_session_summary.get("fast_charge_sessions") or 0),
        "charging_score": charging_score,
        "penalty_score": penalty_score,
        "pre_multiplier_score": round(pre_multiplier_score, 2),
        "post_multiplier_score": post_multiplier_score,
        "pre_bonus_score": pre_bonus_score,
    }


def build_weekly_reward_explanations(score_breakdown, reward_preview):
    explanations = []
    if as_float(score_breakdown.get("verified_miles"), 0.0) > 0:
        explanations.append(f'Verified driving contributed {fmt2(score_breakdown.get("verified_miles"))} score from real miles synced this week.')
    else:
        explanations.append("No verified driving miles have counted yet this week, so the score is relying on supporting behavior only.")

    if int(score_breakdown.get("active_days") or 0) > 0:
        explanations.append(f'Activity across {int(score_breakdown.get("active_days") or 0)} day(s) added {fmt2(score_breakdown.get("active_day_score"))} score and a {score_breakdown.get("streak_multiplier", 1.0):.2f}x streak multiplier.')

    if as_float(score_breakdown.get("charging_score"), 0.0) > 0:
        explanations.append(
            f'Charging behavior added {fmt2(score_breakdown.get("charging_score"))} score from '
            f'{int(score_breakdown.get("charge_sessions") or 0)} inferred session(s), including '
            f'{int(score_breakdown.get("healthy_charge_sessions") or 0)} healthy, '
            f'{int(score_breakdown.get("offpeak_charge_sessions") or 0)} off-peak, and '
            f'{int(score_breakdown.get("ac_charge_sessions") or 0)} AC charging session(s).'
        )

    if int(score_breakdown.get("fast_charge_sessions") or 0) > 0 or int(score_breakdown.get("high_soc_charge_sessions") or 0) > 0:
        explanations.append(
            f'Charging penalties reflect {int(score_breakdown.get("fast_charge_sessions") or 0)} fast-charge and '
            f'{int(score_breakdown.get("high_soc_charge_sessions") or 0)} high-SoC charging snapshot(s).'
        )

    efficiency_score = as_float(score_breakdown.get("efficiency_score"), 0.0)
    if efficiency_score > 0:
        explanations.append(
            f'Efficiency improved against your baseline: {fmt2(score_breakdown.get("avg_efficiency_whmi"))} Wh/mi versus {fmt2(score_breakdown.get("baseline_efficiency_whmi"))} baseline.'
        )
    elif efficiency_score < 0:
        explanations.append(
            f'Efficiency underperformed your baseline this week: {fmt2(score_breakdown.get("avg_efficiency_whmi"))} Wh/mi versus {fmt2(score_breakdown.get("baseline_efficiency_whmi"))}.'
        )

    if as_float(score_breakdown.get("penalty_score"), 0.0) > 0:
        explanations.append(f'Anti-abuse or capped telemetry events reduced score by {fmt2(score_breakdown.get("penalty_score"))}.')

    if as_float(score_breakdown.get("mission_bonus"), 0.0) > 0:
        explanations.append(f'Missions added {fmt2(score_breakdown.get("mission_bonus"))} score after the weekly mission cap was applied.')

    if as_float(score_breakdown.get("staking_bonus"), 0.0) > 0:
        explanations.append(
            f'Your active staking tier added a {score_breakdown.get("staking_boost_pct", 0):.2f}% boost worth {fmt2(score_breakdown.get("staking_bonus"))} score.'
        )

    explanations.append(
        f'The current emission factor is {reward_preview["emissionFactor"]:.6f}, producing an estimated {fmt2(reward_preview["estimatedEvfi"])} EVFi for the week.'
    )
    return explanations[:6]


def update_missions(user_id, score_breakdown):
    ensure_weekly_reset(user_id)
    verified_miles = as_float(score_breakdown.get("verified_miles"), 0.0)
    active_days = int(score_breakdown.get("active_days") or 0)
    sync_events = int(score_breakdown.get("sync_events") or 0)
    healthy_charge_sessions = int(score_breakdown.get("healthy_charge_sessions") or 0)
    efficiency_score = as_float(score_breakdown.get("efficiency_score"), 0.0)

    upsert_mission(user_id, "sync_vehicle", min(sync_events, 1), sync_events >= 1)
    upsert_mission(user_id, "drive_once_today", 1 if verified_miles >= MINIMUM_TRIP_DISTANCE else 0, verified_miles >= MINIMUM_TRIP_DISTANCE)
    upsert_mission(user_id, "efficient_trip", max(0.0, efficiency_score), efficiency_score > 0)
    upsert_mission(user_id, "drive_on_5_days", active_days, active_days >= 5)
    upsert_mission(user_id, "complete_3_healthy_charges", healthy_charge_sessions, healthy_charge_sessions >= 3)
    upsert_mission(user_id, "stay_active_all_week", active_days, active_days >= 7)


def calculate_weekly_score(user_id, vin, event_vehicle_id, charge_health_score=100.0):
    week_start, week_end = current_week_bounds()
    score_breakdown = build_weekly_score_breakdown(user_id, event_vehicle_id, week_start, week_end)
    update_missions(user_id, score_breakdown)
    mission_bonus_raw = get_completed_mission_bonus(user_id)
    mission_bonus_cap = round(score_breakdown["pre_bonus_score"] * MISSION_BONUS_CAP_SHARE, 2)
    mission_bonus = round(min(mission_bonus_raw, mission_bonus_cap), 2)
    pre_stake_score = round(max(0.0, score_breakdown["pre_bonus_score"] + mission_bonus), 2)
    staking_boost_pct = get_active_stake_boost_pct(user_id)
    staking_bonus = round(pre_stake_score * (staking_boost_pct / 100.0), 2)
    total_score = round(max(0.0, pre_stake_score + staking_bonus), 2)
    score_breakdown["mission_bonus_raw"] = round(mission_bonus_raw, 2)
    score_breakdown["mission_bonus_cap"] = mission_bonus_cap
    score_breakdown["mission_bonus_applied"] = mission_bonus
    score_breakdown["staking_boost_pct"] = staking_boost_pct
    score_breakdown["staking_bonus"] = staking_bonus
    score_breakdown["total_score"] = total_score

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO weekly_scores
        (user_id, vin, week_start, week_end, verified_miles, active_days, charge_health_score, streak_multiplier, mission_bonus, total_score, created_at, score_breakdown_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, vin, week_start) DO UPDATE SET
            week_end = excluded.week_end,
            verified_miles = excluded.verified_miles,
            active_days = excluded.active_days,
            charge_health_score = excluded.charge_health_score,
            streak_multiplier = excluded.streak_multiplier,
            mission_bonus = excluded.mission_bonus,
            total_score = excluded.total_score,
            created_at = excluded.created_at,
            score_breakdown_json = excluded.score_breakdown_json
        """,
        (
            user_id,
            vin,
            week_start,
            week_end,
            score_breakdown["verified_miles"],
            score_breakdown["active_days"],
            score_breakdown["charging_score"],
            score_breakdown["streak_multiplier"],
            mission_bonus,
            total_score,
            now_ts(),
            json.dumps(score_breakdown, sort_keys=True),
        ),
    )
    conn.commit()
    cur.execute(
        "SELECT * FROM weekly_scores WHERE user_id = ? AND vin = ? AND week_start = ?",
        (user_id, vin, week_start),
    )
    row = cur.fetchone()
    conn.close()
    log_v2_event("score_calculation", user_id=user_id, vin=vin, week_start=week_start, total_score=total_score)
    return row


def get_current_week_score(user_id, vin):
    week_start, _ = current_week_bounds()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM weekly_scores WHERE user_id = ? AND vin = ? AND week_start = ?",
        (user_id, vin, week_start),
    )
    row = cur.fetchone()
    conn.close()
    return row


def calculate_weekly_emission_factor(week_start, week_end):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(total_score), 0) AS total_score FROM weekly_scores WHERE week_start = ? AND week_end = ?",
        (week_start, week_end),
    )
    total_score = float(cur.fetchone()["total_score"] or 0)
    conn.close()
    effective_network_score = max(total_score, WEEKLY_SCORE_BOOTSTRAP_FLOOR)
    weekly_pool = float(WEEKLY_REWARD_POOL)
    emission_factor = 0.0 if effective_network_score <= 0 else weekly_pool / effective_network_score
    return {
        "actual_network_score": round(total_score, 2),
        "effective_network_score": round(effective_network_score, 2),
        "weekly_pool": round(weekly_pool, 2),
        "emission_factor": round(emission_factor, 8),
    }


def estimate_weekly_reward(score_value, week_start, week_end):
    context = calculate_weekly_emission_factor(week_start, week_end)
    allocated = round(min(float(score_value or 0.0) * context["emission_factor"], MAX_WEEKLY_EVFI), 2)
    context["estimated_evfi"] = allocated
    return context


def distribute_weekly_pool(user_id, week_start, week_end):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(total_score), 0) AS score FROM weekly_scores WHERE user_id = ? AND week_start = ? AND week_end = ?",
        (user_id, week_start, week_end),
    )
    user_score = float(cur.fetchone()["score"] or 0)
    allocation_context = estimate_weekly_reward(user_score, week_start, week_end)
    allocated = allocation_context["estimated_evfi"]
    cur.execute(
        """
        INSERT INTO claims (user_id, week_start, week_end, score, evfi_allocated, claimed, claimed_at, reward_type, allocation_context_json)
        VALUES (?, ?, ?, ?, ?, 0, NULL, 'weekly', ?)
        ON CONFLICT(user_id, week_start, week_end) DO UPDATE SET
            score = excluded.score,
            evfi_allocated = excluded.evfi_allocated,
            reward_type = excluded.reward_type,
            allocation_context_json = excluded.allocation_context_json
        """,
        (user_id, week_start, week_end, user_score, allocated, json.dumps(allocation_context, sort_keys=True)),
    )
    conn.commit()
    cur.execute(
        "SELECT * FROM claims WHERE user_id = ? AND week_start = ? AND week_end = ?",
        (user_id, week_start, week_end),
    )
    claim = cur.fetchone()
    conn.close()
    log_v2_event("distribution", user_id=user_id, week_start=week_start, score=user_score, evfi_allocated=allocated, **allocation_context)
    return claim


def get_last_distribution(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM claims WHERE user_id = ? AND week_start > 0 ORDER BY week_start DESC, id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_user_missions(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT challenge_key, window_key, window_start, window_end, progress, target, completed, completed_at
        FROM gamification_challenge_windows
        WHERE user_id = ?
          AND active = 1
        ORDER BY challenge_key ASC, window_start DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    row_map = {}
    for row in rows:
        key = row["challenge_key"]
        if key not in row_map:
            row_map[key] = row
    ordered_keys = [
        "drive_25_miles_weekly",
        "sync_3_days_in_a_row",
        "earn_250_evfi",
    ]
    missions = []
    for challenge_key in ordered_keys:
        target = float(CHALLENGE_DEFS[challenge_key]["target"])
        row = row_map.get(challenge_key)
        progress = float(row["progress"] if row else 0.0)
        completed = bool(row["completed"]) if row else False
        progress_ratio = 1.0 if target <= 0 else min(progress / target, 1.0)
        missions.append(
            {
                "mission_type": CHALLENGE_DEFS[challenge_key]["label"],
                "progress": round(progress_ratio * 100.0, 2),
                "completed": 1 if completed else 0,
                "completed_at": row["completed_at"] if row else None,
                "badge_asset": "/static/evfi-badge-genesis.svg" if completed else None,
            }
        )
    conn.close()
    return missions


def ensure_airdrop_claim(user_id, total_miles):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM claims WHERE user_id = ? AND week_start = 0 AND week_end = 0", (user_id,))
    claim = cur.fetchone()
    onboarding_amount = round(float(ONBOARDING_AIRDROP_EVFI), 2)
    allocation_context = {
        "reward_bucket": "onboarding_airdrop",
        "fixed_amount_evfi": onboarding_amount,
        "qualifying_total_miles": round(float(total_miles or 0.0), 2),
    }
    if claim is None:
        cur.execute(
            """
            INSERT INTO claims (user_id, week_start, week_end, score, evfi_allocated, claimed, claimed_at, reward_type, allocation_context_json)
            VALUES (?, 0, 0, ?, ?, 0, NULL, 'airdrop', ?)
            """,
            (user_id, round(float(total_miles or 0.0), 2), onboarding_amount, json.dumps(allocation_context, sort_keys=True)),
        )
        conn.commit()
        cur.execute("SELECT * FROM claims WHERE user_id = ? AND week_start = 0 AND week_end = 0", (user_id,))
        claim = cur.fetchone()
        log_v2_event("airdrop_available", user_id=user_id, amount=onboarding_amount, qualifying_total_miles=total_miles)
    else:
        if int(claim["claimed"] or 0) == 0:
            cur.execute(
                """
                UPDATE claims
                SET score = ?,
                    evfi_allocated = ?,
                    reward_type = 'airdrop',
                    allocation_context_json = ?
                WHERE id = ?
                """,
                (round(float(total_miles or 0.0), 2), onboarding_amount, json.dumps(allocation_context, sort_keys=True), int(claim["id"])),
            )
        else:
            cur.execute(
                """
                UPDATE claims
                SET reward_type = 'airdrop',
                    allocation_context_json = ?
                WHERE id = ?
                """,
                (json.dumps(allocation_context, sort_keys=True), int(claim["id"])),
            )
        conn.commit()
        cur.execute("SELECT * FROM claims WHERE id = ?", (int(claim["id"]),))
        claim = cur.fetchone()
    allocated = round(float(claim["evfi_allocated"] or 0.0), 2)
    conn.close()
    record_evfi_earning(user_id, f"airdrop-allocation:{user_id}", allocated, "airdrop_allocation")
    return claim


def get_airdrop_claim(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM claims WHERE user_id = ? AND week_start = 0 AND week_end = 0", (user_id,))
    claim = cur.fetchone()
    conn.close()
    return claim


def driver_coach_agent():
    pass


def reward_optimizer_agent():
    pass


def battery_health_agent():
    pass


def fraud_detection_agent():
    pass


def weekly_distribution_trigger():
    pass


def price_feed_source():
    pass


def random_reward_source():
    pass


def assign_demo_reward_onchain(wallet_address, amount_tokens, batch_id):
    if not is_valid_evm_address(wallet_address):
        raise ValueError("A valid wallet address is required")
    if not EVFI_REWARDS_ADDRESS or not EVFI_TOKEN_ADDRESS:
        raise ValueError("EVFi contract addresses are not configured")

    command = [
        "cmd",
        "/c",
        "node",
        EVFI_ASSIGN_SCRIPT,
        "--wallet",
        wallet_address,
        "--amount",
        str(amount_tokens),
        "--batch-id",
        batch_id,
    ]

    completed = subprocess.run(
        command,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        parsed_error = None
        if stderr:
            try:
                parsed_error = json.loads(stderr)
            except json.JSONDecodeError:
                parsed_error = {"ok": False, "error": {"message": stderr}}
        elif stdout:
            try:
                parsed_error = json.loads(stdout)
            except json.JSONDecodeError:
                parsed_error = {"ok": False, "error": {"message": stdout}}

        if parsed_error:
            raise RuntimeError(json.dumps(parsed_error))
        raise RuntimeError("Reward assignment failed")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": True, "output": stdout}


def mint_airdrop_onchain(wallet_address, amount_tokens, batch_id):
    if not is_valid_evm_address(wallet_address):
        raise ValueError("A valid wallet address is required")
    if not EVFI_TOKEN_ADDRESS:
        raise ValueError("EVFi token address is not configured")

    command = [
        "cmd",
        "/c",
        "node",
        EVFI_ASSIGN_SCRIPT,
        "--mode",
        "mint-airdrop",
        "--wallet",
        wallet_address,
        "--amount",
        str(amount_tokens),
        "--batch-id",
        batch_id,
    ]

    completed = subprocess.run(
        command,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        parsed_error = None
        raw = stderr or stdout
        if raw:
            try:
                parsed_error = json.loads(raw)
            except json.JSONDecodeError:
                parsed_error = {"ok": False, "error": {"message": raw}}
        if parsed_error:
            raise RuntimeError(json.dumps(parsed_error))
        raise RuntimeError("Airdrop mint failed")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": True, "output": stdout}


def load_vehicle_and_summary(vid, wallet_address=None):
    state = tesla_api.get_vehicle_state(vid)
    if state is None:
        raise ValueError("Vehicle not found")

    if state != "online":
        tesla_api.wake_up_vehicle(vid)
        for _ in range(5):
            time.sleep(2)
            poll_state = tesla_api.get_vehicle_state(vid)
            if poll_state == "online":
                break

    data_resp = tesla_api.get_vehicle_data(vid)
    try:
        data = data_resp.json()
    except Exception as exc:
        raise RuntimeError("Unable to parse Tesla response") from exc

    vehicle_info = data.get("response", {})
    if not vehicle_info:
        raise RuntimeError("No vehicle response returned")

    meta = get_vehicle_display_meta(vehicle_info)
    vin = str(vehicle_info.get("vin", "Unknown VIN"))
    current_odometer = extract_odometer(vehicle_info)
    charge_state = vehicle_info.get("charge_state", {}) or {}
    telemetry_data = {
        "battery_level": charge_state.get("battery_level"),
        "charging_state": charge_state.get("charging_state"),
        "charge_rate": charge_state.get("charge_rate"),
        "efficiency_whmi": vehicle_info.get("drive_state", {}).get("energy_used"),
    }
    summary = sync_vehicle_rewards(
        vid,
        meta["display_name"],
        vin,
        current_odometer,
        wallet_address=wallet_address,
        telemetry_data=telemetry_data,
    )

    return {
        "vehicleInfo": vehicle_info,
        "meta": meta,
        "vin": vin,
        "odometer": current_odometer,
        "summary": summary,
    }


def get_vehicle_image_url():
    if os.path.exists(LOCAL_CAR_IMAGE_PATH):
        return "/static/car-avatar.jpg"
    return None


def decode_tesla_model(vehicle_info):
    vc = vehicle_info.get("vehicle_config", {}) or {}
    car_type = (vc.get("car_type") or "").lower()

    mapping = {
        "model3": "Model 3",
        "modely": "Model Y",
        "models": "Model S",
        "modelx": "Model X"
    }
    return mapping.get(car_type, "Tesla")


def decode_trim(vehicle_info):
    vc = vehicle_info.get("vehicle_config", {}) or {}
    trim = vc.get("trim_badging") or vc.get("trim_name") or ""
    if not trim:
        return "Standard"

    trim_map = {
        "p74d": "Performance",
        "p74dplus": "Performance",
        "74d": "Long Range AWD",
        "74": "Long Range",
        "50": "Standard Range",
        "50d": "AWD",
    }

    return trim_map.get(str(trim).lower(), str(trim).replace("_", " ").title())


def decode_year_from_vin(vin):
    if not vin or len(vin) < 10:
        return "—"

    code = vin[9].upper()
    vin_year_map = {
        "L": 2020,
        "M": 2021,
        "N": 2022,
        "P": 2023,
        "R": 2024,
        "S": 2025,
        "T": 2026,
        "V": 2027,
        "W": 2028,
        "X": 2029,
        "Y": 2030,
    }
    return vin_year_map.get(code, "—")


def get_vehicle_display_meta(vehicle_info):
    display_name = vehicle_info.get("display_name") or "Tesla Vehicle"
    vin = vehicle_info.get("vin") or ""
    model = decode_tesla_model(vehicle_info)
    trim = decode_trim(vehicle_info)
    year = decode_year_from_vin(vin)
    return {
        "display_name": display_name,
        "model": model,
        "trim": trim,
        "year": year
    }


def get_reward_summary_for_vehicle(vid, display_name, vin, current_odometer):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM vehicle_rewards WHERE tesla_vehicle_id = ?",
        (str(vid),)
    )
    existing = cur.fetchone()

    now_ts = int(time.time())

    if existing is None:
        cur.execute("""
            INSERT INTO vehicle_rewards
            (tesla_vehicle_id, display_name, vin, baseline_odometer, latest_odometer, total_miles, drv_balance, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(vid),
            display_name,
            vin,
            current_odometer,
            current_odometer,
            0,
            0,
            now_ts
        ))
        conn.commit()

        cur.execute(
            "SELECT * FROM vehicle_rewards WHERE tesla_vehicle_id = ?",
            (str(vid),)
        )
        row = cur.fetchone()
        conn.close()
        return row

    conn.close()
    return existing


def sync_vehicle_rewards(vid, display_name, vin, current_odometer, wallet_address=None, telemetry_data=None):
    user = get_or_create_user(wallet_address or DEFAULT_WALLET_ADDRESS)
    user = expire_sport_mode(user["id"])
    bind_vehicle_to_user(vin, user["id"], current_odometer)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM vehicle_rewards WHERE tesla_vehicle_id = ?",
        (str(vid),)
    )
    existing = cur.fetchone()

    now_ts = int(time.time())

    should_process_telemetry = True
    if existing is None:
        cur.execute("""
            INSERT INTO vehicle_rewards
            (tesla_vehicle_id, display_name, vin, baseline_odometer, latest_odometer, total_miles, drv_balance, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(vid),
            display_name,
            vin,
            current_odometer,
            current_odometer,
            0,
            0,
            now_ts
        ))

        cur.execute("""
            INSERT INTO reward_events
            (user_id, tesla_vehicle_id, odometer_reading, miles_added, verified_miles, drv_earned, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user["id"],
            str(vid),
            current_odometer,
            0,
            0,
            0,
            now_ts
        ))
        verified_miles = 0.0
        miles_delta = 0.0
    else:
        previous_latest = float(existing["latest_odometer"] or 0)
        baseline = float(existing["baseline_odometer"] or current_odometer)
        previous_synced_at = int(existing["last_synced_at"] or now_ts)

        miles_added = current_odometer - previous_latest
        if miles_added < 0:
            log_rule_violation(
                "odometer_regression",
                user_id=user["id"],
                vehicle_id=str(vid),
                previous_odometer=previous_latest,
                current_odometer=current_odometer,
            )
            append_gamification_activity(
                user["id"],
                "telemetry_rejected",
                "anti_abuse",
                {
                    "reason": "odometer_regression",
                    "vehicleId": str(vid),
                    "previous_odometer": previous_latest,
                    "current_odometer": current_odometer,
                },
            )
            miles_added = 0
        if miles_added == 0 and (now_ts - previous_synced_at) < DUPLICATE_SYNC_WINDOW_SECONDS:
            should_process_telemetry = False
            log_rule_violation(
                "duplicate_sync_event",
                user_id=user["id"],
                vehicle_id=str(vid),
                odometer=current_odometer,
                elapsed=(now_ts - previous_synced_at),
            )
            append_gamification_activity(
                user["id"],
                "telemetry_rejected",
                "anti_abuse",
                {
                    "reason": "duplicate_sync_event",
                    "vehicleId": str(vid),
                    "odometer": current_odometer,
                    "elapsed": (now_ts - previous_synced_at),
                },
            )
        miles_delta = float(miles_added)
        verified_miles = 0.0 if not should_process_telemetry else validate_trip_for_scoring(user["id"], str(vid), miles_added, previous_synced_at, now_ts)
        log_v2_event(
            "reward_sync_delta",
            user_id=user["id"],
            vehicle_id=str(vid),
            previous_odometer=previous_latest,
            current_odometer=current_odometer,
            miles_added=miles_delta,
            verified_miles=verified_miles,
            reward_added=verified_miles,
        )

        total_miles = current_odometer - baseline
        if total_miles < 0:
            total_miles = 0

        drv_balance = total_miles

        cur.execute("""
            UPDATE vehicle_rewards
            SET display_name = ?,
                vin = ?,
                latest_odometer = ?,
                total_miles = ?,
                drv_balance = ?,
                last_synced_at = ?
            WHERE tesla_vehicle_id = ?
        """, (
            display_name,
            vin,
            current_odometer,
            total_miles,
            drv_balance,
            now_ts,
            str(vid)
        ))

        if should_process_telemetry:
            cur.execute("""
                INSERT INTO reward_events
                (user_id, tesla_vehicle_id, odometer_reading, miles_added, verified_miles, drv_earned, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user["id"],
                str(vid),
                current_odometer,
                miles_delta,
                verified_miles,
                verified_miles,
                now_ts
            ))

    conn.commit()

    cur.execute(
        "SELECT * FROM vehicle_rewards WHERE tesla_vehicle_id = ?",
        (str(vid),)
    )
    row = cur.fetchone()
    conn.close()
    if should_process_telemetry:
        processTelemetrySync(
            user["id"],
            {
                "odometer": current_odometer,
                "miles_delta": miles_delta,
                "verified_miles": verified_miles,
                "synced_at": now_ts,
                "battery_level": (telemetry_data or {}).get("battery_level"),
                "charging_state": (telemetry_data or {}).get("charging_state"),
                "charge_rate": (telemetry_data or {}).get("charge_rate"),
                "efficiency_whmi": (telemetry_data or {}).get("efficiency_whmi"),
            },
        )
    calculate_weekly_score(user["id"], vin, str(vid))
    ensure_airdrop_claim(user["id"], current_odometer)
    return row


def get_recent_reward_events(vid, limit=10):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM reward_events
        WHERE tesla_vehicle_id = ?
        ORDER BY synced_at DESC, id DESC
        LIMIT ?
    """, (str(vid), limit))

    rows = cur.fetchall()
    conn.close()
    return rows


def get_cached_vehicle_reward_context(vid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM vehicle_rewards WHERE tesla_vehicle_id = ?", (str(vid),))
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ValueError("Vehicle reward context not found")
    return row


def serialize_reward_event(row):
    return {
        "syncedAt": int(row["synced_at"] or 0),
        "syncedAtLabel": fmt_ts(row["synced_at"]),
        "odometer": as_float(row["odometer_reading"], 0.0),
        "milesAdded": as_float(row["miles_added"], 0.0),
        "verifiedMiles": as_float(row["verified_miles"] if "verified_miles" in row.keys() else row["miles_added"], 0.0),
        "scoreAdded": as_float(row["drv_earned"], 0.0),
    }


def build_dashboard_sync_payload(vid, wallet, context):
    user = get_or_create_user(wallet)
    summary = context["summary"]
    weekly_score = get_current_week_score(user["id"], context["vin"]) or calculate_weekly_score(user["id"], context["vin"], str(vid))
    weekly_reward_preview = build_weekly_reward_preview(user["id"], context["vin"], str(vid))
    weekly_score_breakdown = extract_weekly_score_breakdown(weekly_score)
    weekly_score_explanations = build_weekly_reward_explanations(parse_json_object(weekly_score["score_breakdown_json"] if weekly_score and "score_breakdown_json" in weekly_score.keys() else {}), weekly_reward_preview)
    token_utility = get_user_utility_state(user["id"])
    charge_policy = build_charge_policy_summary()
    gamification = getGamificationState(user["id"])
    airdrop_claim = ensure_airdrop_claim(user["id"], context["odometer"])
    events = [serialize_reward_event(row) for row in get_recent_reward_events(vid)]
    return {
        "ok": True,
        "vehicleId": str(vid),
        "wallet": wallet,
        "odometer": as_float(context["odometer"], 0.0),
        "summary": {
            "telemetryScore": as_float(weekly_reward_preview["weeklyScore"], 0.0),
            "totalMiles": as_float(summary["total_miles"], 0.0),
            "lastSyncedAt": int(summary["last_synced_at"] or 0),
            "lastSyncedLabel": fmt_ts(summary["last_synced_at"]),
            "recommendedAssignment": as_float(weekly_reward_preview["estimatedEvfi"], 0.0),
            "airdropAmount": as_float(airdrop_claim["evfi_allocated"] if airdrop_claim else context["odometer"], 0.0),
            "emissionFactor": as_float(weekly_reward_preview["emissionFactor"], 0.0),
        },
        "weeklyScore": {
            "totalScore": as_float(weekly_score["total_score"] if weekly_score else 0.0, 0.0),
            "updatedAt": int((weekly_score["created_at"] if weekly_score else 0) or 0),
            "updatedAtLabel": fmt_ts(weekly_score["created_at"] if weekly_score else 0),
            "breakdown": weekly_score_breakdown,
            "explanations": weekly_score_explanations,
        },
        "chargePolicy": charge_policy,
        "tokenUtility": token_utility,
        "events": events,
        "gamification": gamification,
    }


# =========================================================
# ROUTES
# =========================================================
@app.route("/")
def index():
    if not tesla_api.tokens:
        url = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/authorize?" + urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": tesla_api.state
        })

        body = f"""
        <section class="hero hero-auth" aria-hidden="true"></section>
        <section class="hero pre-auth-info">
            <div class="pre-auth-copy">
                <div class="badge">EvFi Phase 1</div>
                <h1>Connect Tesla telemetry to EVFi rewards.</h1>
                <p>Use live Tesla odometer data as the offchain score engine, then connect a Sepolia wallet to view and claim real EVFi rewards.</p>
            </div>
            <div class="pre-auth-actions">
                <a class="btn btn-primary" href="{url}">Login with Tesla</a>
            </div>
        </section>
        """
        return render_page("EvFi Fleet", body)

    user = get_or_create_user(DEFAULT_WALLET_ADDRESS)
    record_app_activity(user["id"], "login")

    cars = tesla_api.get_vehicles()

    if not cars:
        body = """
        <section class="hero hero-auth" aria-hidden="true"></section>
        <section class="hero pre-auth-info">
            <div class="pre-auth-copy">
                <div class="badge">Connected</div>
                <h1>No vehicles found</h1>
                <p>Your Tesla account authenticated successfully, but no vehicles were returned.</p>
            </div>
        </section>
        """
        return render_page("EvFi Fleet", body)

    cards_html = ""
    for car in cars:
        vid = car.get("id")
        display_name = escape(str(car.get("display_name", "Tesla Vehicle")))
        vin = escape(str(car.get("vin", "Unknown VIN")))
        state = escape(str(car.get("state", "unknown")))

        cards_html += f"""
        <section class="vehicle-card">
            <div class="badge">Connected Vehicle</div>
            <h3>{display_name}</h3>
            <div class="vehicle-meta">
                VIN: {vin}<br>
                State: {state}
            </div>
            <div class="vehicle-actions">
                <a class="btn btn-primary" href="/dashboard/{vid}">Open Dashboard</a>
                <a class="btn btn-secondary" href="/vehicle/{vid}/raw">Raw Data</a>
            </div>
        </section>
        """

    body = f"""
    <section class="hero hero-auth" aria-hidden="true"></section>

    <section class="hero pre-auth-info">
        <div class="pre-auth-copy">
            <div class="badge">Connected</div>
            <h1>Your Tesla Vehicles</h1>
            <p>Select a vehicle to open the EvFi telemetry and rewards dashboard.</p>
        </div>
    </section>

    <section class="vehicle-list">
        {cards_html}
    </section>
    """
    return render_page("Your Vehicles", body)


@app.route("/auth/callback", strict_slashes=False)
def callback():
    if "error" in request.args:
        return render_page(
            "Tesla OAuth Error",
            f"<section class='panel' style='padding:24px;'><h1>Tesla OAuth Error</h1><pre class='error-box'>{escape(str(dict(request.args)))}</pre></section>"
        ), 400

    state = request.args.get("state")
    if state != tesla_api.state:
        return render_page(
            "Invalid State",
            "<section class='panel' style='padding:24px;'><h1>Invalid state parameter</h1><p class='muted'>Possible CSRF or stale auth session.</p></section>"
        ), 400

    code = request.args.get("code")
    if not code:
        return render_page(
            "Missing Code",
            f"<section class='panel' style='padding:24px;'><h1>Missing authorization code</h1><pre class='error-box'>{escape(str(dict(request.args)))}</pre></section>"
        ), 400

    resp = requests.post(
        "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI
        },
        timeout=30
    )

    if resp.status_code != 200:
        return render_page(
            "Token Exchange Failed",
            f"<section class='panel' style='padding:24px;'><h1>Token Exchange Failed</h1><pre class='error-box'>{escape(resp.text)}</pre></section>"
        ), 400

    token = resp.json()
    token["obtained_at"] = int(time.time())
    tesla_api.tokens.update(token)

    return redirect("/")


@app.route("/dashboard/<vid>")
def dashboard(vid):
    state = tesla_api.get_vehicle_state(vid)
    if state is None:
        return render_page(
            "Vehicle Not Found",
            "<section class='panel' style='padding:24px;'><h1>Vehicle not found in account.</h1></section>"
        ), 404

    if state != "online":
        tesla_api.wake_up_vehicle(vid)
        for _ in range(5):
            time.sleep(2)
            poll_state = tesla_api.get_vehicle_state(vid)
            if poll_state == "online":
                break

    data_resp = tesla_api.get_vehicle_data(vid)
    try:
        data = data_resp.json()
    except Exception:
        return render_page(
            "Vehicle Data Error",
            f"<section class='panel' style='padding:24px;'><h1>Error parsing vehicle data response</h1><pre class='error-box'>{escape(data_resp.text)}</pre></section>"
        ), 500

    vehicle_info = data.get("response", {})
    if not vehicle_info:
        return render_page(
            "No Vehicle Response",
            f"<section class='panel' style='padding:24px;'><h1>No vehicle response found.</h1><pre class='error-box'>{escape(str(data))}</pre></section>"
        ), 500

    meta = get_vehicle_display_meta(vehicle_info)

    display_name = meta["display_name"]
    model = meta["model"]
    trim = meta["trim"]
    year = meta["year"]

    vin = str(vehicle_info.get("vin", "Unknown VIN"))
    current_odometer = extract_odometer(vehicle_info)
    charge_level = int(vehicle_info.get("charge_state", {}).get("battery_level", 0) or 0)
    vehicle_state = vehicle_info.get("state", "unknown")
    latitude = vehicle_info.get("drive_state", {}).get("latitude", "—")
    longitude = vehicle_info.get("drive_state", {}).get("longitude", "—")

    vehicle_config = vehicle_info.get("vehicle_config", {}) or {}
    exterior_color = vehicle_config.get("exterior_color", "Unknown")
    wheel_type = vehicle_config.get("wheel_type", "Unknown")

    charge_limit_soc = int(vehicle_info.get("charge_state", {}).get("charge_limit_soc", 100) or 100)
    charging_state = vehicle_info.get("charge_state", {}).get("charging_state", "Disconnected")
    charge_rate = vehicle_info.get("charge_state", {}).get("charge_rate", 0)
    charger_actual_current = vehicle_info.get("charge_state", {}).get("charger_actual_current", 0)
    charger_voltage = vehicle_info.get("charge_state", {}).get("charger_voltage", 0)
    time_to_full_charge = vehicle_info.get("charge_state", {}).get("time_to_full_charge", None)

    summary = get_reward_summary_for_vehicle(vid, display_name, vin, current_odometer)
    events = get_recent_reward_events(vid, limit=5)
    user = get_or_create_user(DEFAULT_WALLET_ADDRESS)
    user = expire_sport_mode(user["id"])
    activity = record_app_activity(user["id"], "reward_check")
    gamification = getGamificationState(user["id"])
    weekly_score = get_current_week_score(user["id"], vin) or calculate_weekly_score(user["id"], vin, str(vid))
    weekly_reward_preview = build_weekly_reward_preview(user["id"], vin, str(vid))
    weekly_score_breakdown = extract_weekly_score_breakdown(weekly_score)
    weekly_score_explanations = build_weekly_reward_explanations(parse_json_object(weekly_score["score_breakdown_json"] if weekly_score and "score_breakdown_json" in weekly_score.keys() else {}), weekly_reward_preview)
    token_utility = get_user_utility_state(user["id"])
    missions = get_user_missions(user["id"])
    last_distribution = get_last_distribution(user["id"])
    airdrop_claim = ensure_airdrop_claim(user["id"], current_odometer)
    sport_active = bool(user["sport_mode_active"])
    sport_countdown = max(0, int(user["sport_mode_end_time"] or 0) - now_ts()) if sport_active else 0

    if time_to_full_charge is not None:
        total_minutes = int(float(time_to_full_charge) * 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        if hours > 0:
            charge_time_text = f"{hours}h {minutes}m remaining to charge limit"
        else:
            charge_time_text = f"{minutes}m remaining to charge limit"
    else:
        charge_time_text = "Charge estimate unavailable"

    current_fill_width = max(0, min(charge_level, 100))
    charge_limit_left = max(0, min(charge_limit_soc, 100))
    battery_icon_width = max(8, min(charge_level, 100))

    vehicle_image_url = get_vehicle_image_url()
    display_wheel_type = "18-inch Aero Wheels" if str(wheel_type).strip().lower() == "pinwheelrefresh18" else str(wheel_type)
    staking_contract_address = os.getenv("EVFI_STAKING_CONTRACT_ADDRESS", "").strip()
    generated_fees_pool_address = os.getenv("GENERATED_FEES_POOL_ADDRESS", "").strip()

    if vehicle_image_url:
        car_visual_html = f"""
        <div class="car-photo-wrap">
            <img
                class="car-photo"
                src="{vehicle_image_url}"
                alt="Vehicle avatar"
                onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
            >
            <div class="car-photo-fallback" style="display:none;">
                Vehicle image not uploaded yet
            </div>
        </div>
        """
    else:
        car_visual_html = """
        <div class="car-photo-wrap">
            <div class="car-photo-fallback">
                Add a file at static/car-avatar.jpeg
            </div>
        </div>
        """

    events_rows = ""
    for e in events:
        synced_at_str = fmt_ts(e["synced_at"])
        events_rows += f"""
        <tr>
            <td>{escape(synced_at_str)}</td>
            <td>{fmt2(e["odometer_reading"])}</td>
            <td>{fmt2(e["miles_added"])}</td>
            <td class="gain value-tone-{value_tone(e["drv_earned"])}">+{fmt2(e["drv_earned"])}</td>
        </tr>
        """

    if not events_rows:
        events_rows = """
        <tr>
            <td colspan="4" class="muted">No sync history yet. Click Sync Miles.</td>
        </tr>
        """

    last_synced = summary["last_synced_at"]
    last_synced_str = fmt_ts(last_synced)
    score_updated_str = fmt_ts(weekly_score["created_at"] if weekly_score else None)
    gamification_updated_str = fmt_ts(gamification["state"].get("updated_at"))
    distribution_updated_str = fmt_ts(last_distribution["claimed_at"] if last_distribution and last_distribution["claimed_at"] else (last_distribution["week_end"] if last_distribution else None))
    last_distribution_value = fmt2_grouped(last_distribution["evfi_allocated"] if last_distribution else 0)
    airdrop_status = "Airdrop Claimed" if airdrop_claim and airdrop_claim["claimed"] else "Airdrop Available"
    airdrop_amount = fmt2(airdrop_claim["evfi_allocated"] if airdrop_claim else ONBOARDING_AIRDROP_EVFI)
    weekly_reward_estimate = fmt2_grouped(weekly_reward_preview["estimatedEvfi"])
    badge_label = "No badge earned yet"
    badge_asset = "/static/evfi-badge-genesis.svg"
    latest_badge = gamification["badges"][0] if gamification["badges"] else None
    if latest_badge:
        badge_label = str(latest_badge.get("badge_name") or badge_label)
        badge_asset = str(latest_badge.get("badge_asset") or badge_asset)
    completed_challenges = sum(1 for challenge in gamification["challenges"] if challenge.get("completed"))
    total_challenges = len(CHALLENGE_DEFS)
    mission_rows = ""
    for mission in missions:
        mission_complete = bool(mission["completed"])
        mission_state = "complete" if mission_complete else "active"
        badge_html = (
            f'<img class="mission-badge" src="{escape(mission["badge_asset"])}" alt="Completed mission badge">'
            if mission_complete and mission["badge_asset"]
            else ""
        )
        mission_rows += f"""
        <div class="mission-row">
            <div class="mission-copy">
                {badge_html}
                <div>
                    <strong>{escape(str(mission["mission_type"]).replace("_", " ").title())}</strong>
                    <div class="sub">Progress: <span class="value-tone-{value_tone(mission["progress"])}">{fmt2(mission["progress"])}</span></div>
                </div>
            </div>
            <span class="mission-pill" data-state="{mission_state}">{'Complete' if mission_complete else 'Active'}</span>
        </div>
        """
    if not mission_rows:
        mission_rows = "<div class='sub'>Sync the vehicle to start missions.</div>"

    completed_missions = [mission for mission in missions if bool(mission["completed"])]
    achievement_badge_html = "".join(
        f"""
        <div class="achievement-badge">
            <img src="/static/evfi-badge-genesis.svg" alt="{escape(str(mission["mission_type"]))} badge">
            <div>
                <strong>{escape(str(mission["mission_type"]).replace("_", " ").title())}</strong>
                <div class="sub">Complete</div>
            </div>
        </div>
        """
        for mission in completed_missions[:4]
    ) or "<div class='sub'>Complete missions to unlock more badges.</div>"

    score_breakdown_rows = [
        ("Verified Miles", fmt2(weekly_score_breakdown["verifiedMiles"]), "scoreBreakdownVerifiedMiles"),
        ("Active Days", str(weekly_score_breakdown["activeDays"]), "scoreBreakdownActiveDays"),
        ("Participation Bonus", fmt2(weekly_score_breakdown["participationBonus"]), "scoreBreakdownParticipationBonus"),
        ("Efficiency Score", fmt2(weekly_score_breakdown["efficiencyScore"]), "scoreBreakdownEfficiencyScore"),
        ("Charge Sessions", str(weekly_score_breakdown["chargeSessions"]), "scoreBreakdownChargeSessions"),
        ("Charging Score", fmt2(weekly_score_breakdown["chargingScore"]), "scoreBreakdownChargingScore"),
        ("Mission Bonus", fmt2(weekly_score_breakdown["missionBonus"]), "scoreBreakdownMissionBonus"),
        ("Penalty Score", fmt2(weekly_score_breakdown["penaltyScore"]), "scoreBreakdownPenaltyScore"),
        ("Streak Multiplier", f'{weekly_score_breakdown["streakMultiplier"]:.2f}x', "scoreBreakdownStreakMultiplier"),
        ("Staking Boost", f'{weekly_score_breakdown["stakingBoostPct"]:.2f}%', "scoreBreakdownStakingBoostPct"),
        ("Staking Bonus", fmt2(weekly_score_breakdown["stakingBonus"]), "scoreBreakdownStakingBonus"),
        ("Avg Wh/mi", fmt2(weekly_score_breakdown["avgEfficiencyWhmi"]), "scoreBreakdownAvgEfficiency"),
        ("Baseline Wh/mi", fmt2(weekly_score_breakdown["baselineEfficiencyWhmi"]), "scoreBreakdownBaselineEfficiency"),
        ("Healthy Charges", str(weekly_score_breakdown["healthyChargeSessions"]), "scoreBreakdownHealthyCharges"),
        ("High SoC Charges", str(weekly_score_breakdown["highSocChargeSessions"]), "scoreBreakdownHighSocCharges"),
        ("Pre-Bonus Score", fmt2(weekly_score_breakdown["preBonusScore"]), "scoreBreakdownPreBonus"),
        ("Emission Factor", f'{weekly_reward_preview["emissionFactor"]:.6f}', "scoreBreakdownEmissionFactor"),
        ("Weekly EVFi Estimate", fmt2(weekly_reward_preview["estimatedEvfi"]), "scoreBreakdownWeeklyEvfi"),
        ("Total Score", fmt2(weekly_score_breakdown["totalScore"]), "scoreBreakdownTotalScore"),
    ]
    score_breakdown_html = "".join(
        f"""
        <div class="score-breakdown-item">
            <div class="score-breakdown-label">{label}</div>
            <div id="{element_id}" class="score-breakdown-value">{escape(value)}</div>
        </div>
        """
        for label, value, element_id in score_breakdown_rows
    )
    score_explanation_html = "".join(
        f'<li class="score-explanation-item">{escape(item)}</li>'
        for item in weekly_score_explanations
    ) or "<li class='score-explanation-item'>Sync the vehicle to generate this week&apos;s reward explanations.</li>"
    utility_card_html = "".join(
        f"""
        <div class="utility-card">
            <div class="utility-card-label">{escape(entry["label"])}</div>
            <div class="utility-card-value">{fmt2(entry.get("costEvfi", entry.get("stakeEvfi", 0)))} EVFi</div>
            <div class="utility-card-copy">{escape(entry["description"])}</div>
            <button
                class="utility-action-button"
                type="button"
                data-action-type="{escape(entry["actionType"])}"
                data-action-key="{escape(entry["key"])}"
                data-stake-evfi="{escape(str(entry.get("stakeEvfi", "")))}"
            >{'Set Stake Amount' if entry["actionType"] == 'onchain_stake_hint' else 'Use EVFi'}</button>
        </div>
        """
        for group in ("analyticsUnlocks", "partnerRewards")
        for entry in token_utility["catalog"][group]
    )

    body = f"""
    <section class="dashboard-brand-banner" aria-label="EVFi banner"></section>

    <section class="topbar">
        <section class="vehicle-panel">
            <div class="vehicle-header">
                <div>
                    <div class="label">Charge & Controls</div>
                    <h2 class="vehicle-title">{escape(display_name)}</h2>
                    <div class="vehicle-sub">{escape(str(year))} {escape(model)} • {escape(trim)} • {escape(str(vehicle_state).title())}</div>
                </div>
                <div class="tesla-mark" aria-label="EVFi logo">
                    <img class="vehicle-brand-logo" src="/static/evfi-token-logo.png" alt="EVFi token logo">
                </div>
            </div>

            <div class="soc-row">
                <div class="battery-icon">
                    <div class="battery-icon-fill" style="width:{battery_icon_width}%;"></div>
                </div>
                <div class="soc-percent">{charge_level}%</div>
                <div style="font-size:26px;color:var(--green);">⚡</div>
            </div>

            <div class="soc-meta">{escape(charge_time_text)}</div>

            {car_visual_html}

            <div class="quick-actions">
                <button id="syncMilesButton" class="quick-btn" data-vehicle-id="{vid}">Sync Miles</button>
                <button id="refreshAndDistributeButton" class="quick-btn" data-vehicle-id="{vid}" data-default-amount="{weekly_reward_preview["estimatedEvfi"]}">Sync + Weekly EVFi</button>
                <button class="quick-btn" onclick="window.location.href='/vehicle/{vid}/raw'">Raw Data</button>
                <button id="claimRewardsButton" class="quick-btn">Claim EVFi</button>
                <button id="claimAirdropButton" class="quick-btn" data-vehicle-id="{vid}" data-airdrop-amount="{airdrop_amount}">{escape(airdrop_status)}</button>
                <button id="sportModeButton" class="quick-btn {'sport-active' if sport_active else ''}" data-vehicle-id="{vid}" data-active="{'true' if sport_active else 'false'}" data-end-time="{int(user['sport_mode_end_time'] or 0)}">SPORT MODE</button>
                <button id="assignRewardsButton" class="quick-btn" data-vehicle-id="{vid}" data-default-amount="{weekly_reward_preview["estimatedEvfi"]}">Assign Test EVFi</button>
                <button class="quick-btn" onclick="alert('Vehicle controls can be wired next')">Controls</button>
            </div>
            <div id="sportModeStatus" class="status-pill" data-state="{'sport-active' if sport_active else 'sport-inactive'}">{'SPORT MODE ACTIVE - ' + str(sport_countdown) + 's remaining' if sport_active else 'Sport Mode available: 15 minutes, 1 use per day.'}</div>
            <div class="admin-stack">
                <input id="distributionRecipientInput" class="admin-input" type="text" value="{escape(DEFAULT_WALLET_ADDRESS)}" placeholder="Distribution recipient wallet 0x...">
                <input id="adminKeyInput" class="admin-input" type="password" placeholder="Admin API key for manual test assignment only">
            </div>

            <div class="charge-card">
                <div class="charge-head">
                    <div>Charge limit: {charge_limit_soc}%</div>
                    <div class="muted">{escape(str(charging_state))}</div>
                </div>

                <div id="vehicleChargeMeta" class="charge-meta">
                    {charge_rate} kW • {charger_actual_current}A • {charger_voltage}V • Last sync {escape(last_synced_str)}
                </div>

                <div class="charge-bar-wrap">
                    <div class="charge-bar" style="width:{current_fill_width}%;"></div>
                    <div class="charge-limit-knob" style="left:{charge_limit_left}%;"></div>
                </div>

                <div class="tip-box">
                    <div class="tip-icon">i</div>
                    <div>
                        <div class="tip-title">Charge Tip</div>
                        <div class="tip-copy">80% is commonly used for daily driving. Raise the limit when you need the extra range.</div>
                    </div>
                </div>
            </div>

            <div class="header-links">
                <a class="soft-link" href="/">Back</a>
                <a id="refreshRewardsLink" class="soft-link" href="/sync/{vid}" data-vehicle-id="{vid}">Refresh Rewards</a>
                <a class="soft-link" href="/vehicle/{vid}/raw">Telemetry</a>
            </div>
        </section>

        <section id="walletModule" class="wallet-panel panel">
            <div class="wallet-panel-header">
                <div>
                    <div class="label">Wallet & Rewards</div>
                    <h2 class="wallet-panel-title">Sepolia EVFi</h2>
                    <p class="wallet-panel-copy">Connect your test wallet, review live ERC-20 balance, and claim pending rewards without leaving the dashboard.</p>
                </div>
                <div id="walletConnectionBadge" class="wallet-badge" data-state="idle">Not Connected</div>
            </div>

            <div class="wallet-actions">
                <button id="connectWalletButton" class="wallet-btn" data-state="idle">
                    <span class="wallet-btn-icon" aria-hidden="true"></span>
                    <span id="connectWalletButtonLabel" class="wallet-btn-label">Connect Sepolia Wallet</span>
                </button>
                <button id="addTokenButton" class="wallet-link wallet-link-button" type="button">Add EVFi to MetaMask</button>
                <button id="disconnectWalletButton" class="wallet-link wallet-link-button is-hidden" type="button">Disconnect</button>
            </div>

            <div class="wallet-grid">
                <div class="wallet-stat">
                    <div class="wallet-stat-label">Wallet EVFi Balance</div>
                    <div id="walletBalanceValue" class="wallet-stat-value">0.0</div>
                    <div class="sub">Live Sepolia token balance.</div>
                </div>
                <div class="wallet-stat">
                    <div class="wallet-stat-label">Claimable EVFi</div>
                    <div id="claimableRewardsValue" class="wallet-stat-value">0.0</div>
                    <div class="sub">Pending rewards ready to claim.</div>
                </div>
            </div>

            <div class="wallet-address">
                <div class="wallet-address-label">Connected Wallet</div>
                <div id="walletAddressText" class="wallet-address-value">{escape(DEFAULT_WALLET_ADDRESS or "Wallet not connected")}</div>
                <div id="web3StatusText" class="wallet-sub">Wallet not connected yet.</div>
            </div>

            <div class="wallet-links">
                <a id="walletExplorerLink" class="wallet-link is-hidden" href="#" target="_blank" rel="noreferrer">Wallet Explorer</a>
                <a id="tokenExplorerLink" class="wallet-link {'' if EVFI_TOKEN_ADDRESS else 'is-hidden'}" href="https://sepolia.etherscan.io/address/{escape(EVFI_TOKEN_ADDRESS)}" target="_blank" rel="noreferrer">EVFi Token</a>
                <a id="rewardsExplorerLink" class="wallet-link {'' if EVFI_REWARDS_ADDRESS else 'is-hidden'}" href="https://sepolia.etherscan.io/address/{escape(EVFI_REWARDS_ADDRESS)}" target="_blank" rel="noreferrer">Rewards Vault</a>
                <a class="wallet-link {'' if staking_contract_address else 'is-hidden'}" href="https://sepolia.etherscan.io/address/{escape(staking_contract_address)}" target="_blank" rel="noreferrer">Staking Contract</a>
                <a class="wallet-link {'' if generated_fees_pool_address else 'is-hidden'}" href="https://sepolia.etherscan.io/address/{escape(generated_fees_pool_address)}" target="_blank" rel="noreferrer">Generated Fees Pool</a>
                <a id="txExplorerLink" class="wallet-link is-hidden" href="#" target="_blank" rel="noreferrer">Latest EVFi Tx</a>
            </div>

            <div id="walletConnectHint" class="wallet-hint">Sepolia contracts are connected. Link your wallet to unlock live EVFi balance reads and claim flow.</div>
            <div id="walletToast" class="inline-toast" data-tone="success"></div>

            <div class="token-metrics-panel">
                <div class="label">EvFi Token Metrics</div>
                <div class="token-metrics-grid">
                    <div><span>Price</span><strong id="mockEvfiPrice">$0.04</strong></div>
                    <div><span>Market Cap</span><strong id="mockMarketCap">$4,000,000.00</strong></div>
                    <div><span>Circulating</span><strong id="mockCirculatingSupply">100,000,000.00</strong></div>
                    <div><span>Max Supply</span><strong>1,000,000,000.00</strong></div>
                </div>
                <div class="mock-chart" id="mockPriceChart" aria-label="EVFi price candle chart"></div>
            </div>
        </section>
    </section>

    <section class="panel secondary-card utility-panel" style="margin-top:16px;">
        <div class="label">EVFi Utility</div>
        <h3 class="secondary-card-title">Unlock & Stake</h3>
        <p class="secondary-card-copy">Stake EVFi through the Sepolia contract and unlock digital in-app perks. Physical perk previews are hidden for now.</p>
        <div id="onchainStakingMount"></div>
        <div class="utility-grid">
            {utility_card_html}
        </div>
    </section>

    <section class="stats-grid v2-score-grid">
        <section class="panel secondary-card score-card">
            <div class="label">Weekly Score</div>
            <h3 id="weeklyScoreValue" class="secondary-card-title value-tone-{value_tone(weekly_score["total_score"] if weekly_score else 0)}" data-count-up="{fmt2(weekly_score["total_score"] if weekly_score else 0)}">{fmt2(weekly_score["total_score"] if weekly_score else 0)} pts</h3>
            <p class="secondary-card-copy">Verified miles, activity consistency, efficiency trends, charging behavior, penalties, and mission bonuses.</p>
            <div class="score-card-metrics">
                <div class="score-mini-metric"><span>Miles</span><strong>{fmt2(weekly_score_breakdown["verifiedMiles"])}</strong></div>
                <div class="score-mini-metric"><span>Stake Boost</span><strong>{weekly_score_breakdown["stakingBoostPct"]:.2f}%</strong></div>
            </div>
            <div id="weeklyScoreUpdatedAt" class="sub">Updated {escape(score_updated_str)}</div>
        </section>

        <section class="panel secondary-card score-breakdown-card">
            <div class="label">Score Breakdown</div>
            <h3 class="secondary-card-title">Weekly Inputs</h3>
            <p class="secondary-card-copy">The weekly EVFi estimate comes from these inputs, then the network emission factor converts score into claimable EVFi.</p>
            <div class="score-breakdown-grid">
                {score_breakdown_html}
            </div>
        </section>

        <section class="panel secondary-card score-explain-card">
            <div class="label">Why Your Reward Changed</div>
            <h3 class="secondary-card-title">Weekly Reward Explanation</h3>
            <p class="secondary-card-copy">This translates the score engine into plain English so users can understand what helped or hurt weekly EVFi.</p>
            <ul id="scoreExplanationList" class="score-explanation-list">
                {score_explanation_html}
            </ul>
        </section>

        <section class="panel secondary-card streak-card">
            <div class="label">Active Streak</div>
            <h3 class="secondary-card-title"><span id="currentStreakValue">{int(gamification["state"].get("current_streak") or 0)}</span> day streak</h3>
            <p class="secondary-card-copy">Longest: <span id="longestStreakValue">{int(gamification["state"].get("longest_streak") or 0)}</span> days</p>
            <div class="streak-metrics">
                <div class="streak-mini-metric"><span>Active Days</span><strong>{weekly_score_breakdown["activeDays"]}</strong></div>
                <div class="streak-mini-metric"><span>Multiplier</span><strong>{weekly_score_breakdown["streakMultiplier"]:.2f}x</strong></div>
            </div>
            <div id="streakUpdatedAt" class="sub">Updated {escape(gamification_updated_str)}</div>
        </section>

        <section class="panel secondary-card missions-card">
            <div class="label">Active Missions</div>
            <h3 class="secondary-card-title"><span id="challengeCompletedCount">{completed_challenges}</span>/<span id="challengeTotalCount">{total_challenges}</span> completed</h3>
            <div id="missionList" class="mission-list">{mission_rows}</div>
            <div id="missionsUpdatedAt" class="sub">Updated {escape(gamification_updated_str)}</div>
        </section>

        <section class="panel secondary-card distribution-card">
            <div class="label">Last Distribution</div>
            <h3 class="secondary-card-title value-tone-{value_tone(last_distribution["evfi_allocated"] if last_distribution else 0)}" data-count-up="{fmt2(last_distribution["evfi_allocated"] if last_distribution else 0)}">{last_distribution_value} EVFi</h3>
            <p class="secondary-card-copy">Fixed-pool deterministic allocation with weekly caps.</p>
            <div class="achievement-strip">{achievement_badge_html}</div>
            <div class="sub">Updated {escape(distribution_updated_str)}</div>
        </section>
    </section>

    <section class="stats-grid reward-engine-grid">
        <section class="panel secondary-card reward-engine-card">
            <div class="label">Weekly Reward Engine</div>
            <h3 class="secondary-card-title">Estimated Weekly EVFi</h3>
            <p class="secondary-card-copy">A single offchain weekly score drives emissions. Sync updates telemetry, weekly score, and the current EVFi estimate. The onboarding airdrop remains a separate one-time grant.</p>

            <div class="distribution-grid">
                <div class="distribution-stat">
                    <div class="distribution-label">Weekly Score</div>
                    <div id="telemetryScoreValue" class="distribution-value value-tone-{value_tone(weekly_score["total_score"] if weekly_score else 0)}">{fmt2_grouped(weekly_score["total_score"] if weekly_score else 0)}</div>
                </div>
                <div class="distribution-stat">
                    <div class="distribution-label">Tracked Miles</div>
                    <div id="milesTrackedValue" class="distribution-value value-tone-{value_tone(summary["total_miles"])}">{fmt2_grouped(summary["total_miles"])}</div>
                </div>
                <div class="distribution-stat">
                    <div class="distribution-label">Weekly EVFi Estimate</div>
                    <div id="airdropAmountValue" class="distribution-value value-tone-{value_tone(weekly_reward_preview["estimatedEvfi"])}">{weekly_reward_estimate}</div>
                </div>
            </div>

            <div class="sub">Use <strong>Assign Test EVFi</strong> for manual testing, <strong>Sync + Weekly EVFi</strong> to refresh telemetry and assign the current weekly reward, and <strong>Airdrop Available</strong> only for the fixed onboarding grant.</div>
        </section>
    </section>

    <section class="dashboard-grid" style="margin-top:16px;">
        <section class="history-panel">
            <h3 class="history-title">Reward Sync History</h3>
            <table>
                <tr>
                    <th>Synced At</th>
                    <th>Odometer</th>
                    <th>Miles Added</th>
                    <th>Score Added</th>
                </tr>
                <tbody id="rewardSyncHistoryBody">
                    {events_rows}
                </tbody>
            </table>
        </section>

        <section class="details-panel panel">
            <h3 class="history-title">Vehicle Details</h3>
            <table>
                <tr><th>Name</th><td>{escape(display_name)}</td></tr>
                <tr><th>Model</th><td>{escape(model)}</td></tr>
                <tr><th>Trim</th><td>{escape(trim)}</td></tr>
                <tr><th>Year</th><td>{escape(str(year))}</td></tr>
                <tr><th>VIN</th><td>{escape(vin)}</td></tr>
                <tr><th>Vehicle State</th><td>{escape(str(vehicle_state))}</td></tr>
                <tr><th>Odometer</th><td id="vehicleDetailsOdometer">{current_odometer:.1f}</td></tr>
                <tr><th>Location</th><td>{latitude}, {longitude}</td></tr>
                <tr><th>Exterior Color</th><td>{escape(str(exterior_color))}</td></tr>
                <tr><th>Wheel Type</th><td>{escape(display_wheel_type)}</td></tr>
            </table>
        </section>
    </section>

    <section class="panel contracts-panel" style="margin-top:16px;">
        <div class="label">Sepolia Contracts</div>
        <h3 class="secondary-card-title">Wallet & Contract References</h3>
        <div class="contracts-grid">
            <div class="contract-item">
                <div class="contract-label">Default Wallet</div>
                <div class="contract-value">{escape(DEFAULT_WALLET_ADDRESS)}</div>
            </div>
            <div class="contract-item">
                <div class="contract-label">EVFi Token</div>
                <div class="contract-value">{escape(EVFI_TOKEN_ADDRESS or "Not configured")}</div>
            </div>
            <div class="contract-item">
                <div class="contract-label">Rewards Vault</div>
                <div class="contract-value">{escape(EVFI_REWARDS_ADDRESS or "Not configured")}</div>
            </div>
            <div class="contract-item">
                <div class="contract-label">Staking Contract</div>
                <div class="contract-value">{escape(staking_contract_address or "Not configured")}</div>
            </div>
            <div class="contract-item">
                <div class="contract-label">Generated Fees Pool</div>
                <div class="contract-value">{escape(generated_fees_pool_address or "Not configured")}</div>
            </div>
        </div>
    </section>

    """
    return render_page(f"{display_name} Dashboard", body)


@app.route("/sync/<vid>")
def sync_rewards(vid):
    try:
        load_vehicle_and_summary(vid, wallet_address=DEFAULT_WALLET_ADDRESS)
    except ValueError:
        return render_page(
            "Vehicle Not Found",
            "<section class='panel' style='padding:24px;'><h1>Vehicle not found in account.</h1></section>"
        ), 404
    except RuntimeError as exc:
        return render_page(
            "Vehicle Data Error",
            f"<section class='panel' style='padding:24px;'><h1>{escape(str(exc))}</h1></section>"
        ), 500

    return redirect(url_for("dashboard", vid=vid))


@app.route("/api/vehicle/<vid>/sync", methods=["POST"])
def sync_rewards_api(vid):
    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    if wallet and not is_valid_evm_address(wallet):
        return jsonify({"error": "A valid wallet is required"}), 400

    log_v2_event("dashboard_sync_requested", vehicle_id=str(vid), wallet=wallet)
    try:
        context = load_vehicle_and_summary(vid, wallet_address=wallet)
    except ValueError:
        return jsonify({"error": "Vehicle not found"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    response_payload = build_dashboard_sync_payload(vid, wallet, context)
    recent_event = response_payload["events"][0] if response_payload["events"] else {}
    log_v2_event(
        "dashboard_sync_completed",
        vehicle_id=str(vid),
        wallet=wallet,
        current_odometer=response_payload["odometer"],
        miles_added=recent_event.get("milesAdded", 0.0),
        reward_added=recent_event.get("scoreAdded", 0.0),
    )
    return jsonify(response_payload)


@app.route("/api/vehicle/<vid>/summary")
def vehicle_summary_api(vid):
    try:
        context = load_vehicle_and_summary(vid, wallet_address=DEFAULT_WALLET_ADDRESS)
    except ValueError:
        return jsonify({"error": "Vehicle not found"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    meta = context["meta"]
    summary = context["summary"]
    user = get_or_create_user(DEFAULT_WALLET_ADDRESS)
    weekly_reward_preview = build_weekly_reward_preview(user["id"], context["vin"], str(vid))

    return jsonify(
        {
            "vehicleId": str(vid),
            "displayName": meta["display_name"],
            "walletDefault": DEFAULT_WALLET_ADDRESS,
            "telemetryScore": float(weekly_reward_preview["weeklyScore"] or 0),
            "totalMiles": float(summary["total_miles"] or 0),
            "recommendedAssignment": weekly_reward_preview["estimatedEvfi"],
        }
    )


@app.route("/api/vehicle/<vid>/gamification")
def vehicle_gamification_api(vid):
    wallet = str(request.args.get("wallet") or DEFAULT_WALLET_ADDRESS)
    if not is_valid_evm_address(wallet):
        return jsonify({"error": "A valid wallet is required"}), 400

    try:
        context = load_vehicle_and_summary(vid, wallet_address=wallet)
    except ValueError:
        return jsonify({"error": "Vehicle not found"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    user = get_or_create_user(wallet)
    weekly_reward_preview = build_weekly_reward_preview(user["id"], context["vin"], str(vid))
    activity = record_app_activity(user["id"], "reward_check")
    gamification = getGamificationState(user["id"])
    return jsonify(
        {
            "ok": True,
            "vehicleId": str(vid),
            "wallet": wallet,
            "telemetryScore": float(weekly_reward_preview["weeklyScore"] or 0),
            "totalMiles": float(context["summary"]["total_miles"] or 0),
            "gamification": gamification,
            "gamificationEvents": activity["events"],
        }
    )


@app.route("/api/vehicle/<vid>/assign-demo-reward", methods=["POST"])
def assign_demo_reward(vid):
    if request.headers.get("x-admin-key") != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    if not os.path.exists(EVFI_ASSIGN_SCRIPT):
        return jsonify({"error": f"Missing reward assignment script: {EVFI_ASSIGN_SCRIPT}"}), 500

    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    if not is_valid_evm_address(wallet):
        return jsonify({"error": "A valid recipient wallet is required"}), 400
    try:
        context = load_vehicle_and_summary(vid, wallet_address=wallet)
    except ValueError:
        return jsonify({"error": "Vehicle not found"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    summary = context["summary"]
    user = get_or_create_user(wallet)
    weekly_reward_preview = build_weekly_reward_preview(user["id"], context["vin"], str(vid))
    amount_tokens = float(payload.get("amountTokens") or weekly_reward_preview["estimatedEvfi"])
    batch_id = str(payload.get("batchId") or build_distribution_batch_id(vid, "demo"))

    try:
        output = assign_demo_reward_onchain(wallet, amount_tokens, batch_id)
    except Exception as exc:
        payload = normalize_assignment_exception(exc)
        return jsonify(payload), 500

    reward_key = f"manual-assignment:{batch_id}"
    record_evfi_earning(user["id"], reward_key, amount_tokens, "manual_assignment")
    activity = record_app_activity(user["id"], "reward_check")
    gamification = getGamificationState(user["id"])

    return jsonify(
        {
            "ok": True,
            "vehicleId": str(vid),
            "wallet": wallet,
            "amountTokens": amount_tokens,
            "batchId": batch_id,
            "telemetryScore": float(weekly_reward_preview["weeklyScore"] or 0),
            "txHash": output.get("txHash"),
            "output": output,
            "gamification": gamification,
            "gamificationEvents": activity["events"],
        }
    )


@app.route("/api/vehicle/<vid>/refresh-and-distribute", methods=["POST"])
def refresh_and_distribute_reward(vid):
    if not os.path.exists(EVFI_ASSIGN_SCRIPT):
        return jsonify({"error": f"Missing reward assignment script: {EVFI_ASSIGN_SCRIPT}"}), 500

    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    if not is_valid_evm_address(wallet):
        return jsonify({"error": "A valid recipient wallet is required"}), 400
    authorized, auth_error = verify_admin_or_wallet_signature(wallet, "refresh-and-distribute", vid)
    if not authorized:
        return jsonify({"error": auth_error or "Unauthorized"}), 401
    try:
        context = load_vehicle_and_summary(vid, wallet_address=wallet)
    except ValueError:
        return jsonify({"error": "Vehicle not found"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    summary = context["summary"]

    user = get_or_create_user(wallet)
    if not bind_vehicle_to_user(context["vin"], user["id"], context["odometer"]):
        return jsonify({"error": "VIN is already bound to another wallet"}), 409

    weekly_score = calculate_weekly_score(user["id"], context["vin"], str(vid))
    weekly_reward_preview = build_weekly_reward_preview(user["id"], context["vin"], str(vid))
    claim = distribute_weekly_pool(user["id"], weekly_score["week_start"], weekly_score["week_end"])
    amount_tokens = float(claim["evfi_allocated"] or 0)
    batch_id = str(payload.get("batchId") or build_distribution_batch_id(vid, "weekly"))

    try:
        output = assign_demo_reward_onchain(wallet, amount_tokens, batch_id)
    except Exception as exc:
        payload = normalize_assignment_exception(exc)
        return jsonify(payload), 500

    record_evfi_earning(
        user["id"],
        f"weekly-allocation:{weekly_score['week_start']}:{weekly_score['week_end']}",
        amount_tokens,
        "weekly_allocation",
    )
    activity = record_app_activity(user["id"], "reward_check")
    gamification = getGamificationState(user["id"])

    return jsonify(
        {
            "ok": True,
            "vehicleId": str(vid),
            "wallet": wallet,
            "amountTokens": amount_tokens,
            "batchId": batch_id,
            "telemetryScore": float(weekly_reward_preview["weeklyScore"] or 0),
            "weeklyScore": float(weekly_score["total_score"] or 0),
            "totalMiles": float(summary["total_miles"] or 0),
            "txHash": output.get("txHash"),
            "output": output,
            "gamification": gamification,
            "gamificationEvents": activity["events"],
        }
    )


@app.route("/api/vehicle/<vid>/claim-airdrop", methods=["POST"])
def claim_airdrop(vid):
    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    if not is_valid_evm_address(wallet):
        return jsonify({"error": "A valid recipient wallet is required"}), 400
    authorized, auth_error = verify_admin_or_wallet_signature(wallet, "claim-airdrop", vid)
    if not authorized:
        return jsonify({"error": auth_error or "Unauthorized"}), 401

    try:
        context = load_vehicle_and_summary(vid, wallet_address=wallet)
    except ValueError:
        return jsonify({"error": "Vehicle not found"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    user = get_or_create_user(wallet)
    if not bind_vehicle_to_user(context["vin"], user["id"], context["odometer"]):
        return jsonify({"error": "VIN is already bound to another wallet"}), 409

    claim = ensure_airdrop_claim(user["id"], context["odometer"])
    if claim["claimed"]:
        activity = record_app_activity(user["id"], "claim")
        gamification = getGamificationState(user["id"])
        return jsonify(
            {
                "ok": True,
                "message": "Airdrop Claimed",
                "claimed": True,
                "amountTokens": claim["evfi_allocated"],
                "gamification": gamification,
                "gamificationEvents": activity["events"],
            }
        )

    amount_tokens = round(float(claim["evfi_allocated"] or 0), 2)
    batch_id = build_distribution_batch_id(vid, "airdrop")

    try:
        output = mint_airdrop_onchain(wallet, amount_tokens, batch_id)
    except Exception as exc:
        payload = normalize_assignment_exception(exc)
        return jsonify(payload), 500

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE claims SET claimed = 1, claimed_at = ? WHERE id = ?", (now_ts(), claim["id"]))
    conn.commit()
    conn.close()
    log_v2_event("airdrop_claim", user_id=user["id"], wallet=wallet, amount=amount_tokens, txHash=output.get("txHash"))
    record_evfi_earning(user["id"], f"airdrop-claim:{claim['id']}", amount_tokens, "airdrop_claim")
    activity = record_app_activity(user["id"], "claim")
    gamification = getGamificationState(user["id"])

    return jsonify(
        {
            "ok": True,
            "claimed": True,
            "message": "Airdrop Claimed",
            "wallet": wallet,
            "amountTokens": amount_tokens,
            "batchId": batch_id,
            "txHash": output.get("txHash"),
            "output": output,
            "gamification": gamification,
            "gamificationEvents": activity["events"],
        }
    )


@app.route("/api/vehicle/<vid>/utility/redeem", methods=["POST"])
def redeem_utility_api(vid):
    if request.headers.get("x-admin-key") != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    action_key = str(payload.get("actionKey") or "")
    if not is_valid_evm_address(wallet):
        return jsonify({"error": "A valid wallet is required"}), 400
    if not action_key:
        return jsonify({"error": "A utility action key is required"}), 400

    user = get_or_create_user(wallet)
    try:
        result = redeem_token_utility(user["id"], action_key)
        reward_context = get_cached_vehicle_reward_context(vid)
        weekly_score = calculate_weekly_score(user["id"], reward_context["vin"], str(vid))
        weekly_reward_preview = build_weekly_reward_preview(user["id"], reward_context["vin"], str(vid))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "ok": True,
            "wallet": wallet,
            "actionKey": action_key,
            "amountEvfi": result["amountEvfi"],
            "utilityState": result["utilityState"],
            "weeklyScore": {
                "totalScore": float(weekly_score["total_score"] or 0),
                "breakdown": extract_weekly_score_breakdown(weekly_score),
                "explanations": build_weekly_reward_explanations(parse_json_object(weekly_score["score_breakdown_json"] or "{}"), weekly_reward_preview),
            },
            "rewardPreview": weekly_reward_preview,
        }
    )


@app.route("/api/vehicle/<vid>/utility/stake", methods=["POST"])
def stake_utility_api(vid):
    if request.headers.get("x-admin-key") != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    tier_key = str(payload.get("tierKey") or "")
    if not is_valid_evm_address(wallet):
        return jsonify({"error": "A valid wallet is required"}), 400
    if not tier_key:
        return jsonify({"error": "A staking tier key is required"}), 400

    user = get_or_create_user(wallet)
    try:
        result = stake_evfi_tier(user["id"], tier_key)
        reward_context = get_cached_vehicle_reward_context(vid)
        weekly_score = calculate_weekly_score(user["id"], reward_context["vin"], str(vid))
        weekly_reward_preview = build_weekly_reward_preview(user["id"], reward_context["vin"], str(vid))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "ok": True,
            "wallet": wallet,
            "tierKey": tier_key,
            "utilityState": result["utilityState"],
            "weeklyScore": {
                "totalScore": float(weekly_score["total_score"] or 0),
                "breakdown": extract_weekly_score_breakdown(weekly_score),
                "explanations": build_weekly_reward_explanations(parse_json_object(weekly_score["score_breakdown_json"] or "{}"), weekly_reward_preview),
            },
            "rewardPreview": weekly_reward_preview,
        }
    )


@app.route("/api/vehicle/<vid>/utility/unstake", methods=["POST"])
def unstake_utility_api(vid):
    if request.headers.get("x-admin-key") != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    if not is_valid_evm_address(wallet):
        return jsonify({"error": "A valid wallet is required"}), 400

    user = get_or_create_user(wallet)
    try:
        result = unstake_evfi(user["id"])
        reward_context = get_cached_vehicle_reward_context(vid)
        weekly_score = calculate_weekly_score(user["id"], reward_context["vin"], str(vid))
        weekly_reward_preview = build_weekly_reward_preview(user["id"], reward_context["vin"], str(vid))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "ok": True,
            "wallet": wallet,
            "tierKey": result["tierKey"],
            "utilityState": result["utilityState"],
            "weeklyScore": {
                "totalScore": float(weekly_score["total_score"] or 0),
                "breakdown": extract_weekly_score_breakdown(weekly_score),
                "explanations": build_weekly_reward_explanations(parse_json_object(weekly_score["score_breakdown_json"] or "{}"), weekly_reward_preview),
            },
            "rewardPreview": weekly_reward_preview,
        }
    )


@app.route("/api/vehicle/<vid>/sport-mode", methods=["POST"])
def activate_sport_mode(vid):
    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    user = get_or_create_user(wallet)
    user = expire_sport_mode(user["id"])
    current = now_ts()
    last_used = int(user["sport_mode_last_used"] or 0)

    if user["sport_mode_active"]:
        return jsonify({"ok": True, "active": True, "endTime": user["sport_mode_end_time"]})

    if user["sport_mode_uses_today"] >= SPORT_MODE_USES_PER_DAY and current - last_used < SPORT_MODE_COOLDOWN_SECONDS:
        log_rule_violation("sport_mode_cooldown", user_id=user["id"], vehicle_id=vid)
        return jsonify({"error": "Sport Mode cooldown is active. Try again tomorrow."}), 429

    end_time = current + SPORT_MODE_DURATION_SECONDS
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE users
        SET sport_mode_active = 1,
            sport_mode_start_time = ?,
            sport_mode_end_time = ?,
            sport_mode_uses_today = ?,
            sport_mode_last_used = ?
        WHERE id = ?
        """,
        (current, end_time, int(user["sport_mode_uses_today"] or 0) + 1, current, user["id"]),
    )
    conn.commit()
    conn.close()
    log_v2_event("sport_mode_activation", user_id=user["id"], vehicle_id=vid, end_time=end_time)
    return jsonify({"ok": True, "active": True, "startTime": current, "endTime": end_time})


@app.route("/api/log-ui-event", methods=["POST"])
def log_ui_event():
    payload = request.get_json(silent=True) or {}
    event_name = str(payload.get("event") or "ui_event")
    if event_name == "chart_data_updated":
        log_v2_event("chart_data_updated", points=payload.get("points"))
    return jsonify({"ok": True})


@app.route("/vehicle/<vid>/raw")
def vehicle_raw(vid):
    state = tesla_api.get_vehicle_state(vid)
    if state is None:
        return render_page(
            "Vehicle Not Found",
            "<section class='panel' style='padding:24px;'><h1>Vehicle not found in account.</h1></section>"
        ), 404

    if state != "online":
        tesla_api.wake_up_vehicle(vid)
        for _ in range(5):
            time.sleep(2)
            poll_state = tesla_api.get_vehicle_state(vid)
            if poll_state == "online":
                break

    data_resp = tesla_api.get_vehicle_data(vid)
    try:
        data = data_resp.json()
    except Exception:
        return render_page(
            "Vehicle Data Error",
            f"<section class='panel' style='padding:24px;'><h1>Error parsing vehicle data response</h1><pre class='error-box'>{escape(data_resp.text)}</pre></section>"
        ), 500

    def render_dict(d, parent_key=""):
        rows = []
        for k, v in d.items():
            key = f"{parent_key}.{k}" if parent_key else k
            if isinstance(v, dict):
                rows.extend(render_dict(v, key))
            else:
                rows.append(f"<tr><td>{escape(str(key))}</td><td>{escape(str(v))}</td></tr>")
        return rows

    vehicle_info = data.get("response", {})
    table_rows = render_dict(vehicle_info)

    body = f"""
    <section class="hero">
        <div>
            <div class="badge">Debug View</div>
            <h1>Raw Tesla Vehicle Data</h1>
            <p>This page is for inspecting every field returned by Tesla.</p>
        </div>
        <div>
            <a class="btn btn-secondary" href="/dashboard/{vid}">Back to Dashboard</a>
        </div>
    </section>

    <section class="history-panel">
        <table>
            <tr><th>Field</th><th>Value</th></tr>
            {''.join(table_rows)}
        </table>
    </section>
    """
    return render_page("Raw Vehicle Data", body)


@app.route('/.well-known/appspecific/<path:filename>')
def well_known(filename):
    return send_from_directory('.well-known/appspecific', filename)


# =========================================================
# START APP
# =========================================================
def run_app():
    init_db()
    app.run(port=DEFAULT_PORT, debug=False)


SEPOLIA_CHAIN_ID = int(os.getenv("SEPOLIA_CHAIN_ID", "11155111"))
SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL", "").strip()
EVFI_TOKEN_DECIMALS = int(os.getenv("EVFI_TOKEN_DECIMALS", "18"))
STAKING_TIER_THRESHOLDS = os.getenv(
    "STAKING_TIER_THRESHOLDS",
    "100:Bronze:5,500:Silver:10,1000:Gold:15",
).strip()

try:
    from web3 import Web3
except Exception:
    Web3 = None


def get_evfi_token_address():
    for key in ("EVFI_TOKEN_ADDRESS", "EVFI_CONTRACT_ADDRESS", "TOKEN_CONTRACT_ADDRESS"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def parse_staking_tier_thresholds():
    thresholds = []
    for raw_chunk in STAKING_TIER_THRESHOLDS.split(","):
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        parts = [part.strip() for part in chunk.split(":")]
        if len(parts) != 3:
            continue
        try:
            minimum_amount = float(parts[0])
            label = parts[1]
            boost_pct = float(parts[2])
        except ValueError:
            continue
        thresholds.append(
            {
                "minimumAmount": minimum_amount,
                "label": label,
                "boostPct": boost_pct,
            }
        )
    thresholds.sort(key=lambda item: item["minimumAmount"])
    return thresholds


def derive_staking_tier(total_staked_evfi):
    chosen_tier = None
    for threshold in parse_staking_tier_thresholds():
        if total_staked_evfi + 1e-9 >= threshold["minimumAmount"]:
            chosen_tier = threshold
    return chosen_tier


def get_user_wallet_address(user_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for column_name in ("wallet_address", "wallet"):
            try:
                row = cur.execute(
                    f"SELECT {column_name} FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
            except Exception:
                continue
            if row and row[0]:
                return str(row[0]).strip()
    finally:
        conn.close()
    return ""


def find_user_id_by_wallet_address(wallet_address):
    normalized_wallet = (wallet_address or "").strip().lower()
    if not normalized_wallet:
        return None
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for column_name in ("wallet_address", "wallet"):
            try:
                row = cur.execute(
                    f"SELECT id FROM users WHERE lower({column_name}) = ?",
                    (normalized_wallet,),
                ).fetchone()
            except Exception:
                continue
            if row and row[0]:
                return int(row[0])
    finally:
        conn.close()
    return None


def get_staking_contract_read_abi():
    return [
        {
            "inputs": [{"internalType": "address", "name": "", "type": "address"}],
            "name": "totalStaked",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [{"internalType": "address", "name": "staker", "type": "address"}],
            "name": "getStakePositionsCount",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "address", "name": "staker", "type": "address"},
                {"internalType": "uint256", "name": "positionId", "type": "uint256"},
            ],
            "name": "getStakePosition",
            "outputs": [
                {
                    "components": [
                        {"internalType": "uint256", "name": "amount", "type": "uint256"},
                        {"internalType": "uint64", "name": "startTime", "type": "uint64"},
                        {"internalType": "uint64", "name": "unlockTime", "type": "uint64"},
                    ],
                    "internalType": "struct EVFIStaking.StakePosition",
                    "name": "",
                    "type": "tuple",
                }
            ],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "address", "name": "staker", "type": "address"},
                {"internalType": "uint256", "name": "positionId", "type": "uint256"},
                {"internalType": "uint256", "name": "amount", "type": "uint256"},
            ],
            "name": "previewUnstake",
            "outputs": [
                {"internalType": "uint256", "name": "returnedAmount", "type": "uint256"},
                {"internalType": "uint256", "name": "penaltyAmount", "type": "uint256"},
                {"internalType": "bool", "name": "early", "type": "bool"},
            ],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [],
            "name": "earlyUnstakePenaltyBps",
            "outputs": [{"internalType": "uint16", "name": "", "type": "uint16"}],
            "stateMutability": "view",
            "type": "function",
        },
    ]


def get_staking_web3():
    if not Web3 or not SEPOLIA_RPC_URL:
        return None
    try:
        web3_client = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
        if not web3_client.is_connected():
            return None
        return web3_client
    except Exception:
        return None


def build_staking_contract():
    staking_address = os.getenv("EVFI_STAKING_CONTRACT_ADDRESS", "").strip()
    web3_client = get_staking_web3()
    if not staking_address or not web3_client:
        return None, None
    try:
        checksum_address = web3_client.to_checksum_address(staking_address)
        contract = web3_client.eth.contract(
            address=checksum_address,
            abi=get_staking_contract_read_abi(),
        )
        return web3_client, contract
    except Exception:
        return None, None


def encode_abi_uint(value):
    return f"{int(value):064x}"


def encode_abi_address(value):
    address = str(value or "").strip()
    if not is_valid_evm_address(address):
        raise ValueError("invalid address")
    return f"{int(address, 16):064x}"


def decode_abi_words(result_hex):
    value = str(result_hex or "0x")
    if value.startswith("0x"):
        value = value[2:]
    if not value:
        return []
    return [int(value[index:index + 64] or "0", 16) for index in range(0, len(value), 64)]


def staking_rpc_call(data):
    staking_address = os.getenv("EVFI_STAKING_CONTRACT_ADDRESS", "").strip()
    if not SEPOLIA_RPC_URL or not staking_address:
        return []
    response = requests.post(
        SEPOLIA_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": staking_address, "data": data}, "latest"],
        },
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return decode_abi_words(payload.get("result"))


def build_onchain_staking_summary_from_rpc(summary, wallet_address):
    checksumless_wallet = str(wallet_address or "").strip()
    if not is_valid_evm_address(checksumless_wallet):
        return summary

    total_staked_raw = staking_rpc_call("0x9bfd8d61" + encode_abi_address(checksumless_wallet))[0]
    position_count = staking_rpc_call("0xb27a1df6" + encode_abi_address(checksumless_wallet))[0]
    penalty_bps = staking_rpc_call("0x3a9b0205")[0]
    total_staked = total_staked_raw / float(10 ** EVFI_TOKEN_DECIMALS)
    positions = []
    for position_id in range(int(position_count)):
        position = staking_rpc_call(
            "0x2e569eff" + encode_abi_address(checksumless_wallet) + encode_abi_uint(position_id)
        )
        amount_raw = int(position[0]) if len(position) > 0 else 0
        if amount_raw <= 0:
            continue
        start_time = int(position[1]) if len(position) > 1 else 0
        unlock_time = int(position[2]) if len(position) > 2 else 0
        preview = staking_rpc_call(
            "0x5ce484b1"
            + encode_abi_address(checksumless_wallet)
            + encode_abi_uint(position_id)
            + encode_abi_uint(amount_raw)
        )
        amount = amount_raw / float(10 ** EVFI_TOKEN_DECIMALS)
        positions.append(
            {
                "positionId": position_id,
                "amount": amount,
                "startTime": start_time,
                "unlockTime": unlock_time,
                "early": bool(preview[2]) if len(preview) > 2 else False,
                "returnedAmount": (int(preview[0]) if len(preview) > 0 else amount_raw) / float(10 ** EVFI_TOKEN_DECIMALS),
                "penaltyAmount": (int(preview[1]) if len(preview) > 1 else 0) / float(10 ** EVFI_TOKEN_DECIMALS),
            }
        )

    active_tier = derive_staking_tier(total_staked)
    summary.update(
        {
            "enabled": True,
            "penaltyBps": int(penalty_bps),
            "totalStaked": total_staked,
            "positionCount": int(position_count),
            "positions": positions,
            "source": "rpc",
            "activeStake": (
                {
                    "tierKey": active_tier["label"].lower(),
                    "stakeTier": active_tier["label"],
                    "stakeEvfi": total_staked,
                    "evfiAmount": total_staked,
                    "rewardBoostPct": active_tier["boostPct"],
                    "boostPct": active_tier["boostPct"],
                }
                if active_tier
                else None
            ),
        }
    )
    return summary


def build_onchain_staking_summary(wallet_address):
    wallet_address = (wallet_address or "").strip()
    summary = {
        "enabled": False,
        "mode": os.getenv("STAKING_MODE", "onchain").strip() or "onchain",
        "chainId": SEPOLIA_CHAIN_ID,
        "walletAddress": wallet_address,
        "contractAddress": os.getenv("EVFI_STAKING_CONTRACT_ADDRESS", "").strip(),
        "generatedFeesPoolAddress": os.getenv("GENERATED_FEES_POOL_ADDRESS", "").strip(),
        "tokenAddress": get_evfi_token_address(),
        "penaltyBps": int(os.getenv("EARLY_UNSTAKE_PENALTY_BPS", "1000") or "1000"),
        "totalStaked": 0.0,
        "positionCount": 0,
        "positions": [],
        "activeStake": None,
        "thresholds": parse_staking_tier_thresholds(),
        "source": "unavailable",
    }

    web3_client, staking_contract = build_staking_contract()
    if not wallet_address or not web3_client or not staking_contract:
        try:
            return build_onchain_staking_summary_from_rpc(summary, wallet_address)
        except Exception as exc:
            summary["source"] = f"unavailable:{exc}"
        return summary

    try:
        checksum_wallet = web3_client.to_checksum_address(wallet_address)
        total_staked_raw = int(staking_contract.functions.totalStaked(checksum_wallet).call())
        position_count = int(staking_contract.functions.getStakePositionsCount(checksum_wallet).call())
        penalty_bps = int(staking_contract.functions.earlyUnstakePenaltyBps().call())
        total_staked = total_staked_raw / float(10 ** EVFI_TOKEN_DECIMALS)
        positions = []
        for position_id in range(position_count):
            position = staking_contract.functions.getStakePosition(checksum_wallet, position_id).call()
            amount_raw = int(position[0])
            start_time = int(position[1])
            unlock_time = int(position[2])
            amount = amount_raw / float(10 ** EVFI_TOKEN_DECIMALS)
            preview = staking_contract.functions.previewUnstake(
                checksum_wallet,
                position_id,
                amount_raw,
            ).call()
            returned_amount = int(preview[0]) / float(10 ** EVFI_TOKEN_DECIMALS)
            penalty_amount = int(preview[1]) / float(10 ** EVFI_TOKEN_DECIMALS)
            early = bool(preview[2])
            positions.append(
                {
                    "positionId": position_id,
                    "amount": amount,
                    "startTime": start_time,
                    "unlockTime": unlock_time,
                    "early": early,
                    "returnedAmount": returned_amount,
                    "penaltyAmount": penalty_amount,
                }
            )

        active_tier = derive_staking_tier(total_staked)
        summary.update(
            {
                "enabled": True,
                "penaltyBps": penalty_bps,
                "totalStaked": total_staked,
                "positionCount": position_count,
                "positions": positions,
                "source": "onchain",
                "activeStake": (
                    {
                        "tierKey": active_tier["label"].lower(),
                        "stakeTier": active_tier["label"],
                        "stakeEvfi": total_staked,
                        "evfiAmount": total_staked,
                        "rewardBoostPct": active_tier["boostPct"],
                        "boostPct": active_tier["boostPct"],
                    }
                    if active_tier
                    else None
                ),
            }
        )
    except Exception as exc:
        summary["source"] = f"error:{exc}"

    return summary


def mirror_onchain_staking_action(wallet_address, action_type, evfi_amount, tx_hash, metadata=None):
    user_id = find_user_id_by_wallet_address(wallet_address)
    if not user_id:
        return False

    status = "confirmed"
    if tx_hash:
        web3_client = get_staking_web3()
        if web3_client:
            try:
                receipt = web3_client.eth.get_transaction_receipt(tx_hash)
                if not receipt or int(receipt.status) != 1:
                    status = "submitted_unverified"
            except Exception:
                status = "submitted_unverified"

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO utility_actions (
                user_id,
                action_key,
                action_type,
                evfi_amount,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "onchain_staking",
                action_type,
                float(evfi_amount or 0.0),
                status,
                int(time.time()),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return True


_base_processTelemetrySync = processTelemetrySync
_base_stake_evfi_tier = stake_evfi_tier
_base_unstake_evfi = unstake_evfi
_base_get_user_utility_state = get_user_utility_state
_base_get_active_stake_boost_pct = get_active_stake_boost_pct


def refresh_charge_sessions_from_history():
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM charge_sessions")
        conn.commit()
        rebuild_charge_sessions(conn)
    finally:
        conn.close()


def processTelemetrySync(*args, **kwargs):
    result = _base_processTelemetrySync(*args, **kwargs)
    try:
        refresh_charge_sessions_from_history()
    except Exception as exc:
        print(f"[charge-policy] failed to refresh charge sessions after sync: {exc}")
    return result


def stake_evfi_tier(user_id, tier_key):
    raise RuntimeError("App-level staking is disabled. Use the onchain staking contract flow.")


def unstake_evfi(user_id):
    raise RuntimeError("App-level unstaking is disabled. Use the onchain staking contract flow.")


def get_active_stake_boost_pct(user_id):
    wallet_address = get_user_wallet_address(user_id)
    summary = build_onchain_staking_summary(wallet_address)
    active_stake = summary.get("activeStake") or {}
    return float(active_stake.get("boostPct", 0.0) or 0.0)


def get_user_utility_state(user_id):
    state = _base_get_user_utility_state(user_id)
    wallet_address = get_user_wallet_address(user_id)
    onchain_staking = build_onchain_staking_summary(wallet_address)
    state["stakingMode"] = "onchain"
    state["onchainStaking"] = onchain_staking
    if onchain_staking.get("activeStake"):
        state["activeStake"] = onchain_staking["activeStake"]
    return state


@app.route("/api/staking/config")
def api_staking_config():
    return jsonify(
        {
            "enabled": bool(os.getenv("EVFI_STAKING_CONTRACT_ADDRESS", "").strip()),
            "chainId": SEPOLIA_CHAIN_ID,
            "tokenAddress": get_evfi_token_address(),
            "stakingContractAddress": os.getenv("EVFI_STAKING_CONTRACT_ADDRESS", "").strip(),
            "generatedFeesPoolAddress": os.getenv("GENERATED_FEES_POOL_ADDRESS", "").strip(),
            "penaltyBps": int(os.getenv("EARLY_UNSTAKE_PENALTY_BPS", "1000") or "1000"),
            "tokenDecimals": EVFI_TOKEN_DECIMALS,
            "thresholds": parse_staking_tier_thresholds(),
            "lockOptions": [
                int(value.strip())
                for value in os.getenv("STAKING_ALLOWED_LOCKS", "21600,86400,604800").split(",")
                if value.strip()
            ],
            "mode": os.getenv("STAKING_MODE", "onchain").strip() or "onchain",
        }
    )


@app.route("/api/staking/state")
def api_staking_state():
    wallet_address = request.args.get("wallet", "").strip()
    return jsonify(build_onchain_staking_summary(wallet_address))


@app.route("/api/staking/audit", methods=["POST"])
def api_staking_audit():
    payload = request.get_json(silent=True) or {}
    mirrored = mirror_onchain_staking_action(
        payload.get("wallet"),
        payload.get("action"),
        payload.get("amount"),
        payload.get("txHash"),
        payload,
    )
    return jsonify({"ok": True, "mirrored": bool(mirrored)})


if __name__ == "__main__":
    run_app()
