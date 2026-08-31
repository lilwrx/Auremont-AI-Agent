// Zone page for the "Hải Âu" villa sub-zone, extracted from the old
// single-scroll CategoryDetailPage so each sub-zone owns its own route.
import { FloorPlanTabs, TowerSpotlight, ZoneHeaderBanner, type ImageTab } from "../shared";

// Real floor plans for Hải Âu — each type has 2 variants, per the crawled image files.
const HAI_AU_FLOOR_PLANS: ImageTab[] = [
  { label: "Đơn lập (mẫu 1)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/mat-bang-don-lap-1-hai-au-1202x1500.jpg" },
  { label: "Đơn lập (mẫu 2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/mat-bang-don-lap-2-hai-au-1213x1500.jpg" },
  { label: "Song lập (mẫu 1)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/mat-bang-song-lap-1-hai-au-1217x1500.jpg" },
  { label: "Song lập (mẫu 2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/mat-bang-song-lap-2-hai-au-1199x1500.jpg" },
  { label: "Liền kề (mẫu 1)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/mat-bang-lien-ke-1-hai-au-1162x1500.jpg" },
  { label: "Liền kề (mẫu 2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/mat-bang-lien-ke-2-hai-au-1212x1500.jpg" },
];

// "Location" tab for Hải Âu — only 1 overall location image (no separate
// "overall rendering" image like Ngọc Trai has; the 3 per-type exterior images
// live separately in HAI_AU_UNIT_PHOTOS, following the same 2-section split as
// Ngọc Trai).
const HAI_AU_LOCATION_TABS: ImageTab[] = [
  { label: "Vị trí Tiểu khu Hải Âu", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/vinhomes-ocean-park-hai-au.jpg" },
];

// Exterior rendering images for each Hải Âu villa type — a dedicated section
// right below the size intro, BEFORE the "floor plan" (technical drawing)
// section, following the same 2-section structure as Ngọc Trai (renderings vs.
// floor plan drawings).
const HAI_AU_UNIT_PHOTOS: ImageTab[] = [
  { label: "Đơn lập", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/don-lap-hai-au.jpg" },
  { label: "Song lập", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/song-lap-hai-au.jpg" },
  { label: "Liền kề", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/lien-ke-vinhomes-ocean-park.jpg" },
];

// Size/storey figures for Hải Âu villa types — sourced directly from pricing in
// hai_au.json, no invented figures.
const HAI_AU_UNIT_TYPES = [
  { label: "Biệt thự đơn lập", size: "141,47 – 417,52m²", storeys: "3 tầng nổi và 1 tum" },
  { label: "Biệt thự song lập", size: "148 – 154,61m²", storeys: "3 tầng nổi và 1 tum" },
  { label: "Biệt thự liền kề", size: "89,96 – 145m²", storeys: "4 tầng nổi và 1 tum" },
];

export function HaiAuZone() {
  return (
    <div id="tieu-khu-hai-au" className="anchor-section">
      <ZoneHeaderBanner title="Tiểu khu Hải Âu" subtitle="Thiết kế theo hình cánh chim Hải Âu" />
      <TowerSpotlight
        projectId="hai-au"
        image="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/vinhomes-ocean-park-hai-au.jpg"
        oval={false}
        hideImage
      />
      <FloorPlanTabs title="Vị trí & Phối cảnh Hải Âu" tabs={HAI_AU_LOCATION_TABS} compact />
      <p className="page-sub" style={{ maxWidth: "none", marginTop: 16 }}>
        <em>
          Lưu ý: Vinhomes Ocean Park là dự án có quy mô lớn, chính vì vậy các hình ảnh và bản vẽ về Mặt
          bằng chia lô chi tiết có độ phân giải và dung lượng file rất lớn. Vì vậy, quý khách hàng muốn
          nhận File Mặt bằng chia lô xin vui lòng đăng ký địa chỉ email, chúng tôi sẽ gửi tới quý khách
          hàng sớm nhất.
        </em>
      </p>
      <section className="section-block zone-spotlight-media-solo">
        <img
          src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/ho-dieu-hoa-bien-ho-1500x600.jpg"
          alt="Cảnh quan Hồ điều hòa & Biển hồ Hải Âu"
        />
      </section>
      <div className="intro-text" style={{ marginBottom: 20 }}>
        <p className="page-sub" style={{ maxWidth: "none" }}>
          <strong>Tiểu khu Hải Âu</strong> bao gồm các loại biệt thự thương mại đơn lập, song lập và liền
          kề, được thiết kế theo hình cánh chim Hải Âu, sở hữu tầm nhìn ra hồ điều hòa và biển hồ nước mặn.
        </p>
        <ul className="zone-spotlight-list">
          {HAI_AU_UNIT_TYPES.map((u) => (
            <li key={u.label}>
              <strong>{u.label}:</strong> diện tích {u.size}; xây dựng {u.storeys}.
            </li>
          ))}
        </ul>
      </div>
      <FloorPlanTabs title="Thiết kế các loại biệt thự khu Hải Âu" tabs={HAI_AU_UNIT_PHOTOS} />
      <FloorPlanTabs title="Thiết kế mặt bằng các loại biệt thự khu Hải Âu" tabs={HAI_AU_FLOOR_PLANS} />
    </div>
  );
}
