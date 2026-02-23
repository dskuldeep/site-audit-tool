"""
Fetches and parses robots.txt for the audit domain.
"""
from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests

from models import RobotsData


def fetch_and_parse_robots(domain_url: str, session: requests.Session, timeout: int = 15) -> RobotsData:
    """Fetch /robots.txt and return a populated RobotsData object."""
    robots_url = _build_robots_url(domain_url)

    data = RobotsData(url=robots_url, exists=False)

    try:
        t0 = time.perf_counter()
        resp = session.get(robots_url, timeout=timeout, allow_redirects=True)
        data.status_code = resp.status_code

        if resp.status_code == 200:
            data.exists = True
            data.raw_text = resp.text
            _parse_robots(data)
        elif resp.status_code == 404:
            data.exists = False
        else:
            data.exists = False
            data.parse_errors.append(f"robots.txt returned HTTP {resp.status_code}")
    except requests.RequestException as exc:
        data.parse_errors.append(f"Failed to fetch robots.txt: {exc}")

    return data


def _build_robots_url(domain_url: str) -> str:
    parsed = urlparse(domain_url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _parse_robots(data: RobotsData) -> None:
    """Parse robots.txt raw text into structured rules."""
    current_agents: list[str] = []
    in_agent_block = False

    for raw_line in data.raw_text.splitlines():
        line = raw_line.strip()

        # Skip blank lines and comments
        if not line or line.startswith("#"):
            if line == "" and in_agent_block:
                current_agents = []
                in_agent_block = False
            continue

        # Split on first colon
        if ":" not in line:
            data.parse_errors.append(f"Invalid line (no colon): {line!r}")
            continue

        directive, _, value = line.partition(":")
        directive = directive.strip().lower()
        value = value.strip()

        if directive == "user-agent":
            if not in_agent_block:
                current_agents = []
                in_agent_block = True
            current_agents.append(value)

        elif directive == "disallow":
            in_agent_block = True
            for agent in current_agents:
                data.disallow_rules.append({"agent": agent, "path": value})

        elif directive == "allow":
            in_agent_block = True
            for agent in current_agents:
                data.allow_rules.append({"agent": agent, "path": value})

        elif directive == "crawl-delay":
            try:
                data.crawl_delay = float(value)
            except ValueError:
                data.parse_errors.append(f"Invalid crawl-delay value: {value!r}")

        elif directive == "sitemap":
            if value:
                data.sitemap_urls.append(value)

        else:
            # Unknown directive — not necessarily an error (e.g. Host:, Noindex:)
            pass


def is_url_allowed(url: str, robots_data: RobotsData, user_agent: str = "*") -> bool:
    """
    Check whether a URL is allowed for the given user-agent.
    Returns True (allowed) if no matching Disallow rule exists.
    Uses longest-path specificity matching.
    """
    if not robots_data.exists:
        return True

    parsed = urlparse(url)
    path = parsed.path or "/"

    # Collect rules for this agent and wildcard
    agents_to_check = [user_agent.lower(), "*"]

    # Build allow/disallow lists scoped to relevant agents
    allows = [
        r["path"] for r in robots_data.allow_rules
        if r["agent"].lower() in agents_to_check
    ]
    disallows = [
        r["path"] for r in robots_data.disallow_rules
        if r["agent"].lower() in agents_to_check
    ]

    # Find the most specific matching rule
    best_allow_len = -1
    best_disallow_len = -1

    for rule_path in allows:
        if path.startswith(rule_path) and len(rule_path) > best_allow_len:
            best_allow_len = len(rule_path)

    for rule_path in disallows:
        # Empty Disallow: means "nothing is disallowed" — skip it entirely
        if not rule_path:
            continue
        if path.startswith(rule_path) and len(rule_path) > best_disallow_len:
            best_disallow_len = len(rule_path)

    if best_disallow_len < 0:
        return True  # No disallow matched

    # Allow wins on equal or greater specificity (Google spec: allow wins on ties)
    return best_allow_len >= best_disallow_len
