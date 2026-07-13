import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { AoiDetail } from "../api/client";
import { dataAssetUrl } from "../api/client";
import type { BuildingScope } from "../buildingScope";
import type { BuildingScopeStats } from "../buildingScope";
import { reportMarkdownComponents } from "../markdownComponents";
import { reportScopeNote, resolveReportMarkdown, splitReportMarkdown } from "../reportScope";
import { SevereBuildingsSection } from "./SevereBuildingsSection";

type SevereBuilding = NonNullable<BuildingScopeStats["top_severe_buildings"]>[number];

type Props = {
  detail: AoiDetail | null;
  buildingScope: BuildingScope;
  buildingsGeojson?: GeoJSON.FeatureCollection | null;
  onShowBuildingOnMap?: (building: SevereBuilding) => void;
};

/** Scope-aware overlay previews in reports — disabled until we refine them. */
const SHOW_REPORT_OVERLAY_PREVIEW = false;

export function ReportPanel({
  detail,
  buildingScope,
  buildingsGeojson,
  onShowBuildingOnMap,
}: Props) {
  const reportMarkdown = useMemo(
    () => resolveReportMarkdown(detail, buildingScope),
    [detail, buildingScope],
  );

  const { head, tail } = useMemo(
    () => (reportMarkdown ? splitReportMarkdown(reportMarkdown) : { head: "", tail: "" }),
    [reportMarkdown],
  );

  if (!reportMarkdown) {
    return <p>No assessment report available for this AOI.</p>;
  }

  const pre = detail?.artifacts?.damage_overlay_pre;
  const post = detail?.artifacts?.damage_overlay_post;

  return (
    <div className="report-panel">
      <p className="stats-note">{reportScopeNote(buildingScope)}</p>
      {SHOW_REPORT_OVERLAY_PREVIEW && (pre || post) && (
        <div className="overlay-preview">
          {pre && (
            <figure>
              <img src={dataAssetUrl(pre)} alt="Pre-disaster damage overlay" />
              <figcaption>Pre-disaster overlay</figcaption>
            </figure>
          )}
          {post && (
            <figure>
              <img src={dataAssetUrl(post)} alt="Post-disaster damage overlay" />
              <figcaption>
                Post-disaster overlay
                {buildingScope === "official" && (
                  <> — imagery overlays may include detected structures outside LARIAC footprints</>
                )}
              </figcaption>
            </figure>
          )}
        </div>
      )}
      <article className="report-md">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={reportMarkdownComponents}>
          {head}
        </ReactMarkdown>
        {onShowBuildingOnMap && (
          <SevereBuildingsSection
            detail={detail}
            buildingScope={buildingScope}
            buildingsGeojson={buildingsGeojson}
            onShowOnMap={onShowBuildingOnMap}
          />
        )}
        {tail ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={reportMarkdownComponents}>
            {tail}
          </ReactMarkdown>
        ) : null}
      </article>
    </div>
  );
}
