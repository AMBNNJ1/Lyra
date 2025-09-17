import sqlite3, os, sys, json

p = sys.argv[1] if len(sys.argv) > 1 else '.data/memory.sqlite'
conn = sqlite3.connect(p)
conn.row_factory = sqlite3.Row
c = conn.cursor()
print('DB:', os.path.abspath(p))
for tbl in ['memory_items','working_summary','tool_logs','emotion_state','emotion_events','sessions','session_items']:
    try:
        c.execute(f'SELECT COUNT(*) FROM {tbl}')
        print(tbl, c.fetchone()[0])
    except Exception as e:
        print(tbl, 'ERR', e)
print('Users:')
c.execute("SELECT DISTINCT user_id FROM memory_items WHERE user_id!='__global__' ORDER BY user_id")
print([r[0] for r in c.fetchall()])
uid = os.getenv('UID', 'noah')
print('User rows for', uid)
c.execute("SELECT id,label,type,title,text,importance,created_ts,recency_ts FROM memory_items WHERE user_id=? ORDER BY recency_ts DESC LIMIT 15", (uid,))
for r in c.fetchall():
    print(dict(r))
print('Working summary rows:')
c.execute('SELECT user_id, summary, updated_ts FROM working_summary')
print([dict(r) for r in c.fetchall()])
print('Tool logs last 5:')
c.execute('SELECT name,args,result,success,created_ts FROM tool_logs ORDER BY created_ts DESC LIMIT 5')
print([dict(r) for r in c.fetchall()])
print('Emotion state rows:')
try:
    c.execute('SELECT * FROM emotion_state')
    cols=[d[0] for d in c.description]
    for r in c.fetchall():
        print(dict(zip(cols, r)))
except Exception as e:
    print('emotion_state err', e)
