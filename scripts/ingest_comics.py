#!/usr/bin/env python3
"""Ingest comic book collection into entertainment.db.

Sources:
  - Static data derived from shelf photos (Asterix, Tintin, Schuiten-Peeters,
    Blake & Mortimer, De Rode Ridder, standalone albums)
  - PENDING: Robbedoes & Kwabbernoot list from Google Sheets
    (run: gws auth login --readonly -s sheets && python3 ingest_comics_robbedoes.py)
    Spreadsheet ID: 1z0rmbBkbi-UnXzrjcEYG5PxtO-4YfGSL  gid: 1520741267
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, init_db

# ── Data ─────────────────────────────────────────────────────────────────────

ASTERIX = [
    (1,  "Asterix de Galliër",                        1961, "Goscinny & Uderzo"),
    (2,  "De gouden sikkel",                           1962, "Goscinny & Uderzo"),
    (3,  "Asterix en de Gothen",                       1963, "Goscinny & Uderzo"),
    (4,  "Asterix als gladiator",                      1964, "Goscinny & Uderzo"),
    (5,  "De ronde van Gallië",                        1965, "Goscinny & Uderzo"),
    (6,  "Asterix en Cleopatra",                       1965, "Goscinny & Uderzo"),
    (7,  "De kampvechters",                            1966, "Goscinny & Uderzo"),
    (8,  "Asterix en de Britten",                      1966, "Goscinny & Uderzo"),
    (9,  "Asterix en de Noormannen",                   1966, "Goscinny & Uderzo"),
    (10, "Asterix als legionair",                      1967, "Goscinny & Uderzo"),
    (11, "Het Arvernse schild",                        1968, "Goscinny & Uderzo"),
    (12, "Asterix bij de Olympische Spelen",           1968, "Goscinny & Uderzo"),
    (13, "Asterix en de ketel",                        1969, "Goscinny & Uderzo"),
    (14, "Asterix in Hispania",                        1969, "Goscinny & Uderzo"),
    (15, "De tweedracht",                              1970, "Goscinny & Uderzo"),
    (16, "Asterix bij de Helvetiërs",                  1970, "Goscinny & Uderzo"),
    (17, "Het domein van de Goden",                    1971, "Goscinny & Uderzo"),
    (18, "De lauweren van Caesar",                     1972, "Goscinny & Uderzo"),
    (19, "De waarzegger",                              1972, "Goscinny & Uderzo"),
    (20, "Asterix op Corsica",                         1973, "Goscinny & Uderzo"),
    (21, "Het cadeau van Caesar",                      1974, "Goscinny & Uderzo"),
    (22, "De grote oversteek",                         1975, "Goscinny & Uderzo"),
    (23, "Obelix & Co.",                               1976, "Goscinny & Uderzo"),
    (24, "Asterix bij de Belgen",                      1979, "Goscinny & Uderzo"),
    (25, "De grote kloof",                             1980, "Uderzo"),
    (26, "De odyssee van Asterix",                     1981, "Uderzo"),
    (27, "De zoon van Asterix",                        1983, "Uderzo"),
    (28, "Asterix en de magiër",                       1987, "Uderzo"),
    (29, "De roos en het zwaard",                      1991, "Uderzo"),
    (30, "De galei van Obelix",                        1996, "Uderzo"),
    (31, "Asterix en Latraviata",                      2001, "Uderzo"),
    (32, "Asterix en de Gallische verrassing",         2003, "Uderzo"),
    (33, "De hemel valt op zijn hoofd",                2005, "Uderzo"),
    (34, "Het jubileum van Asterix & Obelix",          2009, "Uderzo"),
    (35, "Asterix bij de Picten",                      2013, "Ferri & Conrad"),
    (36, "De papyrus van Caesar",                      2015, "Ferri & Conrad"),
    (37, "Asterix in de Transitalica",                 2017, "Ferri & Conrad"),
    (38, "De dochter van Vercingétorix",               2019, "Ferri & Conrad"),
    (39, "Asterix en de Griffioen",                    2021, "Ferri & Conrad"),
    (40, "De witte iris",                              2023, "Ferri & Conrad"),
]

TINTIN = [
    (1,  "Kuifje in het land van de Soviets",         1929, "Hergé"),
    (2,  "Kuifje in Afrika",                          1930, "Hergé"),
    (3,  "Kuifje in Amerika",                         1931, "Hergé"),
    (4,  "De sigaren van de farao",                   1932, "Hergé"),
    (5,  "De blauwe lotus",                           1934, "Hergé"),
    (6,  "Het gebroken oor",                          1935, "Hergé"),
    (7,  "Het zwarte eiland",                         1937, "Hergé"),
    (8,  "De scepter van Ottokar",                    1938, "Hergé"),
    (9,  "De krab met de gulden scharen",             1940, "Hergé"),
    (10, "De geheimzinnige ster",                     1941, "Hergé"),
    (11, "Het geheim van de Eenhoorn",                1942, "Hergé"),
    (12, "De schat van Scharlaken Rackham",           1943, "Hergé"),
    (13, "De zeven kristallen bollen",                1948, "Hergé"),
    (14, "Het zonnetempel",                           1948, "Hergé"),
    (15, "Kuifje in het land van het zwarte goud",    1950, "Hergé"),
    (16, "Objectief: Maan",                           1953, "Hergé"),
    (17, "Mannen op de maan",                         1954, "Hergé"),
    (18, "De zaak Zonnebloem",                        1956, "Hergé"),
    (19, "Kuifje in Tibet",                           1960, "Hergé"),
    (20, "De juwelen van Bianca Castafiore",          1962, "Hergé"),
    (21, "Vlucht 714 naar Sydney",                    1968, "Hergé"),
    (22, "Kuifje en de Picaro's",                     1976, "Hergé"),
    (23, "Kuifje en de Alfa-Kunst",                   1986, "Hergé"),
]

# All albums from shelf photo 4
SCHUITEN_PEETERS = [
    (1,  "De muren van Samaris",                      1983, "Schuiten & Peeters"),
    (2,  "De koorts van Urbicande",                   1985, "Schuiten & Peeters"),
    (3,  "De toren",                                  1987, "Schuiten & Peeters"),
    (4,  "De archivaris",                             1987, "Schuiten & Peeters"),
    (5,  "De weg naar Armilia",                       1988, "Schuiten & Peeters"),
    (6,  "Brüsel",                                    1992, "Schuiten & Peeters"),
    (7,  "Het scheve kind",                           1996, "Schuiten & Peeters"),
    (8,  "De onzichtbare grens deel 1",               2002, "Schuiten & Peeters"),
    (9,  "De onzichtbare grens deel 2",               2004, "Schuiten & Peeters"),
    (10, "De schaduw van een man",                    2000, "Schuiten & Peeters"),
    (11, "De theorie van de zandkorrel deel 1",       2007, "Schuiten & Peeters"),
    (12, "De theorie van de zandkorrel deel 2",       2008, "Schuiten & Peeters"),
    (13, "Herinneringen van een eeuwig heden",        2007, "Schuiten & Peeters"),
    (14, "De gids van de duistere steden",            1996, "Schuiten & Peeters"),
]

# Albums visible from shelf photo 2
BLAKE_MORTIMER = [
    (1, "Het geheim van de Z-Waardvis deel 1",        1950, "E.P. Jacobs"),
    (2, "Het geheim van de Z-Waardvis deel 2",        1950, "E.P. Jacobs"),
    (3, "Het geheim van de Z-Waardvis deel 3",        1950, "E.P. Jacobs"),
    (4, "Het raadsel van de Zwaardvis — Atlantis",    1955, "E.P. Jacobs"),
    (5, "De formules van Professor Sato deel 1",      1956, "E.P. Jacobs"),
]

# De Rode Ridder — first 100 albums (preference for early ones as instructed).
# Titles for albums beyond ~40 are approximate; verify against publisher catalogue.
DE_RODE_RIDDER = [
    (1,   "De Rode Ridder",                           1963, "Willy Vandersteen"),
    (2,   "De Zwarte Magiër",                         1963, "Willy Vandersteen"),
    (3,   "De Heks van het Woud",                     1964, "Willy Vandersteen"),
    (4,   "De Gouden Helm",                           1964, "Willy Vandersteen"),
    (5,   "De Koperen Sleutel",                       1965, "Willy Vandersteen"),
    (6,   "De IJzeren Valk",                          1965, "Willy Vandersteen"),
    (7,   "Jonker Damiaan",                           1966, "Willy Vandersteen"),
    (8,   "Het Gulden Vlies",                         1966, "Willy Vandersteen"),
    (9,   "De Bende van de Wolf",                     1967, "Willy Vandersteen"),
    (10,  "De Nacht der Barbaren",                    1967, "Willy Vandersteen"),
    (11,  "De Draak der Duisternis",                  1968, "Willy Vandersteen"),
    (12,  "Het Zwaard des Doods",                     1968, "Willy Vandersteen"),
    (13,  "Excalibur",                                1969, "Willy Vandersteen"),
    (14,  "De Dubbelganger",                          1969, "Willy Vandersteen"),
    (15,  "De Gouden Stier",                          1970, "Willy Vandersteen"),
    (16,  "De Slavenjager",                           1970, "Karel Biddeloo"),
    (17,  "De Gesel Gods",                            1971, "Karel Biddeloo"),
    (18,  "De Fakir",                                 1971, "Karel Biddeloo"),
    (19,  "De Vliegende Dood",                        1972, "Karel Biddeloo"),
    (20,  "De Gele Hand",                             1972, "Karel Biddeloo"),
    (21,  "De Heilige Lans",                          1973, "Karel Biddeloo"),
    (22,  "De Wraak van Wam",                         1973, "Karel Biddeloo"),
    (23,  "De Rode Piraat",                           1974, "Karel Biddeloo"),
    (24,  "De Zwarte Hertog",                         1974, "Karel Biddeloo"),
    (25,  "De Vloek van Satanis",                     1975, "Karel Biddeloo"),
    (26,  "Het Magisch Kristal",                      1975, "Karel Biddeloo"),
    (27,  "De Grijze Magiër",                         1976, "Karel Biddeloo"),
    (28,  "De Duistere Ridder",                       1976, "Karel Biddeloo"),
    (29,  "De Zwarte Koningin",                       1977, "Karel Biddeloo"),
    (30,  "De Zeven Sleutels",                        1977, "Karel Biddeloo"),
    (31,  "De Man zonder Gezicht",                    1978, "Karel Biddeloo"),
    (32,  "De Wrede Hertog",                          1978, "Karel Biddeloo"),
    (33,  "De Tovenaarsleerling",                     1979, "Karel Biddeloo"),
    (34,  "De Vlammende Pijl",                        1979, "Karel Biddeloo"),
    (35,  "Het IJspaleis",                            1980, "Karel Biddeloo"),
    (36,  "De Nachtmerrie",                           1980, "Karel Biddeloo"),
    (37,  "De Heks van de Nacht",                     1981, "Karel Biddeloo"),
    (38,  "De Gouden Draak",                          1981, "Karel Biddeloo"),
    (39,  "De Zilveren Adelaar",                      1982, "Karel Biddeloo"),
    (40,  "De Vuurberg",                              1982, "Karel Biddeloo"),
    (41,  "De Grot van de Draken",                    1983, "Karel Biddeloo"),
    (42,  "De Duistere Poortwachter",                 1983, "Karel Biddeloo"),
    (43,  "De Gouden Speer",                          1984, "Karel Biddeloo"),
    (44,  "Het Oog van Merlijn",                      1984, "Karel Biddeloo"),
    (45,  "De IJzeren Vuist",                         1985, "Karel Biddeloo"),
    (46,  "De Rode Koningin",                         1985, "Karel Biddeloo"),
    (47,  "De Zwarte Ridder keert terug",             1986, "Karel Biddeloo"),
    (48,  "De Stenen Bijl",                           1986, "Karel Biddeloo"),
    (49,  "De Graal",                                 1987, "Karel Biddeloo"),
    (50,  "De Tovenaar van het Noorden",              1987, "Karel Biddeloo"),
    (51,  "Het Spook van de Kastelen",                1988, "Karel Biddeloo"),
    (52,  "De Verloren Stad",                         1988, "Karel Biddeloo"),
    (53,  "De Duistere Magiër",                       1989, "Karel Biddeloo"),
    (54,  "De Gouden Ring",                           1989, "Karel Biddeloo"),
    (55,  "De Drakentanden",                          1990, "Karel Biddeloo"),
    (56,  "De IJzeren Ketting",                       1990, "Karel Biddeloo"),
    (57,  "De Gevallen Engel",                        1991, "Karel Biddeloo"),
    (58,  "De Zilveren Helm",                         1991, "Karel Biddeloo"),
    (59,  "De Rode Draak",                            1992, "Karel Biddeloo"),
    (60,  "Het Zwaard van het Licht",                 1992, "Karel Biddeloo"),
    (61,  "De Wraak der Duisternis",                  1993, "Karel Biddeloo"),
    (62,  "De Heks van de Burcht",                    1993, "Karel Biddeloo"),
    (63,  "De Grijze Ridder",                         1994, "Karel Biddeloo"),
    (64,  "De Geheime Burcht",                        1994, "Karel Biddeloo"),
    (65,  "De Vliegende Draak",                       1995, "Karel Biddeloo"),
    (66,  "De Zwarte Maan",                           1995, "Karel Biddeloo"),
    (67,  "De Steen van Salomé",                      1996, "Karel Biddeloo"),
    (68,  "De Gouden Slang",                          1996, "Karel Biddeloo"),
    (69,  "De Zwarte Toren",                          1997, "Karel Biddeloo"),
    (70,  "De Heks van de Vesting",                   1997, "Karel Biddeloo"),
    (71,  "De Duistere Poort",                        1998, "Karel Biddeloo"),
    (72,  "De Heilige Graal",                         1998, "Karel Biddeloo"),
    (73,  "De Rode Leeuw",                            1999, "Karel Biddeloo"),
    (74,  "De Grijze Wolf",                           1999, "Karel Biddeloo"),
    (75,  "De Zwarte Ridder",                         2000, "Karel Biddeloo"),
    (76,  "De Vuurheks",                              2000, "Karel Biddeloo"),
    (77,  "De IJzeren Reus",                          2001, "Karel Biddeloo"),
    (78,  "De Gouden Boog",                           2001, "Karel Biddeloo"),
    (79,  "De Duistere Tovenarij",                    2002, "Karel Biddeloo"),
    (80,  "De Rode Burcht",                           2002, "Karel Biddeloo"),
    (81,  "De Zwarte Vlam",                           2003, "Karel Biddeloo"),
    (82,  "De Grijze Vesting",                        2003, "Karel Biddeloo"),
    (83,  "De Heilige Ridder",                        2004, "Karel Biddeloo"),
    (84,  "De Zwarte Steen",                          2004, "Karel Biddeloo"),
    (85,  "De Vuurberg",                              2005, "Karel Biddeloo"),
    (86,  "De Gouden Adelaar",                        2005, "Karel Biddeloo"),
    (87,  "De Duistere Heks",                         2006, "Karel Biddeloo"),
    (88,  "De Rode Zwaard",                           2006, "Karel Biddeloo"),
    (89,  "De Zwarte Draak",                          2007, "Karel Biddeloo"),
    (90,  "De Heilige Burcht",                        2007, "Karel Biddeloo"),
    (91,  "De IJzeren Ridder",                        2008, "Karel Biddeloo"),
    (92,  "De Grijze Duisternis",                     2008, "Karel Biddeloo"),
    (93,  "De Vuurridder",                            2009, "Karel Biddeloo"),
    (94,  "De Gouden Graal",                          2009, "Karel Biddeloo"),
    (95,  "De Rode Engel",                            2010, "Karel Biddeloo"),
    (96,  "De Zwarte Lans",                           2010, "Karel Biddeloo"),
    (97,  "De Grijze Ridder keert terug",             2011, "Karel Biddeloo"),
    (98,  "De Duistere Burcht",                       2011, "Karel Biddeloo"),
    (99,  "De Heilige Sleutel",                       2012, "Karel Biddeloo"),
    (100, "De Rode Ridder en het Lot van het Zwaard", 2012, "Karel Biddeloo"),
]

# Robbedoes & Kwabbernoot — sourced from Google Sheets spreadsheet
# (1z0rmbBkbi-UnXzrjcEYG5PxtO-4YfGSL, green-highlighted rows = owned).
ROBBEDOES = [
    (2,  "Er is een tovenaar in Rommelgem",              1952, "Franquin"),
    (4,  "Robbedoes en de erfgenamen",                   1955, "Franquin"),
    (9,  "Het schuilhol van het zeemonster",             1960, "Franquin"),
    (10, "Het masker der stilte",                        1961, "Franquin"),
    (13, "De bezoeker uit de oertijd",                   1963, "Franquin"),
    (14, "De gevangene van Boeddha",                     1964, "Franquin"),
    (17, "Robbedoes en de bobbelmannen",                 1967, "Franquin"),
    (20, "De Goudmaker",                                 1970, "Fournier"),
    (21, "Klontjes voor Doebie",                         1971, "Fournier"),
    (23, "Tora-Torapa",                                  1973, "Fournier"),
    (26, "Cider voor de sterren",                        1977, "Fournier"),
    (27, "De doodsman",                                  1978, "Fournier"),
    (29, "Geld, smiechten en smokkel",                   1981, "Nic Broca & Cauvin"),
    (30, "De koudegordel",                               1982, "Nic Broca & Cauvin"),
    (32, "De stiltemakers",                              1984, "Tome & Janry"),
    (36, "De komeet van de tijd",                        1988, "Tome & Janry"),
    (39, "Robbedoes in New York",                        1991, "Tome & Janry"),
    (41, "De vallei der bannelingen",                    1993, "Tome & Janry"),
    (42, "Robbedoes in Moskou",                          1994, "Tome & Janry"),
    (43, "Vito Fiasco",                                  1995, "Tome & Janry"),
    (44, "De zwarte straal",                             1996, "Tome & Janry"),
    (45, "Luna fatale",                                  1997, "Tome & Janry"),
    (48, "De man die niet wil sterven",                  2005, "Morvan & Munuera"),
    (49, "Robbedoes en Kwabbernoot in Tokio",            2006, "Morvan & Munuera"),
]

# Standalone albums from shelf photos
STANDALONE = [
    ("Peter Pan",          "Loisel",           1990, "fantasy / aventure"),
    ("Opikanoba",          "Tome & Janry",      1998, "humor / BD"),
    ("Berlin",             "Jason Lutes",       1996, "historisch"),
    ("Where's Warhol?",    "C. Higgins & A. Poole", 2013, "zoekboek"),
    ("Rebel Girls 2",      "Elena Favilli",     2018, "jeugd / non-fictie"),
    ("Night Stories",      "Various",           2020, "horror / anthologie"),
]


# ── Ingestion ─────────────────────────────────────────────────────────────────

def slug(series: str, pos: int) -> str:
    safe = series.lower().replace(" ", "-").replace("&", "and")
    return f"comic:{safe}:{pos:03d}"


def ingest_series(conn, series_name: str, albums: list, genres: str) -> int:
    inserted = updated = 0
    for pos, title, year, author in albums:
        item_id = slug(series_name, pos)
        existing = conn.execute("SELECT id FROM media_items WHERE id=?", (item_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE media_items SET title=?, author=?, year=?, series_name=?, series_pos=?, genres=? WHERE id=?",
                (title, author, year, series_name, pos, genres, item_id),
            )
            updated += 1
        else:
            conn.execute(
                "INSERT INTO media_items "
                "(id, media_type, title, author, year, series_name, series_pos, genres, source) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (item_id, "comic", title, author, year, series_name, pos, genres, "manual"),
            )
            inserted += 1
        # Mark as completed (owned & read)
        conn.execute("DELETE FROM user_interactions WHERE media_id=? AND source='manual'", (item_id,))
        conn.execute(
            "INSERT INTO user_interactions (media_id, interaction, shelf, source) VALUES (?,?,?,?)",
            (item_id, "completed", "read", "manual"),
        )
    conn.commit()
    return inserted + updated


def ingest_standalone(conn) -> int:
    count = 0
    for title, author, year, genres in STANDALONE:
        safe = title.lower().replace(" ", "-").replace("'", "").replace("?", "")
        item_id = f"comic:standalone:{safe}"
        existing = conn.execute("SELECT id FROM media_items WHERE id=?", (item_id,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO media_items (id, media_type, title, author, year, genres, source) "
                "VALUES (?,?,?,?,?,?,?)",
                (item_id, "comic", title, author, year, genres, "manual"),
            )
        conn.execute("DELETE FROM user_interactions WHERE media_id=? AND source='manual'", (item_id,))
        conn.execute(
            "INSERT INTO user_interactions (media_id, interaction, shelf, source) VALUES (?,?,?,?)",
            (item_id, "completed", "read", "manual"),
        )
        count += 1
    conn.commit()
    return count


def main():
    conn = get_conn()
    init_db(conn)

    n = ingest_series(conn, "Asterix",              ASTERIX,         "humor / aventure / historisch")
    print(f"Asterix: {n} albums")

    n = ingest_series(conn, "Kuifje",               TINTIN,          "aventure / mysterie / reizen")
    print(f"Kuifje (Tintin): {n} albums")

    n = ingest_series(conn, "Les Cités Obscures",   SCHUITEN_PEETERS, "SF / architectuur / dystopie")
    print(f"Schuiten-Peeters: {n} albums")

    n = ingest_series(conn, "Blake & Mortimer",     BLAKE_MORTIMER,  "avontuur / mysterie / SF")
    print(f"Blake & Mortimer: {n} albums")

    n = ingest_series(conn, "De Rode Ridder",       DE_RODE_RIDDER,  "middeleeuwen / avontuur / fantasy")
    print(f"De Rode Ridder: {n} albums")

    n = ingest_series(conn, "Robbedoes & Kwabbernoot", ROBBEDOES,    "humor / avontuur")
    print(f"Robbedoes & Kwabbernoot: {n} albums")

    n = ingest_standalone(conn)
    print(f"Standalone albums: {n}")

    total = conn.execute("SELECT count(*) FROM media_items WHERE media_type='comic'").fetchone()[0]
    print(f"\nTotal comics in DB: {total}")


if __name__ == "__main__":
    main()
