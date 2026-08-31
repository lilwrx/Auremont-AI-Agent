// Zone page for the "Sao Biển" villa sub-zone, extracted from the old
// single-scroll CategoryDetailPage so each sub-zone owns its own route.
import { FloorPlanTabs, TowerSpotlight, ZoneHeaderBanner, type ImageTab } from "../shared";

// "Location / Rendering" tab for Sao Biển — only 2 overall images (no per-type
// exterior renderings like Hải Âu, and no per-type floor plans like Ngọc
// Trai/Hải Âu, since the crawled source has none available).
const SAO_BIEN_LOCATION_TABS: ImageTab[] = [
  { label: "Vị trí Tiểu khu Sao Biển", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/sao-bien/vinhomes-ocean-park-sao-bien.jpg" },
  { label: "Phối cảnh Sao Biển", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/sao-bien/phoi-canh-sao-bien-vinhomes-ocean-park.jpg" },
];

// Size/storey figures for Sao Biển villa types — sourced directly from pricing
// in sao_bien.json, no invented figures.
const SAO_BIEN_UNIT_TYPES = [
  { label: "Biệt thự đơn lập", size: "148,5 – 368,6m²", storeys: "3 tầng nổi và 1 tum" },
  { label: "Biệt thự song lập", size: "127,5 – 150m²", storeys: "3 tầng nổi và 1 tum" },
  { label: "Biệt thự liền kề", size: "71,3 – 151,9m²", storeys: "4 tầng nổi và 1 tum" },
  { label: "Nhà phố shophouse", size: "67,5 – 173m²", storeys: "4 tầng nổi và 1 tum" },
];

export function SaoBienZone() {
  return (
    <div id="tieu-khu-sao-bien" className="anchor-section">
      <ZoneHeaderBanner title="Tiểu khu Sao Biển" subtitle="Ôm trọn hồ điều hòa trung tâm 25ha" />
      <TowerSpotlight
        projectId="sao-bien"
        image="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/sao-bien/phoi-canh-sao-bien-vinhomes-ocean-park.jpg"
        oval={false}
        hideImage
      />
      <FloorPlanTabs title="Vị trí & Phối cảnh Sao Biển" tabs={SAO_BIEN_LOCATION_TABS} compact />
      <div className="intro-text" style={{ marginBottom: 20 }}>
        <p className="page-sub" style={{ maxWidth: "none" }}>
          <strong>Tiểu khu Sao Biển</strong> bao gồm các loại biệt thự đơn lập, biệt thự song lập, biệt
          thự liền kề và nhà phố shophouse, ôm trọn hồ điều hòa trung tâm 25ha và biển hồ nước mặn 6,1ha
          của Vinhomes Ocean Park.
        </p>
        <ul className="zone-spotlight-list">
          {SAO_BIEN_UNIT_TYPES.map((u) => (
            <li key={u.label}>
              <strong>{u.label}:</strong> diện tích {u.size}; xây dựng {u.storeys}.
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
