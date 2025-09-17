from pathlib import Path
data = Path("web/index.html").read_text()
idx = data.index("buf.indexOf")
segment = data[idx:idx+40]
print(segment)
print([ord(c) for c in segment])
