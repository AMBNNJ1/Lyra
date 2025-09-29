from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template_string, request


# Default DB = repo-root/.data/memory.sqlite (overridable via env/arg)
_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.getenv("MEMORY_DB_PATH", str(_ROOT / ".data" / "memory.sqlite"))
DEFAULT_PORT = int(os.getenv("MEMORY_DASH_PORT", "8765"))


def _conn(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def list_users(conn: sqlite3.Connection) -> List[str]:
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM memory_items WHERE user_id!='__global__' ORDER BY user_id ASC")
    return [r[0] for r in cur.fetchall()]


def fetch_persona(conn: sqlite3.Connection) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, text, created_ts, recency_ts FROM memory_items WHERE user_id='__global__' AND label='persona' ORDER BY recency_ts DESC LIMIT 1"
    )
    r = cur.fetchone()
    if not r:
        return {"id": None, "text": "", "created_ts": None, "recency_ts": None}
    return {"id": r[0], "text": r[1] or "", "created_ts": r[2], "recency_ts": r[3]}


def fetch_working(conn: sqlite3.Connection, user_id: str) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute("SELECT summary, updated_ts FROM working_summary WHERE user_id=?", (user_id,))
    r = cur.fetchone()
    if not r:
        return {"summary": "", "updated_ts": None}
    return {"summary": r[0] or "", "updated_ts": r[1]}


def fetch_items(conn: sqlite3.Connection, user_id: str) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, label, text, importance, created_ts, recency_ts
        FROM memory_items
        WHERE user_id=? AND label IN ('user','profile','preferences','facts','goals')
        ORDER BY CASE label WHEN 'user' THEN 0 WHEN 'profile' THEN 1 WHEN 'preferences' THEN 2 WHEN 'facts' THEN 3 WHEN 'goals' THEN 4 ELSE 5 END,
                 recency_ts DESC
        """,
        (user_id,),
    )
    out: List[Dict[str, Any]] = []
    for r in cur.fetchall() or []:
        out.append(
            {
                "id": r[0],
                "label": r[1],
                "text": r[2] or "",
                "importance": int(r[3] or 0),
                "created_ts": r[4],
                "recency_ts": r[5],
            }
        )
    return out


def fetch_general(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, source, title, importance, created_ts, recency_ts
        FROM memory_items
        WHERE user_id='__global__' AND type='general'
        ORDER BY recency_ts DESC
        LIMIT 50
        """
    )
    out: List[Dict[str, Any]] = []
    for r in cur.fetchall() or []:
        out.append(
            {
                "id": r[0],
                "source": r[1] or "",
                "title": r[2] or "",
                "importance": int(r[3] or 0),
                "created_ts": r[4],
                "recency_ts": r[5],
            }
        )
    return out


def fetch_tool_logs(conn: sqlite3.Connection, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT name, args, result, success, created_ts FROM tool_logs WHERE user_id=? ORDER BY created_ts DESC LIMIT ?",
            (user_id, int(limit)),
        )
    except Exception:
        return []
    logs: List[Dict[str, Any]] = []
    for r in cur.fetchall() or []:
        logs.append(
            {
                "name": r[0],
                "args": r[1] or "{}",
                "result": r[2] or "",
                "success": bool(r[3] or 0),
                "created_ts": r[4],
            }
        )
    return logs


def fetch_conversation(conn: sqlite3.Connection, user_id: str, limit: int = 32) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, text, importance, created_ts, recency_ts
            FROM memory_items
            WHERE user_id=? AND type='episodic'
            ORDER BY recency_ts DESC
            LIMIT ?
            """,
            (user_id, int(limit)),
        )
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in cur.fetchall() or []:
        out.append(
            {
                "id": r[0],
                "text": r[1] or "",
                "importance": int(r[2] or 0),
                "created_ts": r[3],
                "recency_ts": r[4],
            }
        )
    return out


def fetch_emotion_state(conn: sqlite3.Connection, user_id: str) -> Dict[str, Any]:
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT primary_emotion, intensity, levels, last_reason, updated_ts FROM emotion_state WHERE user_id=?",
            (user_id,),
        )
        r = cur.fetchone()
        if not r:
            return {"primary": None, "intensity": 0.0, "levels": {}, "reason": "", "updated_ts": None}
        try:
            import json as _json

            levels = _json.loads(r[2] or "{}")
        except Exception:
            levels = {}
        return {
            "primary": r[0],
            "intensity": float(r[1] or 0.0),
            "levels": levels,
            "reason": r[3] or "",
            "updated_ts": r[4],
        }
    except Exception:
        return {"primary": None, "intensity": 0.0, "levels": {}, "reason": "", "updated_ts": None}


def fetch_emotion_events(conn: sqlite3.Connection, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT primary_emotion, intensity, reason, levels, created_ts FROM emotion_events WHERE user_id=? ORDER BY created_ts DESC LIMIT ?",
            (user_id, int(limit)),
        )
        rows = cur.fetchall() or []
        out: List[Dict[str, Any]] = []
        import json as _json

        for r in rows:
            try:
                lv = _json.loads(r[3] or "{}")
            except Exception:
                lv = {}
            out.append(
                {
                    "primary": r[0],
                    "intensity": float(r[1] or 0.0),
                    "reason": r[2] or "",
                    "levels": lv,
                    "created_ts": r[4],
                }
            )
        return out
    except Exception:
        return []


def fetch_available_tools(conn: sqlite3.Connection, user_id: str) -> List[str]:
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT name FROM tool_logs WHERE user_id=? ORDER BY name ASC", (user_id,))
        names = [r[0] for r in cur.fetchall() or [] if r and r[0]]
        if names:
            return names
    except Exception:
        pass
    return ["web_search"]


app = Flask(__name__)


@app.route("/favicon.ico")
def _favicon():
    # Some browsers request /favicon.ico by default; return no content instead of 404.
    return ("", 204)


@app.route("/")
def index():
    user = request.args.get("user_id")
    conn = _conn(DB_PATH)
    users = list_users(conn)
    selected = user or (users[0] if users else "default")
    persona = fetch_persona(conn)
    working = fetch_working(conn, selected)
    items = fetch_items(conn, selected)
    general = fetch_general(conn)
    tool_logs = fetch_tool_logs(conn, selected, limit=30)
    tools = fetch_available_tools(conn, selected)
    conversation = fetch_conversation(conn, selected, limit=32)
    emotion_state = fetch_emotion_state(conn, selected)
    emotion_events = fetch_emotion_events(conn, selected, limit=20)
    conn.close()
    return render_template_string(
        INDEX_HTML,
        users=users,
        selected=selected,
        persona=persona,
        working=working,
        items=items,
        general=general,
        tools=tools,
        tool_logs=tool_logs,
        conversation=conversation,
        emotion_state=emotion_state,
        emotion_events=emotion_events,
        now_ms=int(time.time() * 1000),
    )


@app.route("/api/memory")
def api_memory():
    user = request.args.get("user_id")
    conn = _conn(DB_PATH)
    users = list_users(conn)
    selected = user or (users[0] if users else "default")
    data = {
        "users": users,
        "user_id": selected,
        "persona": fetch_persona(conn),
        "working": fetch_working(conn, selected),
        "items": fetch_items(conn, selected),
        "general": fetch_general(conn),
        "tools": fetch_available_tools(conn, selected),
        "tool_logs": fetch_tool_logs(conn, selected, limit=30),
        "conversation": fetch_conversation(conn, selected, limit=32),
        "emotion": {
            "state": fetch_emotion_state(conn, selected),
            "events": fetch_emotion_events(conn, selected, limit=20),
        },
        "now_ms": int(time.time() * 1000),
    }
    conn.close()
    return jsonify(data)


@app.route("/api/memory/delete_by_query", methods=["POST"])
def api_delete_by_query():
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        body = {}
    user = (body or {}).get("user_id") or request.args.get("user_id") or "default"
    query = (body or {}).get("query") or ""
    labels = (body or {}).get("labels") or []
    include_global = bool((body or {}).get("include_global", False))

    # Normalize labels to list
    if isinstance(labels, str):
        labels = [x.strip() for x in labels.split(',') if x.strip()]
    if not isinstance(labels, list):
        labels = []

    conn = _conn(DB_PATH)
    try:
        q = (query or "").strip().lower()
        if not q:
            conn.close()
            return jsonify({"deleted": 0, "error": "empty query"}), 400
        like = f"%{q}%"
        uid_clause = "(user_id=?" + (" OR user_id='__global__'" if include_global else "") + ")"
        params = [user, like, like]
        label_clause = ""
        if labels:
            label_clause = " AND label IN (" + ",".join(["?"] * len(labels)) + ")"
            params.extend(labels)
        # Select ids first
        sql_sel = (
            "SELECT id FROM memory_items WHERE " + uid_clause +
            " AND (LOWER(text) LIKE ? OR LOWER(COALESCE(title,'')) LIKE ?)" +
            label_clause
        )
        cur = conn.cursor()
        cur.execute(sql_sel, tuple(params))
        ids = [r[0] for r in cur.fetchall() or []]
        if not ids:
            conn.close()
            return jsonify({"deleted": 0})
        qmarks = ",".join(["?"] * len(ids))
        cur.execute(f"DELETE FROM memory_items WHERE id IN ({qmarks})", ids)
        deleted = int(cur.rowcount or 0)
        conn.commit()
        try:
            cur.execute(f"DELETE FROM memory_fts WHERE doc_id IN ({qmarks})", ids)
            conn.commit()
        except Exception:
            pass
        conn.close()
        return jsonify({"deleted": deleted})
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"deleted": 0, "error": str(e)}), 500


INDEX_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Neuro Memory Dashboard</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; padding: 0; background: #0b0e14; color: #e6e6e6; }
    header { background: #151a24; padding: 12px 16px; display: flex; gap: 12px; align-items: center; }
    h1 { font-size: 18px; margin: 0; }
    main { padding: 16px; }
    .row { display: flex; gap: 16px; }
    .col { flex: 1; min-width: 320px; background: #11151e; border: 1px solid #1f2430; border-radius: 8px; padding: 12px; }
    .section-title { font-size: 12px; color: #9aa5b1; margin: 0 0 8px 0; text-transform: uppercase; letter-spacing: .08em; }
    .item { border: 1px solid #222839; padding: 8px; border-radius: 6px; margin-bottom: 8px; background: #0e1320; }
    .label { font-size: 12px; color: #7aa2f7; text-transform: uppercase; margin-right: 8px; }
    .meta { font-size: 12px; color: #a1a1a1; }
    .badge { display: inline-block; font-size: 11px; padding: 2px 6px; border-radius: 4px; margin-left: 8px; }
    .new { background: #2a5; color: #021; }
    .updated { background: #f90; color: #210; }
    .flash { animation: flashbg 1s ease-in-out 2; }
    @keyframes flashbg { 0% { background: #173; } 100% { background: #0e1320; } }
    select, button { background: #0e1320; color: #e6e6e6; border: 1px solid #222839; border-radius: 4px; padding: 6px 8px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; }
    .levels { margin-top: 8px; }
    .bar { height: 8px; background: #0d1320; border: 1px solid #1d2433; border-radius: 4px; overflow: hidden; }
    .bar > span { display: block; height: 100%; background: linear-gradient(90deg,#6aa9ff,#7c5cff); }
    .kv { display:flex; align-items:center; justify-content:space-between; font-size: 12px; color:#9aa5b1; margin: 4px 0; }
    .subhead { font-size: 11px; color:#9aa5b1; text-transform: uppercase; letter-spacing:.08em; margin: 8px 0 4px; border-top:1px solid #1f2430; padding-top:6px; }
    .error { color:#ffb3b3; }
  </style>
  <meta http-equiv="Cache-control" content="no-cache">
</head>
<body>
  <header>
    <h1>Neuro Memory</h1>
    <label>User:
      <select id="userSel">
        {% for u in users %}
          <option value="{{u}}" {% if u==selected %}selected{% endif %}>{{u}}</option>
        {% endfor %}
      </select>
    </label>
    <button id="refreshBtn">Refresh</button>
  </header>
  <main>
    <div class="row">
      <div class="col">
        <div class="section-title">Persona</div>
        <div id="persona" class="item">
          <div class="meta">updated: <span data-ts="{{ persona.recency_ts }}">{{ persona.recency_ts }}</span></div>
          <div id="personaText">{{ persona.text }}</div>
        </div>
        <div class="section-title">Working Memory</div>
        <div id="working" class="item">
          <div class="meta">updated: <span data-ts="{{ working.updated_ts }}">{{ working.updated_ts }}</span></div>
          <pre style="white-space: pre-wrap; margin: 0;">{{ working.summary }}</pre>
        </div>
      </div>
      <div class="col">
        <div class="section-title">Long-Term Memory</div>
        <div id="items"></div>
      </div>
      <div class="col">
        <div class="section-title">General (latest)</div>
        <div id="general"></div>
      </div>
    </div>
    <div class="row" style="margin-top:16px;">
      <div class="col" style="flex:2;">
        <div class="section-title">Short-Term Memory</div>
        <div id="conversation"></div>
      </div>
    </div>
    <div class="row" style="margin-top:16px;">
      <div class="col" style="flex:1.5;">
        <div class="section-title">Emotion</div>
        <div id="emotionCard" class="item">
          <div class="meta">updated: <span id="emotionUpdated"></span></div>
          <div><strong id="emotionPrimary">neutral</strong> <span id="emotionIntensity" class="meta"></span></div>
          <div id="emotionReason" class="meta" style="margin-top:6px;"></div>
          <div class="levels" id="emotionLevels"></div>
        </div>
      </div>
      <div class="col">
        <div class="section-title">Available Tools</div>
        <div id="tools">{% for t in tools %}<span class="badge" style="background:#234;color:#9cf;margin-right:6px;">{{t}}</span>{% endfor %}</div>
      </div>
      <div class="col" style="flex:2;">
        <div class="section-title">Recent Tool Calls</div>
        <div id="toolLogs"></div>
      </div>
    </div>
    <div class="row" style="margin-top:16px;">
      <div class="col" style="flex:2;">
        <div class="section-title">Emotion Events</div>
        <div id="emotionEvents"></div>
      </div>
    </div>
    <div class="row" style="margin-top:16px;">
      <div class="col" style="flex:2;">
        <div class="section-title">Maintenance</div>
        <div class="item">
          <div class="meta">Delete by keyword (e.g., xrp, valorant)</div>
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:6px;">
            <input id="delQuery" placeholder="keyword" style="flex:1; padding:8px; border-radius:6px; border:1px solid #222839; background:#0e1320; color:#e6e6e6;" />
            <label class="meta"><input type="checkbox" id="labFacts"> facts</label>
            <label class="meta"><input type="checkbox" id="labGoals"> goals</label>
            <label class="meta"><input type="checkbox" id="labPrefs"> preferences</label>
            <label class="meta"><input type="checkbox" id="labProfile"> profile</label>
            <label class="meta"><input type="checkbox" id="labGeneral"> general</label>
            <label class="meta"><input type="checkbox" id="incGlobal"> include global</label>
            <button id="deleteByQueryBtn">Delete by query</button>
          </div>
          <div id="delResult" class="meta" style="margin-top:6px;"></div>
        </div>
      </div>
    </div>
  </main>
  <script>
    const userSel = document.getElementById('userSel');
    const refreshBtn = document.getElementById('refreshBtn');
    const itemsDiv = document.getElementById('items');
    const generalDiv = document.getElementById('general');
    const personaDiv = document.getElementById('persona');
    const personaText = document.getElementById('personaText');
    const toolsDiv = document.getElementById('tools');
    const toolLogsDiv = document.getElementById('toolLogs');
    const conversationDiv = document.getElementById('conversation');
    const emotionUpdated = document.getElementById('emotionUpdated');
    const emotionPrimary = document.getElementById('emotionPrimary');
    const emotionIntensity = document.getElementById('emotionIntensity');
    const emotionReason = document.getElementById('emotionReason');
    const emotionLevels = document.getElementById('emotionLevels');
    const emotionEventsDiv = document.getElementById('emotionEvents');
    const delQuery = document.getElementById('delQuery');
    const labFacts = document.getElementById('labFacts');
    const labGoals = document.getElementById('labGoals');
    const labPrefs = document.getElementById('labPrefs');
    const labProfile = document.getElementById('labProfile');
    const labGeneral = document.getElementById('labGeneral');
    const incGlobal = document.getElementById('incGlobal');
    const deleteByQueryBtn = document.getElementById('deleteByQueryBtn');
    const delResult = document.getElementById('delResult');

    let lastItems = new Map();
    let lastGeneral = new Map();
    let lastPersonaTs = 0;

    function fmt(ts){ if(!ts) return 'N/A'; const d = new Date(Number(ts)); return d.toLocaleString(); }
    function esc(s){ return String(s||'').replace(/</g,'&lt;'); }
    function badge(now, created, recency){ const fresh=1000*60*60*6; const out=[]; if(created && (now-created)<fresh) out.push('<span class="badge new">new</span>'); if(recency && created && recency>created && (now-recency)<fresh) out.push('<span class="badge updated">updated</span>'); return out.join(' '); }

    function renderItems(arr){ const now=Date.now(); let html=''; for(const it of (arr||[])){ const prev=lastItems.get(it.id); const changed=prev && (prev.recency_ts!==it.recency_ts || prev.text!==it.text); html += `<div class="item ${!prev? 'flash':''} ${changed? 'flash':''}">`+`<div><span class="label">${it.label}</span> <span class="meta">imp:${it.importance} - created: ${fmt(it.created_ts)} - updated: ${fmt(it.recency_ts)} ${badge(now,it.created_ts,it.recency_ts)}</span></div>`+`<div>${esc(it.text)}</div>`+`</div>`; } itemsDiv.innerHTML = html || '<div class="meta">No items.</div>'; lastItems = new Map((arr||[]).map(x=>[x.id,x])); }

    function renderLongTerm(arr){ const order=['user','profile','preferences','facts','goals']; const groups={}; for(const it of (arr||[])){ const k=(it.label||'').toLowerCase(); (groups[k]||(groups[k]=[])).push(it); } let html=''; const now=Date.now(); for(const k of order){ const list=groups[k]||[]; if(!list.length) continue; html += `<div class="subhead">${k} (${list.length})</div>`; for(const it of list){ const prev=lastItems.get(it.id); const changed=prev && (prev.recency_ts!==it.recency_ts || prev.text!==it.text); html += `<div class="item ${!prev? 'flash':''} ${changed? 'flash':''}">`+`<div class="meta">imp:${it.importance} · created: ${fmt(it.created_ts)} · updated: ${fmt(it.recency_ts)} ${badge(now,it.created_ts,it.recency_ts)}</div>`+`<div>${esc(it.text)}</div>`+`</div>`; } } itemsDiv.innerHTML = html || '<div class="meta">No long‑term memory yet.</div>'; lastItems = new Map((arr||[]).map(x=>[x.id,x])); }

    function renderGeneral(arr){ const now=Date.now(); let html=''; for(const it of (arr||[])){ const prev=lastGeneral.get(it.id); const changed=prev && (prev.recency_ts!==it.recency_ts); html += `<div class="item ${!prev? 'flash':''} ${changed? 'flash':''}">`+`<div class="meta">${esc(it.title||it.source||'')}</div>`+`<div class="meta">imp:${it.importance} - created: ${fmt(it.created_ts)} - updated: ${fmt(it.recency_ts)} ${badge(now,it.created_ts,it.recency_ts)}</div>`+`</div>`; } generalDiv.innerHTML = html || '<div class="meta">No general items.</div>'; lastGeneral = new Map((arr||[]).map(x=>[x.id,x])); }

    function renderToolLogs(arr){ let html=''; for(const log of (arr||[])){ const ok=!!log.success; const when=fmt(Number(log.created_ts||0)); html += `<div class="item ${ok? '':'flash'}">`+`<div><span class="label">${log.name}</span> <span class="badge ${ok? 'new':'updated'}">${ok? 'ok':'error'}</span> <span class="meta">${when}</span></div>`+`<div class="meta">args: ${esc(log.args||'{}')}</div>`+`<div class="meta">result: ${esc(String((log.result||'')).substring(0,300))}</div>`+`</div>`; } toolLogsDiv.innerHTML = html || '<div class="meta">No tool calls yet.</div>'; }

    function renderTools(arr){ toolsDiv.innerHTML = (arr||[]).map(t => `<span class="badge" style="background:#234;color:#9cf;margin-right:6px;">${t}</span>`).join(' ') || '<div class="meta">No tools.</div>'; }

    function renderConversation(arr){ let html=''; for(const it of (arr||[])){ html += `<div class="item">`+`<div class="meta">${fmt(Number(it.recency_ts||it.created_ts||0))} - imp:${it.importance||0}</div>`+`<div class="mono">${esc(it.text||'')}</div>`+`</div>`; } conversationDiv.innerHTML = html || '<div class="meta">No conversation yet.</div>'; }

    function renderEmotion(state){ const upd=Number(state.updated_ts||0); if(emotionUpdated) emotionUpdated.textContent = upd? fmt(upd) : 'N/A'; if(emotionPrimary) emotionPrimary.textContent = state.primary || 'neutral'; if(emotionIntensity) emotionIntensity.textContent = `(intensity ${Number(state.intensity||0).toFixed(2)})`; if(emotionReason) emotionReason.textContent = state.reason ? `Because: ${state.reason}` : ''; const entries = Object.entries(state.levels||{}).sort((a,b)=>b[1]-a[1]).slice(0,6); let html=''; for(const [k,v] of entries){ const pct=Math.max(0,Math.min(100,Math.round(v*100))); html += `<div class="kv"><span>${k}</span><span>${pct}%</span></div><div class="bar"><span style="width:${pct}%;"></span></div>`; } if(emotionLevels) emotionLevels.innerHTML = html || '<div class="meta">No data yet.</div>'; }

    function renderEmotionEvents(arr){ let html=''; for(const ev of (arr||[])){ const when=fmt(Number(ev.created_ts||0)); const inten=Number(ev.intensity||0).toFixed(2); html += `<div class="item">`+`<div><span class="label">${ev.primary||'neutral'}</span> <span class="meta">${when} · intensity ${inten}</span></div>`+`<div class="meta">${esc(ev.reason||'')}</div>`+`</div>`; } if(emotionEventsDiv) emotionEventsDiv.innerHTML = html || '<div class="meta">No emotion events yet.</div>'; }

    async function refresh(){
      const u = userSel.value;
      let data;
      try{
        const res = await fetch(`/api/memory?user_id=${encodeURIComponent(u)}`);
        data = await res.json();
      } catch(e){
        const msg = String((e && e.message) || e || 'fetch failed');
        const err = `<div class="meta error">Refresh failed: ${esc(msg)}</div>`;
        itemsDiv.innerHTML = err; generalDiv.innerHTML = err; toolLogsDiv.innerHTML = err; if(conversationDiv) conversationDiv.innerHTML = err; return;
      }
      const persona = data.persona || {};
      personaText.textContent = persona.text || '';
      const pTs = Number(persona.recency_ts || 0);
      if(pTs && pTs !== lastPersonaTs){ personaDiv.classList.add('flash'); setTimeout(()=>personaDiv.classList.remove('flash'), 1200); }
      lastPersonaTs = pTs;
      const working = data.working || {};
      const tsEl = document.querySelector('#working [data-ts]'); if(tsEl) tsEl.textContent = fmt(Number(working.updated_ts || 0));
      const preEl = document.querySelector('#working pre'); if(preEl) preEl.textContent = working.summary || '';
      renderLongTerm(data.items || []);
      renderTools(data.tools || []);
      renderGeneral(data.general || []);
      renderToolLogs(data.tool_logs || []);
      renderConversation(data.conversation || []);
    if(data.emotion){ renderEmotion((data.emotion || {}).state || {}); renderEmotionEvents((data.emotion || {}).events || []); }
    }
    async function deleteByQuery(){
      const q = (delQuery && delQuery.value || '').trim();
      const labels = [];
      if(labFacts && labFacts.checked) labels.push('facts');
      if(labGoals && labGoals.checked) labels.push('goals');
      if(labPrefs && labPrefs.checked) labels.push('preferences');
      if(labProfile && labProfile.checked) labels.push('profile');
      if(labGeneral && labGeneral.checked) labels.push('general');
      if(!q){ if(delResult) delResult.textContent = 'Enter a keyword.'; return; }
      if(delResult) delResult.textContent = 'Deleting...';
      try{
        const res = await fetch('/api/memory/delete_by_query', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userSel.value, query: q, labels, include_global: !!(incGlobal && incGlobal.checked) })
        });
        const data = await res.json();
        if(res.ok){ if(delResult) delResult.textContent = `Deleted ${data.deleted||0} item(s).`; await refresh(); }
        else { if(delResult) delResult.textContent = `Error: ${esc(data.error||'unknown')}`; }
      } catch(e){ if(delResult) delResult.textContent = `Error: ${esc(e&&e.message||e||'failed')}`; }
    }

    if(deleteByQueryBtn) deleteByQueryBtn.addEventListener('click', deleteByQuery);
    refreshBtn.addEventListener('click', refresh); userSel.addEventListener('change', refresh); setInterval(refresh, 2000); setTimeout(refresh, 150);
  </script>
</body>
</html>
"""


def main():
    import argparse
    global DB_PATH

    ap = argparse.ArgumentParser(description="Neuro Memory Dashboard")
    ap.add_argument("--db", type=str, default=DB_PATH)
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    DB_PATH = args.db
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
