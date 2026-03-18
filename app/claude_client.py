"""
claude_client.py - Anthropic Claude API client.

Sends the assembled prompt to Claude, parses the JSON response
into a validated trading decision. Falls back to HOLD on any
parsing or validation failure.
"""

import json
import re
import time

import anthropic

from config import get_api_key, get_model

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

REQUIRED_FIELDS = {"action", "confidence", "reasoning", "signals", "risk"}

DEFAULT_HOLD = {
    "action": "HOLD",
    "confidence": 0.0,
    "reasoning": "Failed to parse Claude response, defaulting to HOLD.",
    "signals": [],
    "risk": "unknown",
}


def _call_claude(prompt_payload: dict) -> str:
    """Send the prompt to Claude and return the raw response text.

    Args:
        prompt_payload: dict with 'system' (str) and 'messages' (list)
                        as built by prompt_builder.build_messages().

    Returns:
        Raw response text from Claude.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    client = anthropic.Anthropic(api_key=get_api_key())

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=get_model(),
                max_tokens=256,
                system=prompt_payload["system"],
                messages=prompt_payload["messages"],
            )
            return response.content[0].text

        except anthropic.APIConnectionError as e:
            last_error = e
        except anthropic.RateLimitError as e:
            last_error = e
        except anthropic.APIStatusError as e:
            if e.status_code < 500 and e.status_code != 429:
                raise RuntimeError(f"Claude API error: {e}") from e
            last_error = e

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError(
        f"Claude API failed after {MAX_RETRIES} retries: {last_error}"
    )


def extract_json(text: str) -> dict:
    """Extract a JSON object from Claude's response text.

    Handles both raw JSON and JSON wrapped in ```json code fences.

    Args:
        text: Raw response string from Claude.

    Returns:
        Parsed dict.

    Raises:
        ValueError: If no valid JSON object can be extracted.
    """
    # Try to find a fenced JSON block first
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    # Fall back to finding a bare JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError("No JSON object found in response")


def validate_decision(data: dict) -> dict:
    """Validate that a parsed decision contains all required fields.

    Args:
        data: Parsed JSON dict from Claude.

    Returns:
        The decision dict with action uppercased.

    Raises:
        ValueError: If required fields are missing or action is invalid.
    """
    missing = REQUIRED_FIELDS - data.keys()
    if missing:
        raise ValueError(f"Missing fields: {missing}")

    data["action"] = str(data["action"]).upper()
    if data["action"] not in ("BUY", "SELL", "HOLD"):
        raise ValueError(f"Invalid action: {data['action']}")

    return data


def get_trading_decision(prompt_payload: dict) -> dict:
    """Send prompt to Claude, parse and validate the trading decision.

    Returns the validated decision dict on success, or a default
    HOLD decision if the API call, parsing, or validation fails.

    Args:
        prompt_payload: dict with 'system' and 'messages' keys.

    Returns:
        dict with keys: action, confidence, reasoning, signals, risk.
    """
    try:
        raw_text = _call_claude(prompt_payload)
        data = extract_json(raw_text)
        return validate_decision(data)
    except Exception as e:
        print(f"[claude_client] Decision failed, defaulting to HOLD: {e}")
        return DEFAULT_HOLD.copy()


DEFAULT_REJECT = {
    "approved": False,
    "reasoning": "Risk review failed, defaulting to reject.",
    "risk_notes": "unknown",
}


def get_risk_verdict(prompt_payload: dict) -> dict:
    """Send prompt to Claude Risk Manager and parse the verdict.

    Returns a dict with 'approved' (bool), 'reasoning', and 'risk_notes'.
    Defaults to rejection on any failure.

    Args:
        prompt_payload: dict with 'system' and 'messages' keys.

    Returns:
        dict with keys: approved, reasoning, risk_notes.
    """
    try:
        raw_text = _call_claude(prompt_payload)
        data = extract_json(raw_text)

        missing = {"approved", "reasoning", "risk_notes"} - data.keys()
        if missing:
            raise ValueError(f"Missing fields: {missing}")

        data["approved"] = bool(data["approved"])
        return data

    except Exception as e:
        print(f"[claude_client] Risk verdict failed, defaulting to REJECT: {e}")
        return DEFAULT_REJECT.copy()
