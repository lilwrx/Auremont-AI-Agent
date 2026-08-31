// Zone page for a single commercial shophouse row (SH09/SB11A/HA08/BH9B),
// extracted from the old single-scroll CategoryDetailPage. The shared data
// arrays live here too, since the Shophouse catalogue page reuses them for its
// common intro block.
import { FloorPlanTabs, TowerSpotlight, ZoneHeaderBanner } from "../shared";

// Data for the 4 commercial shophouse rows (SH09/SB11A/HA08/BH9B) — sourced
// directly from 4 separate crawled JSON files (shop_thuong_mai_*.json); NOT
// unified into a shared template because each row has its own address/size/
// amenities. Each image file was individually checked before assignment
// (vi-tri = location map, mat-bang = plot layout, the rest are exterior/
// rendering photos — a couple of files named "mat_b1/mat_b2" (HA08) are also
// exterior photos despite the misleading name).
export interface ShopTmdvProject {
  projectId: string;
  code: string;
  fullName: string;
  subtitle: string;
  anchorId: string;
  overview: {
    totalUnits: number;
    storeys: string;
    landArea: string;
    constructionArea: string;
    floorArea: string;
    handover: string;
    ownership: string;
  };
  locationTabs: { label: string; src: string }[];
  exteriorTabs: { label: string; src: string }[];
  masterPlanTabs: { label: string; src: string }[];
  businessNote?: string;
}

export const SHOP_TMDV_PROJECTS: ShopTmdvProject[] = [
  {
    projectId: "shop-thuong-mai-sh09",
    code: "SH09",
    fullName: "Shop thương mại dịch vụ San Hô 09 (SH09)",
    subtitle: "Kế cận Đại lộ 52m và Đường 30m",
    anchorId: "shop-sh09",
    overview: {
      totalUnits: 24,
      storeys: "4 tầng nổi + 1 tum",
      landArea: "81 – 165,5m²",
      constructionArea: "57,9 – 61,2m²",
      floorArea: "218,1m²",
      handover: "Nhận nhà ngay",
      ownership: "Sở hữu 50 năm, được làm sổ hồng ngay",
    },
    locationTabs: [
      { label: "Vị trí SH09", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/vi-tri-shop-thuong-mai-dich-vu-bien-ho-sh09-vinhomes-ocean-park.jpg" },
      { label: "Vị trí SH09 (2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/vi-tri-shop-thuong-mai-dich-vu-bien-ho-sh09-vinhomes-ocean-park-1.jpg" },
    ],
    exteriorTabs: [
      { label: "Ảnh thực tế", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/shop-tmdv-sh09.jpg" },
      { label: "Ảnh thực tế (2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/sanho_anh_thuc_te_1.jpg" },
      { label: "Ảnh thực tế (3)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/sanho_anh_thuc_te_2.jpg" },
      { label: "Ảnh thực tế (4)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/sanho_anh_thuc_te_3.jpg" },
      { label: "Ảnh thực tế (5)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/sanho_anh_thuc_te_4.jpg" },
    ],
    masterPlanTabs: [
      { label: "Tổng mặt bằng SH09", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/mat-bang-shop-thuong-mai-dich-vu-bien-ho-sh09-vinhomes-ocean-park-2048x1152.jpg" },
    ],
    businessNote: "Được phép kinh doanh đa dạng ngành nghề: văn phòng, nhà hàng, cafe, cửa hàng và các dịch vụ khác. Vỉa hè rộng được phép sử dụng cho hoạt động kinh doanh.",
  },
  {
    projectId: "shop-thuong-mai-sb11a",
    code: "SB11A",
    fullName: "Shop thương mại dịch vụ Sao Biển 11A (SB11A)",
    subtitle: "Điểm giao đường Sao Biển (30m) và đường Sao Biển 11 (20m)",
    anchorId: "shop-sb11a",
    overview: {
      totalUnits: 34,
      storeys: "4 tầng nổi + 1 tum",
      landArea: "99 – 164,6m²",
      constructionArea: "59 – 69,5m²",
      floorArea: "209,6 – 243,2m²",
      handover: "Nhận nhà ngay",
      ownership: "Sở hữu 50 năm, làm ngay sổ hồng",
    },
    // The SB11A crawled source has no dedicated "location" image — an overview/
    // rendering image is used instead, rather than fabricating one that doesn't exist.
    locationTabs: [
      { label: "Tổng quan Thương mại dịch vụ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sb11a/Tong-quan-Thuong-mai-dich-vu-Vinhomes-Ocean-Park.jpg" },
    ],
    exteriorTabs: [
      { label: "Ảnh thực tế", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sb11a/shop-tmdv-sb11a-vinhomes-ocean-park.jpg" },
    ],
    masterPlanTabs: [
      { label: "Tổng mặt bằng SB11A", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sb11a/Mat-bang-Thuong-mai-dich-vu-Sao-Bien-Vinhomes-Ocean-Park.jpg" },
    ],
    businessNote: "Các căn shop sở hữu thiết kế vuông vắn, mặt tiền rộng và cửa kính lớn, cùng phần không gian vỉa hè rất rộng được phép sử dụng cho việc kinh doanh.",
  },
  {
    projectId: "shop-thuong-mai-ha08",
    code: "HA08",
    fullName: "Shop thương mại dịch vụ Hải Âu 08 (HA08)",
    subtitle: "Trung tâm phân khu Hải Âu",
    anchorId: "shop-ha08",
    overview: {
      totalUnits: 44,
      storeys: "4 tầng nổi + 1 tum",
      landArea: "88 – 232,8m²",
      constructionArea: "53,1 – 56,6m²",
      floorArea: "194,1 – 206,9m²",
      handover: "Nhận nhà ngay (bàn giao thô)",
      ownership: "Sở hữu 50 năm, làm ngay sổ hồng",
    },
    locationTabs: [
      { label: "Vị trí HA08", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-ha08/vi-tri-shop-thuong-mai-dich-vu-bien-ho-ha08-vinhomes-ocean-park.jpg" },
      { label: "Vị trí HA08 (2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-ha08/vi-tri-shop-thuong-mai-dich-vu-bien-ho-ha08-vinhomes-ocean-park-1.jpg" },
    ],
    exteriorTabs: [
      { label: "Phối cảnh", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-ha08/shop-thuong-mai-dich-vu-hai-au-vinhomes-ocean-park.jpg" },
      { label: "Ảnh thực tế", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-ha08/shop-thuong-mai-dich-vu-ha08-vinhomes-ocean-park.jpg" },
      { label: "Ảnh thực tế (2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-ha08/mat_b1.jpg" },
      { label: "Ảnh thực tế (3)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-ha08/mat_b2.jpg" },
    ],
    masterPlanTabs: [
      { label: "Tổng mặt bằng HA08", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-ha08/mat-bang-shop-thuong-mai-dich-vu-bien-ho-ha08-vinhomes-ocean-park-2048x1152.jpg" },
    ],
    businessNote: "Phân khu Hải Âu quy hoạch 100% shophouse — các căn liền kề và biệt thự đều được phép kinh doanh, tạo lợi thế đa dạng cho các cửa hàng dịch vụ.",
  },
  {
    projectId: "shop-thuong-mai-bh9b",
    code: "BH9B",
    fullName: "Shop thương mại dịch vụ Biển Hồ 9B (BH9B)",
    subtitle: "Mặt đường Đại Tây Dương rộng 40m",
    anchorId: "shop-bh9b",
    overview: {
      totalUnits: 19,
      storeys: "4 tầng nổi + 1 tum",
      landArea: "107,3 – 159,2m²",
      constructionArea: "66,3 – 91m²",
      floorArea: "201,4 – 364,8m²",
      handover: "Nhận nhà ngay",
      ownership: "Sở hữu 50 năm, làm ngay sổ hồng",
    },
    locationTabs: [
      { label: "Vị trí BH9B", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-bh9b/vi-tri-shop-thuong-mai-dich-vu-bien-ho-9b-vinhomes-ocean-park.jpg" },
      { label: "Vị trí BH9B (2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-bh9b/vi-tri-shop-thuong-mai-dich-vu-bien-ho-9b-vinhomes-ocean-park-1.jpg" },
    ],
    exteriorTabs: [
      { label: "Ảnh thực tế", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-bh9b/shop-thuong-mai-dich-vu-bien-ho-9b-vinhomes-ocean-park.jpg" },
    ],
    masterPlanTabs: [
      { label: "Tổng mặt bằng BH9B", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-bh9b/mat-bang-shop-thuong-mai-dich-vu-bh9b-vinhomes-ocean-park-2048x1152.jpg" },
    ],
  },
];

// Shared sales policy — 7 clauses IDENTICAL across all 4 shop rows (verified
// against each JSON file; only the project name in "content" differs), so
// merged into one shared block instead of repeating it 4 times.
export const SHOP_TMDV_SALES_POLICIES = [
  "Thanh toán sớm 100% giá trị hợp đồng: chiết khấu 7,5% giá bán",
  "Hỗ trợ vay 70% giá trị, lãi suất 0%, ân hạn nợ gốc và không phạt trả nợ trước hạn trong 36 tháng",
  "Sau thời gian hỗ trợ vay: đảm bảo lãi suất 9%/năm trong 2 năm tiếp theo",
  "Gói hoàn thiện trị giá 500 triệu đồng, trừ trực tiếp vào giá bán",
  "Tặng miễn phí phí dịch vụ 60 tháng",
  "Hỗ trợ tiền thuê tương đương chiết khấu 2% giá bán",
  "Voucher Vinmec trị giá 100 triệu đồng",
];

// One shop row per page: the caller passes the row code (e.g. "SH09") and only
// that entry is rendered, instead of mapping over all 4 as the old page did.
export function ShopTmdvZone({ shopCode }: { shopCode: string }) {
  const p = SHOP_TMDV_PROJECTS.find((s) => s.code === shopCode);
  if (!p) return null;

  return (
    <div id={p.anchorId} className="anchor-section">
      <ZoneHeaderBanner title={p.fullName} subtitle={p.subtitle} />
      <TowerSpotlight projectId={p.projectId} image={p.exteriorTabs[0].src} oval={false} hideImage />
      <FloorPlanTabs title={`Vị trí ${p.code}`} tabs={p.locationTabs} compact />
      <div className="intro-text" style={{ marginBottom: 20 }}>
        <ul className="zone-spotlight-list">
          <li>
            <strong>Tổng số căn:</strong> {p.overview.totalUnits} căn
          </li>
          <li>
            <strong>Số tầng:</strong> {p.overview.storeys}
          </li>
          <li>
            <strong>Diện tích đất:</strong> {p.overview.landArea}
          </li>
          <li>
            <strong>Diện tích xây dựng:</strong> {p.overview.constructionArea}
          </li>
          <li>
            <strong>Tổng diện tích sàn:</strong> {p.overview.floorArea}
          </li>
          <li>
            <strong>Sở hữu:</strong> {p.overview.ownership}
          </li>
          <li>
            <strong>Bàn giao:</strong> {p.overview.handover}
          </li>
        </ul>
        {p.businessNote && (
          <p className="page-sub" style={{ maxWidth: "none" }}>
            <em>{p.businessNote}</em>
          </p>
        )}
      </div>
      <FloorPlanTabs title={`Ảnh thực tế & Phối cảnh ${p.code}`} tabs={p.exteriorTabs} />
      <FloorPlanTabs title={`Tổng mặt bằng ${p.code}`} tabs={p.masterPlanTabs} compact />
    </div>
  );
}
