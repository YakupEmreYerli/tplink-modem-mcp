"""Parse the text log returned by the router's web panel."""

import re


def parse_entries(lines: list[str]) -> list[dict]:
    entries = []
    for line in reversed(lines):
        match = re.match(r"([\d-]+\s[\d:]+)\s\[(\d)\]\s(\w+):\s(.*)", line)
        if match:
            timestamp, severity, module, message = match.groups()
            entries.append({"time": timestamp, "severity": int(severity),
                            "module": module.upper(), "message": message})
    return entries
