"""Tests for shared Overpass client helpers."""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

from geoagent.tools.overpass_client import post_overpass
from geoagent.tools.situation_roads import _overpass_closure_query


class OverpassClientTests(unittest.TestCase):
    def test_post_overpass_fails_over_endpoints(self) -> None:
        good_payload = {"elements": [{"type": "node", "id": 1}]}

        def fake_urlopen(request, timeout=None):  # noqa: ANN001
            url = request.full_url if hasattr(request, "full_url") else str(request.get_full_url())
            if "lz4" in url:
                resp = MagicMock()
                resp.read.return_value = json.dumps(good_payload).encode("utf-8")
                resp.__enter__ = lambda s: s
                resp.__exit__ = MagicMock(return_value=False)
                return resp
            raise TimeoutError("slow mirror")

        with patch("geoagent.tools.overpass_client.urllib.request.urlopen", side_effect=fake_urlopen):
            payload = post_overpass(
                '[out:json];node(1);out;',
                timeout_sec=20.0,
                label="test",
            )
        self.assertEqual(payload["elements"][0]["id"], 1)

    def test_road_query_avoids_bare_construction(self) -> None:
        q = _overpass_closure_query([-118.6, 34.0, -118.5, 34.1])
        self.assertNotIn('way["construction"](', q)
        self.assertIn('["access"="no"]', q)
        self.assertIn("out geom;", q)


if __name__ == "__main__":
    unittest.main()
