from flask import Flask, jsonify, redirect, request, send_from_directory, url_for
import json
import secrets
import requests
import urllib.parse
import time
import sqlite3
import os
import subprocess
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
EVFI_ASSIGN_SCRIPT = os.getenv("EVFI_ASSIGN_SCRIPT", "evfi_assign_rewards.mjs")
EVFI_ASSIGN_RATE = float(os.getenv("EVFI_ASSIGN_RATE", "0.25"))
EVFI_MIN_ASSIGNMENT = float(os.getenv("EVFI_MIN_ASSIGNMENT", "5"))

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
        tesla_vehicle_id TEXT,
        odometer_reading REAL,
        miles_added REAL,
        drv_earned REAL,
        synced_at INTEGER
    )
    """)

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
        background:linear-gradient(180deg, #ff2d46, #dd1b38);
        box-shadow:0 8px 0 rgba(120, 10, 30, .9), 0 18px 30px rgba(0,0,0,.3);
    }

    .btn-primary:active{
        transform:translateY(4px);
        box-shadow:0 3px 0 rgba(120, 10, 30, .9), 0 10px 18px rgba(0,0,0,.28);
    }

    .btn-secondary{
        background:rgba(255,255,255,.04);
        box-shadow:0 8px 20px rgba(0,0,0,.18);
    }

    .vehicle-list{
        display:grid;
        grid-template-columns:repeat(auto-fit, minmax(300px,1fr));
        gap:18px;
    }

    .vehicle-card,
    .panel, .stat-card, .vehicle-panel, .history-panel{
        background:linear-gradient(180deg, rgba(18,20,27,.96), rgba(14,17,24,.98));
        border:1px solid var(--stroke);
        border-radius:24px;
        box-shadow:var(--shadow);
    }

    .vehicle-card{
        padding:22px;
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
        gap:22px;
        margin-bottom:22px;
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
        gap:22px;
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
        padding:24px;
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
        gap:22px;
    }

    .stack{
        display:grid;
        gap:22px;
    }

    .stats-grid{
        display:grid;
        grid-template-columns:repeat(2, minmax(0,1fr));
        gap:18px;
    }

    .secondary-card{
        padding:24px;
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
        width:64px;
        height:64px;
        border-radius:18px;
        background:rgba(255,255,255,.04);
        display:flex;
        align-items:center;
        justify-content:center;
        font-family:'Oxanium', sans-serif;
        font-size:30px;
        font-weight:700;
        color:#fff;
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

    @media (max-width: 1120px){
        .topbar{
            grid-template-columns:1fr;
        }

        .hero-vehicle{
            grid-template-columns:1fr;
        }

        .dashboard-grid{
            grid-template-columns:1fr;
        }

        .stats-grid{
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


def build_demo_assignment_amount(summary):
    telemetry_score = float(summary["total_miles"] or 0)
    computed = telemetry_score * EVFI_ASSIGN_RATE
    return round(max(EVFI_MIN_ASSIGNMENT, computed), 4)


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


def assign_demo_reward_onchain(wallet_address, amount_tokens, batch_id):
    if not is_valid_evm_address(wallet_address):
        raise ValueError("A valid wallet address is required")
    if not EVFI_REWARDS_ADDRESS or not EVFI_TOKEN_ADDRESS:
        raise ValueError("EVFI contract addresses are not configured")

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


def load_vehicle_and_summary(vid):
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
    summary = sync_vehicle_rewards(vid, meta["display_name"], vin, current_odometer)

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


def sync_vehicle_rewards(vid, display_name, vin, current_odometer):
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

        cur.execute("""
            INSERT INTO reward_events
            (tesla_vehicle_id, odometer_reading, miles_added, drv_earned, synced_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(vid),
            current_odometer,
            0,
            0,
            now_ts
        ))
    else:
        previous_latest = float(existing["latest_odometer"] or 0)
        baseline = float(existing["baseline_odometer"] or current_odometer)

        miles_added = current_odometer - previous_latest
        if miles_added < 0:
            miles_added = 0

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

        cur.execute("""
            INSERT INTO reward_events
            (tesla_vehicle_id, odometer_reading, miles_added, drv_earned, synced_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(vid),
            current_odometer,
            miles_added,
            miles_added,
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
        <section class="hero">
            <div>
                <div class="badge">EvFi Phase 1</div>
                <h1>Connect Tesla telemetry to EVFI rewards.</h1>
                <p>Use live Tesla odometer data as the offchain score engine, then connect a Sepolia wallet to view and claim real EVFI rewards.</p>
            </div>
            <div>
                <a class="btn btn-primary" href="{url}">Login with Tesla</a>
            </div>
        </section>
        """
        return render_page("EvFi Fleet", body)

    cars = tesla_api.get_vehicles()

    if not cars:
        body = """
        <section class="hero">
            <div>
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
    <section class="hero">
        <div>
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
    events = get_recent_reward_events(vid)

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
        synced_at_str = time.strftime("%b %d, %Y %I:%M %p", time.localtime(e["synced_at"]))
        events_rows += f"""
        <tr>
            <td>{escape(synced_at_str)}</td>
            <td>{e["odometer_reading"]}</td>
            <td>{e["miles_added"]}</td>
            <td class="gain">+{e["drv_earned"]}</td>
        </tr>
        """

    if not events_rows:
        events_rows = """
        <tr>
            <td colspan="4" class="muted">No sync history yet. Click Sync Miles.</td>
        </tr>
        """

    last_synced = summary["last_synced_at"]
    last_synced_str = time.strftime("%b %d, %Y %I:%M %p", time.localtime(last_synced)) if last_synced else "Never"

    body = f"""
    <section class="topbar">
        <section class="vehicle-panel">
            <div class="vehicle-header">
                <div>
                    <div class="label">Charge & Controls</div>
                    <h2 class="vehicle-title">{escape(display_name)}</h2>
                    <div class="vehicle-sub">{escape(str(year))} {escape(model)} • {escape(trim)} • {escape(str(vehicle_state).title())}</div>
                </div>
                <div class="tesla-mark">T</div>
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
                <button class="quick-btn" onclick="window.location.href='/sync/{vid}'">Sync Miles</button>
                <button id="refreshAndDistributeButton" class="quick-btn" data-vehicle-id="{vid}" data-default-amount="{build_demo_assignment_amount(summary)}">Sync + Airdrop</button>
                <button class="quick-btn" onclick="window.location.href='/vehicle/{vid}/raw'">Raw Data</button>
                <button id="claimRewardsButton" class="quick-btn">Claim EVFI</button>
                <button id="assignRewardsButton" class="quick-btn" data-vehicle-id="{vid}" data-default-amount="{build_demo_assignment_amount(summary)}">Assign Test EVFI</button>
                <button class="quick-btn" onclick="alert('Vehicle controls can be wired next')">Controls</button>
            </div>
            <div class="admin-stack">
                <input id="distributionRecipientInput" class="admin-input" type="text" value="{escape(DEFAULT_WALLET_ADDRESS)}" placeholder="Distribution recipient wallet 0x...">
                <input id="adminKeyInput" class="admin-input" type="password" placeholder="Admin API key">
            </div>

            <div class="charge-card">
                <div class="charge-head">
                    <div>Charge limit: {charge_limit_soc}%</div>
                    <div class="muted">{escape(str(charging_state))}</div>
                </div>

                <div class="charge-meta">
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
                <a class="soft-link" href="/sync/{vid}">Refresh Rewards</a>
                <a class="soft-link" href="/vehicle/{vid}/raw">Telemetry</a>
            </div>
        </section>

        <section id="walletModule" class="wallet-panel panel">
            <div class="wallet-panel-header">
                <div>
                    <div class="label">Wallet & Rewards</div>
                    <h2 class="wallet-panel-title">Sepolia EVFI</h2>
                    <p class="wallet-panel-copy">Connect your test wallet, review live ERC-20 balance, and claim pending rewards without leaving the dashboard.</p>
                </div>
                <div id="walletConnectionBadge" class="wallet-badge" data-state="idle">Not Connected</div>
            </div>

            <div class="wallet-actions">
                <button id="connectWalletButton" class="wallet-btn" data-state="idle">
                    <span class="wallet-btn-icon" aria-hidden="true"></span>
                    <span id="connectWalletButtonLabel" class="wallet-btn-label">Connect Sepolia Wallet</span>
                </button>
                <button id="disconnectWalletButton" class="wallet-link wallet-link-button is-hidden" type="button">Disconnect</button>
            </div>

            <div class="wallet-grid">
                <div class="wallet-stat">
                    <div class="wallet-stat-label">Wallet EVFI Balance</div>
                    <div id="walletBalanceValue" class="wallet-stat-value">0.0</div>
                    <div class="sub">Live Sepolia token balance.</div>
                </div>
                <div class="wallet-stat">
                    <div class="wallet-stat-label">Claimable EVFI</div>
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
                <a id="tokenExplorerLink" class="wallet-link {'' if EVFI_TOKEN_ADDRESS else 'is-hidden'}" href="https://sepolia.etherscan.io/address/{escape(EVFI_TOKEN_ADDRESS)}" target="_blank" rel="noreferrer">EVFI Token</a>
                <a id="rewardsExplorerLink" class="wallet-link {'' if EVFI_REWARDS_ADDRESS else 'is-hidden'}" href="https://sepolia.etherscan.io/address/{escape(EVFI_REWARDS_ADDRESS)}" target="_blank" rel="noreferrer">Rewards Vault</a>
                <a id="txExplorerLink" class="wallet-link is-hidden" href="#" target="_blank" rel="noreferrer">Latest EVFI Tx</a>
            </div>

            <div id="walletConnectHint" class="wallet-hint">Sepolia contracts are connected. Link your wallet to unlock live EVFI balance reads and claim flow.</div>
            <div id="walletToast" class="inline-toast" data-tone="success"></div>
        </section>
    </section>

    <section class="stats-grid">
        <section class="panel secondary-card">
            <div class="label">Vehicle Summary</div>
            <h3 class="secondary-card-title">{escape(display_name)}</h3>
            <p class="secondary-card-copy">{escape(str(year))} {escape(model)} • {escape(trim)} • {escape(str(vehicle_state).title())}</p>

            <div class="summary-grid">
                <div class="summary-item wide">
                    <div class="summary-label">Full VIN</div>
                    <div class="summary-value">{escape(vin)}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Odometer</div>
                    <div class="summary-value">{current_odometer:.1f}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Last Sync</div>
                    <div class="summary-value">{escape(last_synced_str)}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Exterior</div>
                    <div class="summary-value">{escape(str(exterior_color))}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Wheel Type</div>
                    <div class="summary-value">{escape(str(wheel_type))}</div>
                </div>
            </div>
        </section>

        <section class="panel secondary-card">
            <div class="label">Mileage / Distribution</div>
            <h3 class="secondary-card-title">Weekly EVFI Output</h3>
            <p class="secondary-card-copy">Mileage stays offchain. This module surfaces the current reward math and the test airdrop amount used by the assignment tools.</p>

            <div class="distribution-grid">
                <div class="distribution-stat">
                    <div class="distribution-label">Telemetry Score</div>
                    <div class="distribution-value">{float(summary["drv_balance"]):.1f}</div>
                </div>
                <div class="distribution-stat">
                    <div class="distribution-label">Miles Tracked</div>
                    <div class="distribution-value">{float(summary["total_miles"]):.1f}</div>
                </div>
                <div class="distribution-stat">
                    <div class="distribution-label">Airdrop Amount</div>
                    <div class="distribution-value">{build_demo_assignment_amount(summary):.1f}</div>
                </div>
            </div>

            <div class="sub">Use <strong>Assign Test EVFI</strong> for a manual pending reward, or <strong>Sync + Airdrop</strong> to refresh mileage and assign the newly computed amount in one step.</div>
        </section>
    </section>

    <section class="dashboard-grid" style="margin-top:22px;">
        <section class="history-panel">
            <h3 class="history-title">Reward Sync History</h3>
            <table>
                <tr>
                    <th>Synced At</th>
                    <th>Odometer</th>
                    <th>Miles Added</th>
                    <th>Score Added</th>
                </tr>
                {events_rows}
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
                <tr><th>Odometer</th><td>{current_odometer:.1f}</td></tr>
                <tr><th>Location</th><td>{latitude}, {longitude}</td></tr>
                <tr><th>Exterior Color</th><td>{escape(str(exterior_color))}</td></tr>
                <tr><th>Wheel Type</th><td>{escape(str(wheel_type))}</td></tr>
                <tr><th>Default Wallet</th><td>{escape(DEFAULT_WALLET_ADDRESS)}</td></tr>
                <tr><th>EvFiToken</th><td>{escape(EVFI_TOKEN_ADDRESS or "Not configured")}</td></tr>
                <tr><th>EvFiRewards</th><td>{escape(EVFI_REWARDS_ADDRESS or "Not configured")}</td></tr>
            </table>
        </section>
    </section>
    """
    return render_page(f"{display_name} Dashboard", body)


@app.route("/sync/<vid>")
def sync_rewards(vid):
    try:
        load_vehicle_and_summary(vid)
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


@app.route("/api/vehicle/<vid>/summary")
def vehicle_summary_api(vid):
    try:
        context = load_vehicle_and_summary(vid)
    except ValueError:
        return jsonify({"error": "Vehicle not found"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    meta = context["meta"]
    summary = context["summary"]

    return jsonify(
        {
            "vehicleId": str(vid),
            "displayName": meta["display_name"],
            "walletDefault": DEFAULT_WALLET_ADDRESS,
            "telemetryScore": float(summary["drv_balance"] or 0),
            "totalMiles": float(summary["total_miles"] or 0),
            "recommendedAssignment": build_demo_assignment_amount(summary),
        }
    )


@app.route("/api/vehicle/<vid>/assign-demo-reward", methods=["POST"])
def assign_demo_reward(vid):
    if request.headers.get("x-admin-key") != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    if not os.path.exists(EVFI_ASSIGN_SCRIPT):
        return jsonify({"error": f"Missing reward assignment script: {EVFI_ASSIGN_SCRIPT}"}), 500

    try:
        context = load_vehicle_and_summary(vid)
    except ValueError:
        return jsonify({"error": "Vehicle not found"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    summary = context["summary"]

    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    amount_tokens = float(payload.get("amountTokens") or build_demo_assignment_amount(summary))
    batch_id = str(payload.get("batchId") or build_distribution_batch_id(vid, "demo"))

    try:
        output = assign_demo_reward_onchain(wallet, amount_tokens, batch_id)
    except Exception as exc:
        payload = normalize_assignment_exception(exc)
        return jsonify(payload), 500

    return jsonify(
        {
            "ok": True,
            "vehicleId": str(vid),
            "wallet": wallet,
            "amountTokens": amount_tokens,
            "batchId": batch_id,
            "telemetryScore": float(summary["drv_balance"] or 0),
            "txHash": output.get("txHash"),
            "output": output,
        }
    )


@app.route("/api/vehicle/<vid>/refresh-and-distribute", methods=["POST"])
def refresh_and_distribute_reward(vid):
    if request.headers.get("x-admin-key") != ADMIN_API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    if not os.path.exists(EVFI_ASSIGN_SCRIPT):
        return jsonify({"error": f"Missing reward assignment script: {EVFI_ASSIGN_SCRIPT}"}), 500

    try:
        context = load_vehicle_and_summary(vid)
    except ValueError:
        return jsonify({"error": "Vehicle not found"}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500

    summary = context["summary"]
    payload = request.get_json(silent=True) or {}
    wallet = str(payload.get("wallet") or DEFAULT_WALLET_ADDRESS)
    if not is_valid_evm_address(wallet):
        return jsonify({"error": "A valid recipient wallet is required"}), 400

    amount_tokens = float(payload.get("amountTokens") or build_demo_assignment_amount(summary))
    batch_id = str(payload.get("batchId") or build_distribution_batch_id(vid, "sync"))

    try:
        output = assign_demo_reward_onchain(wallet, amount_tokens, batch_id)
    except Exception as exc:
        payload = normalize_assignment_exception(exc)
        return jsonify(payload), 500

    return jsonify(
        {
            "ok": True,
            "vehicleId": str(vid),
            "wallet": wallet,
            "amountTokens": amount_tokens,
            "batchId": batch_id,
            "telemetryScore": float(summary["drv_balance"] or 0),
            "totalMiles": float(summary["total_miles"] or 0),
            "txHash": output.get("txHash"),
            "output": output,
        }
    )


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


if __name__ == "__main__":
    run_app()
