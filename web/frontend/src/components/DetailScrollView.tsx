import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { FacilitiesPanel } from "./HospitalsPanel";
import { MapPanel, type BasemapId } from "./MapPanel";
import { ReportPanel } from "./ReportPanel";
import { StatsPanel } from "./StatsPanel";
import { VlmArbitrationPanel } from "./VlmArbitrationPanel";
import { BuildingScopeToggle } from "./BuildingScopeToggle";
import type { AoiDetail, AssessmentJob, Hospital, SituationRoads, SituationWeather, VlmReviewMode } from "../api/client";
import { getSituationRoads, getSituationWeather } from "../api/client";
import {
  filterBuildingsGeojson,
  hasFusedBuildingView,
  hasVlmReviewedView,
  type BuildingScope,
} from "../buildingScope";
import { findHospitalForFocus, hospitalRowKey, mergeFacilityDetails, resolveHospitalCoords } from "../hospitalUtils";
import type { MapFocus } from "../mapFocus";
import type { BuildingScopeStats } from "../buildingScope";
import { featureCentroidWgs84, findBuildingFeatureById } from "../regionStats";
import type { ImageryCorners } from "./RotatedImageryOverlay";

export type SectionId = "map" | "stats" | "vlm" | "report" | "facilities";

const BASE_SECTIONS: { id: SectionId; label: string }[] = [
  { id: "map", label: "Map" },
  { id: "stats", label: "Stats" },
  { id: "report", label: "Report" },
  { id: "facilities", label: "Facilities" },
];

const VLM_SECTION = { id: "vlm" as const, label: "VLM reasoning" };

function resolveBasemapForAoi(
  choice: BasemapId,
  hasPre: boolean,
  hasPost: boolean,
): BasemapId {
  if (choice === "street") return "street";
  if (choice === "post") {
    if (hasPost) return "post";
    if (hasPre) return "pre";
    return "street";
  }
  if (hasPre) return "pre";
  if (hasPost) return "post";
  return "street";
}

type Props = {
  /** Null / empty = shared idle map; chrome fades in when set. */
  aoiId: string | null;
  detail: AoiDetail | null;
  bounds?: [number, number, number, number];
  imageryCorners?: ImageryCorners | null;
  buildingsGeojson?: GeoJSON.FeatureCollection | null;
  detectedExtraCount?: number;
  detailLoading?: boolean;
  mapCenter?: [number, number];
  hospitals: Hospital[];
  externalMapFocus?: MapFocus | null;
  onClearExternalMapFocus?: () => void;
  onRunVlm?: (
    mode: VlmReviewMode,
    options?: { damagedOnly?: boolean; limit?: number },
  ) => void;
  onStopVlm?: () => void;
  onVlmPreference?: (
    reviewType: "discrepancy" | "damage",
    featureId: string,
    decision: "agree" | "disagree",
  ) => Promise<void> | void;
  vlmJob?: AssessmentJob | null;
  vlmBusy?: boolean;
  /** Active assessment job for this AOI — drives progressive map reveal. */
  assessmentJob?: AssessmentJob | null;
  /**
   * Bumped when chat finishes weather_context / situation_roads so the map
   * re-reads the warm situation cache instead of waiting on a stale in-flight GET.
   */
  weatherRefreshKey?: number;
  roadsRefreshKey?: number;
};

function DetailSection({
  id,
  title,
  actions,
  children,
  sectionRef,
}: {
  id: SectionId;
  title: string;
  actions?: ReactNode;
  children: ReactNode;
  sectionRef: (node: HTMLElement | null) => void;
}) {
  return (
    <section
      ref={sectionRef}
      id={`section-${id}`}
      className="detail-section"
      aria-labelledby={`heading-${id}`}
    >
      <div className="detail-section-header">
        <h2 id={`heading-${id}`} className="detail-section-title">
          {title}
        </h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

function scrollOffsetInContainer(container: HTMLElement, element: HTMLElement): number {
  const containerTop = container.getBoundingClientRect().top;
  const elementTop = element.getBoundingClientRect().top;
  return container.scrollTop + (elementTop - containerTop);
}

function pickActiveSection(
  container: HTMLElement,
  sectionRefs: Record<SectionId, HTMLElement | null>,
  sections: { id: SectionId; label: string }[],
): SectionId {
  const marker = container.getBoundingClientRect().top + 24;
  let active: SectionId = sections[0]?.id ?? "map";

  for (const { id } of sections) {
    const element = sectionRefs[id];
    if (!element) continue;
    if (element.getBoundingClientRect().top <= marker) {
      active = id;
    }
  }

  return active;
}

export function DetailScrollView({
  aoiId,
  detail,
  bounds,
  imageryCorners,
  buildingsGeojson,
  detectedExtraCount,
  detailLoading = false,
  mapCenter,
  hospitals,
  externalMapFocus = null,
  onClearExternalMapFocus,
  onRunVlm,
  onStopVlm,
  onVlmPreference,
  vlmJob = null,
  vlmBusy = false,
  assessmentJob = null,
  weatherRefreshKey = 0,
  roadsRefreshKey = 0,
}: Props) {
  const isActive = Boolean(aoiId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevAoiIdRef = useRef<string | null>(null);
  const basemapChoiceRef = useRef<BasemapId>("pre");
  const [basemap, setBasemap] = useState<BasemapId>("pre");
  const sectionRefs = useRef<Record<SectionId, HTMLElement | null>>({
    map: null,
    stats: null,
    vlm: null,
    report: null,
    facilities: null,
  });
  const [activeSection, setActiveSection] = useState<SectionId>("map");
  const [buildingScope, setBuildingScope] = useState<BuildingScope>("official");
  const [mapFocus, setMapFocus] = useState<MapFocus | null>(null);
  const mapFocusKeyRef = useRef(0);
  const ticking = useRef(false);
  const [situationWeather, setSituationWeather] = useState<SituationWeather | null>(null);
  const [situationLoading, setSituationLoading] = useState(false);
  const [situationError, setSituationError] = useState<string | null>(null);
  const [situationRoads, setSituationRoads] = useState<SituationRoads | null>(null);
  const [situationRoadsLoading, setSituationRoadsLoading] = useState(false);
  const [situationRoadsError, setSituationRoadsError] = useState<string | null>(null);
  const situationWeatherAoiRef = useRef<string | null>(null);
  const situationRoadsAoiRef = useRef<string | null>(null);

  useEffect(() => {
    if (!aoiId) {
      situationWeatherAoiRef.current = null;
      setSituationWeather(null);
      setSituationError(null);
      setSituationLoading(false);
      return;
    }
    const aoiChanged = situationWeatherAoiRef.current !== aoiId;
    situationWeatherAoiRef.current = aoiId;
    let cancelled = false;
    if (aoiChanged) {
      setSituationWeather(null);
      setSituationError(null);
    }
    setSituationLoading(true);
    getSituationWeather(aoiId)
      .then((payload) => {
        if (!cancelled) {
          setSituationWeather(payload);
          setSituationError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          if (aoiChanged) setSituationWeather(null);
          setSituationError(err instanceof Error ? err.message : "situation_unavailable");
        }
      })
      .finally(() => {
        if (!cancelled) setSituationLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [aoiId, weatherRefreshKey]);

  useEffect(() => {
    if (!aoiId) {
      situationRoadsAoiRef.current = null;
      setSituationRoads(null);
      setSituationRoadsError(null);
      setSituationRoadsLoading(false);
      return;
    }
    const aoiChanged = situationRoadsAoiRef.current !== aoiId;
    situationRoadsAoiRef.current = aoiId;
    let cancelled = false;
    if (aoiChanged) {
      setSituationRoads(null);
      setSituationRoadsError(null);
    }
    setSituationRoadsLoading(true);
    getSituationRoads(aoiId)
      .then((payload) => {
        if (!cancelled) {
          setSituationRoads(payload);
          setSituationRoadsError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          if (aoiChanged) setSituationRoads(null);
          setSituationRoadsError(err instanceof Error ? err.message : "roads_unavailable");
        }
      })
      .finally(() => {
        if (!cancelled) setSituationRoadsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [aoiId, roadsRefreshKey]);

  const showVlmSection = Boolean(aoiId && detail?.aoi_id === aoiId);

  const sections = useMemo(() => {
    if (!showVlmSection) return BASE_SECTIONS;
    const next = [...BASE_SECTIONS];
    const statsIndex = next.findIndex((section) => section.id === "stats");
    next.splice(statsIndex + 1, 0, VLM_SECTION);
    return next;
  }, [showVlmSection]);

  const setSectionRef = useCallback((id: SectionId) => {
    return (node: HTMLElement | null) => {
      sectionRefs.current[id] = node;
    };
  }, []);

  const syncActiveSection = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;
    const next = pickActiveSection(container, sectionRefs.current, sections);
    setActiveSection((prev) => (prev === next ? prev : next));
  }, [sections]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const onScroll = () => {
      if (ticking.current) return;
      ticking.current = true;
      requestAnimationFrame(() => {
        syncActiveSection();
        ticking.current = false;
      });
    };

    container.addEventListener("scroll", onScroll, { passive: true });
    syncActiveSection();

    return () => container.removeEventListener("scroll", onScroll);
  }, [aoiId, sections, syncActiveSection]);

  const handleBasemapChange = useCallback((next: BasemapId) => {
    basemapChoiceRef.current = next;
    setBasemap(next);
  }, []);

  const detailReady = detail?.aoi_id === aoiId && Boolean(bounds);
  const imagery = detail?.aoi_id === aoiId ? detail.imagery : undefined;

  const imageryTimeline = useMemo(() => {
    if (!detail || detail.aoi_id !== aoiId) return null;
    const pickDate = (...candidates: unknown[]): string | null => {
      for (const raw of candidates) {
        const text = String(raw ?? "").trim();
        if (!text) continue;
        const iso = text.match(/(20\d{2})-(\d{2})-(\d{2})/);
        if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;
        const compact = text.match(/(20\d{2})(\d{2})(\d{2})/);
        if (compact) return `${compact[1]}-${compact[2]}-${compact[3]}`;
      }
      return null;
    };
    const dates = detail.imagery_dates ?? {};
    const match = detail.pre_match ?? {};
    const extras = (match.extras ?? {}) as Record<string, unknown>;
    return {
      pre: pickDate(dates.pre, match.date),
      post: pickDate(dates.post, match.disaster_date, extras.disaster_date),
    };
  }, [detail, aoiId]);

  const pipelineProgress = useMemo(() => {
    if (!assessmentJob || assessmentJob.aoi_id !== aoiId) return null;
    const progress = assessmentJob.progress;
    return {
      status: assessmentJob.status,
      currentStep: progress?.current_step ?? null,
      completedSteps: [
        ...(assessmentJob.completed_steps ?? []),
        ...(progress?.completed_steps ?? []),
      ],
    };
  }, [assessmentJob, aoiId]);

  // New AOI (including in-progress upload): start from Pre so parent state cannot skip the reveal.
  useEffect(() => {
    if (prevAoiIdRef.current === aoiId) return;
    prevAoiIdRef.current = aoiId;
    basemapChoiceRef.current = "pre";
    setBasemap("pre");
  }, [aoiId]);

  useEffect(() => {
    if (!detailReady || !imagery) return;
    // While an assessment cinematic is running, MapPanel owns Pre → Post.
    if (assessmentJob && assessmentJob.aoi_id === aoiId) {
      const status = String(assessmentJob.status || "");
      if (status && status !== "completed" && status !== "failed" && status !== "cancelled") {
        return;
      }
    }

    const hasPre = Boolean(imagery.pre);
    const hasPost = Boolean(imagery.post);
    const next = resolveBasemapForAoi(basemapChoiceRef.current, hasPre, hasPost);
    if (next !== basemap) {
      basemapChoiceRef.current = next;
      setBasemap(next);
    }
  }, [aoiId, detailReady, imagery, assessmentJob, basemap]);

  useEffect(() => {
    setBuildingScope("official");
  }, [aoiId]);

  const showFusedBuildingView = hasFusedBuildingView(detail, detectedExtraCount);
  const showVlmBuildingView = hasVlmReviewedView(detail);
  const scopedBuildingsGeojson = useMemo(
    () => filterBuildingsGeojson(buildingsGeojson ?? null, buildingScope, detail),
    [buildingsGeojson, buildingScope, detail],
  );

  useEffect(() => {
    if (buildingScope === "vlm" && !showVlmBuildingView) {
      setBuildingScope(showFusedBuildingView ? "fused" : "official");
    }
  }, [buildingScope, showVlmBuildingView, showFusedBuildingView]);

  const buildingScopeToggle = (
    <BuildingScopeToggle
      value={buildingScope}
      onChange={setBuildingScope}
      showFused={showFusedBuildingView}
      showVlm={showVlmBuildingView}
      pending={detailLoading && !showFusedBuildingView}
    />
  );

  function scrollToSection(id: SectionId) {
    const container = scrollRef.current;
    const element = sectionRefs.current[id];
    if (!container || !element) return;

    const top = scrollOffsetInContainer(container, element);
    const target = Math.max(0, top - 8);
    // Already on this section — avoid smooth-scroll micro-jitter on every map deep-link.
    if (Math.abs(container.scrollTop - target) < 12) {
      setActiveSection(id);
      return;
    }
    container.scrollTo({ top: target, behavior: "smooth" });
    setActiveSection(id);
  }

  const showHospitalOnMap = useCallback((hospital: Hospital) => {
    const coordinates_wgs84 = resolveHospitalCoords(hospital);
    if (!coordinates_wgs84) return;
    mapFocusKeyRef.current += 1;
    setMapFocus({
      kind: "hospital",
      key: mapFocusKeyRef.current,
      hospitalKey: hospitalRowKey(hospital),
      name: hospital.name,
      coordinates_wgs84,
    });
    scrollToSection("map");
  }, []);

  useEffect(() => {
    if (!externalMapFocus) return;
    if (externalMapFocus.kind === "hospital") {
      const matched = findHospitalForFocus(hospitals, externalMapFocus);
      if (matched) {
        const enriched = mergeFacilityDetails(
          {
            name: externalMapFocus.name,
            coordinates_wgs84: externalMapFocus.coordinates_wgs84,
            distance_mi: externalMapFocus.distance_mi
              ? Number(externalMapFocus.distance_mi)
              : undefined,
            phone: externalMapFocus.phone,
            email: externalMapFocus.email,
            website: externalMapFocus.website,
            operator: externalMapFocus.operator,
            contact_name: externalMapFocus.contact_name,
            emergency: externalMapFocus.emergency,
            beds: externalMapFocus.beds,
            opening_hours: externalMapFocus.opening_hours,
            address: externalMapFocus.address,
            osm_type: externalMapFocus.osm_type,
            osm_id: externalMapFocus.osm_id,
            kind: externalMapFocus.facilityKind,
          },
          matched,
        );
        setMapFocus({
          ...externalMapFocus,
          hospitalKey: hospitalRowKey(matched),
          facilityKind: enriched.kind || externalMapFocus.facilityKind,
          phone: enriched.phone,
          email: enriched.email,
          website: enriched.website,
          operator: enriched.operator,
          contact_name: enriched.contact_name,
          emergency: enriched.emergency != null ? String(enriched.emergency) : undefined,
          beds: enriched.beds != null ? String(enriched.beds) : undefined,
          opening_hours: enriched.opening_hours,
          address: enriched.address ?? undefined,
          osm_type: enriched.osm_type,
          osm_id: enriched.osm_id != null ? String(enriched.osm_id) : undefined,
          distance_mi:
            enriched.distance_mi != null
              ? String(enriched.distance_mi)
              : externalMapFocus.distance_mi,
        });
        scrollToSection("map");
        return;
      }
    }
    setMapFocus(externalMapFocus);
    scrollToSection("map");
  }, [externalMapFocus, hospitals]);

  const handleMapRecenter = useCallback(() => {
    setMapFocus(null);
    onClearExternalMapFocus?.();
  }, [onClearExternalMapFocus]);

  const showBuildingOnMap = useCallback(
    (building: NonNullable<BuildingScopeStats["top_severe_buildings"]>[number]) => {
      const coordinates_wgs84 = building.centroid_wgs84;
      const bldId = building.bld_id != null ? String(building.bld_id) : "";
      if (!coordinates_wgs84 || !bldId) return;
      mapFocusKeyRef.current += 1;
      setMapFocus({
        kind: "building",
        key: mapFocusKeyRef.current,
        bldId,
        coordinates_wgs84,
      });
      scrollToSection("map");
    },
    [],
  );

  const showVlmBuildingOnMap = useCallback(
    (bldId: string) => {
      const feature = findBuildingFeatureById(buildingsGeojson, bldId);
      const coordinates_wgs84 = featureCentroidWgs84(feature);
      if (!feature || !coordinates_wgs84) return;

      const origin = String(feature.properties?.building_origin ?? "");
      const presenceRec = (detail?.vlm_arbitration?.results ?? []).find(
        (row) => row.feature_id === bldId,
      )?.vlm?.recommendation;
      const rejectedExtra = origin === "detected" && presenceRec === "reject_as_building";

      let nextScope: BuildingScope | null = null;
      if (rejectedExtra && buildingScope === "vlm") {
        // Rejected extras are removed from the VLM-reviewed layer; show them in fused.
        nextScope = showFusedBuildingView ? "fused" : "official";
      } else if (
        origin === "detected" &&
        buildingScope === "official" &&
        (showVlmBuildingView || showFusedBuildingView)
      ) {
        nextScope = showVlmBuildingView && !rejectedExtra ? "vlm" : "fused";
      }

      if (nextScope) setBuildingScope(nextScope);

      const focus = () => {
        mapFocusKeyRef.current += 1;
        setMapFocus({
          kind: "building",
          key: mapFocusKeyRef.current,
          bldId,
          coordinates_wgs84,
        });
        scrollToSection("map");
      };

      if (nextScope) {
        window.setTimeout(focus, 200);
      } else {
        focus();
      }
    },
    [
      buildingsGeojson,
      buildingScope,
      detail,
      showFusedBuildingView,
      showVlmBuildingView,
    ],
  );

  return (
    <section
      className={`detail-panel ${
        isActive ? "detail-chrome-visible" : "detail-panel-idle-map"
      }`}
    >
      <nav className="section-nav detail-chrome-nav" aria-label="AOI sections">
        {sections.map(({ id, label }) => {
          const enabled = isActive || id === "map";
          return (
            <button
              key={id}
              type="button"
              className={`section-nav-btn ${activeSection === id ? "active" : ""}`}
              onClick={() => {
                if (!enabled) return;
                scrollToSection(id);
              }}
              disabled={!enabled}
              title={enabled ? undefined : "Select or upload an AOI to open this section"}
            >
              {label}
            </button>
          );
        })}
      </nav>

      <div className="detail-scroll" ref={scrollRef}>
        <DetailSection
          id="map"
          title="Damage Map"
          sectionRef={setSectionRef("map")}
        >
          <MapPanel
            aoiId={aoiId}
            bounds={bounds}
            imagery={imagery}
            imageryReady={
              Boolean(aoiId) &&
              detail?.aoi_id === aoiId &&
              Boolean(bounds || detail.imagery?.pre || detail.imagery?.post)
            }
            imageryCorners={imageryCorners}
            buildingsGeojson={scopedBuildingsGeojson}
            buildingScope={buildingScope}
            onBuildingScopeChange={setBuildingScope}
            showFusedBuildingScope={showFusedBuildingView}
            buildingScopePending={detailLoading && !showFusedBuildingView}
            center={mapCenter}
            basemap={basemap}
            onBasemapChange={handleBasemapChange}
            hospitals={hospitals}
            focusMap={mapFocus}
            onRecenter={handleMapRecenter}
            situationWeather={situationWeather}
            situationLoading={situationLoading}
            situationError={situationError}
            situationRoads={situationRoads}
            situationRoadsLoading={situationRoadsLoading}
            situationRoadsError={situationRoadsError}
            aoiStats={(detail?.stats as Record<string, unknown> | undefined) ?? null}
            imageryTimeline={imageryTimeline}
            pipelineProgress={pipelineProgress}
          />
        </DetailSection>

        {isActive && (
          <>
            <DetailSection
              id="stats"
              title="Assessment Stats"
              actions={buildingScopeToggle}
              sectionRef={setSectionRef("stats")}
            >
              <StatsPanel
                detail={detail}
                buildingScope={buildingScope}
                buildingsGeojson={buildingsGeojson}
              />
            </DetailSection>

            {showVlmSection && (
              <DetailSection
                id="vlm"
                title="Visual Verifier（VLM reasoning）"
                sectionRef={setSectionRef("vlm")}
              >
                <VlmArbitrationPanel
                  detail={detail}
                  onShowBuildingOnMap={showVlmBuildingOnMap}
                  onRunVlm={onRunVlm}
                  onStopVlm={onStopVlm}
                  onVlmPreference={onVlmPreference}
                  vlmJob={vlmJob}
                  vlmBusy={vlmBusy}
                />
              </DetailSection>
            )}

            <DetailSection
              id="report"
              title="Assessment Report"
              actions={buildingScopeToggle}
              sectionRef={setSectionRef("report")}
            >
              <ReportPanel
                detail={detail}
                buildingScope={buildingScope}
                buildingsGeojson={buildingsGeojson}
                onShowBuildingOnMap={showBuildingOnMap}
              />
            </DetailSection>

            <DetailSection
              id="facilities"
              title="Facilities"
              sectionRef={setSectionRef("facilities")}
            >
              <FacilitiesPanel detail={detail} onShowOnMap={showHospitalOnMap} />
            </DetailSection>
          </>
        )}
      </div>
    </section>
  );
}
