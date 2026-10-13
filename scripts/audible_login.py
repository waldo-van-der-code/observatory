#!/usr/bin/env python3
"""One-time Audible login. Run on the machine that will run the sync (oracle).

    ~/audible-env/bin/python3 scripts/audible_login.py

Prints an Amazon login URL. Open it in any browser, sign in (OTP/CAPTCHA handled by Amazon),
then paste the final redirect URL (the page that says "page not found") back here.
Credentials are written to ~/.config/audible/credentials.json (chmod 600), never into the repo.
"""
import os
import sys
from pathlib import Path

import audible

CRED = Path(os.environ.get("AUDIBLE_CREDENTIALS", Path.home() / ".config" / "audible" / "credentials.json"))
LOCALE = os.environ.get("AUDIBLE_LOCALE", "de")


def prompt_for_redirect(url: str) -> str:
    print("\n1. Open this URL in a browser and sign in to Amazon/Audible:\n")
    print(url)
    print("\n2. After login you land on an error/'page not found' page. Copy that page's full URL.\n")
    return input("Paste the URL here: ").strip()


def main() -> int:
    auth = audible.Authenticator.from_login_external(locale=LOCALE, login_url_callback=prompt_for_redirect)
    CRED.parent.mkdir(parents=True, exist_ok=True)
    auth.to_file(CRED)
    CRED.chmod(0o600)
    print(f"Saved credentials to {CRED}")
    with audible.Client(auth=auth) as client:
        n = client.get("1.0/library", num_results=1).get("total_results", "?")
    print(f"Login OK. Library size: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
