"""Authorize this local single-user application to read files from Google Drive."""
from __future__ import annotations

import os
from pathlib import Path

from backend.downloader.adapters.google_drive import SCOPES


def main() -> None:
    client_file = os.getenv("VTT_GOOGLE_DRIVE_OAUTH_CLIENT_FILE", "").strip()
    token_file = Path(os.getenv("VTT_GOOGLE_DRIVE_TOKEN_FILE", "").strip() or str(Path.home() / ".video-to-transcript" / "google-drive-token.json")).expanduser()
    if not client_file or not Path(client_file).is_file():
        raise SystemExit("Set VTT_GOOGLE_DRIVE_OAUTH_CLIENT_FILE to the OAuth Desktop client JSON path first.")
    if token_file.exists():
        raise SystemExit(f"Refusing to overwrite existing token file: {token_file}")
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    credentials = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass
    print(f"Google Drive read authorization saved to {token_file}")


if __name__ == "__main__":
    main()
