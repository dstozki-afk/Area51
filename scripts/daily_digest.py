#!/usr/bin/env python3
"""Builds and sends the Daily Digest email.

Reads all Gmail messages from the last 24 hours, asks Claude to stack-rank
them by importance with action items and dates, then sends the result as an
email titled "Daily Digest - <date>" to DIGEST_TO_EMAIL.

Required environment variables:
  GMAIL_CLIENT_ID
  GMAIL_CLIENT_SECRET
  GMAIL_REFRESH_TOKEN   (must include gmail.readonly + gmail.send scopes)
  ANTHROPIC_API_KEY
  DIGEST_TO_EMAIL
"""
import base64
import os
from datetime import datetime
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import anthropic

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=GMAIL_SCOPES,
    )
    return build("gmail", "v1", credentials=creds)


def fetch_last_24h_messages(service):
    results = service.users().messages().list(
        userId="me", q="newer_than:1d in:inbox", maxResults=100
    ).execute()
    message_ids = [m["id"] for m in results.get("messages", [])]

    summaries = []
    for msg_id in message_ids:
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="metadata",
            metadataHeaders=["From", "Subject", "Date", "To"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        summaries.append({
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
        })
    return summaries


def build_digest_text(messages):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    listing = "\n\n".join(
        f"From: {m['from']}\nSubject: {m['subject']}\nDate: {m['date']}\n"
        f"Snippet: {m['snippet']}"
        for m in messages
    )

    prompt = (
        "Below are all emails received in the last 24 hours. Stack-rank them "
        "by importance (financial/security alerts and time-sensitive items "
        "first, then personal/family, then career/work opportunities, then "
        "logistics/travel, then informational, then promotional/newsletters "
        "last). For each item give a 1-2 sentence summary, the date, and a "
        "clear recommended action (or 'No action needed'). Group low-value "
        "promotional items into a single bullet list at the end. Output "
        "plain text suitable for an email body.\n\n"
        f"{listing}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def send_digest(service, body_text):
    today = datetime.now().strftime("%B %d, %Y")
    message = MIMEText(body_text)
    message["to"] = os.environ["DIGEST_TO_EMAIL"]
    message["subject"] = f"Daily Digest - {today}"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def main():
    service = gmail_service()
    messages = fetch_last_24h_messages(service)
    digest_text = build_digest_text(messages)
    send_digest(service, digest_text)
    print(f"Sent Daily Digest covering {len(messages)} messages.")


if __name__ == "__main__":
    main()
