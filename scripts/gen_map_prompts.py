"""
Generate narrative terrain prompts for the 12 taste-zone island images.
Outputs: static/map-pieces/prompts.md

Usage:
    python3 scripts/gen_map_prompts.py

Then paste each prompt into Gemini / Imagen 3 (imagen-3.0-generate-001) at 1024×1024 PNG.
Run through rembg or remove.bg if the background is white.
Save to: static/map-pieces/{ZONE_ID}.png

Design principle:
  Each zone gets NARRATIVE terrain that visually tells the story of the genre —
  desert circuit-board roads for Electronic, enchanted forest for Folk, megacity
  for Sci-Fi, Discworld turtle for Fantasy, etc. The art style is consistent
  antique atlas / hand-painted watercolor across all zones so they composite
  into one unified world map.

  CRITICAL for compositing: every image must have a heavy dark vignette at its
  borders (terrain fades to near-black ocean within ~20% of each edge). This
  allows adjacent zone images to be blended seamlessly without colour seams.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
BRAIN_DATA_PATH = ROOT / "data" / "processed" / "brain_data.json"
LAYOUT_PATH     = ROOT / "config" / "layout.json"
EXEMPLARS_PATH  = ROOT / "config" / "exemplars.json"
OUT_PATH        = ROOT / "static" / "map-pieces" / "prompts.md"

# ── Shared preamble ────────────────────────────────────────────────────────────
PREAMBLE = (
    "Antique fantasy atlas illustration. Hand-painted watercolor with fine ink linework, "
    "aged parchment texture. Top-down aerial map perspective, as if viewed from directly above. "
    "No text labels, no cartouches, no compass roses, no borders, no decorative frames. "
    "Shallow coastal/edge waters rendered with fine hatching and a pale wash fading outward. "
    "Style: 1890s geographical survey plate combined with illustrated fantasy map, museum-quality print. "
    "CRITICAL COMPOSITING REQUIREMENT: The terrain and landmass must be concentrated in the "
    "center of the image. All four edges of the image fade through a gradual dark vignette to "
    "deep near-black ocean water (approximately #091b28) — the outermost 20% of image width on "
    "every side must be this dark ocean transition zone. This allows the image to be composited "
    "edge-to-edge with adjacent zone images without visible colour seams."
)

# ── Per-zone narrative descriptors ────────────────────────────────────────────
ZONE_DESCRIPTORS: dict[str, dict] = {
    "SOUL_JAZZ": {
        "colors": "warm sienna, deep amber, honey gold, terracotta — warm throughout",
        "terrain": (
            "A wide river delta seen from directly above: the main river bends in long "
            "slow curves (like a saxophone phrase) before fanning into an estuary with "
            "marshland and mudflats. A dense circular jazz-club district sits at the river bend — "
            "from above it reads as concentric rings of small round-roofed buildings. "
            "Tributary streams branch off like musical staves. "
            "The river mouth glows amber where it meets the ocean."
        ),
        "texture": (
            "Warm amber and sienna washes dominate the interior. "
            "The river water is deep gold. Marshland hatching is loose and rhythmic. "
            "The club district has a warm glow in its center. "
            "The overall mood: late-night, unhurried, deeply human."
        ),
        "exemplars": "Nina Simone, Bill Withers, Django Reinhardt",
    },
    "FOLK_SINGER": {
        "colors": "deep forest green, sage, mossy grey-green, muted ochre — cool and verdant",
        "terrain": (
            "An ancient enchanted forest seen from directly above. Dense canopy covers most of "
            "the island — the tree crowns form an unbroken dark-green carpet. "
            "In the center, a stone circle clearing is visible (a perfect ring of standing stones). "
            "Narrow winding paths cut through the canopy, one leading to a small round hobbit-hole "
            "mound with a green door just visible. A second clearing reveals a lone figure sitting "
            "on a fallen log — barely a silhouette, but clearly holding a guitar. "
            "Creatures are half-visible at forest edges: a deer, an owl roosting, a fox trail. "
            "A mossy brook winds through."
        ),
        "texture": (
            "Deep forest greens with cool grey-green shadows beneath the canopy. "
            "The stone circle clearing is lighter — pale grey stones on dark grass. "
            "Edges are soft and overgrown, almost moss-covered at the coastline. "
            "Mood: intimate, ancient, handmade, slightly magical."
        ),
        "exemplars": "Bob Dylan, Paul Simon, Leonard Cohen",
    },
    "ELECTRONIC_HIP": {
        "colors": "steel blue, slate grey, charcoal, cool indigo, cracked-earth tan — cold and geometric",
        "terrain": (
            "A vast salt flat / cracked desert seen from directly above. "
            "Perfectly straight roads form an exact circuit-board grid across the terrain — "
            "intersections at right angles, some roads wider (highways), some narrower (traces). "
            "In the center, a massive circular crater dominates (like a subwoofer seen from above), "
            "its concentric rings visible as geological strata. "
            "Industrial dock shapes line one coast — angular, geometric, with loading cranes as "
            "thin parallel lines. Grid-like canal patterns fill a floodplain district. "
            "The cracked desert surface shows a repeating hexagonal cell pattern."
        ),
        "texture": (
            "Cool blue-grey washes on the cracked flats. Strong dark ink lines on the road grid. "
            "The crater rings are precisely drawn. Industrial zones have heavy cross-hatching. "
            "No soft curves anywhere — every edge is deliberate and angular. "
            "Mood: urban, precise, nocturnal, powerful."
        ),
        "exemplars": "DJ Shadow, Bonobo, Parov Stelar",
    },
    "INDIE_WORLD": {
        "colors": "muted violet, dusty rose, warm ochre, olive, slate — eclectic and mismatched",
        "terrain": (
            "An eclectic patchwork port city seen from above. Each neighborhood has a completely "
            "different roof texture and street pattern — one district is a dense medieval tangle "
            "of alleys, another a grid of modernist blocks, another a chaotic organic market. "
            "Three suspension bridges connect mismatched districts over water. "
            "The harbor is packed with small boats of every shape, docked at irregular piers. "
            "At the edges: dense jungle meets a rocky headland meets a sand beach — "
            "multiple biomes converging on one island."
        ),
        "texture": (
            "Each district has its own watercolor palette — warm ochre for one, dusty violet "
            "for another, olive-grey for the third. They sit next to each other without blending. "
            "Coastline is irregular and surprising. Overall mood: layered, curious, "
            "globally influenced, slightly chaotic but alive."
        ),
        "exemplars": "dEUS, Eels, Beirut",
    },
    "DRAMA": {
        "colors": "deep crimson, burgundy, ash grey, charcoal — heavy, contrasty, bleak",
        "terrain": (
            "Nordic fjord landscape from directly above. Sheer fjord walls create deep shadowed "
            "gorges cutting inland from the coast — from above they read as dark chasms. "
            "A single isolated farmstead sits on a high plateau above the fjords — "
            "one small building, one field, surrounded by nothing. "
            "Storm cloud shadows are visible as dark patches on the terrain below. "
            "A single narrow road leads from the farmstead to a black sand beach on one coast, "
            "then stops. The opposite coast is pure sheer cliff."
        ),
        "texture": (
            "Heavy atmospheric shadows dominate. The fjord gorges are near-black. "
            "The plateau is pale grey-ash. The farmstead field is a single warm ochre rectangle "
            "in a sea of cold grey. Storm shadow washes are dark blue-grey. "
            "Mood: Bergman, Cassavetes — isolated, emotionally intense, unsparing."
        ),
        "exemplars": "Bergman, Cassavetes, Wong Kar-Wai",
    },
    "CRIME_THRILLER": {
        "colors": "dark slate, iron grey, near-black shadow, deep navy — low-key and nocturnal",
        "terrain": (
            "Rain-soaked industrial docklands at night, seen from above. "
            "A labyrinthine canal system branches through the interior — "
            "waterways split and reconnect in complex patterns. "
            "Warehouses form dark rectangular blocks along the waterfront. "
            "From one warehouse, a single lit window glows — the only warm light in the whole image. "
            "Narrow alleys form a maze between the warehouse blocks. "
            "At the coast: shadowed sea caves at the base of dark cliffs, accessible only by water. "
            "A bridge is reflected in the canal below."
        ),
        "texture": (
            "Near-black washes everywhere. The canal water reflects dim light. "
            "Heavy ink linework on the warehouse edges and alley walls. "
            "The single lit window is a tiny amber rectangle. "
            "The overall image reads as very dark with subtle detail emerging from shadow. "
            "Mood: Hitchcock, Coen Brothers, Michael Mann — dangerous, complex, watching you."
        ),
        "exemplars": "Hitchcock, Coen Brothers, Michael Mann",
    },
    "ARTHOUSE": {
        "colors": "olive drab, moss, faded gold, muted sage, bone white — sparse, painterly",
        "terrain": (
            "Dreamlike empty plains seen from above. "
            "One single perfectly straight road runs from one edge of the island to the other — "
            "it goes nowhere, ends at water on both sides. "
            "A mirror-flat lake in the center perfectly reflects the sky (painted as pure pale wash). "
            "Near the lake: a stone staircase rises from the flat ground and leads to nothing — "
            "it just stops in mid-air (the steps are visible from above as a rectangle with shadow). "
            "Flat-topped mesas at the edges with perfectly vertical walls. "
            "Sparse — most of the terrain is just empty plain."
        ),
        "texture": (
            "Extremely sparse use of color. The plain is bone-white with faint ochre washes. "
            "The road is a single dark ink line. The lake is a pale silver mirror. "
            "The mesa walls have strong geometric shadow. "
            "Layers of translucent wash create depth in the empty plain. "
            "Mood: Tarkovsky, Godard, Lynch — the emptiness is the point."
        ),
        "exemplars": "Tarkovsky, Godard, David Lynch",
    },
    "SCI_FI": {
        "colors": "deep teal, electric cyan, silver-white, cool grey — alien and precise",
        "terrain": (
            "A megacity sprawl seen from directly above, like Coruscant or Trantor. "
            "The entire landmass is covered in dense urban grid — city blocks packed edge to edge, "
            "with thin monorail lines crossing at elevated level (drawn as thin silver threads). "
            "At the coast: spacecraft docking bays cut into the shoreline — "
            "each bay is a long rectangular notch with mooring lines visible as thin parallel marks, "
            "and one large docked vessel is visible in the biggest bay (a sleek shape, "
            "like a Federation starship seen from above). "
            "Cooling towers in the industrial district read as perfect circles from above. "
            "At the center: a perfectly circular crater lake — the only natural feature remaining."
        ),
        "texture": (
            "Cool cyan washes on the urban grid. Silver highlights on the monorail lines. "
            "The docking bays are deep teal. The starship outline is silver-white. "
            "The crater lake is electric cyan at its center fading to grey. "
            "Mood: Dan Simmons, Arthur C. Clarke, Kubrick — "
            "vast, cold, organized, slightly inhuman."
        ),
        "exemplars": "Dan Simmons, Arthur C. Clarke, Kubrick",
    },
    "FANTASY_COMEDY": {
        "colors": "warm ochre, straw yellow, gentle green, soft terracotta, sky blue — cheerful and whimsical",
        "terrain": (
            "Discworld-inspired: a flat disc of land sits at the center of the image, "
            "its circular edge clearly defined. At the four cardinal points of the disc, "
            "the tops of four enormous elephants are visible from above — "
            "massive grey-brown ovals with tiny ear flaps and tusk tips. "
            "Below the disc edge (at the very bottom of the image) "
            "the top of the Great A'Tuin the turtle is faintly visible — "
            "its enormous shell pattern just visible at the image bottom. "
            "On the disc itself: an Ankh-Morpork-style chaotic city (winding streets, "
            "a river cutting through), green hills, tiny broomstick silhouettes in the sky "
            "(witches, barely visible as small curved marks), and a wizarding tower."
        ),
        "texture": (
            "Warm, golden, afternoon-light washes. The disc edge is clearly defined. "
            "Elephant skin is grey-brown, cheerfully rendered. "
            "The city is warm ochre with winding streets. "
            "Hills are round and inviting. The broomstick silhouettes are tiny but recognizable. "
            "Mood: Terry Pratchett, Douglas Adams, Miyazaki — "
            "funny, humanist, delightfully absurd."
        ),
        "exemplars": "Terry Pratchett, Douglas Adams, Miyazaki",
    },
    "ACTION_ADV": {
        "colors": "rust red, volcanic black, burnt orange, deep sienna — high contrast, dramatic",
        "terrain": (
            "A rugged volcanic archipelago seen from above. "
            "Multiple volcanic peaks dominate — the tallest has a smoking caldera, "
            "visible as a dark circular pit with ash radiating outward in grey streaks. "
            "Exposed lava fields cover the slopes (black-on-rust texture). "
            "The terrain is visibly scarred by conflict: parallel lines of battle trenches "
            "are carved into one hillside, a ruined fortress sits on a headland. "
            "The coastline is pure jagged cliff — no beaches, nowhere safe to land. "
            "One rope bridge connects two peaks above a deep gorge."
        ),
        "texture": (
            "High contrast — volcanic black against rust red and burnt orange. "
            "Strong, confident ink linework on every edge. "
            "Ash streaks from the caldera are heavy grey washes. "
            "The trench lines are precise parallel marks. The ruined fortress is a dark hulk. "
            "Mood: Kurosawa, John Huston — physical, elemental, every inch hard-won."
        ),
        "exemplars": "Kurosawa, John Huston, Mad Max",
    },
    "ANIMATION": {
        "colors": "jade green, bright cyan, vivid teal, clean white highlights — vivid and graphic",
        "terrain": (
            "Ghibli-inspired landscape from directly above. "
            "In the center: one enormous ancient tree (a baobab or forest spirit tree) "
            "dominates — its crown is a massive dark-green circle, its exposed roots spread "
            "outward like rivers. "
            "Rolling bright green hills surround it, with bold clean contour lines. "
            "A clear bright blue lagoon sits to one side — "
            "perfectly circular, impossibly vivid cyan. "
            "On one hill: a castle that seems to be walking (moving castle — visible as "
            "a building with mechanical legs, seen from above as a rectangular shape "
            "with thin leg marks below it). "
            "Clean graphic shapes throughout — this looks illustrated, not surveyed."
        ),
        "texture": (
            "Vivid saturated watercolor washes — the greenest greens, the most cyan cyan. "
            "Bold clean contour lines on every hill. The ancient tree crown is very dark green. "
            "The lagoon is flat vivid cyan. The castle has precise ink linework. "
            "Mood: Miyazaki, Pixar, Laika — joyful, crafted, alive."
        ),
        "exemplars": "Miyazaki, Pixar, Laika",
    },
    "HISTORY": {
        "colors": "bronze, umber, dusty terracotta, aged parchment, iron grey — timeworn",
        "terrain": (
            "An island where multiple civilizations have built on top of each other, "
            "all visible from above at once. "
            "At the center: a Roman amphitheater (oval, clearly recognizable from above). "
            "Around it: the walls of a medieval castle, partially collapsed. "
            "At the coast: WWI-era parallel trenches carved across a headland — "
            "precise zigzag lines still visible in the terrain. "
            "On the cliff faces: geological strata are exposed as horizontal bands of color "
            "(different eras visible as layers). "
            "An overgrown river valley shows archaeological excavation grids — "
            "thin square divisions marked in the soil."
        ),
        "texture": (
            "Aged parchment tones throughout. The amphitheater is drawn with careful hatching. "
            "Castle walls are heavy dark stone. Trench zigzags are precise ink marks. "
            "Geological strata on cliffs show distinct color bands: ochre, umber, grey, rust. "
            "Excavation grids are thin pale lines. "
            "Mood: Ken Burns, Terrence Malick — the weight of time on every surface."
        ),
        "exemplars": "Ken Burns, Terrence Malick, Rome (HBO)",
    },
}


def build_prompt(zone_id: str, desc: dict, exemplars_override: list[str] | None = None) -> str:
    exemplars = exemplars_override or desc.get("exemplars", "")
    if isinstance(exemplars, list):
        exemplars = ", ".join(exemplars[:3])
    exemplar_line = f"The atmosphere of the island evokes: {exemplars}. " if exemplars else ""
    return (
        f"{PREAMBLE} "
        f"Color palette: {desc['colors']}. "
        f"Terrain: {desc['terrain']} "
        f"Visual texture and mood: {desc['texture']} "
        f"{exemplar_line}"
        f"The island must feel like a place a person could explore — "
        f"rich with detail at the center, fading into dark ocean at all edges."
    )


def load_zones() -> list[dict]:
    if BRAIN_DATA_PATH.exists():
        zones = json.loads(BRAIN_DATA_PATH.read_text())
        return [{"id": z["id"], "label": z["label"], "exemplars": z.get("exemplars", [])}
                for z in zones]
    layout = json.loads(LAYOUT_PATH.read_text())
    ex = json.loads(EXEMPLARS_PATH.read_text())
    return [
        {"id": n["id"], "label": n["label"], "exemplars": ex.get(n["id"], [])}
        for n in layout["nodes"]
    ]


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    zones = load_zones()

    lines: list[str] = [
        "# Taste Map — Narrative Terrain Prompts (v2)",
        "",
        "**Concept:** Each zone is a place that *tells the story* of the genre —",
        "desert circuit roads for Electronic, enchanted forest for Folk,",
        "Discworld turtle for Fantasy, megacity for Sci-Fi, etc.",
        "",
        "**How to use:**",
        "1. Copy the full prompt for each zone.",
        "2. Paste into Gemini / Imagen 3 (`imagen-3.0-generate-001`) at 1024×1024, PNG.",
        "3. If background is white: run through `rembg` or remove.bg.",
        "4. Save to the path shown.",
        "",
        "**Critical:** The dark-edge vignette is embedded in every prompt.",
        "This allows `scripts/composite_map.py` to blend all 12 images into one world map.",
        "",
        "**Test first:** Generate SOUL_JAZZ + ELECTRONIC_HIP + FOLK_SINGER first (most",
        "different palettes). Share screenshots. Once blending looks right, generate the rest.",
        "",
        "---",
        "",
    ]

    for zone in zones:
        zid = zone["id"]
        desc = ZONE_DESCRIPTORS.get(zid)
        if not desc:
            print(f"Warning: no descriptor for {zid}, skipping")
            continue

        ex_override = zone["exemplars"] if zone["exemplars"] else None
        prompt = build_prompt(zid, desc, ex_override)
        save_path = f"static/map-pieces/{zid}.png"

        lines += [
            f"## {zid} — {zone['label']}",
            "",
            f"**Save to:** `{save_path}`",
            "",
            "**Prompt:**",
            "",
            f"> {prompt}",
            "",
            "---",
            "",
        ]

    OUT_PATH.write_text("\n".join(lines))
    print(f"Wrote {OUT_PATH} with {len(zones)} zone prompts")


if __name__ == "__main__":
    main()
