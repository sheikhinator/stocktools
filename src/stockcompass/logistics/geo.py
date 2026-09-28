"""Geography that needs no internet: Pakistani cities, approximate store points, road distances between the big
cities (to turn a straight line into a realistic road distance), and reading coordinates out of anything a user
pastes (a Google Maps link, "31.52, 74.35", a plus code is not supported)."""

from __future__ import annotations

import math
import re

# city: (lat, lng, other spellings)
CITIES: dict[str, tuple[float, float, tuple[str, ...]]] = {
    "Lahore": (31.5204, 74.3587, ("LHR", "LAH", "LHE")),
    "Karachi": (24.8607, 67.0011, ("KHI", "KCH", "KARACHI CITY")),
    "Islamabad": (33.6844, 73.0479, ("ISB", "ISL")),
    "Rawalpindi": (33.5651, 73.0169, ("RWP", "PINDI", "RAWALPINDI CANTT")),
    "Faisalabad": (31.4504, 73.1350, ("FSD", "FAI", "LYALLPUR")),
    "Multan": (30.1575, 71.5249, ("MUX", "MUL")),
    "Peshawar": (34.0151, 71.5249, ("PEW", "PSH")),
    "Quetta": (30.1798, 66.9750, ("UET", "QTA")),
    "Gujranwala": (32.1877, 74.1945, ("GRW", "GUJ")),
    "Sialkot": (32.4945, 74.5229, ("SKT",)),
    "Hyderabad": (25.3960, 68.3578, ("HYD",)),
    "Bahawalpur": (29.3544, 71.6911, ("BWP",)),
    "Sargodha": (32.0740, 72.6861, ("SGD",)),
    "Sukkur": (27.7052, 68.8574, ("SKZ",)),
    "Abbottabad": (34.1688, 73.2215, ("ATD",)),
    "Gujrat": (32.5731, 74.0789, ("GRT",)),
    "Sahiwal": (30.6682, 73.1114, ()),
    "Sheikhupura": (31.7167, 73.9850, ()),
    "Kasur": (31.1187, 74.4460, ()),
    "Okara": (30.8138, 73.4534, ()),
    "Rahim Yar Khan": (28.4212, 70.2989, ("RYK",)),
    "Jhelum": (32.9425, 73.7257, ()),
    "Mardan": (34.1989, 72.0231, ()),
    "Dera Ghazi Khan": (30.0561, 70.6348, ("DG KHAN", "DGK")),
    "Dera Ismail Khan": (31.8314, 70.9019, ("DI KHAN", "DIK")),
    "Larkana": (27.5570, 68.2264, ()),
    "Nawabshah": (26.2442, 68.4100, ("SHAHEED BENAZIRABAD",)),
    "Mirpur": (33.1478, 73.7517, ("MIRPUR AJK",)),
    "Muzaffarabad": (34.3700, 73.4711, ()),
    "Gilgit": (35.9208, 74.3080, ()),
    "Wah Cantt": (33.7715, 72.7512, ("WAH",)),
    "Taxila": (33.7463, 72.7887, ()),
    "Attock": (33.7667, 72.3598, ()),
    "Chiniot": (31.7200, 72.9800, ()),
    "Jhang": (31.2681, 72.3181, ()),
    "Mandi Bahauddin": (32.5836, 73.4917, ()),
    "Hafizabad": (32.0714, 73.6883, ()),
    "Narowal": (32.1020, 74.8730, ()),
    "Murree": (33.9070, 73.3943, ()),
    "Gwadar": (25.1264, 62.3225, ()),
    "Mingora": (34.7717, 72.3600, ("SWAT",)),
    "Kohat": (33.5869, 71.4429, ()),
    "Nowshera": (34.0153, 71.9747, ()),
    "Khanewal": (30.3017, 71.9321, ()),
    "Vehari": (30.0445, 72.3556, ()),
    "Pakpattan": (30.3436, 73.3860, ()),
    "Bahawalnagar": (29.9985, 73.2527, ()),
    "Toba Tek Singh": (30.9709, 72.4827, ()),
    "Muridke": (31.8021, 74.2550, ()),
    "Kamoke": (31.9744, 74.2244, ()),
    "Daska": (32.3243, 74.3500, ()),
    "Wazirabad": (32.4436, 74.1200, ()),
    "Lodhran": (29.5339, 71.6324, ()),
    "Hub": (25.0470, 66.8870, ()),
    "Jamshoro": (25.4304, 68.2809, ()),
    "Thatta": (24.7461, 67.9235, ()),
}

# Road distances (km) between big cities by the usual truck route (motorways where they exist). They calibrate
# the straight-line estimate when there is no internet: the same detour factor is used for any two points in
# those two cities.
CITY_ROAD_KM: dict[frozenset, float] = {frozenset(k): v for k, v in [
    (("Lahore", "Islamabad"), 375), (("Lahore", "Rawalpindi"), 380), (("Lahore", "Faisalabad"), 185),
    (("Lahore", "Gujranwala"), 70), (("Lahore", "Sialkot"), 130), (("Lahore", "Multan"), 340),
    (("Lahore", "Karachi"), 1210), (("Lahore", "Peshawar"), 510), (("Lahore", "Sargodha"), 190),
    (("Lahore", "Sheikhupura"), 40), (("Lahore", "Kasur"), 55), (("Lahore", "Sahiwal"), 170),
    (("Islamabad", "Rawalpindi"), 20), (("Islamabad", "Peshawar"), 185), (("Islamabad", "Faisalabad"), 305),
    (("Islamabad", "Gujranwala"), 225), (("Islamabad", "Karachi"), 1415), (("Islamabad", "Multan"), 540),
    (("Islamabad", "Abbottabad"), 125), (("Islamabad", "Sialkot"), 250), (("Rawalpindi", "Gujranwala"), 210),
    (("Rawalpindi", "Faisalabad"), 300), (("Karachi", "Hyderabad"), 165), (("Karachi", "Multan"), 900),
    (("Karachi", "Faisalabad"), 1140), (("Karachi", "Gujranwala"), 1270), (("Karachi", "Quetta"), 690),
    (("Karachi", "Sukkur"), 470), (("Hyderabad", "Sukkur"), 330), (("Faisalabad", "Gujranwala"), 165),
    (("Faisalabad", "Multan"), 240), (("Faisalabad", "Sargodha"), 95), (("Gujranwala", "Sialkot"), 60),
    (("Multan", "Bahawalpur"), 100), (("Multan", "Peshawar"), 700), (("Faisalabad", "Peshawar"), 480),
]}

# Approximate store points (mall / area). Shown as "approximate" until someone drags the pin to the exact spot.
STORE_POINTS: dict[str, tuple[float, float]] = {
    "500": (31.5316, 74.3657),    # Fortress Stadium, Lahore Cantt
    "502": (33.5238, 73.1576),    # Giga Mall / WTC, DHA 2, Islamabad
    "503": (31.4674, 74.2656),    # Emporium Mall, Johar Town, Lahore
    "504": (31.4712, 74.3553),    # Packages Mall, Walton Road, Lahore
    "505": (24.9325, 67.0870),    # Lucky One Mall, Karachi
    "506": (31.4149, 73.0993),    # Lyallpur Galleria, Faisalabad
    "P03": (32.1650, 74.1830),    # Gujranwala
    "P06": (33.7040, 72.9690),    # D-12, Islamabad
    "P07": (31.3900, 74.2400),    # DHA Rahbar (Phase 11), Lahore
    "P08": (31.4705, 74.4790),    # DHA Phase 7, Lahore
    "P09": (31.5150, 74.3990),    # Askari 10, Lahore
    "PA6": (31.5380, 74.4520),    # Paragon City, Lahore
}


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line km between two (lat, lng) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _key(s: str) -> str:
    return re.sub(r"[^A-Z0-9 ]+", " ", (s or "").upper()).strip()


_CITY_INDEX: dict[str, str] = {}
for _n, (_la, _lo, _al) in CITIES.items():
    _CITY_INDEX[_key(_n)] = _n
    for _a in _al:
        _CITY_INDEX[_key(_a)] = _n


def city_of(text: str) -> str | None:
    """The city named in a text ("Plot 12, Sundar Industrial Estate, Lahore" -> Lahore)."""
    k = _key(text)
    if not k:
        return None
    if k in _CITY_INDEX:
        return _CITY_INDEX[k]
    words = k.split()
    for n in (3, 2, 1):                       # longest names first ("Rahim Yar Khan" before "Khan")
        for i in range(len(words) - n + 1):
            c = _CITY_INDEX.get(" ".join(words[i:i + n]))
            if c and (n > 1 or len(words[i]) > 3):
                return c
    return None


def city_point(text: str) -> tuple[float, float] | None:
    c = city_of(text)
    return (CITIES[c][0], CITIES[c][1]) if c else None


def nearest_city(p: tuple[float, float]) -> str:
    return min(CITIES, key=lambda c: haversine(p, CITIES[c][:2]))


_COORD_PATTERNS = [
    r"@(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)",               # google.com/maps/@31.52,74.35,15z
    r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)",              # place links
    r"[?&](?:q|query|ll|center|destination|daddr)=(-?\d{1,2}\.\d+)(?:,|%2C)\s*(-?\d{1,3}\.\d+)",
    r"^\s*\(?(-?\d{1,2}\.\d{3,})\s*[, ]\s*(-?\d{1,3}\.\d{3,})\)?\s*$",   # "31.5204, 74.3587"
]


def parse_coords(text: str) -> tuple[float, float] | None:
    """(lat, lng) from a Google Maps / OpenStreetMap link or typed coordinates; None if there are none."""
    s = (text or "").strip()
    for rx in _COORD_PATTERNS:
        m = re.search(rx, s, re.I)
        if m:
            la, lo = float(m.group(1)), float(m.group(2))
            if 20 <= la <= 40 and 58 <= lo <= 80:
                return la, lo
            if 20 <= lo <= 40 and 58 <= la <= 80:            # written lng, lat
                return lo, la
            if -90 <= la <= 90 and -180 <= lo <= 180:
                return la, lo
    m = re.search(r"#map=\d+/(-?\d+\.\d+)/(-?\d+\.\d+)", s)    # openstreetmap.org/#map=15/31.52/74.35
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def in_pakistan(p: tuple[float, float] | None) -> bool:
    return bool(p) and 23.0 <= p[0] <= 37.5 and 60.5 <= p[1] <= 78.0


def road_factor(a: tuple[float, float], b: tuple[float, float]) -> float:
    """How much longer the road is than the straight line, for these two points."""
    straight = haversine(a, b)
    if straight < 30:
        return 1.35                           # inside a city: streets, one-ways, U-turns
    ca, cb = nearest_city(a), nearest_city(b)
    known = CITY_ROAD_KM.get(frozenset((ca, cb)))
    if known and ca != cb:
        base = haversine(CITIES[ca][:2], CITIES[cb][:2])
        if base > 5:
            return max(1.05, min(1.8, known / base))
    return 1.25
