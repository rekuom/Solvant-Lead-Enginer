"""forum_reader: listing filter and topic parsing (no network)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from signal_engine.discovery.platform import forum_reader as fr

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)


class ForumReader(unittest.TestCase):
    def test_filter_keeps_fresh_buyer_topics_only(self):
        topics = [
            {"id": 1, "slug": "a", "title": "Looking to Hire an n8n Expert to Build a Lead Workflow", "created_at": "2026-11-18T10:00:00Z", "posts_count": 1},
            {"id": 2, "slug": "b", "title": "[For Hire] n8n automation builder", "created_at": "2026-11-18T10:00:00Z"},
            {"id": 3, "slug": "c", "title": "[HIRING] Full-Time CRM Engineer | $2,000/month", "created_at": "2026-11-18T10:00:00Z"},
            {"id": 4, "slug": "d", "title": "Looking for BD & Referral Partners — Commission-Based", "created_at": "2026-11-18T10:00:00Z"},
            {"id": 5, "slug": "e", "title": "Hiring: Make.com + Airtable specialist", "created_at": "2026-10-01T10:00:00Z"},
        ]
        out = fr.filter_topics(topics, "community.n8n.io", days=3, now=NOW)
        self.assertEqual([o["url"] for o in out], ["https://community.n8n.io/t/a/1"])

    def test_topic_text_strips_html(self):
        d = {"title": "T", "created_at": "2026-11-17T00:00:00Z", "closed": True,
             "post_stream": {"posts": [{"cooked": "<p>Need a <b>Gumroad</b> &amp; Airtable integration</p>"}]}}
        self.assertEqual(fr.topic_text(d)["text"], "Need a Gumroad & Airtable integration")

    def test_only_approved_forums_are_read(self):
        self.assertIn("error", fr.thread(["https://www.reddit.com/r/x/comments/1/a"])[0])
