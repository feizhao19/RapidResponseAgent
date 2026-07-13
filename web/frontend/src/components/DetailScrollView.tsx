import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { HospitalsPanel } from "./HospitalsPanel";
import { MapPanel, type BasemapId } from "./MapPanel";
import { ReportPanel } from "./ReportPanel";
import { StatsPanel } from "./StatsPanel";
import { VlmArbitrationPanel } from "./VlmArbitrationPanel";
import { BuildingScopeToggle } from "./BuildingScopeToggle";
import type { AoiDetail, AssessmentJob, Hospital, VlmReviewMode } from "../api/client";
import {
  filterBuildingsGeojson,
  hasFusedBuildingView,
  hasVlmReviewedView,
  type BuildingScope,
} from "../buildingScope";
import { hospitalRowKey, resolveHospitalCoords } from "../hospitalUtils";
import type { MapFocus } from "../mapFocus";
import type { BuildingScopeStats } from "../buildingScope";
import { featureCentroidWgs84, findBuildingFeatureById } from "../regionStats";
import type { ImageryCorners } from "./RotatedImageryOverlay";

export type SectionId = "map" | "stats" | "vlm" | "report" | "hospitals";

const BASE_SECTIONS: { id: SectionId; label: string }[] = [
  { id: "map", label: "Map" },
  { id: "stats", label: "Stats" },
  { id: "report", label: "Report" },
  { id: "hospitals", label: "Hospitals" },
];

const VLM_SECTION = { id: "vlm" as const, label: "VLM Review" };

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
  aoiId: string;
  detail: AoiDetail | null;
  bounds?: [number, number, number, number];
  imageryCorners?: ImageryCorners | null;
  buildingsGeojson?: GeoJSON.FeatureCollection | null;
  detectedExtraCount?: number;
  detailLoading?: boolean;
  mapCenter?: [number, number];
  hospitals: Hospital[];
  externalMapFocus?: MapFocus | null;
  onRunVlm?: (mode: VlmReviewMode, options?: { damagedOnly?: boolean }) => void;
  onStopVlm?: () => void;
  vlmJob?: AssessmentJob | null;
  vlmBusy?: boolean;
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
  onRunVlm,
  onStopVlm,
  vlmJob = null,
  vlmBusy = false,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevAoiIdRef = useRef<string | null>(null);
  const basemapChoiceRef = useRef<BasemapId>("pre");
  const [basemap, setBasemap] = useState<BasemapId>("pre");
  const sectionRefs = useRef<Record<SectionId, HTMLElement | null>>({
    map: null,
    stats: null,
    vlm: null,
    report: null,
    hospitals: null,
  });
  const [activeSection, setActiveSection] = useState<SectionId>("map");
  const [buildingScope, setBuildingScope] = useState<BuildingScope>("official");
  const [mapFocus, setMapFocus] = useState<MapFocus | null>(null);
  const mapFocusKeyRef = useRef(0);
  const ticking = useRef(false);

  const showVlmSection = Boolean(detail?.aoi_id === aoiId);

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
  const imagery = detailReady ? detail?.imagery : undefined;

  useEffect(() => {
    if (!detailReady || !imagery) return;

    const hasPre = Boolean(imagery.pre);
    const hasPost = Boolean(imagery.post);
    const switched = prevAoiIdRef.current !== null && prevAoiIdRef.current !== aoiId;

    if (switched) {
      const next = resolveBasemapForAoi(basemapChoiceRef.current, hasPre, hasPost);
      basemapChoiceRef.current = next;
      setBasemap(next);
    } else if (prevAoiIdRef.current === null) {
      const next = resolveBasemapForAoi("pre", hasPre, hasPost);
      basemapChoiceRef.current = next;
      setBasemap(next);
    }

    prevAoiIdRef.current = aoiId;
  }, [aoiId, detailReady, imagery]);

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
    container.scrollTo({ top: Math.max(0, top - 8), behavior: "smooth" });
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
    setMapFocus(externalMapFocus);
    scrollToSection("map");
  }, [externalMapFocus]);

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
    <section className="detail-panel">
      <nav className="section-nav" aria-label="AOI sections">
        {sections.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            className={`section-nav-btn ${activeSection === id ? "active" : ""}`}
            onClick={() => scrollToSection(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="detail-scroll" ref={scrollRef}>
        <DetailSection
          id="map"
          title="Damage Map"
          actions={buildingScopeToggle}
          sectionRef={setSectionRef("map")}
        >
          <MapPanel
            key={aoiId}
            aoiId={aoiId}
            bounds={bounds}
            imagery={imagery}
            imageryReady={detailReady}
            imageryCorners={imageryCorners}
            buildingsGeojson={scopedBuildingsGeojson}
            buildingScope={buildingScope}
            center={mapCenter}
            basemap={basemap}
            onBasemapChange={handleBasemapChange}
            hospitals={hospitals}
            focusMap={mapFocus}
          />
        </DetailSection>

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
          <DetailSection id="vlm" title="VLM Building Review" sectionRef={setSectionRef("vlm")}>
            <VlmArbitrationPanel
              detail={detail}
              onShowBuildingOnMap={showVlmBuildingOnMap}
              onRunVlm={onRunVlm}
              onStopVlm={onStopVlm}
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

        <DetailSection id="hospitals" title="Nearest Hospitals" sectionRef={setSectionRef("hospitals")}>
          <HospitalsPanel detail={detail} onShowOnMap={showHospitalOnMap} />
        </DetailSection>
      </div>
    </section>
  );
}
