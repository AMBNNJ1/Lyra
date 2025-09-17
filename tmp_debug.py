from pathlib import Path
path = Path("web/styles.css")
text = path.read_text()
old_main = ".message{ display:grid; grid-template-columns:44px 1fr; gap:16px; padding:16px; border-radius:8px; line-height:1.55; }"
print(old_main)
