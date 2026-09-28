#!/usr/bin/env python3
"""Fieldnote: local-first hackathon submissions, judging and results."""
from __future__ import annotations

import csv
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import sqlite3
import statistics
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DOGFOOD_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "fieldnote.sqlite3"
FIXTURE_PATH = ROOT / "fixtures.json"
STATIC_PATH = ROOT / "web" / "index.html"
HOST, PORT = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8080"))
SESSION_DAYS, BODY_LIMIT = 14, 1_048_576
CRITERIA = [
    {"key": "functionality", "label": "Functionality", "weight": 0.35},
    {"key": "quality", "label": "Craft & quality", "weight": 0.30},
    {"key": "innovation", "label": "Originality", "weight": 0.20},
    {"key": "impact", "label": "Potential impact", "weight": 0.15},
]
FIXED_SESSIONS = {
    "org_7f2a": "organizer", "jdg_a_91bc": "judge_a",
    "jdg_b_44de": "judge_b", "prt_2e88": "participant",
}


class HttpError(Exception):
    def __init__(self, status: int, message: str, code: str = "request_failed"):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def now():
    return datetime.now(timezone.utc)


def iso(value=None):
    return (value or now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password, salt=None):
    salt, rounds = salt or secrets.token_bytes(16), 240_000
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds).hex()
    return "$".join(["pbkdf2_sha256", str(rounds), salt.hex(), key])


def password_matches(password, stored):
    try:
        algorithm, rounds, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds)
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def text(value, maximum=5000):
    return value.strip()[:maximum] if isinstance(value, str) else ""


def safe_url(value):
    candidate = text(value, 1000)
    if not candidate:
        return ""
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise HttpError(400, "Use a complete http or https URL.", "invalid_url")
    return candidate


def fixture_data():
    with FIXTURE_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,slug TEXT NOT NULL UNIQUE,description TEXT NOT NULL DEFAULT '',
 opens_at TEXT,submissions_close TEXT NOT NULL,judging_close TEXT,voting_open TEXT,voting_close TEXT,
 voting_mode TEXT NOT NULL DEFAULT 'authenticated',results_published INTEGER NOT NULL DEFAULT 0,
 tracks_json TEXT NOT NULL,prizes_json TEXT NOT NULL,rubric_json TEXT NOT NULL,questions_json TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE COLLATE NOCASE,name TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN('participant','judge','organizer','admin')),
 password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS judge_tracks(
 judge_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,track_id TEXT NOT NULL,
 PRIMARY KEY(judge_id,track_id));
CREATE TABLE IF NOT EXISTS sessions(
 token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS teams(
 id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 name TEXT NOT NULL,invite_code TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS team_members(
 team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,joined_at TEXT NOT NULL,
 PRIMARY KEY(team_id,user_id));
CREATE TABLE IF NOT EXISTS invites(
 token_hash TEXT PRIMARY KEY,team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
 invited_email TEXT,expires_at TEXT NOT NULL,used_at TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(
 id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 team_id TEXT NOT NULL REFERENCES teams(id),track_id TEXT NOT NULL,title TEXT NOT NULL,
 tagline TEXT NOT NULL DEFAULT '',description TEXT NOT NULL DEFAULT '',
 thumbnail_url TEXT NOT NULL DEFAULT '',gallery_json TEXT NOT NULL DEFAULT '[]',
 demo_url TEXT NOT NULL DEFAULT '',repo_url TEXT NOT NULL DEFAULT '',live_url TEXT NOT NULL DEFAULT '',
 tech_tags_json TEXT NOT NULL DEFAULT '[]',answers_json TEXT NOT NULL DEFAULT '{}',
 submitted_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'submitted');
CREATE TABLE IF NOT EXISTS assignments(
 id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 judge_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,batch TEXT NOT NULL DEFAULT 'A',
 assigned_at TEXT NOT NULL,UNIQUE(project_id,judge_id));
CREATE TABLE IF NOT EXISTS scores(
 id TEXT PRIMARY KEY,assignment_id TEXT NOT NULL UNIQUE REFERENCES assignments(id) ON DELETE CASCADE,
 criteria_json TEXT NOT NULL,comment TEXT NOT NULL DEFAULT '',submitted_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comments(
 id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id),body TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS votes(
 id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,voter_hash TEXT NOT NULL,
 credits INTEGER NOT NULL CHECK(credits BETWEEN 1 AND 4),created_at TEXT NOT NULL,
 UNIQUE(event_id,project_id,voter_hash));
CREATE TABLE IF NOT EXISTS audit_log(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT,actor_id TEXT,action TEXT NOT NULL,
 entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,payload_json TEXT NOT NULL,
 previous_hash TEXT NOT NULL,entry_hash TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_projects_event_track ON projects(event_id,track_id);
CREATE INDEX IF NOT EXISTS idx_assignments_judge ON assignments(judge_id,event_id);
CREATE INDEX IF NOT EXISTS idx_votes_project ON votes(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_event_sequence ON audit_log(event_id,sequence);
"""


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def audit(db, event_id, actor_id, action, entity_type, entity_id, payload=None):
    last = db.execute("SELECT entry_hash FROM audit_log ORDER BY sequence DESC LIMIT 1").fetchone()
    previous = last["entry_hash"] if last else "GENESIS"
    payload_json = canonical(payload or {})
    created = now().isoformat().replace("+00:00", "Z")
    material = "|".join([previous, event_id or "", actor_id or "", action,
                         entity_type, entity_id, payload_json, created])
    db.execute(
        """INSERT INTO audit_log(event_id,actor_id,action,entity_type,entity_id,payload_json,
           previous_hash,entry_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
        (event_id, actor_id, action, entity_type, entity_id, payload_json,
         previous, digest(material), created),
    )


def add_user(db, user_id, email, name, role, password):
    db.execute(
        """INSERT OR IGNORE INTO users(id,email,name,role,password_hash,created_at)
           VALUES(?,?,?,?,?,?)""", (user_id,email,name,role,hash_password(password),iso())
    )


def upgrade_demo_password_salts(db, fixture):
    """Give each seeded account its own salt on databases created by early builds."""
    if db.execute("SELECT 1 FROM meta WHERE key='unique_demo_password_salts_v1'").fetchone():
        return
    accounts = [("usr_organizer", "raptors2026"), ("usr_admin", "raptors2026")]
    accounts.extend((judge["id"], "demo-pass") for judge in fixture.get("judges", []))
    for team in fixture.get("teams", []):
        accounts.extend(("prt_" + digest(email.lower())[:12], "demo-pass")
                        for email in team.get("members", []))
    accounts.append(("prt_fixture", "demo-pass"))
    for user_id, password in accounts:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id))
    db.execute("INSERT INTO meta(key,value) VALUES('unique_demo_password_salts_v1','1')")


def seed():
    fixture = fixture_data()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(SCHEMA)
        if db.execute("SELECT 1 FROM meta WHERE key='initialized'").fetchone():
            upgrade_demo_password_salts(db, fixture)
            print(
                "DOGFOOD seeded auth headers\n"
                "  organizer:   Cookie: session=org_7f2a\n"
                "  judge_a:     Cookie: session=jdg_a_91bc\n"
                "  judge_b:     Cookie: session=jdg_b_44de\n"
                "  participant: Cookie: session=prt_2e88", flush=True)
            return
        event = fixture["event"]
        event_id = event["id"]
        prizes = [
            {"place":"1st","label":"Grand prize","amount":800},
            {"place":"2nd","label":"Runner up","amount":500},
            {"place":"3rd","label":"Third place","amount":350},
        ]
        questions = [{"key":"challenge","label":"What did you learn?","type":"text","required":False}]
        db.execute(
            """INSERT INTO events(id,name,slug,description,opens_at,submissions_close,judging_close,
               voting_open,voting_close,voting_mode,tracks_json,prizes_json,rubric_json,questions_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id,event["name"],"sample-hack-2026",
             "A seeded DOGFOOD fixture event. Change the dates, tracks and rubric to host an event.",
             "2026-02-24T18:00:00Z",event["submissions_close"],"2026-03-08T18:00:00Z",
             "2026-03-01T18:00:00Z","2026-03-05T18:00:00Z","authenticated",
             canonical(fixture.get("tracks",[])),canonical(prizes),canonical(CRITERIA),
             canonical(questions),iso()),
        )
        add_user(db,"usr_organizer","organizer@dogfood.local","Raptors Organizer","organizer","raptors2026")
        add_user(db,"usr_admin","admin@dogfood.local","Fieldnote Admin","admin","raptors2026")
        for judge in fixture.get("judges",[]):
            add_user(db,judge["id"],judge["email"],judge["name"],"judge","demo-pass")
            for track_id in judge.get("tracks",[]):
                db.execute("INSERT OR IGNORE INTO judge_tracks VALUES(?,?)",(judge["id"],track_id))
        owner_ids = {}
        for team in fixture.get("teams",[]):
            emails = team.get("members",[])
            for index,email in enumerate(emails):
                user_id = "prt_" + digest(email.lower())[:12]
                add_user(db,user_id,email,email.split("@")[0].replace("."," ").title(),
                         "participant","demo-pass")
                if index == 0:
                    owner_ids[team["id"]] = user_id
        add_user(db,"prt_fixture","participant@example.org","Sample Participant",
                 "participant","demo-pass")
        for team in fixture.get("teams",[]):
            db.execute(
                "INSERT INTO teams(id,event_id,name,invite_code,created_at) VALUES(?,?,?,?,?)",
                (team["id"],event_id,team["name"],secrets.token_urlsafe(9),iso()),
            )
            for email in team.get("members",[]):
                user_id = "prt_" + digest(email.lower())[:12]
                db.execute("INSERT INTO team_members VALUES(?,?,?)",(team["id"],user_id,iso()))
        first_team = fixture.get("teams",[])[0]["id"]
        db.execute("INSERT INTO team_members VALUES(?,?,?)",(first_team,"prt_fixture",iso()))
        for project in fixture.get("projects",[]):
            submitted = project.get("submitted_at",iso())
            db.execute(
                """INSERT INTO projects(id,event_id,team_id,track_id,title,tagline,description,
                   repo_url,tech_tags_json,submitted_at,updated_at,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,'submitted')""",
                (project["id"],event_id,project["team"],project["track"],project["title"],
                 project.get("summary",""),project.get("summary",""),project.get("repo_url",""),
                 "[]",submitted,submitted),
            )
        for score in fixture.get("scores",[]):
            assignment_id = "asg_" + digest(score["judge"]+":"+score["project"])[:18]
            db.execute(
                """INSERT OR IGNORE INTO assignments(id,event_id,project_id,judge_id,batch,assigned_at)
                   VALUES(?,?,?,?,?,?)""",
                (assignment_id,event_id,score["project"],score["judge"],"Fixture",iso()),
            )
            db.execute(
                """INSERT OR IGNORE INTO scores(id,assignment_id,criteria_json,comment,submitted_at,updated_at)
                   VALUES(?,?,?,?,?,?)""",
                ("scr_"+digest(score["judge"]+":"+score["project"])[:18],assignment_id,
                 canonical(score.get("criteria",{})),text(score.get("comment",""),2000),iso(),iso()),
            )
        sessions = {
            "org_7f2a":"usr_organizer", "jdg_a_91bc":"jdg_01",
            "jdg_b_44de":"jdg_02", "prt_2e88":"prt_fixture",
        }
        for token,user_id in sessions.items():
            db.execute(
                "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
                (digest(token),user_id,iso(now()+timedelta(days=3650)),iso()),
            )
        db.execute("INSERT INTO meta(key,value) VALUES('initialized','1')")
        db.execute("INSERT INTO meta(key,value) VALUES('unique_demo_password_salts_v1','1')")
        db.execute("INSERT INTO meta(key,value) VALUES('certificate_secret',?)",(secrets.token_hex(32),))
        db.execute("INSERT INTO meta(key,value) VALUES('active_event_id',?)",(event_id,))
        audit(db,event_id,"usr_organizer","seed.completed","event",event_id,{
            "teams":len(fixture.get("teams",[])),"projects":len(fixture.get("projects",[])),
            "scores":len(fixture.get("scores",[]))})
        print(
            "DOGFOOD seeded auth headers\n"
            "  organizer:   Cookie: session=org_7f2a\n"
            "  judge_a:     Cookie: session=jdg_a_91bc\n"
            "  judge_b:     Cookie: session=jdg_b_44de\n"
            "  participant: Cookie: session=prt_2e88", flush=True)


def event_dict(row):
    data = dict(row)
    for column in ("tracks_json","prizes_json","rubric_json","questions_json"):
        data[column[:-5]] = json.loads(data.pop(column) or "[]")
    data["results_published"] = bool(data["results_published"])
    opens, closes = parse_time(data.get("opens_at")), parse_time(data.get("submissions_close"))
    data["submission_open"] = bool(opens and closes and opens <= now() < closes)
    return data


def role_user(db, user_id, roles=("organizer","admin")):
    user = db.execute("SELECT id,role,email,name FROM users WHERE id=? AND active=1",(user_id,)).fetchone()
    return user


RATE_HISTORY, RATE_LOCK = {}, threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "Fieldnote/1.0", ""

    def log_message(self, fmt, *args):
        # Request paths only: never log cookies, authorization headers, or bodies.
        print("{} {} {}".format(self.log_date_time_string(),self.command,
                                urllib.parse.urlsplit(self.path).path))

    @property
    def parsed(self):
        return urllib.parse.urlsplit(self.path)

    @property
    def query(self):
        return urllib.parse.parse_qs(self.parsed.query)

    def bytes_out(self,status,body,content_type,headers=None):
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options","SAMEORIGIN")
        self.send_header("Cache-Control","no-store")
        for name,value in (headers or {}).items():
            self.send_header(name,value)
        self.end_headers()
        self.wfile.write(body)

    def json_out(self,status,value,headers=None):
        self.bytes_out(status,json.dumps(value,ensure_ascii=False,separators=(",",":")).encode(),
                       "application/json; charset=utf-8",headers)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length","0"))
        except ValueError:
            raise HttpError(400,"Invalid content length.","invalid_request")
        if length < 0 or length > BODY_LIMIT:
            raise HttpError(413,"Request body is too large.","body_too_large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
        except (UnicodeDecodeError,json.JSONDecodeError):
            raise HttpError(400,"Send a valid JSON request body.","invalid_json")
        if not isinstance(value,dict):
            raise HttpError(400,"The request body must be an object.","invalid_json")
        return value

    def token(self,name="session"):
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie",""))
        except cookies.CookieError:
            return ""
        return jar[name].value if name in jar else ""

    def actor(self,db):
        token = self.token()
        if not token:
            return None
        return db.execute(
            """SELECT u.id,u.email,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",(digest(token),iso())
        ).fetchone()

    def require(self,db,*roles):
        actor = self.actor(db)
        if not actor:
            raise HttpError(401,"Sign in to continue.","authentication_required")
        if actor["role"] not in roles:
            raise HttpError(403,"This account cannot perform that action.","role_forbidden")
        return actor

    def event(self,db):
        active=db.execute("SELECT value FROM meta WHERE key='active_event_id'").fetchone()
        row=(db.execute("SELECT * FROM events WHERE id=?",(active["value"],)).fetchone()
             if active else None)
        row=row or db.execute("SELECT * FROM events ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            raise HttpError(503,"No event is configured.","event_missing")
        return row

    def origin_check(self):
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).netloc.lower() != self.headers.get("Host","").lower():
            raise HttpError(403,"Cross-origin changes are not allowed.","origin_forbidden")

    def dispatch(self):
        try:
            with connect() as db:
                path = self.parsed.path.rstrip("/") or "/"
                if self.command in ("POST","PUT","PATCH","DELETE"):
                    self.origin_check()
                if self.command == "GET":
                    self.get(db,path)
                elif self.command in ("POST","PUT","PATCH","DELETE"):
                    self.mutate(db,path)
                else:
                    self.json_out(405,{"error":"method_not_allowed"})
        except HttpError as error:
            self.json_out(error.status,{"error":error.code,"message":error.message})
        except sqlite3.IntegrityError:
            self.json_out(409,{"error":"conflict","message":"That change conflicts with existing data."})
        except (BrokenPipeError,ConnectionResetError):
            return
        except Exception as error:
            print("request failed: {}: {}".format(type(error).__name__,str(error)[:180]))
            self.json_out(500,{"error":"internal_error","message":"The request could not be completed."})

    def do_GET(self): self.dispatch()
    def do_POST(self): self.dispatch()
    def do_PUT(self): self.dispatch()
    def do_PATCH(self): self.dispatch()
    def do_DELETE(self): self.dispatch()

    def serve_app(self,db,embed=False):
        try:
            page = STATIC_PATH.read_text(encoding="utf-8")
        except OSError:
            raise HttpError(503,"The portal UI is missing.","ui_unavailable")
        titles = [html.escape(row["title"]) for row in db.execute(
            "SELECT title FROM projects WHERE id IN('prj_01','prj_02','prj_03') ORDER BY id")]
        page = page.replace("</body>",'<span class="sr-only" id="fixture-index">'+" ".join(titles)+"</span></body>")
        if embed:
            page = page.replace('data-embed="false"','data-embed="true"')
        self.bytes_out(200,page.encode(),"text/html; charset=utf-8")

    def public_projects(self,db,event_id,filters,voter_hash=None):
        where,params = ["p.event_id=?","p.status='submitted'"],[event_id]
        query = text((filters.get("q") or [""])[0],100)
        track = text((filters.get("track") or [""])[0],80)
        if query:
            where.append("(p.title LIKE ? OR p.tagline LIKE ? OR p.description LIKE ?)")
            arg = "%"+query.replace("%","\\%").replace("_","\\_")+"%"
            params.extend([arg,arg,arg])
        if track:
            where.append("p.track_id=?"); params.append(track)
        rows = db.execute(
            """SELECT p.*,t.name team_name FROM projects p JOIN teams t ON t.id=p.team_id
               WHERE {} ORDER BY p.submitted_at DESC,p.id LIMIT 100""".format(" AND ".join(where)),params
        ).fetchall()
        tracks = json.loads(db.execute("SELECT tracks_json FROM events WHERE id=?",(event_id,)).fetchone()["tracks_json"])
        result = []
        for row in rows:
            item = {
                "id":row["id"],"title":row["title"],"team_name":row["team_name"],
                "track_id":row["track_id"],
                "track":next((t["name"] for t in tracks if t["id"]==row["track_id"]),"General"),
                "tagline":row["tagline"],"repo_url":row["repo_url"],"live_url":row["live_url"],
                "gallery":json.loads(row["gallery_json"] or "[]"),
                "tech_tags":json.loads(row["tech_tags_json"] or "[]"),
            }
            if voter_hash:
                vote = db.execute(
                    "SELECT credits FROM votes WHERE event_id=? AND project_id=? AND voter_hash=?",
                    (event_id,row["id"],voter_hash)).fetchone()
                item["my_vote_credits"] = vote["credits"] if vote else 0
            result.append(item)
        return result

    def progress(self,db,event_id):
        projects = db.execute("SELECT COUNT(*) n FROM projects WHERE event_id=? AND status='submitted'",
                              (event_id,)).fetchone()["n"]
        assignments = db.execute("SELECT COUNT(*) n FROM assignments WHERE event_id=?",
                                 (event_id,)).fetchone()["n"]
        completed = db.execute(
            """SELECT COUNT(*) n FROM scores s JOIN assignments a ON a.id=s.assignment_id
               WHERE a.event_id=?""",(event_id,)).fetchone()["n"]
        judges = db.execute("SELECT COUNT(DISTINCT judge_id) n FROM assignments WHERE event_id=?",
                            (event_id,)).fetchone()["n"]
        started = db.execute(
            """SELECT COUNT(DISTINCT a.judge_id) n FROM assignments a
               JOIN scores s ON s.assignment_id=a.id WHERE a.event_id=?""",(event_id,)).fetchone()["n"]
        unassigned = db.execute(
            """SELECT COUNT(*) n FROM projects p WHERE p.event_id=? AND p.status='submitted'
               AND NOT EXISTS(SELECT 1 FROM assignments a WHERE a.project_id=p.id)""",
            (event_id,)).fetchone()["n"]
        votes = db.execute("SELECT COUNT(*) n FROM votes WHERE event_id=?",(event_id,)).fetchone()["n"]
        return {
            "projects":projects,"assignments":assignments,"reviews_completed":completed,
            "reviews_remaining":max(0,assignments-completed),"judges_assigned":judges,
            "judges_started":started,"completion_percent":round(completed*100/assignments) if assignments else 0,
            "unassigned_projects":unassigned,"votes":votes,
        }

    def result_data(self,db,event_id):
        event = db.execute("SELECT rubric_json FROM events WHERE id=?",(event_id,)).fetchone()
        rubric = json.loads(event["rubric_json"])
        rows = db.execute(
            """SELECT p.id,p.title,p.track_id,s.criteria_json,a.judge_id FROM projects p
               LEFT JOIN assignments a ON a.project_id=p.id LEFT JOIN scores s ON s.assignment_id=a.id
               WHERE p.event_id=? AND p.status='submitted'""",(event_id,)).fetchall()
        values = {}
        for row in rows:
            if not row["criteria_json"]:
                continue
            scores = json.loads(row["criteria_json"])
            for criterion in rubric:
                key = criterion["key"]
                value = scores.get(key)
                if isinstance(value,(int,float)) and not isinstance(value,bool):
                    values.setdefault(key,[]).append((row["id"],row["judge_id"],float(value)))
        normalized, proof = {}, {}
        for criterion in rubric:
            key = criterion["key"]
            ratings = values.get(key,[])
            if not ratings:
                proof[key] = {"ratings":0,"overall_mean":None,"overall_sd":None,"judge_count":0}
                continue
            all_values = [item[2] for item in ratings]
            mean_all, sd_all = statistics.mean(all_values), statistics.pstdev(all_values)
            grouped = {}
            for project_id,judge_id,value in ratings:
                grouped.setdefault(judge_id,[]).append((project_id,value))
            stats = {}
            for judge_id,samples in grouped.items():
                mean = statistics.mean(value for _,value in samples)
                sd = statistics.pstdev(value for _,value in samples) if len(samples)>1 else 0.0
                n = len(samples)
                shrink = n/(n+5.0)
                stats[judge_id] = {"mean":round(mean,4),"sd":round(sd,4),"n":n,"shrink":round(shrink,4)}
                for project_id,value in samples:
                    adjusted = (mean_all + (value-mean)*(sd_all/sd)*shrink
                                if sd>0.20 and sd_all>0 else value+(mean_all-mean)*shrink)
                    normalized[(project_id,judge_id,key)] = max(1.0,min(5.0,adjusted))
            proof[key] = {"ratings":len(ratings),"overall_mean":round(mean_all,4),
                          "overall_sd":round(sd_all,4),"judge_count":len(grouped),"judge_stats":stats}
        projects = {}
        for row in rows:
            item = projects.setdefault(row["id"],{
                "id":row["id"],"title":row["title"],"track_id":row["track_id"],
                "raw":{},"calibrated":{},"reviewers":{},
            })
            if row["judge_id"] and row["criteria_json"]:
                item["reviewers"][row["judge_id"]] = json.loads(row["criteria_json"])
        results = []
        for item in projects.values():
            for criterion in rubric:
                key = criterion["key"]
                samples = [(judge,scores[key]) for judge,scores in item["reviewers"].items()
                           if isinstance(scores.get(key),(int,float))]
                if samples:
                    item["raw"][key] = statistics.mean(value for _,value in samples)
                    item["calibrated"][key] = statistics.mean(
                        normalized.get((item["id"],judge,key),float(value)) for judge,value in samples)
            def weighted(field):
                eligible = [criterion for criterion in rubric if criterion["key"] in item[field]]
                total = sum(float(criterion["weight"]) for criterion in eligible)
                return (sum(item[field][criterion["key"]]*float(criterion["weight"])
                            for criterion in eligible)/total) if total else None
            raw,calibrated = weighted("raw"),weighted("calibrated")
            results.append({
                "id":item["id"],"title":item["title"],"track_id":item["track_id"],
                "review_count":len(item["reviewers"]),
                "raw_score":round(raw,4) if raw is not None else None,
                "normalized_score":round(calibrated,4) if calibrated is not None else None,
                "criteria":{key:round(value,3) for key,value in item["calibrated"].items()},
            })
        results.sort(key=lambda item:(item["normalized_score"] is not None,
                                     item["normalized_score"] or -1),reverse=True)
        return {"results":results,"normalization":proof}

    def export_event(self,db,event_id):
        return {
            "format":"fieldnote-event-export-v1","exported_at":iso(),
            "event":event_dict(db.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()),
            "teams":[dict(r) for r in db.execute("SELECT * FROM teams WHERE event_id=? ORDER BY id",(event_id,))],
            "memberships":[dict(r) for r in db.execute(
                "SELECT m.team_id,m.user_id,m.joined_at FROM team_members m JOIN teams t ON t.id=m.team_id WHERE t.event_id=? ORDER BY m.team_id,m.user_id",
                (event_id,))],
            "projects":[dict(r) for r in db.execute("SELECT * FROM projects WHERE event_id=? ORDER BY id",(event_id,))],
            "assignments":[dict(r) for r in db.execute("SELECT * FROM assignments WHERE event_id=? ORDER BY id",(event_id,))],
            "scores":[dict(r) for r in db.execute(
                "SELECT s.* FROM scores s JOIN assignments a ON a.id=s.assignment_id WHERE a.event_id=? ORDER BY s.id",
                (event_id,))],
            "comments":[dict(r) for r in db.execute("SELECT * FROM comments WHERE event_id=? ORDER BY id",(event_id,))],
            "votes":[dict(r) for r in db.execute("SELECT * FROM votes WHERE event_id=? ORDER BY id",(event_id,))],
        }

    def get(self,db,path):
        static={"/style.css":"text/css; charset=utf-8","/app.js":"text/javascript; charset=utf-8",
                "/favicon.svg":"image/svg+xml"}
        if path in static:
            filenames={"/style.css":"style.css","/app.js":"app.js","/favicon.svg":"favicon.svg"}
            try: content=(ROOT/"web"/filenames[path]).read_bytes()
            except OSError: raise HttpError(404,"Asset not found.","not_found")
            self.bytes_out(200,content,static[path]);return
        if path in ("/","/projects","/projects/new","/login","/app","/embed") or path.startswith("/invite/"):
            self.serve_app(db,path=="/embed")
            return
        if path=="/widget.js":
            script=("""(function(){var s=document.currentScript,u=new URL('/embed',s.src);
            var f=document.createElement('iframe');f.src=u.href;f.title='Hackathon project gallery';
            f.loading='lazy';f.style.cssText='width:100%;min-height:520px;border:0;border-radius:16px';
            s.parentNode.insertBefore(f,s.nextSibling)})();""")
            self.bytes_out(200,script.encode(),"text/javascript; charset=utf-8"); return
        if path=="/api/health":
            self.json_out(200,{"status":"ok","service":"fieldnote","time":iso()}); return
        if path=="/api/session":
            actor=self.actor(db)
            self.json_out(200,{"user":dict(actor) if actor else None}); return
        if path=="/api/bootstrap":
            event=self.event(db); actor=self.actor(db)
            voter=self.token("voter")
            self.json_out(200,{
                "event":event_dict(event),
                "user":{k:actor[k] for k in ("id","name","email","role")} if actor else None,
                "projects":self.public_projects(db,event["id"],self.query,digest(voter) if voter else None),
                "tracks":json.loads(event["tracks_json"]),
                "events":[{"id":r["id"],"name":r["name"]} for r in db.execute(
                    "SELECT id,name FROM events ORDER BY created_at")],
                "metrics":self.progress(db,event["id"]) if actor and actor["role"] in ("organizer","admin") else {},
            }); return
        if path=="/api/events":
            self.json_out(200,{"events":[dict(r) for r in db.execute(
                "SELECT id,name,slug,submissions_close,voting_mode,results_published FROM events ORDER BY created_at")]})
            return
        if path=="/api/projects":
            event=self.event(db); voter=self.token("voter")
            self.json_out(200,{"projects":self.public_projects(
                db,event["id"],self.query,digest(voter) if voter else None)}); return
        if path=="/api/my/projects":
            actor=self.require(db,"participant")
            rows=db.execute(
                """SELECT p.* FROM projects p JOIN team_members m ON m.team_id=p.team_id
                   WHERE p.event_id=? AND m.user_id=? ORDER BY p.updated_at DESC""",
                (self.event(db)["id"],actor["id"])).fetchall()
            self.json_out(200,{"projects":[{**dict(r),"gallery":json.loads(r["gallery_json"]),
                "tech_tags":json.loads(r["tech_tags_json"]),"answers":json.loads(r["answers_json"])}
                for r in rows]});return
        if path=="/api/my/teams":
            actor=self.require(db,"participant")
            rows=db.execute(
                """SELECT t.id,t.name,t.event_id,COUNT(m2.user_id) member_count FROM teams t
                   JOIN team_members m ON m.team_id=t.id LEFT JOIN team_members m2 ON m2.team_id=t.id
                   WHERE t.event_id=? AND m.user_id=? GROUP BY t.id ORDER BY t.created_at""",
                (self.event(db)["id"],actor["id"]))
            self.json_out(200,{"teams":[dict(row) for row in rows]});return
        match=re.fullmatch(r"/api/projects/([A-Za-z0-9_-]+)",path)
        if match:
            row=db.execute(
                """SELECT p.*,t.name team_name FROM projects p JOIN teams t ON t.id=p.team_id
                   WHERE p.id=? AND p.status='submitted'""",(match.group(1),)).fetchone()
            if not row: raise HttpError(404,"Project not found.","not_found")
            data=dict(row)
            for column in ("gallery_json","tech_tags_json","answers_json"):
                data[column[:-5]]=json.loads(data.pop(column) or ("{}" if column=="answers_json" else "[]"))
            data.pop("answers",None)
            event=db.execute("SELECT * FROM events WHERE id=?",(row["event_id"],)).fetchone()
            data["track"]=next((t["name"] for t in json.loads(event["tracks_json"])
                                if t["id"]==row["track_id"]),"General")
            data["comments"]=[dict(item) for item in db.execute(
                """SELECT c.id,c.body,c.created_at,u.name author FROM comments c JOIN users u ON u.id=c.user_id
                   WHERE c.project_id=? ORDER BY c.created_at DESC LIMIT 50""",(row["id"],))]
            self.json_out(200,{"project":data}); return
        if path=="/api/judge/assignments":
            actor=self.require(db,"judge","organizer","admin")
            sql="""SELECT a.id assignment_id,a.batch,a.assigned_at,p.id,p.title,p.tagline,p.description,
                   p.track_id,p.repo_url,p.live_url,p.demo_url,p.tech_tags_json,p.submitted_at,
                   t.name team_name,s.criteria_json,s.comment,s.updated_at score_updated_at
                   FROM assignments a JOIN projects p ON p.id=a.project_id JOIN teams t ON t.id=p.team_id
                   LEFT JOIN scores s ON s.assignment_id=a.id WHERE a.event_id=?"""
            params=[self.event(db)["id"]]
            if actor["role"]=="judge":
                sql+=" AND a.judge_id=?";params.append(actor["id"])
            rows=db.execute(sql+" ORDER BY a.assigned_at,p.title",params)
            result=[]
            for row in rows:
                item=dict(row)
                item["tech_tags"]=json.loads(item.pop("tech_tags_json") or "[]")
                item["criteria"]=json.loads(item.pop("criteria_json") or "{}")
                result.append(item)
            self.json_out(200,{"assignments":result});return
        if path=="/api/judge/scores":
            actor=self.require(db,"judge","organizer","admin")
            requested=(self.query.get("judge") or [""])[0]
            if actor["role"]=="judge" and requested and requested!=actor["id"]:
                raise HttpError(403,"Judges can only read their own ballots.","peer_ballot_forbidden")
            judge_id=actor["id"] if actor["role"]=="judge" else (requested or actor["id"])
            rows=db.execute(
                """SELECT a.project_id,a.judge_id,s.criteria_json,s.comment,s.updated_at,p.track_id,p.title
                   FROM assignments a JOIN projects p ON p.id=a.project_id
                   LEFT JOIN scores s ON s.assignment_id=a.id
                   WHERE a.event_id=? AND a.judge_id=? ORDER BY p.title""",
                (self.event(db)["id"],judge_id)).fetchall()
            self.json_out(200,{"scores":[{**dict(r),"criteria":json.loads(r["criteria_json"] or "{}")}
                                           for r in rows]});return
        if path=="/api/voting/ballot":
            event=self.event(db);actor=self.actor(db)
            mode=event["voting_mode"]
            if mode in ("email","authenticated") and not actor:
                raise HttpError(401,"Sign in with an email account to vote.","authentication_required")
            self.voting_window(event)
            token=self.token("voter");headers={}
            if not token:
                token=secrets.token_urlsafe(24)
                headers["Set-Cookie"]="voter={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(token,365*86400)
            voter_hash=digest("account:"+actor["id"]) if actor else digest(token)
            projects=self.public_projects(db,event["id"],{},voter_hash)
            projects.sort(key=lambda p:digest(event["id"]+":"+voter_hash+":"+p["id"]))
            spent=db.execute("SELECT COALESCE(SUM(credits*credits),0) n FROM votes WHERE event_id=? AND voter_hash=?",
                             (event["id"],voter_hash)).fetchone()["n"]
            self.json_out(200,{"projects":projects,"credits_total":16,"credits_spent":spent},headers);return
        if path=="/api/results":
            event=self.event(db)
            if not event["results_published"]:
                raise HttpError(403,"Results are private until the organizer publishes them.","results_private")
            result=self.result_data(db,event["id"])
            totals={r["project_id"]:r["credits"] for r in db.execute(
                "SELECT project_id,SUM(credits) credits FROM votes WHERE event_id=? GROUP BY project_id",
                (event["id"],))}
            for item in result["results"]:
                item["community_credits"]=totals.get(item["id"],0)
            self.json_out(200,result);return
        if path=="/api/organizer/progress":
            self.require(db,"organizer","admin")
            self.json_out(200,self.progress(db,self.event(db)["id"]));return
        if path=="/api/organizer/judges":
            self.require(db,"organizer","admin")
            judges=[]
            for row in db.execute("SELECT id,name,email FROM users WHERE role='judge' ORDER BY name"):
                scopes=[item["track_id"] for item in db.execute(
                    "SELECT track_id FROM judge_tracks WHERE judge_id=? ORDER BY track_id",(row["id"],))]
                assigned=db.execute("SELECT COUNT(*) n FROM assignments WHERE judge_id=? AND event_id=?",
                                    (row["id"],self.event(db)["id"])).fetchone()["n"]
                judges.append({**dict(row),"tracks":scopes,"assigned":assigned})
            self.json_out(200,{"judges":judges});return
        if path=="/api/organizer/results":
            self.require(db,"organizer","admin")
            self.json_out(200,self.result_data(db,self.event(db)["id"]));return
        if path=="/api/audit":
            self.require(db,"organizer","admin")
            rows=db.execute(
                """SELECT sequence,actor_id,action,entity_type,entity_id,payload_json,
                   previous_hash,entry_hash,created_at FROM audit_log WHERE event_id=?
                   ORDER BY sequence DESC LIMIT 250""",(self.event(db)["id"],)).fetchall()
            self.json_out(200,{"entries":[{**dict(r),"payload":json.loads(r["payload_json"])} for r in rows]});return
        if path=="/api/export.csv":
            actor=self.require(db,"organizer","admin");event=self.event(db)
            kind=(self.query.get("kind") or ["scores"])[0]
            output=io.StringIO(newline="");writer=csv.writer(output)
            if kind=="projects":
                writer.writerow(["project_id","title","team","track","submitted_at","repository"])
                rows=db.execute(
                    """SELECT p.id,p.title,t.name,p.track_id,p.submitted_at,p.repo_url FROM projects p
                       JOIN teams t ON t.id=p.team_id WHERE p.event_id=? ORDER BY p.title""",(event["id"],))
            elif kind=="votes":
                writer.writerow(["project_id","credits","created_at"])
                rows=db.execute("SELECT project_id,credits,created_at FROM votes WHERE event_id=? ORDER BY created_at",
                                (event["id"],))
            elif kind=="audit":
                writer.writerow(["sequence","actor_id","action","entity_type","entity_id","created_at","entry_hash"])
                rows=db.execute(
                    """SELECT sequence,actor_id,action,entity_type,entity_id,created_at,entry_hash
                       FROM audit_log WHERE event_id=? ORDER BY sequence""",(event["id"],))
            elif kind=="assignments":
                writer.writerow(["project_id","project_title","team","track_id","judge_id","batch","assigned_at","score_submitted"])
                rows=db.execute(
                    """SELECT p.id,p.title,t.name,p.track_id,a.judge_id,a.batch,a.assigned_at,
                       CASE WHEN s.id IS NULL THEN 'no' ELSE 'yes' END FROM assignments a
                       JOIN projects p ON p.id=a.project_id JOIN teams t ON t.id=p.team_id
                       LEFT JOIN scores s ON s.assignment_id=a.id WHERE a.event_id=? ORDER BY p.title,a.judge_id""",
                    (event["id"],))
            elif kind=="results":
                writer.writerow(["rank","project_id","title","track_id","raw_mean","normalized_weighted_score","review_count"])
                results=self.result_data(db,event["id"])["results"]
                for rank,item in enumerate(results,1):
                    writer.writerow([rank,item["id"],item["title"],item["track_id"],
                                     item["raw_score"],item["normalized_score"],item["review_count"]])
                audit(db,event["id"],actor["id"],"export.csv","event",event["id"],{"kind":kind})
                self.bytes_out(200,output.getvalue().encode("utf-8-sig"),"text/csv; charset=utf-8",
                               {"Content-Disposition":'attachment; filename="fieldnote-results.csv"'})
                return
            else:
                writer.writerow(["project_id","project_title","judge_id","criteria_json","comment","updated_at"])
                rows=db.execute(
                    """SELECT p.id,p.title,a.judge_id,s.criteria_json,s.comment,s.updated_at FROM scores s
                       JOIN assignments a ON a.id=s.assignment_id JOIN projects p ON p.id=a.project_id
                       WHERE p.event_id=? ORDER BY p.title,a.judge_id""",(event["id"],))
            for row in rows: writer.writerow(list(row))
            audit(db,event["id"],actor["id"],"export.csv","event",event["id"],{"kind":kind})
            self.bytes_out(200,output.getvalue().encode("utf-8-sig"),"text/csv; charset=utf-8",
                           {"Content-Disposition":'attachment; filename="fieldnote-{}.csv"'.format(kind)})
            return
        if path=="/api/export.json":
            actor=self.require(db,"organizer","admin");event=self.event(db)
            document=self.export_event(db,event["id"])
            audit(db,event["id"],actor["id"],"export.json","event",event["id"],{})
            self.json_out(200,document,{"Content-Disposition":'attachment; filename="fieldnote-export.json"'});return
        match=re.fullmatch(r"/api/certificates/([A-Za-z0-9_-]+)",path)
        if match:
            judge=db.execute("SELECT id,name,role FROM users WHERE id=?",(match.group(1),)).fetchone()
            if not judge or judge["role"]!="judge": raise HttpError(404,"Judge record not found.","not_found")
            count=db.execute(
                """SELECT COUNT(*) n FROM scores s JOIN assignments a ON a.id=s.assignment_id
                   WHERE a.judge_id=?""",(judge["id"],)).fetchone()["n"]
            if not count: raise HttpError(404,"No completed judging record exists yet.","not_found")
            event=self.event(db)
            record={"issuer":"Fieldnote","event_id":event["id"],"judge_id":judge["id"],
                    "judge_name":judge["name"],"reviews_submitted":count,"record_type":"judge-participation"}
            key=bytes.fromhex(db.execute("SELECT value FROM meta WHERE key='certificate_secret'").fetchone()["value"])
            signature=hmac.new(key,canonical(record).encode(),hashlib.sha256).hexdigest()
            self.json_out(200,{"record":record,"signature":signature,"algorithm":"HMAC-SHA256"});return
        if path=="/api/verify/audit":
            rows=db.execute("SELECT * FROM audit_log ORDER BY sequence").fetchall()
            previous="GENESIS"
            for row in rows:
                material="|".join([previous,row["event_id"] or "",row["actor_id"] or "",
                    row["action"],row["entity_type"],row["entity_id"],row["payload_json"],row["created_at"]])
                expected=digest(material)
                if expected!=row["entry_hash"] or row["previous_hash"]!=previous:
                    self.json_out(200,{"valid":False,"broken_at":row["sequence"]});return
                previous=expected
            self.json_out(200,{"valid":True,"entries":len(rows),"head":previous});return
        match=re.fullmatch(r"/api/verify/certificate/([A-Za-z0-9_-]+)",path)
        if match:
            signature=(self.query.get("signature") or [""])[0]
            certificate=self.get_certificate(db,match.group(1))
            valid=hmac.compare_digest(signature,certificate["signature"])
            self.json_out(200,{"valid":valid,"record":certificate["record"] if valid else None});return
        match=re.fullmatch(r"/invite/([A-Za-z0-9_-]+)",path)
        if match:
            self.serve_app(db);return
        if path=="/openapi.json":
            self.bytes_out(200,(ROOT/"openapi.json").read_bytes(),"application/json; charset=utf-8");return
        if path.startswith("/api/"): raise HttpError(404,"No API route matches this path.","not_found")
        raise HttpError(404,"This page does not exist.","not_found")

    def mutate(self,db,path):
        if path=="/api/auth/register" and self.command=="POST":
            body=self.read_json()
            email=text(body.get("email"),254).lower()
            name=text(body.get("name"),100)
            password=body.get("password") if isinstance(body.get("password"),str) else ""
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) or len(name)<2 or len(password)<10:
                raise HttpError(400,"Enter a name, valid email and password of at least 10 characters.","invalid_registration")
            user_id="usr_"+secrets.token_hex(10)
            db.execute("INSERT INTO users(id,email,name,role,password_hash,created_at) VALUES(?,?,?,?,?,?)",
                       (user_id,email,name,"participant",hash_password(password),iso()))
            token=secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
                       (digest(token),user_id,iso(now()+timedelta(days=SESSION_DAYS)),iso()))
            audit(db,self.event(db)["id"],user_id,"auth.registered","user",user_id,{})
            self.json_out(201,{"user":{"id":user_id,"name":name,"email":email,"role":"participant"}},
                          {"Set-Cookie":"session={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(
                              token,SESSION_DAYS*86400)})
            return
        if path=="/api/auth/login" and self.command=="POST":
            body=self.read_json()
            email=text(body.get("email"),254).lower()
            password=body.get("password") if isinstance(body.get("password"),str) else ""
            if not self.rate_limit("login:"+self.client_address[0],20,300):
                raise HttpError(429,"Too many sign-in attempts. Try again in five minutes.","rate_limited")
            user=db.execute("SELECT * FROM users WHERE email=? AND active=1",(email,)).fetchone()
            if not user or not password_matches(password,user["password_hash"]):
                raise HttpError(401,"Email or password is incorrect.","invalid_credentials")
            token=secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
                       (digest(token),user["id"],iso(now()+timedelta(days=SESSION_DAYS)),iso()))
            audit(db,self.event(db)["id"],user["id"],"auth.login","user",user["id"],{})
            self.json_out(200,{"user":{"id":user["id"],"name":user["name"],
                                      "email":user["email"],"role":user["role"]}},
                          {"Set-Cookie":"session={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(
                              token,SESSION_DAYS*86400)})
            return
        if path=="/api/auth/logout" and self.command=="POST":
            token=self.token();actor=self.actor(db)
            if token: db.execute("DELETE FROM sessions WHERE token_hash=?",(digest(token),))
            if actor: audit(db,self.event(db)["id"],actor["id"],"auth.logout","user",actor["id"],{})
            self.json_out(200,{"ok":True},{"Set-Cookie":"session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"})
            return
        if path=="/api/events/select" and self.command=="POST":
            actor=self.require(db,"organizer","admin")
            event_id=text(self.read_json().get("event_id"),80)
            if not db.execute("SELECT 1 FROM events WHERE id=?",(event_id,)).fetchone():
                raise HttpError(404,"Event not found.","not_found")
            db.execute("INSERT INTO meta(key,value) VALUES('active_event_id',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",(event_id,))
            audit(db,event_id,actor["id"],"event.selected","event",event_id,{})
            self.json_out(200,{"ok":True,"event_id":event_id});return
        if path=="/api/projects/new" and self.command=="POST":
            self.create_project(db);return
        if path=="/projects/new" and self.command=="POST":
            event=self.event(db);closes=parse_time(event["submissions_close"])
            if closes and now()>=closes:
                raise HttpError(409,"The submission window is closed.","submissions_closed")
            self.create_project(db);return
        if path=="/api/projects" and self.command=="POST":
            self.create_project(db);return
        match=re.fullmatch(r"/api/projects/([A-Za-z0-9_-]+)",path)
        if match and self.command in ("PUT","PATCH"):
            actor=self.require(db,"participant")
            project=db.execute("SELECT * FROM projects WHERE id=?",(match.group(1),)).fetchone()
            if not project: raise HttpError(404,"Project not found.","not_found")
            if not db.execute("SELECT 1 FROM team_members WHERE team_id=? AND user_id=?",
                              (project["team_id"],actor["id"])).fetchone():
                raise HttpError(403,"Only a project teammate can edit this entry.","project_owner_required")
            event=self.event(db);closes=parse_time(event["submissions_close"])
            if closes and now()>=closes: raise HttpError(409,"The submission window is closed.","submissions_closed")
            self.save_project(db,actor,self.read_json(),project);return
        if path=="/api/judge/scores" and self.command in ("POST","PUT"):
            actor=self.require(db,"judge")
            body=self.read_json();project_id=text(body.get("project_id"),80)
            assignment=db.execute(
                """SELECT a.* FROM assignments a JOIN projects p ON p.id=a.project_id
                   WHERE a.project_id=? AND a.judge_id=? AND p.event_id=?""",
                (project_id,actor["id"],self.event(db)["id"])).fetchone()
            if not assignment: raise HttpError(403,"This project is not in your judging batch.","assignment_required")
            project=db.execute("SELECT track_id FROM projects WHERE id=?",(project_id,)).fetchone()
            if not db.execute("SELECT 1 FROM judge_tracks WHERE judge_id=? AND track_id=?",
                              (actor["id"],project["track_id"])).fetchone():
                raise HttpError(403,"You are not assigned to this track.","track_forbidden")
            rubric=json.loads(self.event(db)["rubric_json"])
            incoming=body.get("criteria")
            if not isinstance(incoming,dict): raise HttpError(400,"Scores must match the event rubric.","invalid_score")
            scores={}
            for item in rubric:
                value=incoming.get(item["key"])
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not 1<=value<=5:
                    raise HttpError(400,"Every criterion must have a score from 1 to 5.","invalid_score")
                scores[item["key"]]=float(value)
            comment=text(body.get("comment"),2000);stamp=iso()
            existing=db.execute("SELECT id FROM scores WHERE assignment_id=?",(assignment["id"],)).fetchone()
            if existing:
                score_id=existing["id"]
                db.execute("UPDATE scores SET criteria_json=?,comment=?,updated_at=? WHERE assignment_id=?",
                           (canonical(scores),comment,stamp,assignment["id"]))
            else:
                score_id="scr_"+secrets.token_hex(9)
                db.execute("INSERT INTO scores VALUES(?,?,?,?,?,?)",
                           (score_id,assignment["id"],canonical(scores),comment,stamp,stamp))
            audit(db,assignment["event_id"],actor["id"],"score.submitted","score",score_id,
                  {"project_id":project_id,"criteria":scores})
            self.json_out(200,{"ok":True,"score_id":score_id,"updated_at":stamp});return
        if path=="/api/events" and self.command=="POST":
            self.create_event(db);return
        if path=="/api/judges" and self.command=="POST":
            self.create_judge(db);return
        match=re.fullmatch(r"/api/events/([A-Za-z0-9_-]+)",path)
        if match and self.command in ("PATCH","PUT"):
            self.update_event(db,match.group(1));return
        if path=="/api/organizer/assignments/auto" and self.command=="POST":
            self.auto_assign(db);return
        if path=="/api/results/publish" and self.command=="POST":
            actor=self.require(db,"organizer","admin");event=self.event(db)
            opened,closed=parse_time(event["voting_open"]),parse_time(event["voting_close"])
            if opened and closed and opened<=now()<closed:
                raise HttpError(409,"Results stay private until community voting closes.","voting_in_progress")
            db.execute("UPDATE events SET results_published=1 WHERE id=?",(event["id"],))
            audit(db,event["id"],actor["id"],"results.published","event",event["id"],{})
            self.json_out(200,{"ok":True});return
        if path=="/api/voting/settings" and self.command=="PATCH":
            actor=self.require(db,"organizer","admin")
            mode=text(self.read_json().get("mode"),20)
            if mode not in ("open","email","authenticated"):
                raise HttpError(400,"Voting mode must be open, email, or authenticated.","invalid_settings")
            event=self.event(db)
            db.execute("UPDATE events SET voting_mode=? WHERE id=?",(mode,event["id"]))
            audit(db,event["id"],actor["id"],"voting.configured","event",event["id"],{"mode":mode})
            self.json_out(200,{"mode":mode});return
        if path=="/api/votes" and self.command=="POST":
            self.cast_vote(db);return
        if path=="/api/comments" and self.command=="POST":
            self.add_comment(db);return
        if path=="/api/teams" and self.command=="POST":
            actor=self.require(db,"participant");name=text(self.read_json().get("name"),100)
            if len(name)<2: raise HttpError(400,"Team name must contain at least two characters.","invalid_team")
            event=self.event(db);team_id="tm_"+secrets.token_hex(8);invite_code=secrets.token_urlsafe(12)
            db.execute("INSERT INTO teams VALUES(?,?,?,?,?)",(team_id,event["id"],name,invite_code,iso()))
            db.execute("INSERT INTO team_members VALUES(?,?,?)",(team_id,actor["id"],iso()))
            audit(db,event["id"],actor["id"],"team.created","team",team_id,{"name":name})
            self.json_out(201,{"team":{"id":team_id,"name":name},"invite_code":invite_code});return
        match=re.fullmatch(r"/api/teams/([A-Za-z0-9_-]+)/invites",path)
        if match and self.command=="POST":
            actor=self.require(db,"participant")
            if not db.execute("SELECT 1 FROM team_members WHERE team_id=? AND user_id=?",
                              (match.group(1),actor["id"])).fetchone():
                raise HttpError(403,"Only a team member can invite teammates.","team_member_required")
            email=text(self.read_json().get("email"),254).lower()
            if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email):
                raise HttpError(400,"Enter a valid email address.","invalid_email")
            token=secrets.token_urlsafe(24)
            db.execute("INSERT INTO invites VALUES(?,?,?,?,NULL,?)",
                       (digest(token),match.group(1),email or None,iso(now()+timedelta(days=7)),iso()))
            audit(db,self.event(db)["id"],actor["id"],"team.invite_created","team",match.group(1),{"email":email})
            self.json_out(201,{"invite_url":"/invite/"+token,"expires_in_days":7});return
        match=re.fullmatch(r"/api/invites/([A-Za-z0-9_-]+)/accept",path)
        if match and self.command=="POST":
            actor=self.require(db,"participant")
            invite=db.execute("SELECT * FROM invites WHERE token_hash=?",(digest(match.group(1)),)).fetchone()
            if not invite or invite["used_at"] or parse_time(invite["expires_at"])<now():
                raise HttpError(404,"Invitation is expired or already used.","invite_unavailable")
            if invite["invited_email"] and invite["invited_email"].lower()!=actor["email"].lower():
                raise HttpError(403,"Sign in with the invited email address.","invite_email_mismatch")
            db.execute("INSERT OR IGNORE INTO team_members VALUES(?,?,?)",(invite["team_id"],actor["id"],iso()))
            db.execute("UPDATE invites SET used_at=? WHERE token_hash=?",(iso(),invite["token_hash"]))
            audit(db,self.event(db)["id"],actor["id"],"team.invite_accepted","team",invite["team_id"],{})
            self.json_out(200,{"ok":True,"team_id":invite["team_id"]});return
        if path=="/api/export/import" and self.command=="POST":
            self.import_event(db);return
        if path=="/api/webhooks" and self.command=="POST":
            raise HttpError(501,"Webhook delivery is not enabled in this build.","not_implemented")
        raise HttpError(404,"No action matches this path.","not_found")

    def save_project(self,db,actor,body,existing=None):
        event=self.event(db);tracks=json.loads(event["tracks_json"])
        membership=(existing["team_id"] if existing else None)
        if not membership:
            team=db.execute(
                """SELECT t.id FROM team_members m JOIN teams t ON t.id=m.team_id
                   WHERE m.user_id=? AND t.event_id=? ORDER BY m.joined_at LIMIT 1""",
                (actor["id"],event["id"])).fetchone()
            if not team: raise HttpError(403,"Join or create a team before submitting.","team_required")
            membership=team["id"]
        title=text(body.get("title",existing["title"] if existing else body.get("name","")),120)
        if len(title)<3: raise HttpError(400,"Project name must contain at least three characters.","invalid_project")
        track_id=text(body.get("track_id",body.get("track",existing["track_id"] if existing else "")),80)
        if track_id not in {track["id"] for track in tracks}:
            raise HttpError(400,"Choose a track from this event.","invalid_track")
        tags=body.get("tech_tags",body.get("tags",json.loads(existing["tech_tags_json"]) if existing else []))
        if isinstance(tags,str): tags=[item.strip() for item in tags.split(",")]
        if not isinstance(tags,list) or len(tags)>20: raise HttpError(400,"Use up to 20 tech tags.","invalid_tags")
        tags=[text(tag,40) for tag in tags if text(tag,40)]
        gallery=body.get("gallery",json.loads(existing["gallery_json"]) if existing else [])
        if not isinstance(gallery,list) or len(gallery)>12: raise HttpError(400,"Use up to 12 image URLs.","invalid_gallery")
        gallery=[safe_url(url) for url in gallery if text(url,1000)]
        answers=body.get("answers",json.loads(existing["answers_json"]) if existing else {})
        if not isinstance(answers,dict): answers={}
        for question in json.loads(event["questions_json"]):
            if question.get("required") and not text(answers.get(question.get("key")),1000):
                raise HttpError(400,"Answer the required question: "+text(question.get("label"),100),"required_answer")
        status="draft" if body.get("draft") or body.get("status")=="draft" else "submitted"
        stamp=iso();project_id=existing["id"] if existing else "prj_"+secrets.token_hex(8)
        values=(
            track_id,title,text(body.get("tagline",existing["tagline"] if existing else ""),200),
            text(body.get("description",existing["description"] if existing else ""),8000),
            safe_url(body.get("thumbnail_url",existing["thumbnail_url"] if existing else "")) if
                body.get("thumbnail_url",existing["thumbnail_url"] if existing else "") else "",
            canonical(gallery),
            safe_url(body.get("demo_url",existing["demo_url"] if existing else "")) if
                body.get("demo_url",existing["demo_url"] if existing else "") else "",
            safe_url(body.get("repo_url",existing["repo_url"] if existing else "")) if
                body.get("repo_url",existing["repo_url"] if existing else "") else "",
            safe_url(body.get("live_url",existing["live_url"] if existing else "")) if
                body.get("live_url",existing["live_url"] if existing else "") else "",
            canonical(tags),canonical(answers),stamp,status)
        if existing:
            db.execute(
                """UPDATE projects SET track_id=?,title=?,tagline=?,description=?,thumbnail_url=?,
                   gallery_json=?,demo_url=?,repo_url=?,live_url=?,tech_tags_json=?,answers_json=?,
                   updated_at=?,status=? WHERE id=?""",values+(project_id,))
            action="project.updated"
        else:
            db.execute(
                """INSERT INTO projects(id,event_id,team_id,track_id,title,tagline,description,thumbnail_url,
                   gallery_json,demo_url,repo_url,live_url,tech_tags_json,answers_json,submitted_at,updated_at,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (project_id,event["id"],membership)+values[:11]+(stamp,stamp,status))
            action="project.created"
        audit(db,event["id"],actor["id"],action,"project",project_id,{"title":title,"track_id":track_id,"status":status})
        self.json_out(200 if existing else 201,{"project":{"id":project_id,"title":title,"status":status}})

    def create_project(self,db):
        actor=self.require(db,"participant")
        event=self.event(db);closes=parse_time(event["submissions_close"]);opens=parse_time(event["opens_at"])
        if closes and now()>=closes: raise HttpError(409,"The submission window is closed.","submissions_closed")
        if opens and now()<opens: raise HttpError(409,"The submission window has not opened.","submissions_not_open")
        body=self.read_json()
        self.save_project(db,actor,body)

    def create_event(self,db):
        actor=self.require(db,"organizer","admin");body=self.read_json()
        name=text(body.get("name"),150);opens=text(body.get("opens_at"),50) or iso()
        closes=text(body.get("submissions_close"),50)
        if len(name)<3: raise HttpError(400,"Event name must contain at least three characters.","invalid_event")
        if not parse_time(opens) or not parse_time(closes) or parse_time(closes)<=parse_time(opens):
            raise HttpError(400,"Use valid dates and a close date after opening.","invalid_dates")
        tracks_in=body.get("tracks",[])
        if isinstance(tracks_in,str): tracks_in=[line.strip() for line in tracks_in.splitlines() if line.strip()]
        if not isinstance(tracks_in,list) or not tracks_in: raise HttpError(400,"Add at least one track.","invalid_tracks")
        tracks=[]
        for track in tracks_in[:32]:
            if isinstance(track,str): tracks.append({"id":"trk_"+secrets.token_hex(4),"name":text(track,80)})
            elif isinstance(track,dict): tracks.append({"id":text(track.get("id"),80) or "trk_"+secrets.token_hex(4),
                                                         "name":text(track.get("name"),80)})
        rubric=self.validate_rubric(body.get("rubric",CRITERIA));event_id="evt_"+secrets.token_hex(8)
        slug=(re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")[:55] or "event")+"-"+event_id[-4:]
        db.execute(
            """INSERT INTO events(id,name,slug,description,opens_at,submissions_close,judging_close,
               voting_open,voting_close,voting_mode,tracks_json,prizes_json,rubric_json,questions_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id,name,slug,text(body.get("description"),3000),opens,closes,
             text(body.get("judging_close"),50) or None,text(body.get("voting_open"),50) or None,
             text(body.get("voting_close"),50) or None,text(body.get("voting_mode"),20) or "authenticated",
             canonical(tracks),canonical(body.get("prizes",[])),canonical(rubric),
             canonical(body.get("questions",[])),iso()))
        db.execute("INSERT INTO meta(key,value) VALUES('active_event_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (event_id,))
        audit(db,event_id,actor["id"],"event.created","event",event_id,{"name":name})
        self.json_out(201,{"event":event_dict(db.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone())})

    def create_judge(self,db):
        actor=self.require(db,"organizer","admin");body=self.read_json()
        email=text(body.get("email"),254).lower();name=text(body.get("name"),100)
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) or len(name)<2:
            raise HttpError(400,"Add a name and valid email address.","invalid_judge")
        event=self.event(db);scope=body.get("tracks",[])
        valid_tracks={item["id"] for item in json.loads(event["tracks_json"])}
        if not isinstance(scope,list) or not scope or any(track not in valid_tracks for track in scope):
            raise HttpError(400,"Choose one or more tracks from this event.","invalid_judge_tracks")
        judge_id="jdg_"+secrets.token_hex(8);temporary=secrets.token_urlsafe(12)
        db.execute("INSERT INTO users(id,email,name,role,password_hash,created_at) VALUES(?,?,?,?,?,?)",
                   (judge_id,email,name,"judge",hash_password(temporary),iso()))
        for track_id in set(scope):
            db.execute("INSERT INTO judge_tracks VALUES(?,?)",(judge_id,track_id))
        audit(db,event["id"],actor["id"],"judge.invited","user",judge_id,
              {"email":email,"tracks":sorted(set(scope))})
        self.json_out(201,{"judge":{"id":judge_id,"name":name,"email":email,"tracks":sorted(set(scope))},
                           "temporary_password":temporary})

    def validate_rubric(self,incoming):
        if not isinstance(incoming,list) or not 2<=len(incoming)<=12:
            raise HttpError(400,"A rubric needs between 2 and 12 criteria.","invalid_rubric")
        rubric=[]
        for item in incoming:
            if not isinstance(item,dict): raise HttpError(400,"Rubric criteria must be objects.","invalid_rubric")
            key=re.sub(r"[^a-z0-9_]+","_",text(item.get("key"),50).lower()).strip("_")
            label=text(item.get("label"),100)
            try: weight=float(item.get("weight"))
            except (ValueError,TypeError): weight=0
            if not key or not label or weight<=0: raise HttpError(400,"Each criterion needs a key, label and positive weight.","invalid_rubric")
            rubric.append({"key":key,"label":label,"weight":weight})
        if len({x["key"] for x in rubric})!=len(rubric): raise HttpError(400,"Criterion keys must be unique.","invalid_rubric")
        total=sum(x["weight"] for x in rubric)
        for item in rubric: item["weight"]=round(item["weight"]/total,6)
        return rubric

    def update_event(self,db,event_id):
        actor=self.require(db,"organizer","admin");event=db.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
        if not event: raise HttpError(404,"Event not found.","not_found")
        body=self.read_json()
        fields={
            "name":text(body.get("name",event["name"]),150),
            "description":text(body.get("description",event["description"]),3000),
            "opens_at":text(body.get("opens_at",event["opens_at"]),50),
            "submissions_close":text(body.get("submissions_close",event["submissions_close"]),50),
            "judging_close":text(body.get("judging_close",event["judging_close"]),50) or None,
            "voting_open":text(body.get("voting_open",event["voting_open"]),50) or None,
            "voting_close":text(body.get("voting_close",event["voting_close"]),50) or None,
            "voting_mode":text(body.get("voting_mode",event["voting_mode"]),20),
        }
        if not parse_time(fields["opens_at"]) or not parse_time(fields["submissions_close"]) or \
           parse_time(fields["submissions_close"])<=parse_time(fields["opens_at"]):
            raise HttpError(400,"Use valid event dates with closing after opening.","invalid_dates")
        if fields["voting_mode"] not in ("open","email","authenticated"):
            raise HttpError(400,"Voting mode must be open, email, or authenticated.","invalid_settings")
        tracks=event["tracks_json"]
        if isinstance(body.get("tracks"),list):
            checked=[]
            for item in body["tracks"]:
                if not isinstance(item,dict) or not text(item.get("id"),80) or not text(item.get("name"),80):
                    raise HttpError(400,"Each track needs an id and a name.","invalid_tracks")
                checked.append({"id":text(item["id"],80),"name":text(item["name"],80)})
            if not checked: raise HttpError(400,"An event needs at least one track.","invalid_tracks")
            tracks=canonical(checked)
        prizes=canonical(body["prizes"]) if isinstance(body.get("prizes"),list) else event["prizes_json"]
        questions=canonical(body["questions"]) if isinstance(body.get("questions"),list) else event["questions_json"]
        rubric=canonical(self.validate_rubric(body["rubric"])) if isinstance(body.get("rubric"),list) else event["rubric_json"]
        db.execute(
            """UPDATE events SET name=?,description=?,opens_at=?,submissions_close=?,judging_close=?,
               voting_open=?,voting_close=?,voting_mode=?,tracks_json=?,prizes_json=?,questions_json=?,
               rubric_json=? WHERE id=?""",
            (*fields.values(),tracks,prizes,questions,rubric,event_id))
        audit(db,event_id,actor["id"],"event.updated","event",event_id,{"fields":sorted(body)})
        self.json_out(200,{"event":event_dict(db.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone())})

    def auto_assign(self,db):
        actor=self.require(db,"organizer","admin");event=self.event(db)
        try: target=int(self.read_json().get("reviews_per_project",3))
        except (TypeError,ValueError): target=3
        target=min(5,max(1,target));added=0
        projects=db.execute("SELECT id,track_id FROM projects WHERE event_id=? AND status='submitted' ORDER BY id",
                            (event["id"],)).fetchall()
        judges=[r["id"] for r in db.execute("SELECT id FROM users WHERE role='judge' AND active=1")]
        for project in projects:
            existing={r["judge_id"] for r in db.execute("SELECT judge_id FROM assignments WHERE project_id=?",
                                                        (project["id"],))}
            candidates=[judge for judge in judges if judge not in existing and db.execute(
                "SELECT 1 FROM judge_tracks WHERE judge_id=? AND track_id=?",
                (judge,project["track_id"])).fetchone()]
            candidates.sort(key=lambda judge:(db.execute(
                "SELECT COUNT(*) n FROM assignments WHERE judge_id=? AND event_id=?",
                (judge,event["id"])).fetchone()["n"],
                digest(event["id"]+":"+project["id"]+":"+judge)))
            for judge in candidates[:max(0,target-len(existing))]:
                assignment_id="asg_"+digest(judge+":"+project["id"])[:18]
                db.execute("INSERT OR IGNORE INTO assignments VALUES(?,?,?,?,?,?)",
                           (assignment_id,event["id"],project["id"],judge,"Auto",iso()))
                added+=1
        audit(db,event["id"],actor["id"],"assignments.generated","event",event["id"],
              {"reviews_per_project":target,"added":added})
        self.json_out(200,{"added":added,"progress":self.progress(db,event["id"])})

    def voting_window(self,event):
        opening,closing=parse_time(event["voting_open"]),parse_time(event["voting_close"])
        if opening and now()<opening: raise HttpError(409,"Community voting has not opened yet.","voting_not_open")
        if closing and now()>=closing: raise HttpError(409,"Community voting is closed.","voting_closed")

    def cast_vote(self,db):
        body=self.read_json();event=self.event(db);actor=self.actor(db)
        if event["voting_mode"] in ("email","authenticated") and not actor:
            raise HttpError(401,"Sign in with an email account to vote.","authentication_required")
        self.voting_window(event)
        try: credits=int(body.get("credits",1))
        except (ValueError,TypeError): credits=0
        if credits<1 or credits>4: raise HttpError(400,"Choose 1 to 4 credits.","invalid_vote")
        project_id=text(body.get("project_id"),80)
        project=db.execute("SELECT id,team_id FROM projects WHERE id=? AND event_id=? AND status='submitted'",
                           (project_id,event["id"])).fetchone()
        if not project: raise HttpError(404,"Project not found.","not_found")
        if actor and actor["role"]=="participant" and db.execute(
            "SELECT 1 FROM team_members WHERE team_id=? AND user_id=?",(project["team_id"],actor["id"])).fetchone():
            raise HttpError(403,"Teams cannot vote for their own project.","self_vote_forbidden")
        token=self.token("voter");headers={}
        if not token:
            token=secrets.token_urlsafe(24)
            headers["Set-Cookie"]="voter={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(token,365*86400)
        voter_hash=digest("account:"+actor["id"]) if actor else digest(token)
        if not self.rate_limit("vote:"+voter_hash,40,3600):
            raise HttpError(429,"Ballot rate limit reached.","rate_limited")
        existing=db.execute("SELECT credits FROM votes WHERE event_id=? AND project_id=? AND voter_hash=?",
                            (event["id"],project_id,voter_hash)).fetchone()
        spent=db.execute("SELECT COALESCE(SUM(credits*credits),0) n FROM votes WHERE event_id=? AND voter_hash=?",
                         (event["id"],voter_hash)).fetchone()["n"]
        prior_cost=existing["credits"]**2 if existing else 0
        if spent-prior_cost+credits*credits>16:
            raise HttpError(409,"This ballot has spent its 16-credit quadratic budget.","vote_budget_exceeded")
        if existing:
            db.execute("UPDATE votes SET credits=?,created_at=? WHERE event_id=? AND project_id=? AND voter_hash=?",
                       (credits,iso(),event["id"],project_id,voter_hash))
        else:
            db.execute("INSERT INTO votes VALUES(?,?,?,?,?,?)",
                       ("vot_"+secrets.token_hex(9),event["id"],project_id,voter_hash,credits,iso()))
        audit(db,event["id"],actor["id"] if actor else "anonymous","vote.cast","project",project_id,
              {"credits":credits,"quadratic_cost":credits*credits})
        self.json_out(201,{"ok":True,"credits":credits,"spent":spent-prior_cost+credits*credits},headers)

    def add_comment(self,db):
        actor=self.require(db,"participant","judge","organizer","admin");body=self.read_json()
        project_id=text(body.get("project_id"),80);comment=text(body.get("body"),1000);event=self.event(db)
        if len(comment)<2: raise HttpError(400,"Write at least two characters.","invalid_comment")
        if not db.execute("SELECT 1 FROM projects WHERE id=? AND event_id=? AND status='submitted'",
                          (project_id,event["id"])).fetchone():
            raise HttpError(404,"Project not found.","not_found")
        if not self.rate_limit("comment:"+actor["id"],10,3600):
            raise HttpError(429,"Comment limit reached. Try again later.","rate_limited")
        comment_id="cmt_"+secrets.token_hex(9)
        db.execute("INSERT INTO comments VALUES(?,?,?,?,?,?)",
                   (comment_id,event["id"],project_id,actor["id"],comment,iso()))
        audit(db,event["id"],actor["id"],"comment.created","comment",comment_id,{"project_id":project_id})
        self.json_out(201,{"id":comment_id})

    def rate_limit(self,key,limit,seconds):
        with RATE_LOCK:
            current=time.time();history=RATE_HISTORY.setdefault(key,[])
            history[:]=[stamp for stamp in history if current-stamp<seconds]
            if len(history)>=limit: return False
            history.append(current);return True

    def get_certificate(self,db,judge_id):
        judge=db.execute("SELECT id,name,role FROM users WHERE id=?",(judge_id,)).fetchone()
        if not judge or judge["role"]!="judge": raise HttpError(404,"Judge record not found.","not_found")
        count=db.execute(
            """SELECT COUNT(*) n FROM scores s JOIN assignments a ON a.id=s.assignment_id
               WHERE a.judge_id=?""",(judge_id,)).fetchone()["n"]
        if not count: raise HttpError(404,"No completed judging record exists yet.","not_found")
        event=self.event(db)
        record={"issuer":"Fieldnote","event_id":event["id"],"judge_id":judge_id,
                "judge_name":judge["name"],"reviews_submitted":count,"record_type":"judge-participation"}
        secret=bytes.fromhex(db.execute("SELECT value FROM meta WHERE key='certificate_secret'").fetchone()["value"])
        signature=hmac.new(secret,canonical(record).encode(),hashlib.sha256).hexdigest()
        return {"record":record,"signature":signature,"algorithm":"HMAC-SHA256"}

    def import_event(self,db):
        actor=self.require(db,"organizer","admin");body=self.read_json()
        if body.get("format")!="fieldnote-event-export-v1":
            raise HttpError(400,"This is not a Fieldnote event export.","invalid_import")
        source=body.get("event")
        if not isinstance(source,dict) or not source.get("name") or not source.get("submissions_close"):
            raise HttpError(400,"The event export is incomplete.","invalid_import")
        event_id="evt_"+secrets.token_hex(8)
        slug=re.sub(r"[^a-z0-9]+","-",text(source["name"],150).lower()).strip("-")+"-"+event_id[-4:]
        db.execute(
            """INSERT INTO events(id,name,slug,description,opens_at,submissions_close,judging_close,
               voting_open,voting_close,voting_mode,results_published,tracks_json,prizes_json,
               rubric_json,questions_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id,source["name"],slug,source.get("description",""),source.get("opens_at"),
             source["submissions_close"],source.get("judging_close"),source.get("voting_open"),
             source.get("voting_close"),source.get("voting_mode","authenticated"),0,
             canonical(source.get("tracks",[])),canonical(source.get("prizes",[])),
             canonical(source.get("rubric",CRITERIA)),canonical(source.get("questions",[])),iso()))
        team_map={}
        for team in body.get("teams",[]):
            new_id="tm_"+secrets.token_hex(8);team_map[team["id"]]=new_id
            db.execute("INSERT INTO teams VALUES(?,?,?,?,?)",
                       (new_id,event_id,team["name"],secrets.token_urlsafe(10),iso()))
        memberships=0
        for member in body.get("memberships",[]):
            new_team=team_map.get(member.get("team_id"));user_id=member.get("user_id")
            if new_team and user_id and db.execute("SELECT 1 FROM users WHERE id=?",(user_id,)).fetchone():
                db.execute("INSERT OR IGNORE INTO team_members VALUES(?,?,?)",
                           (new_team,user_id,member.get("joined_at",iso())))
                memberships+=1
        project_map={}
        for project in body.get("projects",[]):
            team_id=team_map.get(project.get("team_id"))
            if not team_id: continue
            new_id="prj_"+secrets.token_hex(8);project_map[project["id"]]=new_id
            db.execute(
                """INSERT INTO projects(id,event_id,team_id,track_id,title,tagline,description,thumbnail_url,
                   gallery_json,demo_url,repo_url,live_url,tech_tags_json,answers_json,submitted_at,updated_at,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_id,event_id,team_id,project["track_id"],project["title"],project.get("tagline",""),
                 project.get("description",""),project.get("thumbnail_url",""),project.get("gallery_json","[]"),
                 project.get("demo_url",""),project.get("repo_url",""),project.get("live_url",""),
                 project.get("tech_tags_json","[]"),project.get("answers_json","{}"),
                 project.get("submitted_at",iso()),project.get("updated_at",iso()),project.get("status","submitted")))
        assignment_map={}
        for assignment in body.get("assignments",[]):
            project_id=project_map.get(assignment.get("project_id"));judge_id=assignment.get("judge_id")
            if not project_id or not db.execute("SELECT 1 FROM users WHERE id=? AND role='judge'",(judge_id,)).fetchone():
                continue
            new_id="asg_"+secrets.token_hex(9);assignment_map[assignment["id"]]=new_id
            db.execute("INSERT OR IGNORE INTO assignments VALUES(?,?,?,?,?,?)",
                       (new_id,event_id,project_id,judge_id,assignment.get("batch","Imported"),iso()))
        for score in body.get("scores",[]):
            new_assignment=assignment_map.get(score.get("assignment_id"))
            if new_assignment:
                db.execute("INSERT OR IGNORE INTO scores VALUES(?,?,?,?,?,?)",
                           ("scr_"+secrets.token_hex(9),new_assignment,score.get("criteria_json","{}"),
                            score.get("comment",""),score.get("submitted_at",iso()),score.get("updated_at",iso())))
        for comment in body.get("comments",[]):
            project_id=project_map.get(comment.get("project_id"))
            user_id=comment.get("user_id")
            if project_id and db.execute("SELECT 1 FROM users WHERE id=?",(user_id,)).fetchone():
                db.execute("INSERT INTO comments VALUES(?,?,?,?,?,?)",
                           ("cmt_"+secrets.token_hex(9),event_id,project_id,user_id,
                            comment["body"],comment.get("created_at",iso())))
        for vote in body.get("votes",[]):
            project_id=project_map.get(vote.get("project_id"))
            if project_id:
                db.execute("INSERT OR IGNORE INTO votes VALUES(?,?,?,?,?,?)",
                           ("vot_"+secrets.token_hex(9),event_id,project_id,vote["voter_hash"],
                            vote["credits"],vote.get("created_at",iso())))
        db.execute("INSERT INTO meta(key,value) VALUES('active_event_id',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value",(event_id,))
        audit(db,event_id,actor["id"],"event.imported","event",event_id,
              {"projects":len(project_map),"linked_memberships":memberships})
        self.json_out(201,{"event_id":event_id,"projects":len(project_map),"linked_memberships":memberships})


def main():
    seed()
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    server.daemon_threads=True
    print("Fieldnote listening at http://{}:{}".format(HOST,PORT),flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("Stopping Fieldnote.",flush=True)
    finally:
        server.server_close()


if __name__=="__main__":
    main()
