"""
Tetris — Search Agent (Serper API Integration)
================================================

Provides web search capabilities via the Serper.dev Google Search API.

Functions
---------
search_web(query, num_results=5) -> SearchResult
    Executes a real web search via Serper API.
    Returns a SearchResult with status, results list, and error info.

format_search_results(search_result) -> str
    Formats a SearchResult into a bounded text block for LLM consumption.

SearchStatus
    SUCCESS  — API returned results normally
    DEGRADED — API returned partial/empty results but did not error
    FAILED   — API call failed (network, auth, timeout, etc.)

Design
------
- Never fabricates results on failure
- Never logs the API key
- Returns explicit status so callers can distinguish success/failure
- Caps result payload to avoid token overflow
- Preserves source URLs for evidence tracing
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERPER_ENDPOINT = "https://google.serper.dev/search"
SERPER_TIMEOUT_SECONDS = 10
MAX_SNIPPET_LENGTH = 300


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class SearchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass
class SearchResultItem:
    title: str = ""
    url: str = ""
    snippet: str = ""
    position: int = 0


@dataclass
class SearchResult:
    status: SearchStatus = SearchStatus.FAILED
    query: str = ""
    results: List[SearchResultItem] = field(default_factory=list)
    total_results: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Core search function
# ---------------------------------------------------------------------------

def search_web(query: str, num_results: int = 5) -> SearchResult:
    """
    Execute a real web search via the Serper.dev Google Search API.

    Parameters
    ----------
    query : str
        The search query string.
    num_results : int
        Maximum number of results to request (capped at 10).

    Returns
    -------
    SearchResult
        Contains status, parsed results, and error information.
        Callers MUST check .status before treating results as valid.
    """
    num_results = min(max(num_results, 1), 10)

    # 1. Check for API key
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        logger.error("SERPER_API_KEY is not set or empty")
        return SearchResult(
            status=SearchStatus.FAILED,
            query=query,
            error="SERPER_API_KEY environment variable is not configured",
        )

    # 2. Build request
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "num": num_results,
    }

    # 3. Execute HTTP request
    try:
        response = requests.post(
            SERPER_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=SERPER_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        logger.error("Serper API request timed out after %ds", SERPER_TIMEOUT_SECONDS)
        return SearchResult(
            status=SearchStatus.FAILED,
            query=query,
            error=f"Serper API request timed out after {SERPER_TIMEOUT_SECONDS}s",
        )
    except requests.exceptions.ConnectionError as exc:
        logger.error("Serper API connection error: %s", str(exc)[:200])
        return SearchResult(
            status=SearchStatus.FAILED,
            query=query,
            error=f"Serper API connection error: {str(exc)[:200]}",
        )
    except requests.exceptions.RequestException as exc:
        logger.error("Serper API request failed: %s", str(exc)[:200])
        return SearchResult(
            status=SearchStatus.FAILED,
            query=query,
            error=f"Serper API request error: {str(exc)[:200]}",
        )

    # 4. Check HTTP status
    if response.status_code != 200:
        error_body = response.text[:300] if response.text else "No response body"
        logger.error(
            "Serper API returned HTTP %d: %s", response.status_code, error_body
        )
        return SearchResult(
            status=SearchStatus.FAILED,
            query=query,
            error=f"Serper API HTTP {response.status_code}: {error_body}",
        )

    # 5. Parse JSON response
    try:
        data = response.json()
    except (ValueError, TypeError) as exc:
        logger.error("Serper API returned invalid JSON: %s", str(exc)[:200])
        return SearchResult(
            status=SearchStatus.FAILED,
            query=query,
            error=f"Serper API returned invalid JSON: {str(exc)[:200]}",
        )

    # 6. Extract organic results
    organic = data.get("organic", [])
    if not isinstance(organic, list):
        logger.warning("Serper response 'organic' field is not a list")
        return SearchResult(
            status=SearchStatus.DEGRADED,
            query=query,
            error="Serper response format unexpected: 'organic' is not a list",
        )

    items: List[SearchResultItem] = []
    for i, entry in enumerate(organic[:num_results]):
        if not isinstance(entry, dict):
            continue
        items.append(SearchResultItem(
            title=str(entry.get("title", ""))[:200],
            url=str(entry.get("link", ""))[:500],
            snippet=str(entry.get("snippet", ""))[:MAX_SNIPPET_LENGTH],
            position=i + 1,
        ))

    # 7. Determine status
    if len(items) == 0:
        status = SearchStatus.DEGRADED
        error_msg = "Serper returned 200 but no organic results for this query"
    else:
        status = SearchStatus.SUCCESS
        error_msg = None

    return SearchResult(
        status=status,
        query=query,
        results=items,
        total_results=len(items),
        error=error_msg,
    )


# ---------------------------------------------------------------------------
# Formatting for LLM consumption
# ---------------------------------------------------------------------------

def format_search_results(search_result: SearchResult) -> str:
    """
    Format a SearchResult into a bounded text block suitable for LLM prompts.

    Parameters
    ----------
    search_result : SearchResult
        The result from search_web().

    Returns
    -------
    str
        Formatted text with titles, URLs, and snippets.
        Includes explicit status markers so the LLM knows if data is real.
    """
    # Handle legacy callers that might pass a raw list (backward compat)
    if isinstance(search_result, list):
        if not search_result:
            return "Search results unavailable (no data provided)."
        # Try to format as list of dicts
        lines = []
        for item in search_result[:5]:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('title', 'Untitled')}\n"
                    f"  URL: {item.get('url', 'N/A')}\n"
                    f"  {item.get('snippet', '')}"
                )
        return "\n".join(lines) if lines else "Search results unavailable."

    if search_result.status == SearchStatus.FAILED:
        return (
            f"[SEARCH FAILED] {search_result.error or 'Unknown error'}\n"
            f"Query: {search_result.query}\n"
            f"NOTE: The following analysis is NOT based on live web data."
        )

    if search_result.status == SearchStatus.DEGRADED:
        return (
            f"[SEARCH DEGRADED] {search_result.error or 'Partial results'}\n"
            f"Query: {search_result.query}\n"
            f"NOTE: Search returned limited or no results. Analysis may be incomplete."
        )

    # SUCCESS
    lines = [
        f"[SEARCH SUCCESS] {search_result.total_results} results for: {search_result.query}",
        "",
    ]
    for item in search_result.results:
        lines.append(f"{item.position}. {item.title}")
        lines.append(f"   URL: {item.url}")
        if item.snippet:
            lines.append(f"   {item.snippet}")
        lines.append("")

    return "\n".join(lines)
