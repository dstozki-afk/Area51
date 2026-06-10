#!/usr/bin/env python3
"""One-time helper: run this LOCALLY (not in CI) to obtain a Gmail OAuth
refresh token for the Daily Digest workflow.

Usage:
  1. In Google Cloud Console, create an OAuth 2.0 Client ID of type
     "Desktop app" and download its client_secret.json into this directory.
  2. pip install -r requirements.txt
  3. python get_gmail_refresh_token.py
  4. A browser window opens - sign in as dstozki@gmail.com and grant access.
  5. The script prints GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and
     GMAIL_REFRESH_TOKEN. Add these as repository secrets (Settings > Secrets
     and variables > Actions), along with ANTHROPIC_API_KEY.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def main():
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0)
    print("\nAdd these as GitHub repository secrets:\n")
    print(f"GMAIL_CLIENT_ID={creds.client_id}")
    print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
