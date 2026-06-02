"""
Load brain_data.json into the thought-graph SQLite session for taste exploration.
Run once: python3 scripts/load_taste_graph.py [session_id]
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
BRAIN_DATA = ROOT / "data" / "processed" / "brain_data.json"
TG_DB_DIR = Path.home() / ".claude" / "skills" / "thought-graph" / "db"


def find_or_create_session(session_id: str | None) -> tuple[str, Path]:
    if session_id:
        candidates = list(TG_DB_DIR.glob(f"session_{session_id}*.db"))
        if candidates:
            db_path = candidates[0]
            sid = db_path.stem.replace("session_", "")
            print(f"Using existing session: {sid}")
            return sid, db_path
    # Create new
    import subprocess, json as _json
    result = subprocess.run(
        ["python3", str(Path.home() / ".claude/skills/thought-graph/invoke.py")],
        input='{"action": "init_session", "session_name": "taste_map"}',
        capture_output=True, text=True
    )
    data = _json.loads(result.stdout)
    sid = data["session_id"]
    db_path = Path(data["db_path"])
    print(f"Created session: {sid}")
    return sid, db_path


def add_node(conn: sqlite3.Connection, session_id: str, node_type: str,
             content: str, confidence: float = 0.9, metadata: dict | None = None) -> int:
    now = int(time.time())
    meta_json = json.dumps(metadata or {})
    cur = conn.execute(
        "INSERT INTO nodes (session_id, type, content, confidence, timestamp, metadata) "
        "VALUES (?,?,?,?,?,?)",
        (session_id, node_type, content, confidence, now, meta_json)
    )
    conn.commit()
    return cur.lastrowid


def add_edge(conn: sqlite3.Connection, session_id: str, src: int, tgt: int,
             relation: str, strength: float = 0.8) -> None:
    now = int(time.time())
    conn.execute(
        "INSERT INTO edges (session_id, source_id, target_id, relation, strength, timestamp) "
        "VALUES (?,?,?,?,?,?)",
        (session_id, src, tgt, relation, strength, now)
    )
    conn.commit()


def load(session_id: str | None = None) -> None:
    if not BRAIN_DATA.exists():
        print("brain_data.json not found — run build_brain.py first")
        sys.exit(1)

    brain = json.loads(BRAIN_DATA.read_text())
    sid, db_path = find_or_create_session(session_id)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Wipe any existing nodes for this session to allow re-load
    existing = conn.execute("SELECT COUNT(*) FROM nodes WHERE session_id=?", (sid,)).fetchone()[0]
    if existing > 0:
        print(f"Session already has {existing} nodes — clearing and reloading")
        conn.execute("DELETE FROM edges WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM nodes WHERE session_id=?", (sid,))
        conn.commit()

    max_eng = max(z["engagement"]["total"] for z in brain)

    zone_node_ids: dict[str, int] = {}

    # ── Add zone nodes ────────────────────────────────────────────────────────
    for zone in brain:
        eng = zone["engagement"]
        pct = round(eng["total"] / max_eng * 100)
        dominant = max(("music", eng["music"]), ("film", eng["film"]), ("book", eng["book"]),
                       key=lambda t: t[1])[0]
        exemplars = " · ".join(zone["exemplars"])
        content = (
            f"{zone['label']} [{zone['id']}] — {pct}% explored — "
            f"dominant: {dominant} — exemplars: {exemplars}"
        )
        nid = add_node(conn, sid, "finding", content, confidence=0.95, metadata={
            "zone_id": zone["id"],
            "label": zone["label"],
            "x": zone["x"],
            "y": zone["y"],
            "engagement_total": eng["total"],
            "engagement_music": eng["music"],
            "engagement_film": eng["film"],
            "engagement_book": eng["book"],
            "explored_pct": pct,
            "dominant_medium": dominant,
            "exemplars": zone["exemplars"],
            "neighbors": zone["neighbors"],
            "art_cached": zone["art_cached"],
        })
        zone_node_ids[zone["id"]] = nid
        print(f"  Zone node {nid}: {zone['label']} ({pct}%)")

    # ── Add neighbor edges between zones ─────────────────────────────────────
    added_edges: set[frozenset] = set()
    for zone in brain:
        src = zone_node_ids[zone["id"]]
        for nbr_id in zone["neighbors"]:
            key = frozenset([zone["id"], nbr_id])
            if key in added_edges:
                continue
            tgt = zone_node_ids.get(nbr_id)
            if tgt:
                add_edge(conn, sid, src, tgt, "leads_to", strength=0.7)
                added_edges.add(key)

    print(f"  Added {len(added_edges)} neighbor edges")

    # ── Add top item nodes + zone edges ──────────────────────────────────────
    item_count = 0
    for zone in brain:
        zone_nid = zone_node_ids[zone["id"]]
        for item in zone.get("top_items", []):
            rating = item.get("rating")
            rating_str = f" ★{rating:.0f}" if rating else ""
            content = (
                f"{item['title']} ({item.get('year', '?')}) "
                f"[{item['media_type']}]{rating_str} — in {zone['label']}"
            )
            item_nid = add_node(conn, sid, "finding", content,
                                confidence=min(1.0, 0.6 + (rating or 0) * 0.08),
                                metadata={
                                    "title": item["title"],
                                    "media_type": item["media_type"],
                                    "year": item.get("year"),
                                    "rating": rating,
                                    "zone_id": zone["id"],
                                    "source": item.get("source"),
                                    "source_id": item.get("source_id"),
                                })
            add_edge(conn, sid, item_nid, zone_nid, "supports", strength=0.9)
            item_count += 1

    print(f"  Added {item_count} item nodes")

    # ── Add exploration questions ─────────────────────────────────────────────
    unexplored = [z for z in brain if z["engagement"]["total"] / max_eng < 0.15]
    for zone in unexplored:
        exemplars = zone["exemplars"][:2]
        q_content = (
            f"What to explore in {zone['label']}? "
            f"Start with: {', '.join(exemplars)}"
        )
        q_nid = add_node(conn, sid, "question", q_content, confidence=0.5, metadata={
            "zone_id": zone["id"],
            "engagement_pct": round(zone["engagement"]["total"] / max_eng * 100),
        })
        add_edge(conn, sid, zone_node_ids[zone["id"]], q_nid, "leads_to", strength=0.6)

    print(f"  Added {len(unexplored)} exploration questions for low-engagement zones")

    conn.close()

    total_nodes = len(zone_node_ids) + item_count + len(unexplored)
    print(f"\nLoaded {total_nodes} nodes into session {sid}")
    print(f"DB: {db_path}")
    print(f"\nSession ID for explore_taste.py: {sid}")


if __name__ == "__main__":
    load(sys.argv[1] if len(sys.argv) > 1 else None)
