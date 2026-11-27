"""Authorize Twitch Clips access with Twitch's official device code flow."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
SCOPES = "editor:manage:clips"


def _post(url: str, values: dict[str, str]) -> dict:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace"))
        except json.JSONDecodeError:
            detail = {}
        detail["http_status"] = exc.code
        return detail


def main() -> None:
    client_id = os.getenv("VTT_TWITCH_CLIENT_ID", "").strip()
    if not client_id:
        raise SystemExit("Set VTT_TWITCH_CLIENT_ID to your Twitch Developer application's Client ID first.")
    token_file = Path(os.getenv("VTT_TWITCH_TOKEN_FILE", "").strip() or str(Path.home() / ".video-to-transcript" / "twitch-token.json")).expanduser()
    if token_file.exists():
        raise SystemExit(f"Refusing to overwrite existing Twitch token file: {token_file}")

    device = _post(DEVICE_URL, {"client_id": client_id, "scopes": SCOPES})
    if not device.get("device_code"):
        raise SystemExit(f"Twitch device authorization could not start (HTTP {device.get('http_status', '?')}). Check the Client ID and public-client app configuration.")
    verification_uri = device.get("verification_uri") or "https://www.twitch.tv/activate"
    print(f"Open {verification_uri} and enter code: {device.get('user_code')}")
    webbrowser.open(verification_uri)

    expires_at = time.time() + int(device.get("expires_in", 0))
    interval = max(1, int(device.get("interval", 5)))
    while time.time() < expires_at:
        time.sleep(interval)
        result = _post(TOKEN_URL, {
            "client_id": client_id,
            "device_code": device["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })
        if result.get("access_token"):
            token_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "client_id": client_id,
                "access_token": result["access_token"],
                "refresh_token": result.get("refresh_token"),
                "expires_at": time.time() + int(result.get("expires_in", 0)),
                "scope": result.get("scope", []),
                "token_type": result.get("token_type", "bearer"),
            }
            token_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            try:
                token_file.chmod(0o600)
            except OSError:
                pass
            print(f"Twitch token saved locally to {token_file}; do not share or commit this file.")
            return
        error = result.get("message") or result.get("error") or ""
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if result.get("http_status") == 400 and "authorization_pending" in str(result):
            continue
        raise SystemExit(f"Twitch device authorization ended: {error or result.get('http_status', 'unknown error')}")
    raise SystemExit("Twitch device code expired before authorization completed. Run the command again.")


if __name__ == "__main__":
    main()
