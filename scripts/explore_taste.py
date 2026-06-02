"""
Taste Map Brain Explorer — query interface for the thought-graph.

Usage:
  python3 scripts/explore_taste.py near ARTHOUSE
  python3 scripts/explore_taste.py unexplored
  python3 scripts/explore_taste.py zone DRAMA
  python3 scripts/explore_taste.py frontier
  python3 scripts/explore_taste.py search "tarkovsky"

The session ID is stored in data/processed/taste_graph_session.txt after first load.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SESSION_FILE = ROOT / "data" / "processed" / "taste_graph_session.txt"
TG_DB_DIR = Path.home() / ".claude" / "skills" / "thought-graph" / "db"


def _get_db() -> tuple[str, sqlite3.Connection]:
    if not SESSION_FILE.exists():
        print("No session found. Run load_taste_graph.py first.")
        sys.exit(1)
    sid = SESSION_FILE.read_text().strip()
    candidates = list(TG_DB_DIR.glob(f"session_{sid}.db"))
    if not candidates:
        candidates = list(TG_DB_DIR.glob(f"session_{sid}*.db"))
    if not candidates:
        print(f"DB not found for session {sid}.")
        sys.exit(1)
    conn = sqlite3.connect(candidates[0])
    conn.row_factory = sqlite3.Row
    return sid, conn


def _zones(conn: sqlite3.Connection, sid: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, content, metadata FROM nodes WHERE session_id=? AND type='finding' AND metadata LIKE '%\"zone_id\": %'",
        (sid,)
    ).fetchall()
    result = []
    for r in rows:
        try:
            meta = json.loads(r["metadata"])
        except Exception:
            continue
        # Only zone-level nodes (not items): they have "label" key
        if "label" in meta and "zone_id" in meta and meta["zone_id"] == meta.get("zone_id") and "exemplars" in meta:
            result.append({"node_id": r["id"], **meta})
    return result


def _items_for_zone(conn: sqlite3.Connection, sid: str, zone_id: str) -> list[dict]:
    """Return item nodes that belong to a zone."""
    rows = conn.execute(
        "SELECT n.id, n.content, n.metadata FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE n.session_id=? AND n.type='finding' "
        "AND n.metadata LIKE ? AND e.relation='supports'",
        (sid, f'%"zone_id": "{zone_id}"%')
    ).fetchall()
    items = []
    for r in rows:
        try:
            meta = json.loads(r["metadata"])
        except Exception:
            continue
        if "title" in meta:
            items.append({"node_id": r["id"], **meta})
    return sorted(items, key=lambda x: -(x.get("rating") or 0))


def cmd_zone(zone_arg: str) -> None:
    """Show full detail for a zone."""
    sid, conn = _get_db()
    zones = _zones(conn, sid)
    zone = next((z for z in zones if zone_arg.upper() in z["zone_id"] or zone_arg.lower() in z["label"].lower()), None)
    if not zone:
        print(f"Zone {zone_arg!r} not found. Available: {', '.join(z['zone_id'] for z in zones)}")
        return

    items = _items_for_zone(conn, sid, zone["zone_id"])
    print(f"\n✦ {zone['label']} [{zone['zone_id']}]")
    print(f"  Explored: {zone['explored_pct']}% · Dominant: {zone['dominant_medium']}")
    print(f"  Exemplars: {' · '.join(zone['exemplars'])}")
    print(f"  Coordinates: x={zone['x']} y={zone['y']} (Intimate↔Epic × Visceral↔Intellectual)")
    print(f"  Neighbors: {' · '.join(zone['neighbors'])}")
    print(f"\n  Top items ({len(items)}):")
    for it in items[:8]:
        rating_str = f" ★{it['rating']:.0f}" if it.get("rating") else ""
        print(f"    {it['title']} ({it.get('year','?')}) [{it['media_type']}]{rating_str}")


def cmd_near(zone_arg: str) -> None:
    """Show zones near a given zone, sorted by distance in taste-space."""
    sid, conn = _get_db()
    zones = _zones(conn, sid)
    zone = next((z for z in zones if zone_arg.upper() in z["zone_id"] or zone_arg.lower() in z["label"].lower()), None)
    if not zone:
        print(f"Zone {zone_arg!r} not found.")
        return

    import math
    def dist(a: dict, b: dict) -> float:
        return math.sqrt((a["x"] - b["x"])**2 + (a["y"] - b["y"])**2)

    neighbors = sorted(
        [z for z in zones if z["zone_id"] != zone["zone_id"]],
        key=lambda z: dist(zone, z)
    )

    print(f"\n✦ Zones near {zone['label']}:")
    for z in neighbors[:6]:
        d = dist(zone, z)
        exp = z["explored_pct"]
        bar = "█" * (exp // 10) + "░" * (10 - exp // 10)
        unexplored_marker = " ← unexplored" if exp < 20 else ""
        print(f"  {z['label']:28s}  dist={d:4.0f}  [{bar}] {exp:3d}%{unexplored_marker}")
        items = _items_for_zone(conn, sid, z["zone_id"])
        if items:
            top = items[0]
            print(f"    → start with: {top['title']} ({top.get('year','?')})")


def cmd_unexplored() -> None:
    """List zones with <25% engagement, sorted by proximity to well-explored zones."""
    sid, conn = _get_db()
    zones = _zones(conn, sid)

    import math
    def dist(a: dict, b: dict) -> float:
        return math.sqrt((a["x"] - b["x"])**2 + (a["y"] - b["y"])**2)

    explored = [z for z in zones if z["explored_pct"] >= 30]
    low = sorted(
        [z for z in zones if z["explored_pct"] < 25],
        key=lambda z: min(dist(z, e) for e in explored) if explored else 0
    )

    print(f"\n✦ Unexplored zones (< 25%), closest to your comfort zone first:")
    for z in low:
        closest = min(explored, key=lambda e: dist(z, e)) if explored else None
        nearest_str = f"  closest to: {closest['label']}" if closest else ""
        print(f"\n  {z['label']} [{z['zone_id']}] — {z['explored_pct']}% explored")
        print(f"  Exemplars: {', '.join(z['exemplars'])}")
        print(f"  Neighbors: {', '.join(z['neighbors'])}{nearest_str}")


def cmd_frontier() -> None:
    """Show the frontier: high-engagement zones whose neighbors are underexplored."""
    sid, conn = _get_db()
    zones = _zones(conn, sid)
    zone_by_id = {z["zone_id"]: z for z in zones}

    frontier = []
    for z in zones:
        if z["explored_pct"] < 30:
            continue
        for nbr_id in z["neighbors"]:
            nbr = zone_by_id.get(nbr_id)
            if nbr and nbr["explored_pct"] < 25:
                frontier.append((z, nbr))
                break

    print(f"\n✦ Frontier zones (well-explored → unexplored neighbor):")
    for src, tgt in sorted(frontier, key=lambda p: -p[0]["explored_pct"]):
        print(f"\n  {src['label']} ({src['explored_pct']}%) → {tgt['label']} ({tgt['explored_pct']}%)")
        items = _items_for_zone(conn, sid, tgt["zone_id"])
        if tgt["exemplars"]:
            print(f"  Start exploring with: {', '.join(tgt['exemplars'][:2])}")
        if items:
            print(f"  You've already touched: {items[0]['title']} ({items[0].get('year','?')})")


def cmd_search(query: str) -> None:
    """Full-text search across all nodes."""
    sid, conn = _get_db()
    q = query.lower()
    rows = conn.execute(
        "SELECT id, type, content, metadata FROM nodes WHERE session_id=? AND lower(content) LIKE ?",
        (sid, f"%{q}%")
    ).fetchall()
    print(f"\n✦ Search results for {query!r} ({len(rows)} found):")
    for r in rows[:15]:
        meta = {}
        try:
            meta = json.loads(r["metadata"])
        except Exception:
            pass
        zone_label = meta.get("label", meta.get("zone_id", ""))
        print(f"  [{r['type']}] {r['content'][:100]}")


COMMANDS = {
    "zone": (cmd_zone, "zone <ID>     — full zone detail"),
    "near": (cmd_near, "near <ID>     — zones near X in taste-space"),
    "unexplored": (cmd_unexplored, "unexplored    — low-engagement zones closest to comfort zone"),
    "frontier": (cmd_frontier, "frontier      — well-explored zones with unexplored neighbors"),
    "search": (cmd_search, "search <text> — full-text search across all nodes"),
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python3 explore_taste.py <command> [args]")
        for desc in [v[1] for v in COMMANDS.values()]:
            print(f"  {desc}")
        sys.exit(0)

    cmd = sys.argv[1]
    arg = sys.argv[2] if len(sys.argv) > 2 else ""
    COMMANDS[cmd][0](arg) if arg else COMMANDS[cmd][0]()
