"""Curated block/allow list URLs for Blocking → Lists (disabled by default)."""

# Technitium: строка с # в начале = comment / выключенный список
PRESET_BLOCK_LISTS: list[dict[str, str]] = [
    {
        "kind": "block",
        "url": "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
        "note": "StevenBlack — ads, trackers, malware (merged community hosts)",
    },
    {
        "kind": "block",
        "url": "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/hosts/light.txt",
        "note": "HaGeZi Light — ads, trackers, telemetry; light, low breakage",
    },
    {
        "kind": "block",
        "url": "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/hosts/pro.txt",
        "note": "HaGeZi Pro — ads, trackers, malware, scam; recommended default",
    },
    {
        "kind": "block",
        "url": "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/hosts/tif.txt",
        "note": "HaGeZi TIF — malware, phishing, C2, cryptojacking (heavy, needs RAM)",
    },
    {
        "kind": "block",
        "url": "https://small.oisd.nl/",
        "note": "OISD small — ads & trackers; compact set",
    },
    {
        "kind": "block",
        "url": "https://big.oisd.nl/",
        "note": "OISD big — ads & trackers; large set, more false positives",
    },
    {
        "kind": "block",
        "url": "https://urlhaus.abuse.ch/downloads/hostfile/",
        "note": "URLhaus — hosts known for malware downloads (abuse.ch)",
    },
    {
        "kind": "block",
        "url": "https://phishing.army/download/phishing_army_blocklist_extended.txt",
        "note": "Phishing Army — phishing & scam sites (extended)",
    },
    {
        "kind": "block",
        "url": "https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt",
        "note": "AdGuard DNS — ads, trackers, phishing (AdGuard DNS rules)",
    },
    {
        "kind": "block",
        "url": "https://someonewhocares.org/hosts/zero/hosts",
        "note": "SomeoneWhoCares — classic ads & malware hosts",
    },
]


def encode_preset_disabled(item: dict[str, str]) -> str:
    url = item["url"].strip()
    if item.get("kind") == "allow":
        url = "!" + url
    return "#" + url


def merge_presets_disabled(existing: list[str] | None) -> list[str]:
    """Добавить пресеты как #url, не трогая уже присутствующие URL (с # / ! или без)."""
    cur = [str(x).strip() for x in (existing or []) if str(x).strip()]
    known: set[str] = set()
    for line in cur:
        s = line.lstrip("#").strip()
        if s.startswith("!"):
            s = s[1:].strip()
        if s:
            known.add(s.lower())
    out = list(cur)
    for item in PRESET_BLOCK_LISTS:
        key = item["url"].strip().lower()
        if key in known:
            continue
        out.append(encode_preset_disabled(item))
        known.add(key)
    return out
