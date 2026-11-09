"""Regression OBS-051: disposable local Oracle with fake answers and reviews.

Run with the entertainment venv Python and a port argument. Never uses the live DB.
"""
from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8011
    with tempfile.TemporaryDirectory(prefix="obs-051-browser-") as folder:
        tmp = Path(folder)
        os.environ["OBS_DB_PATH"] = str(tmp / "test.db")
        os.environ["OBS_CLAUDE_TOKEN_FILE"] = str(tmp / "no-token")
        cli = tmp / "claude"
        cli.write_text(f'''#!{sys.executable}
import json, sys
system = sys.argv[sys.argv.index("--system-prompt") + 1]
prompt = sys.stdin.read()
if "Name this conversation" in system:
    print("Pantheon praise")
elif "security reviewer" in system:
    print(json.dumps({{"verdict": "reject", "reason": "Please confirm this rating yourself."}}))
else:
    print("**Pantheon** is a thoughtful choice. <img src=x onerror=alert(1)>")
    latest = prompt.split("Waldo's latest message:")[-1].lower()
    if "rate pantheon" in latest:
        print('```observatory-actions')
        print(json.dumps([{{"action": "rate", "title": "Pantheon", "year": 2022,
                          "media_type": "tv_show", "rating": 4,
                          "user_quote": "rate pantheon"}}]))
        print('```')
''')
        cli.chmod(0o700)
        os.environ["OBS_CLAUDE_CLI"] = str(cli)
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / "scripts"))
        from db import get_conn, init_db
        with get_conn() as conn:
            init_db(conn)
            conn.execute("INSERT INTO media_items (id,media_type,title,year,source,genres) VALUES ('pantheon','tv_show','Pantheon',2022,'tmdb','[]')")
            conn.execute("INSERT INTO user_interactions (media_id,interaction,shelf,source) VALUES ('pantheon','added','to-watch','tmdb')")
            # Leave the old schema intact so startup exercises the real migration.
            conn.execute("CREATE TABLE oracle_conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, answer TEXT NOT NULL, created_at TEXT NOT NULL)")
            conn.executemany("INSERT INTO oracle_conversations (question,answer,created_at) VALUES (?,?,?)", [
                ("Older books conversation", "Try a novel.", "2026-01-01T09:00:00Z"),
                ("Recent films conversation", "Try a film.", "2026-01-02T09:00:00Z"),
            ])
            conn.commit()
        import server
        if not server.DASHBOARD.exists():
            # A missing generated dashboard is a documented optional browser scenario.
            from fastapi.responses import Response
            server.app.router.routes[:] = [r for r in server.app.router.routes if getattr(r, "path", None) != "/"]
            server.app.add_api_route("/", lambda: Response(status_code=404))
        import uvicorn
        uvicorn.run(server.app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
