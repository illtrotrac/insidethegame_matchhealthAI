"""A fictional eight-club league: club identities, playing styles and the
fixture schedule. Deterministic; no LLM.

Names are invented to *sound* like an English league table (City, Rovers,
Albion...) without referring to any real club, place-club pairing or player.
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Club:
    name: str
    style: str             # one-line label for overlays and storylines
    strength: float        # passing reliability + finishing, 0..1
    press: float           # 0 sits off .. 1 relentless high press
    tempo: float           # 0 patient build-up .. 1 quick, vertical
    directness: float      # 0 short passing .. 1 long balls
    players: tuple[str, ...] = ()  # starting XI: GK, RB, CB, CB, LB, DM, CM, CM, RW, ST, LW
    bench: tuple[str, ...] = ()    # five substitutes


POSITIONS = ("GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW")


# Riverside and Northgate keep their original rosters so existing tests and
# stored moments still read the same.
_FIXED_ROSTERS = {
    "Riverside FC": (
        "A. Okafor", "L. Brandt", "M. Silva", "J. Kowalski", "T. Reyes", "K. Haddad",
        "S. Lindqvist", "D. Mensah", "R. Takeda", "E. Novak", "C. Duarte",
    ),
    "Northgate United": (
        "P. Varga", "H. Osei", "N. Petrov", "G. Moreau", "I. Santos", "B. Achterberg",
        "F. Kamara", "O. Castillo", "Y. Park", "V. Ricci", "Z. Adeyemi",
    ),
}

_SURNAMES = [
    "Abara", "Lund", "Ferreira", "Nowak", "Quinlan", "Bakker", "Sorensen", "Okorafor",
    "Hartley", "Moretti", "Ivanov", "Kovac", "Okonjo", "Pereira", "Ashworth", "Brennan",
    "Castell", "Dorsey", "Eklund", "Farrow", "Gallo", "Halvorsen", "Ibarra", "Jansen",
    "Kearney", "Lopes", "Mbatha", "Nilsen", "Oduya", "Pellucci", "Quist", "Rautio",
    "Sandoval", "Tiernan", "Uchida", "Vukas", "Whitlow", "Yilmaz", "Zelenko", "Arkwright",
    "Bonsu", "Cardoso", "Delacroix", "Esposito", "Fenwick", "Grieve", "Holloway", "Iversen",
    "Jovanovic", "Kessler", "Lindgren", "Maddox", "Nakamura", "Ortega", "Prescott", "Rudd",
    "Strand", "Tamura", "Underhill", "Valdez", "Wexford", "Yawson", "Ziegler", "Amadi",
    "Blackwood", "Cotterill", "Dunmore", "Ellery", "Foley", "Gunnarsson", "Haskins", "Ilori",
    "Juric", "Kilbride", "Lacey", "Mendel", "Norrie", "Ostrowski", "Pickard", "Rasmussen",
    "Sefton", "Tanko", "Varela", "Wakefield", "Asante", "Brightmore", "Crane", "Dossou",
    "Aldous", "Birkett", "Calloway", "Dinsdale", "Ekwueme", "Fairbairn", "Gorecki", "Hennessy",
    "Ingram", "Jessop", "Kowalczyk", "Larkspur", "Mwangi", "Nordahl", "Oyelaran", "Penhaligon",
    "Quaye", "Rourke", "Saarinen", "Thackeray", "Uwimana", "Vesely", "Wainwright", "Yardley",
    "Zubiri", "Achterlo", "Brannigan", "Corrigan", "Delahunt", "Ellwood",
]
_INITIALS = "ABCDEFGHJKLMNOPRSTVWY"

_CLUB_DEFS = [
    # name, style, strength, press, tempo, directness
    ("Kingsmere City", "Possession kings: slow, patient, suffocating",
     0.64, 0.60, 0.35, 0.25),
    ("Riverside FC", "Neat passing side that builds from the back", 0.56, 0.45, 0.45, 0.35),
    ("Hollowbrook Athletic", "Relentless high press, chaos by design", 0.52, 0.85, 0.70, 0.45),
    ("Ashvale Wanderers", "Sit deep, break fast on the counter", 0.50, 0.25, 0.80, 0.70),
    ("Redfern Albion", "Balanced and hard to beat", 0.49, 0.50, 0.50, 0.50),
    ("Northgate United", "Energetic pressers who live on turnovers", 0.46, 0.70, 0.60, 0.50),
    ("Saltmarsh Rovers", "Direct and physical: long balls, second balls", 0.44, 0.40, 0.55, 0.85),
    ("Port Calder Town", "Low block, frustrate, hope for a set piece", 0.40, 0.20, 0.30, 0.60),
]


def _roster(name: str, used: set[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(starting XI, bench of five)."""
    rng = random.Random(zlib.crc32(name.encode()))  # stable across runs, unlike hash()
    fixed = _FIXED_ROSTERS.get(name)
    taken = {p.split(". ", 1)[1] for r in _FIXED_ROSTERS.values() for p in r}
    pool = [s for s in _SURNAMES if s not in used and s not in taken]
    picks = rng.sample(pool, 5 if fixed else 16)
    used.update(picks)
    names = tuple(f"{rng.choice(_INITIALS)}. {s}" for s in picks)
    return (fixed, names) if fixed else (names[:11], names[11:])


# Kits, fictional like the clubs: (shirt colour, text colour that reads on the
# page's dark base). The page takes its team colours from the two kits on show.
KITS = {
    "Kingsmere City": {"home": ("#5B2A86", "#C9A7FF"), "away": ("#E8B931", "#F2C94C")},
    "Riverside FC": {"home": ("#0F7C7A", "#4FD1C5"), "away": ("#F2F2F2", "#F2F2F2")},
    "Hollowbrook Athletic": {"home": ("#FF7A2E", "#FF8A47"), "away": ("#2F80ED", "#6FA8FF")},
    "Ashvale Wanderers": {"home": ("#1E6B3A", "#5FD39A"), "away": ("#EDE6D6", "#EDE6D6")},
    "Redfern Albion": {"home": ("#C1272D", "#FF6B6B"), "away": ("#1B2A5C", "#8FA8FF")},
    "Northgate United": {"home": ("#1B2A5C", "#7CA4FF"), "away": ("#C6E94B", "#C6E94B")},
    "Saltmarsh Rovers": {"home": ("#1F6FB2", "#5AA9F0"), "away": ("#F4D03F", "#F4D03F")},
    "Port Calder Town": {"home": ("#7A1F3D", "#FF7A9C"), "away": ("#2E7D32", "#7FD35F")},
}
CLASH_DISTANCE = 90  # RGB distance under which two kits are too alike to tell apart


def _rgb(hex_colour: str) -> tuple[int, ...]:
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def _clash(a: str, b: str) -> bool:
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b), strict=True)) ** 0.5 < CLASH_DISTANCE


def match_kits(home: str, away: str) -> dict[str, dict]:
    """The kits on show: the home side in its home kit; the away side in its
    home kit unless the two clash, then in its away kit, as in real football."""
    h, a, worn = KITS[home]["home"], KITS[away]["home"], "home"
    if _clash(h[0], a[0]) or _clash(h[1], a[1]):
        a, worn = KITS[away]["away"], "away"
    return {home: {"kit": "home", "shirt": h[0], "ink": h[1]},
            away: {"kit": worn, "shirt": a[0], "ink": a[1]}}


def _build_league() -> tuple[Club, ...]:
    used: set[str] = set()
    return tuple(Club(n, st, s, p, t, d, *_roster(n, used)) for n, st, s, p, t, d in _CLUB_DEFS)


LEAGUE: tuple[Club, ...] = _build_league()
CLUBS: dict[str, Club] = {c.name: c for c in LEAGUE}


def lineup_for(club: str, matchweek: int) -> tuple[list[str], list[str]]:
    """This matchweek's starting XI and bench. Managers rotate 0-3 outfield
    starters a week (deterministic per club and week); the player rotated in
    takes the starter's position slot (POSITIONS[i])."""
    c = CLUBS[club]
    xi, bench = list(c.players), list(c.bench)
    rng = random.Random(zlib.crc32(f"{club}:{matchweek}".encode()))
    k = rng.choice((0, 1, 1, 2, 2, 3))
    for slot, b in zip(rng.sample(range(1, 11), k), rng.sample(range(len(bench)), k),
                       strict=True):
        xi[slot], bench[b] = bench[b], xi[slot]
    return xi, bench


def schedule() -> list[list[tuple[str, str]]]:
    """Double round robin (circle method): 14 matchweeks of 4 (home, away) fixtures."""
    names = [c.name for c in LEAGUE]
    n = len(names)
    first_half = []
    rot = names[:]
    for rnd in range(n - 1):
        week = []
        for i in range(n // 2):
            a, b = rot[i], rot[n - 1 - i]
            week.append((a, b) if (rnd + i) % 2 == 0 else (b, a))
        first_half.append(week)
        rot = [rot[0], rot[-1], *rot[1:-1]]
    return first_half + [[(b, a) for a, b in week] for week in first_half]


def resolve_club(query: str) -> str:
    """Full club name from a case-insensitive exact, prefix or substring match."""
    q = query.strip().lower()
    for match in (lambda n: n.lower() == q, lambda n: n.lower().startswith(q),
                  lambda n: q in n.lower()):
        hits = [c.name for c in LEAGUE if match(c.name)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"'{query}' is ambiguous: {', '.join(hits)}")
    raise ValueError(f"No club matches '{query}'. Clubs: {', '.join(c.name for c in LEAGUE)}")


def matchweek_of(home: str, away: str) -> int:
    """The matchweek (1-based) in which `home` hosts `away` -- each ordered
    pairing appears exactly once in a double round robin."""
    for week, fixtures in enumerate(schedule()):
        if (home, away) in fixtures:
            return week + 1
    raise ValueError(f"{home} can't play itself")


def fixture_for(seed: int) -> tuple[int, str, str]:
    """(matchweek 1-based, home, away) for the live match of this seed. Never
    matchweek 1, so there's always some season context to tell stories from."""
    weeks = schedule()
    rng = random.Random(seed)
    week = rng.randrange(1, len(weeks))  # index 1..13 -> matchweek 2..14
    home, away = weeks[week][rng.randrange(len(weeks[week]))]
    return week + 1, home, away
