#!/usr/bin/env python3
"""Unified daily digest: email (IMAP), calendar (iCal), and news (RSS/Atom)."""

import argparse
import imaplib
import email as email_lib
import email.message
import re
import sys
import textwrap
from datetime import datetime, timezone, timedelta, date
from email.header import decode_header as _decode_header
from email.utils import parsedate_to_datetime
from typing import NamedTuple
from xml.etree import ElementTree


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    for entity, repl in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " ")):
        text = text.replace(entity, repl)
    text = re.sub(r"&[a-z]+;", "", text)
    return " ".join(text.split())


def _parse_rfc_date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# News (RSS / Atom)
# ---------------------------------------------------------------------------

class NewsEntry(NamedTuple):
    title: str
    link: str
    published: datetime | None
    summary: str


def _fetch_url(url: str) -> bytes:
    import urllib.request
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.read()


def _parse_feed(xml_bytes: bytes) -> tuple[str, list[NewsEntry]]:
    root = ElementTree.fromstring(xml_bytes)
    ns = {"a": "http://www.w3.org/2005/Atom"}

    # Atom
    if "Atom" in root.tag or root.tag == "feed":
        feed_title = root.findtext("a:title", default="(untitled)", namespaces=ns) or \
                     root.findtext("title", default="(untitled)")
        entries = []
        for e in root.findall("a:entry", ns) or root.findall("entry"):
            title = e.findtext("a:title", namespaces=ns) or e.findtext("title") or ""
            link_el = e.find("a:link", ns) or e.find("link")
            link = (link_el.get("href") or link_el.text or "") if link_el is not None else ""
            pub = _parse_rfc_date(
                e.findtext("a:published", namespaces=ns) or e.findtext("a:updated", namespaces=ns) or
                e.findtext("published") or e.findtext("updated")
            )
            body_el = e.find("a:summary", ns) or e.find("a:content", ns) or \
                      e.find("summary") or e.find("content")
            summary = _strip_html(body_el.text or "") if body_el is not None else ""
            entries.append(NewsEntry(title.strip(), link.strip(), pub, summary))
        return (feed_title or "(untitled)").strip(), entries

    # RSS 2.0
    ch = root.find("channel")
    if ch is None:
        return "(unknown feed)", []
    feed_title = ch.findtext("title", default="(untitled)")
    entries = []
    for item in ch.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = _parse_rfc_date(item.findtext("pubDate"))
        summary = _strip_html(item.findtext("description") or "")
        entries.append(NewsEntry(title, link, pub, summary))
    return (feed_title or "(untitled)").strip(), entries


def fetch_news(feed_urls: list[str], limit: int) -> list[tuple[str, list[NewsEntry]]]:
    sections = []
    for url in feed_urls:
        try:
            xml = _fetch_url(url)
            title, entries = _parse_feed(xml)
            sections.append((title, entries[:limit]))
        except Exception as exc:
            print(f"Warning: could not fetch feed {url}: {exc}", file=sys.stderr)
            sections.append((url, []))
    return sections


# ---------------------------------------------------------------------------
# Email (IMAP)
# ---------------------------------------------------------------------------

class EmailMessage(NamedTuple):
    subject: str
    sender: str
    date: datetime | None
    snippet: str


def _decode_str(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    parts = _decode_header(value)
    result = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            result.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(chunk)
    return "".join(result)


def _body_snippet(msg: email_lib.message.Message, max_chars: int = 200) -> str:
    plain = ""
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                plain = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                break
        elif ct == "text/html" and not plain:
            payload = part.get_payload(decode=True)
            if payload:
                plain = _strip_html(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    return " ".join(plain.split())[:max_chars]


def fetch_email(
    host: str,
    port: int,
    username: str,
    password: str,
    mailbox: str,
    limit: int,
    since_days: int,
    use_ssl: bool,
) -> list[EmailMessage]:
    try:
        if use_ssl:
            conn = imaplib.IMAP4_SSL(host, port)
        else:
            conn = imaplib.IMAP4(host, port)
            conn.starttls()
        conn.login(username, password)
        conn.select(mailbox, readonly=True)

        since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        _, data = conn.search(None, f'(SINCE "{since}")')
        ids = (data[0].split() if data[0] else [])[-limit:]  # newest N

        messages = []
        for uid in reversed(ids):
            _, raw = conn.fetch(uid, "(RFC822)")
            for part in raw:
                if isinstance(part, tuple):
                    msg = email_lib.message_from_bytes(part[1])
                    messages.append(EmailMessage(
                        subject=_decode_str(msg.get("Subject")),
                        sender=_decode_str(msg.get("From")),
                        date=_parse_rfc_date(msg.get("Date")),
                        snippet=_body_snippet(msg),
                    ))
        conn.logout()
        return messages
    except Exception as exc:
        print(f"Warning: email fetch failed: {exc}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Calendar (iCal / .ics)
# ---------------------------------------------------------------------------

class CalEvent(NamedTuple):
    summary: str
    start: datetime | None
    end: datetime | None
    location: str
    description: str


def _parse_ical_dt(value: str, tzid: str | None = None) -> datetime | None:
    value = value.strip()
    # Basic datetime formats used in iCal
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _unfold_ical(text: str) -> str:
    """Remove iCal line folding (CRLF + SPACE/TAB continuation)."""
    return re.sub(r"\r?\n[ \t]", "", text)


def parse_ical(ical_text: str, since_days: int, limit: int) -> list[CalEvent]:
    text = _unfold_ical(ical_text)
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(days=since_days)

    events = []
    current: dict[str, str] = {}
    in_event = False

    for line in text.splitlines():
        if line.strip() == "BEGIN:VEVENT":
            in_event = True
            current = {}
        elif line.strip() == "END:VEVENT":
            in_event = False
            # Extract fields (strip TZID and other params from key)
            def get(prefix: str) -> str:
                for k, v in current.items():
                    if k == prefix or k.startswith(prefix + ";"):
                        return v
                return ""

            summary = get("SUMMARY")
            start = _parse_ical_dt(get("DTSTART"))
            end = _parse_ical_dt(get("DTEND"))
            location = get("LOCATION")
            description = get("DESCRIPTION").replace("\\n", " ").replace("\\,", ",")

            if start and start >= cutoff:
                events.append(CalEvent(summary, start, end, location, description))
        elif in_event and ":" in line:
            key, _, value = line.partition(":")
            current[key.strip()] = value.strip()

    events.sort(key=lambda e: e.start or datetime.min.replace(tzinfo=timezone.utc))
    return events[:limit]


def fetch_calendar(sources: list[str], since_days: int, limit: int) -> list[CalEvent]:
    all_events: list[CalEvent] = []
    for src in sources:
        try:
            if src.startswith("http://") or src.startswith("https://") or src.startswith("webcal://"):
                url = src.replace("webcal://", "https://")
                raw = _fetch_url(url).decode("utf-8", errors="replace")
            else:
                with open(src, encoding="utf-8", errors="replace") as f:
                    raw = f.read()
            all_events.extend(parse_ical(raw, since_days=since_days, limit=limit))
        except Exception as exc:
            print(f"Warning: could not load calendar {src}: {exc}", file=sys.stderr)
    all_events.sort(key=lambda e: e.start or datetime.min.replace(tzinfo=timezone.utc))
    return all_events[:limit]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "?"
    return dt.strftime("%Y-%m-%d %H:%M")


def render_text(
    news: list[tuple[str, list[NewsEntry]]],
    emails: list[EmailMessage],
    cal_events: list[CalEvent],
    width: int,
) -> str:
    now = datetime.now(tz=timezone.utc)
    lines = [
        "=" * width,
        f"  DAILY DIGEST  —  {now.strftime('%A, %d %B %Y')}",
        "=" * width,
    ]

    # Calendar
    if cal_events is not None:
        lines += ["", "UPCOMING EVENTS", "-" * width]
        if cal_events:
            for ev in cal_events:
                start = _fmt_dt(ev.start)
                end = _fmt_dt(ev.end) if ev.end else ""
                time_range = f"{start} – {end}" if end else start
                lines.append(f"  {ev.summary}")
                lines.append(f"  {time_range}" + (f"  @ {ev.location}" if ev.location else ""))
                if ev.description:
                    wrapped = textwrap.fill(ev.description[:300], width - 4, initial_indent="    ", subsequent_indent="    ")
                    lines.append(wrapped)
                lines.append("")
        else:
            lines += ["  (no upcoming events)", ""]

    # Email
    if emails is not None:
        lines += ["EMAIL", "-" * width]
        if emails:
            for msg in emails:
                pub = msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "?"
                lines.append(f"  {msg.subject or '(no subject)'}")
                lines.append(f"  From: {msg.sender}  |  {pub}")
                if msg.snippet:
                    wrapped = textwrap.fill(msg.snippet, width - 4, initial_indent="    ", subsequent_indent="    ")
                    lines.append(wrapped)
                lines.append("")
        else:
            lines += ["  (no messages)", ""]

    # News
    if news is not None:
        for feed_title, entries in news:
            lines += [f"NEWS: {feed_title}", "-" * width]
            if entries:
                for entry in entries:
                    pub = entry.published.strftime("%Y-%m-%d") if entry.published else "?"
                    lines.append(f"  {entry.title}")
                    lines.append(f"  {pub}  |  {entry.link}")
                    if entry.summary:
                        wrapped = textwrap.fill(entry.summary[:400], width - 4, initial_indent="    ", subsequent_indent="    ")
                        lines.append(wrapped)
                    lines.append("")
            else:
                lines += ["  (no entries)", ""]

    lines.append("=" * width)
    return "\n".join(lines)


def render_html(
    news: list[tuple[str, list[NewsEntry]]],
    emails: list[EmailMessage],
    cal_events: list[CalEvent],
) -> str:
    from html import escape
    now = datetime.now(tz=timezone.utc)
    parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>Daily Digest — {escape(now.strftime('%d %B %Y'))}</title>",
        "<style>",
        "body{font-family:sans-serif;max-width:860px;margin:2em auto;color:#222;line-height:1.5}",
        "h1{border-bottom:3px solid #333;padding-bottom:.3em}",
        "h2{margin-top:2em;border-bottom:1px solid #ccc;color:#444}",
        "article{border-left:3px solid #ddd;padding:.4em .8em;margin:.8em 0}",
        ".meta{color:#666;font-size:.85em}",
        ".cal-event{background:#f0f7ff;border-left:3px solid #4a90d9}",
        ".email-item{background:#fffbe6;border-left:3px solid #e6b800}",
        "</style></head><body>",
        f"<h1>Daily Digest &mdash; {escape(now.strftime('%A, %d %B %Y'))}</h1>",
    ]

    if cal_events is not None:
        parts.append("<h2>Upcoming Events</h2>")
        if cal_events:
            for ev in cal_events:
                time_range = _fmt_dt(ev.start)
                if ev.end:
                    time_range += f" – {_fmt_dt(ev.end)}"
                loc = f" @ {escape(ev.location)}" if ev.location else ""
                parts += [
                    "<article class='cal-event'>",
                    f"<strong>{escape(ev.summary)}</strong>",
                    f"<p class='meta'>{escape(time_range)}{loc}</p>",
                ]
                if ev.description:
                    parts.append(f"<p>{escape(ev.description[:400])}</p>")
                parts.append("</article>")
        else:
            parts.append("<p><em>No upcoming events.</em></p>")

    if emails is not None:
        parts.append("<h2>Email</h2>")
        if emails:
            for msg in emails:
                pub = msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "?"
                parts += [
                    "<article class='email-item'>",
                    f"<strong>{escape(msg.subject or '(no subject)')}</strong>",
                    f"<p class='meta'>From: {escape(msg.sender)} &nbsp;|&nbsp; {escape(pub)}</p>",
                ]
                if msg.snippet:
                    parts.append(f"<p>{escape(msg.snippet)}</p>")
                parts.append("</article>")
        else:
            parts.append("<p><em>No messages.</em></p>")

    if news is not None:
        for feed_title, entries in news:
            parts.append(f"<h2>News: {escape(feed_title)}</h2>")
            if entries:
                for entry in entries:
                    pub = entry.published.strftime("%Y-%m-%d") if entry.published else "?"
                    href = escape(entry.link)
                    parts += [
                        "<article>",
                        f"<a href='{href}'><strong>{escape(entry.title)}</strong></a>",
                        f"<p class='meta'>{escape(pub)}</p>",
                    ]
                    if entry.summary:
                        parts.append(f"<p>{escape(entry.summary[:400])}</p>")
                    parts.append("</article>")
            else:
                parts.append("<p><em>No entries.</em></p>")

    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a daily digest from email, calendar, and news feeds.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              # News only (RSS feeds)
              digest.py --feeds https://hnrss.org/frontpage https://feeds.bbci.co.uk/news/rss.xml

              # Calendar from .ics file + news
              digest.py --ical ~/calendar.ics --feeds https://hnrss.org/frontpage

              # Full digest with IMAP email (app password recommended)
              digest.py \\
                --imap-host imap.gmail.com --imap-user me@gmail.com --imap-pass "xxxx" \\
                --ical https://calendar.google.com/calendar/ical/XXXX/basic.ics \\
                --feeds https://hnrss.org/frontpage \\
                --format html > digest.html

              # Load feed list from file
              digest.py --feed-file feeds.txt
        """),
    )

    # News
    news_group = parser.add_argument_group("News (RSS/Atom)")
    news_group.add_argument("--feeds", nargs="+", metavar="URL", default=[], help="RSS/Atom feed URLs")
    news_group.add_argument("--feed-file", metavar="FILE", help="Text file with one feed URL per line")
    news_group.add_argument("--news-limit", type=int, default=5, metavar="N",
                            help="Max news entries per feed (default: 5)")

    # Email
    mail_group = parser.add_argument_group("Email (IMAP)")
    mail_group.add_argument("--imap-host", metavar="HOST", help="IMAP server hostname")
    mail_group.add_argument("--imap-port", type=int, default=993, metavar="PORT",
                            help="IMAP port (default: 993 for SSL)")
    mail_group.add_argument("--imap-user", metavar="USER", help="IMAP username / email address")
    mail_group.add_argument("--imap-pass", metavar="PASS", help="IMAP password or app password")
    mail_group.add_argument("--imap-mailbox", default="INBOX", metavar="BOX",
                            help="Mailbox to read (default: INBOX)")
    mail_group.add_argument("--email-limit", type=int, default=10, metavar="N",
                            help="Max emails to include (default: 10)")
    mail_group.add_argument("--email-days", type=int, default=1, metavar="N",
                            help="Fetch emails from the last N days (default: 1)")
    mail_group.add_argument("--imap-no-ssl", action="store_true",
                            help="Use STARTTLS instead of SSL (port 143)")

    # Calendar
    cal_group = parser.add_argument_group("Calendar (iCal)")
    cal_group.add_argument("--ical", nargs="+", metavar="URL_OR_FILE", default=[],
                           help="iCal (.ics) file paths or URLs (webcal:// is supported)")
    cal_group.add_argument("--cal-days", type=int, default=7, metavar="N",
                           help="Show events in the next N days (default: 7)")
    cal_group.add_argument("--cal-limit", type=int, default=10, metavar="N",
                           help="Max calendar events (default: 10)")

    # Output
    out_group = parser.add_argument_group("Output")
    out_group.add_argument("--format", choices=["text", "html"], default="text",
                           help="Output format (default: text)")
    out_group.add_argument("--width", type=int, default=80,
                           help="Text output column width (default: 80)")

    args = parser.parse_args()

    feed_urls = list(args.feeds)
    if args.feed_file:
        try:
            with open(args.feed_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        feed_urls.append(line)
        except OSError as exc:
            print(f"Error reading feed file: {exc}", file=sys.stderr)
            sys.exit(1)

    # Validate: at least one source requested
    has_news = bool(feed_urls)
    has_email = bool(args.imap_host and args.imap_user and args.imap_pass)
    has_cal = bool(args.ical)

    if not any([has_news, has_email, has_cal]):
        parser.print_help()
        sys.exit(0)

    news_data = fetch_news(feed_urls, args.news_limit) if has_news else None
    email_data = (
        fetch_email(
            host=args.imap_host,
            port=args.imap_port,
            username=args.imap_user,
            password=args.imap_pass,
            mailbox=args.imap_mailbox,
            limit=args.email_limit,
            since_days=args.email_days,
            use_ssl=not args.imap_no_ssl,
        )
        if has_email
        else None
    )
    cal_data = fetch_calendar(args.ical, since_days=0, limit=args.cal_limit) if has_cal else None

    if args.format == "html":
        print(render_html(news_data, email_data, cal_data))
    else:
        print(render_text(news_data, email_data, cal_data, args.width))


if __name__ == "__main__":
    main()
