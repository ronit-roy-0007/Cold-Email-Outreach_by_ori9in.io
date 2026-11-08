from __future__ import annotations

import urllib.robotparser


def robots_allows(
    robots_txt: str | None,
    url: str,
    user_agent: str = "IntentLeadBot",
) -> bool:
    if robots_txt is None:
        return True

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(robots_txt.splitlines())
    return parser.can_fetch(user_agent, url)
