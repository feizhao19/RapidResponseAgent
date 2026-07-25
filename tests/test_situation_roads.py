"""Tests for Environmental Situation Layer road conditions (Caltrans LCS / OSM)."""

from __future__ import annotations

import unittest

from geoagent.tools.situation_roads import (
    build_situation_roads,
    classify_chp_logtype,
    classify_lcs_closure,
    districts_for_bounds,
    filter_features_to_bounds,
    format_situation_roads_markdown,
    normalize_lcs_record,
    normalize_osm_element,
    parse_chp_latlon,
    parse_chp_xml,
    parse_lcs_payload,
    summarize_features,
    wants_road_conditions,
)

EMPTY_CHP = '<?xml version="1.0"?><State></State>'

SAMPLE_CHP = """<?xml version="1.0"?>
<State><Center ID="LA"><Dispatch ID="WLA">
  <Log ID="260724XX0001">
    <LogTime>"Jul 24 2026  7:10PM"</LogTime>
    <LogType>"1182-Trfc Collision-No Inj"</LogType>
    <Location>"PCH / Topanga Canyon"</Location>
    <LocationDesc>"NB PCH"</LocationDesc>
    <Area>"Malibu"</Area>
    <LATLON>"34050000:118550000"</LATLON>
    <LogDetails>
      <details><IncidentDetail>"[1] SOLO TC"</IncidentDetail></details>
    </LogDetails>
  </Log>
  <Log ID="260724XX0002">
    <LogTime>"Jul 24 2026  7:00PM"</LogTime>
    <LogType>"CLOSURE of a Road"</LogType>
    <Location>"SR-1 / Sunset"</Location>
    <LocationDesc>""</LocationDesc>
    <Area>"Pacific Palisades"</Area>
    <LATLON>"34060000:118560000"</LATLON>
    <LogDetails></LogDetails>
  </Log>
</Dispatch></Center></State>
"""


def _lcs_item(
    *,
    closure_id: str = "C1AB",
    log: str = "1",
    lon1: float = -118.55,
    lat1: float = 34.05,
    lon2: float = -118.54,
    lat2: float = 34.06,
    type_of_closure: str = "Full",
    start_epoch: int = 1000,
    end_epoch: int = 2000,
    code_1097: bool = False,
    route: str = "SR-1",
) -> dict:
    return {
        "lcs": {
            "index": f"{closure_id}-{log}",
            "recordTimestamp": {"recordEpoch": "1500"},
            "location": {
                "travelFlowDirection": "North",
                "begin": {
                    "beginDistrict": "7",
                    "beginLocationName": "A St",
                    "beginNearbyPlace": "Los Angeles",
                    "beginLongitude": str(lon1),
                    "beginLatitude": str(lat1),
                    "beginRoute": route,
                },
                "end": {
                    "endLongitude": str(lon2),
                    "endLatitude": str(lat2),
                    "endRoute": route,
                    "endLocationName": "B St",
                },
            },
            "closure": {
                "closureID": closure_id,
                "logNumber": log,
                "closureTimestamp": {
                    "closureStartEpoch": str(start_epoch),
                    "closureEndEpoch": str(end_epoch),
                    "isClosureEndIndefinite": "false",
                },
                "facility": "Mainline",
                "typeOfClosure": type_of_closure,
                "typeOfWork": "Utility Work",
                "lanesClosed": "1, 2",
                "totalExistingLanes": "4",
                "code1097": {"isCode1097": "true" if code_1097 else "false"},
            },
        }
    }


class SituationRoadsHelpersTests(unittest.TestCase):
    def test_districts_for_la_bounds(self) -> None:
        districts = districts_for_bounds([-118.6, 34.0, -118.5, 34.1])
        self.assertIn(7, districts)

    def test_classify_full_closure(self) -> None:
        kind, severity = classify_lcs_closure({"typeOfClosure": "Full"})
        self.assertEqual(kind, "closure")
        self.assertEqual(severity, "closed")

    def test_normalize_active_window(self) -> None:
        feature = normalize_lcs_record(_lcs_item(start_epoch=1000, end_epoch=2000), now_epoch=1500)
        self.assertIsNotNone(feature)
        assert feature is not None
        self.assertEqual(feature["status"], "active")
        self.assertEqual(feature["severity"], "closed")
        self.assertEqual(feature["geometry"]["type"], "LineString")

    def test_normalize_skips_far_future(self) -> None:
        feature = normalize_lcs_record(
            _lcs_item(start_epoch=1500 + 48 * 3600, end_epoch=1500 + 50 * 3600),
            now_epoch=1500,
        )
        self.assertIsNone(feature)

    def test_filter_and_summary(self) -> None:
        payload = {"data": [_lcs_item(), _lcs_item(log="2", lon1=-117.0, lat1=33.0, lon2=-116.9, lat2=33.1)]}
        candidates = parse_lcs_payload(payload, now_epoch=1500)
        hits = filter_features_to_bounds(candidates, [-118.6, 34.0, -118.5, 34.1])
        self.assertEqual(len(hits), 1)
        summary = summarize_features(hits)
        self.assertEqual(summary["closure_count"], 1)
        self.assertEqual(summary["feature_count"], 1)

    def test_osm_access_no(self) -> None:
        feature = normalize_osm_element(
            {
                "type": "way",
                "id": 99,
                "tags": {"highway": "residential", "access": "no", "name": "Blocked Rd"},
                "geometry": [
                    {"lon": -118.55, "lat": 34.05},
                    {"lon": -118.54, "lat": 34.05},
                ],
            }
        )
        self.assertIsNotNone(feature)
        assert feature is not None
        self.assertEqual(feature["severity"], "closed")
        self.assertEqual(feature["source"], "OpenStreetMap")


class SituationChpTests(unittest.TestCase):
    def test_parse_latlon(self) -> None:
        coords = parse_chp_latlon('"34050000:118550000"')
        self.assertIsNotNone(coords)
        assert coords is not None
        self.assertAlmostEqual(coords[0], 34.05, places=4)
        self.assertAlmostEqual(coords[1], -118.55, places=4)

    def test_classify_collision(self) -> None:
        kind, severity = classify_chp_logtype("1182-Trfc Collision-No Inj")
        self.assertEqual(kind, "incident")
        self.assertEqual(severity, "major")

    def test_parse_and_merge_chp(self) -> None:
        candidates = parse_chp_xml(SAMPLE_CHP)
        self.assertEqual(len(candidates), 2)
        hits = filter_features_to_bounds(candidates, [-118.6, 34.0, -118.5, 34.1])
        self.assertEqual(len(hits), 2)
        kinds = {f["kind"] for f in hits}
        self.assertIn("incident", kinds)
        self.assertIn("closure", kinds)

    def test_wants_road_conditions(self) -> None:
        self.assertTrue(wants_road_conditions("any road closures near this AOI?"))
        self.assertTrue(wants_road_conditions("CHP incidents nearby"))
        self.assertFalse(wants_road_conditions("nearest hospital"))


class SituationRoadsBuildTests(unittest.TestCase):
    def test_build_from_lcs_fixture(self) -> None:
        def lcs_fetch(_url: str):
            return {
                "data": [
                    _lcs_item(code_1097=True, start_epoch=100, end_epoch=200),
                    _lcs_item(
                        closure_id="C2",
                        log="1",
                        type_of_closure="Lane",
                        lon1=-118.552,
                        lat1=34.051,
                        lon2=-118.551,
                        lat2=34.052,
                        start_epoch=1400,
                        end_epoch=1600,
                    ),
                ]
            }

        def osm_fetch(_endpoint: str, _body: bytes):
            raise AssertionError("OSM should not be called when LCS has hits")

        payload = build_situation_roads(
            "demo_aoi",
            bounds_wgs84=[-118.6, 34.0, -118.5, 34.1],
            centroid_wgs84=[-118.55, 34.05],
            lcs_fetch_fn=lcs_fetch,
            osm_fetch_fn=osm_fetch,
            chp_fetch_fn=lambda _url: EMPTY_CHP,
            now_epoch=1500,
            use_district_cache=False,
            use_chp_cache=False,
        )
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["source"], "Caltrans LCS")
        self.assertGreaterEqual(payload["summary"]["feature_count"], 1)
        self.assertTrue(all(f["geometry"]["type"] in {"Point", "LineString"} for f in payload["features"]))

    def test_build_merges_lcs_and_chp(self) -> None:
        def lcs_fetch(_url: str):
            return {"data": [_lcs_item(code_1097=True, start_epoch=100, end_epoch=200)]}

        payload = build_situation_roads(
            "demo_aoi",
            bounds_wgs84=[-118.6, 34.0, -118.5, 34.1],
            lcs_fetch_fn=lcs_fetch,
            osm_fetch_fn=lambda *_a, **_k: {"elements": []},
            chp_fetch_fn=lambda _url: SAMPLE_CHP,
            now_epoch=1500,
            use_district_cache=False,
            use_chp_cache=False,
        )
        self.assertIn("Caltrans LCS", payload["source"])
        self.assertIn("CHP", payload["source"])
        self.assertGreaterEqual(payload["summary"]["incident_count"], 1)
        md = format_situation_roads_markdown(payload)
        self.assertIn("Road conditions", md)
        self.assertIn("incidents", md)

    def test_osm_fallback_when_lcs_empty(self) -> None:
        def lcs_fetch(_url: str):
            return {"data": []}

        def osm_fetch(_endpoint: str, _body: bytes):
            return {
                "elements": [
                    {
                        "type": "way",
                        "id": 1,
                        "tags": {"highway": "secondary", "access": "no", "name": "Closed Ave"},
                        "geometry": [
                            {"lon": -118.55, "lat": 34.05},
                            {"lon": -118.549, "lat": 34.051},
                        ],
                    }
                ]
            }

        payload = build_situation_roads(
            "demo_aoi",
            bounds_wgs84=[-118.6, 34.0, -118.5, 34.1],
            lcs_fetch_fn=lcs_fetch,
            osm_fetch_fn=osm_fetch,
            chp_fetch_fn=lambda _url: EMPTY_CHP,
            now_epoch=1500,
            use_district_cache=False,
            use_chp_cache=False,
        )
        self.assertEqual(payload["source"], "OpenStreetMap")
        self.assertEqual(payload["summary"]["feature_count"], 1)


if __name__ == "__main__":
    unittest.main()
