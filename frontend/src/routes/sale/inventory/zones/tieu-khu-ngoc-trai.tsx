// Zone page for the "Ngọc Trai" villa sub-zone, extracted from the old
// single-scroll CategoryDetailPage so each sub-zone owns its own route.
import { FloorPlanTabs, TowerSpotlight, ZoneHeaderBanner, type ImageTab } from "../shared";

// "Location / Rendering" tab specific to Ngọc Trai — follows the reference
// mockup design (which also has a "Sub-zone Locations" tab, but that's already
// covered by VillaLocationMap above, so only the remaining 2 tabs are kept here
// to avoid duplication).
const NGOC_TRAI_LOCATION_TABS: ImageTab[] = [
  { label: "Vị trí Tiểu khu Ngọc Trai", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinhomes-ocean-park-ngoc-trai.jpg" },
  { label: "Phối cảnh Ngọc Trai", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/phan-khu-ngoc-trai-vinhomes-ocean-park.jpg" },
];

// Size/storey figures for Ngọc Trai villa types — sourced directly from pricing
// in ngoc_trai.json (size_min_sqm/size_max_sqm/storeys), no invented figures.
const NGOC_TRAI_UNIT_TYPES = [
  { label: "Biệt thự đơn lập", size: "227,5 – 347,5m²", storeys: "3 tầng nổi và 1 tum" },
  { label: "Biệt thự song lập", size: "135 – 338m²", storeys: "3 tầng nổi và 1 tum" },
  { label: "Biệt thự liền kề", size: "70,8 - 121m²", storeys: "4 tầng nổi và 1 tum" },
  { label: "Nhà phố shophouse", size: "67,2 – 102m²", storeys: "4 tầng nổi và 1 tum" },
];

// Exterior rendering images for each Ngọc Trai villa type — a dedicated section
// right below the size intro, BEFORE the "floor plan" (technical drawing) section.
const NGOC_TRAI_UNIT_PHOTOS: ImageTab[] = [
  { label: "Đơn lập", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinhomes-ocean-park-don-lap.jpg" },
  { label: "Song lập", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinhomes-ocean-park-song-lap.jpg" },
  { label: "Liền kề", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/lien-ke-vinhomes-ocean-park.jpg" },
  { label: "Shophouse", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinhomes-ocean-park-shop-house.jpg" },
];

// Real floor plans for Ngọc Trai — covers detached/semi-detached/townhouse/
// shophouse types per the crawled image files; types without an image are not invented.
const NGOC_TRAI_FLOOR_PLANS: ImageTab[] = [
  { label: "Đơn lập", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/don-lap-ngoc-trai-vinhomes-ocean-park-1500x925.jpg" },
  { label: "Song lập", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/song-lap-lap-ngoc-trai-vinhomes-ocean-park-1500x1024.jpg" },
  { label: "Song lập (mẫu 2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/song-lap-2-ngoc-trai-vinhomes-ocean-park-1500x968.jpg" },
  { label: "Liền kề", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/lien-ke-ngoc-trai-vinhomes-ocean-park-1500x959.jpg" },
  { label: "Shophouse (mẫu 1)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/shophouse-1-ngoc-trai-vinhomes-ocean-park-1500x1009.jpg" },
  { label: "Shophouse (mẫu 2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/shophouse-2-ngoc-trai-vinhomes-ocean-park-1500x919.jpg" },
];

export function NgocTraiZone() {
  return (
    <div id="tieu-khu-ngoc-trai" className="anchor-section">
      <ZoneHeaderBanner
        title="Tiểu khu Ngọc Trai"
        subtitle="Vị trí trung tâm - 'trái tim' của Vinhomes Ocean Park"
      />
      <TowerSpotlight
        projectId="ngoc-trai"
        image="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinhomes-ocean-park-ngoc-trai.jpg"
        oval={false}
        hideImage
      />
      <FloorPlanTabs title="Vị trí & Phối cảnh Ngọc Trai" tabs={NGOC_TRAI_LOCATION_TABS} compact />
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
          src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/tien-ich-ngoc-trai.jpg"
          alt="Tiện ích Tiểu khu Ngọc Trai"
        />
      </section>
      <div className="intro-text" style={{ marginBottom: 20 }}>
        <p className="page-sub" style={{ maxWidth: "none" }}>
          <strong>Tiểu khu Ngọc Trai</strong> bao gồm các loại biệt thự đơn lập, biệt thự song lập, biệt
          thự liền kề và nhà phố thương mại shophouse. Dãy phố kinh doanh shophouse được bố trí tại mặt
          trục đường chính rộng 52m của cả dự án Vinhomes Ocean Park, trong khi các loại hình đơn lập, song
          lập và liền kề nằm các vị trí riêng tư bên trong.
        </p>
        <ul className="zone-spotlight-list">
          {NGOC_TRAI_UNIT_TYPES.map((u) => (
            <li key={u.label}>
              <strong>{u.label}:</strong> diện tích {u.size}; xây dựng {u.storeys}.
            </li>
          ))}
        </ul>
      </div>
      <FloorPlanTabs title="Thiết kế các loại biệt thự khu Ngọc Trai" tabs={NGOC_TRAI_UNIT_PHOTOS} />
      <FloorPlanTabs title="Thiết kế mặt bằng các loại biệt thự khu Ngọc Trai" tabs={NGOC_TRAI_FLOOR_PLANS} />
    </div>
  );
}
