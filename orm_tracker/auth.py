"""Google credentials, by either of the two routes that actually work here.

Service account (GOOGLE_APPLICATION_CREDENTIALS)
    Cleanest for unattended runs, but somebody with the *Manager* role on the
    Shared Drive has to add the service account as a member. Content Manager
    is not enough. Use this if you can get that done.

OAuth as yourself (GOOGLE_OAUTH_CLIENT_SECRETS + GOOGLE_OAUTH_TOKEN)
    Runs as your own Google account, so it inherits the access you already
    have -- Content Manager is plenty. One interactive consent, once:

        python -m orm_tracker.auth

    That writes token.json (a refresh token). After that every run is
    unattended. For CI, put the contents of token.json in a secret.

Service account wins if both are configured.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

TOKEN_ENV = "GOOGLE_OAUTH_TOKEN"
CLIENT_ENV = "GOOGLE_OAUTH_CLIENT_SECRETS"
SA_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
DEFAULT_TOKEN = "token.json"

_HELP = f"""No Google credentials found. Set one of:

  {SA_ENV}=/path/to/service-account.json
      A service account. Someone with Manager on the Shared Drive must add it
      as a member, and it needs Editor on the Sheet.

  {CLIENT_ENV}=/path/to/client_secrets.json
      An OAuth desktop client. Then run `python -m orm_tracker.auth` once to
      authorise as yourself; it writes {DEFAULT_TOKEN}.
"""


def _service_account(path: str, scopes: list[str]):
    from google.oauth2 import service_account

    if not Path(path).is_file():
        raise SystemExit(f"{SA_ENV} points at a missing file: {path}")
    return service_account.Credentials.from_service_account_file(path, scopes=scopes)


def _stored_token(path: Path, scopes: list[str]):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_info(
        json.loads(path.read_text(encoding="utf-8")), scopes
    )
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json(), encoding="utf-8")
        return creds
    raise SystemExit(
        f"{path} is no longer usable (no refresh token, or consent was revoked). "
        "Re-run `python -m orm_tracker.auth`."
    )


def credentials(scopes: list[str]):
    sa = os.environ.get(SA_ENV, "").strip()
    if sa:
        return _service_account(sa, scopes)

    token_path = Path(os.environ.get(TOKEN_ENV, "").strip() or DEFAULT_TOKEN)
    if token_path.is_file():
        return _stored_token(token_path, scopes)

    raise SystemExit(_HELP)


def authorise(scopes: list[str]) -> Path:
    """One-time interactive consent. Writes the token file and returns its path."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    client = os.environ.get(CLIENT_ENV, "").strip()
    if not client:
        raise SystemExit(
            f"{CLIENT_ENV} is not set. Create an OAuth client of type 'Desktop app' "
            "in Google Cloud, download the JSON, and point this at it."
        )
    if not Path(client).is_file():
        raise SystemExit(f"{CLIENT_ENV} points at a missing file: {client}")

    flow = InstalledAppFlow.from_client_secrets_file(client, scopes)
    # run_console is gone from recent google-auth-oauthlib; run_local_server
    # falls back to printing a URL when it cannot open a browser.
    creds = flow.run_local_server(port=0, open_browser=True)

    token_path = Path(os.environ.get(TOKEN_ENV, "").strip() or DEFAULT_TOKEN)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return token_path


def main() -> int:
    from .drive import SCOPES_CREATE, SCOPES_RO
    from .sheets import SCOPES_RW

    path = authorise(list(SCOPES_RO) + list(SCOPES_CREATE) + list(SCOPES_RW))
    print(f"authorised; token written to {path}")
    print("Keep this file out of git. It is already in .gitignore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
