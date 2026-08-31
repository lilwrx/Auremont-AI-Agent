// Zone page for "The Ocean View" (apartment group), extracted from the old
// single-scroll CategoryDetailPage. Its 2 sub-zones (Zenpark / Pavilion) stay as
// anchor sections inside this page so the nav menu can still scroll to them.
import {
  AmenityPhotoBanner,
  FloorPlanTabs,
  LayoutGallery,
  PriceTable,
  SoloImage,
  TowerSpotlight,
  type ImageTab,
} from "../shared";

// "The Ocean View" copy is sourced from the reference mockup provided by the user
// (not invented) — this is a parent group (The Zenpark/The Pavilion/The Bayfront),
// not a standalone project in the DB, so it cannot be fetched from the API; same
// approach as MetropolitanSpotlight.
function OceanViewSpotlight() {
  return (
    <section className="zone-spotlight">
      <h3 className="zone-spotlight-title zone-spotlight-title--amber">Phân khu The Ocean View</h3>
      <p className="zone-spotlight-subtitle">Thiên đường nghỉ dưỡng sinh thái</p>

      <div className="zone-spotlight-grid">
        <div className="zone-spotlight-text">
          <p className="page-sub" style={{ maxWidth: "none" }}>
            <strong className="zone-spotlight-lead">The Ocean View</strong> Vinhomes Ocean Park là phân khu chung cư
            được mở bán tiếp theo phân khu The Sapphire. Được quy hoạch theo mô hình "Nghỉ dưỡng sinh thái đẳng cấp"
            giữa biển xanh khoáng đạt, The Ocean View là nơi mà cư dân có thể thư thái tận hưởng sự tiện nghi của
            thiên đường tiện ích, sự trong lành của "ốc đảo xanh" và sự yên tĩnh ngay tại một Đại đô thị sôi động.
          </p>
          <p className="page-sub" style={{ maxWidth: "none" }}>
            The Ocean View bao gồm <strong>3 tiểu khu</strong> với tổng số <strong>12 tòa</strong> căn hộ, đó là:
          </p>
          <ul className="zone-spotlight-list">
            <li>
              <strong>The Zenpark:</strong> 4 tòa căn hộ cao cấp phong cách Nhật Bản, đánh số từ R1.01 đến R1.05.
            </li>
            <li>
              <strong>The Pavilion:</strong> 4 tòa căn hộ phong cách Singapore, đánh số từ P1 đến P4.
            </li>
            <li>
              <strong>The Bayfront:</strong> 4 tòa căn hộ hạng sang phong cách Dubai, gồm 3 tòa BF1, BF2, BF3 và 1 tòa
              căn hộ dịch vụ Royal Sail.
            </li>
          </ul>
        </div>
        <div className="zone-spotlight-media">
          <img
            src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-ocean-view/the-ocean-view.jpg"
            alt="Phân khu The Ocean View"
          />
        </div>
      </div>
    </section>
  );
}

// All 6 The Zenpark unit layout images per the provided list — no confirmed size
// per image, so the label is left blank (same approach as ZURICH_LAYOUTS) to
// avoid inventing figures.
const ZENPARK_LAYOUTS: ImageTab[] = [
  { label: "Căn Studio", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/can-ho-studio-r1-01-vinhomes-ocean-park.jpg" },
  { label: "Căn 1 ngủ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/can-ho-1-ngu-r1-01-vinhomes-ocean-park.jpg" },
  { label: "Căn 1 ngủ + 1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/can-ho-1-ngu-1-r1-01-vinhomes-ocean-park.jpg" },
  { label: "Căn 2 ngủ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/can-ho-2-ngu-r1-01-vinhomes-ocean-park.jpg" },
  { label: "Căn 2 ngủ + 1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/can-ho-2-ngu-1-r1-01-vinhomes-ocean-park.jpg" },
  { label: "Căn 3 ngủ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/can-ho-3-ngu-r1-01-vinhomes-ocean-park.jpg" },
];

// All 6 The Pavilion unit layout images per the provided list — no confirmed
// size per image, so the label is left blank, same approach as ZENPARK_LAYOUTS.
const PAVILION_LAYOUTS: ImageTab[] = [
  { label: "Căn Studio", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/can-ho-studio-p1-vinhomes-ocean-park.jpg" },
  { label: "Căn 1 ngủ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/can-ho-1-ngu-p1-vinhomes-ocean-park.jpg" },
  { label: "Căn 1 ngủ + 1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/can-ho-1-ngu-1-p1-vinhomes-ocean-park.jpg" },
  { label: "Căn 2 ngủ (mẫu 1)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/can-ho-2-ngu-p1-vinhomes-ocean-park-mau-1.jpg" },
  { label: "Căn 2 ngủ (mẫu 2)", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/can-ho-2-ngu-p1-vinhomes-ocean-park-mau-2.jpg" },
  { label: "Căn 3 ngủ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/can-ho-3-ngu-p1-vinhomes-ocean-park.jpg" },
];

const ZENPARK_FLOOR_PLANS: ImageTab[] = [
  { label: "Tòa R1.01", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/mat-bang-toa-r1-01-the-zenpark-vinhomes-ocean-park-2048x1365.jpg" },
  { label: "Tòa R1.02", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/toa-r1-02-zenpark.jpg" },
  { label: "Tòa R1.03", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/toa-R1-03-vinhomes-ocean-park-2048x1558.jpg" },
  { label: "Tòa R1.05", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/toa-r1-05-zenpark.jpg" },
];

const ZENPARK_AMENITIES: ImageTab[] = [
  { label: "Bể bơi 4 mùa", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/be-boi-4-mua-the-zenpark.jpg" },
  { label: "Cầu Nhật", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/cau-nhat-the-zenpark.jpg" },
  { label: "Cổng Tori", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/cong-tori-the-zenpark.jpg" },
  { label: "Vườn Nhật", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/vuon-nhat-the-zenpark.jpg" },
  { label: "Phòng tập gym", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/phong-tap-gym-the-zenpark.jpg" },
  { label: "Phòng chơi trẻ em", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/phong-choi-tre-em-the-zenpark.jpg" },
  { label: "Sân thể thao", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/san-the-thao-the-zenpark.jpg" },
  { label: "Nội thất căn hộ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/noi-that-the-zenpark-4.jpg" },
];

const PAVILION_FLOOR_PLANS: ImageTab[] = [
  { label: "Tòa P1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/mat-bang-toa-p1-pavillion-vinhomes-ocean-park-2048x1152.jpg" },
  { label: "Tòa P2", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/mat-bang-toa-p2-pavillion-vinhomes-ocean-park.jpg" },
  { label: "Tòa P3", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/mat-bang-toa-p3-pavillion-vinhomes-ocean-park-2048x1152.jpg" },
  { label: "Tòa P4", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/mat-bang-toa-p4-the-pavilion-2048x1392.jpg" },
];

// The MinIO bucket holds duplicate "... (1).jpg" copies of the garden landscape
// and lake shots; only the original name is referenced here.
const PAVILION_AMENITIES: ImageTab[] = [
  { label: "Bể trị liệu", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/be-tri-lieu-pavilion.jpg" },
  { label: "Cảnh quan vườn", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/canh-quan-vuon-the-pavilion-vinhomes-ocean-park.jpg" },
  { label: "Hồ cảnh quan", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/ho-canh-quan-pavilion.jpg" },
  { label: "Sân chơi", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/san-choi-the-pavilion.jpg" },
  { label: "Mặt ngoài tòa nhà", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/mat-ngoai-the-pavilion-vinhomes-ocean-park.jpg" },
  { label: "Phòng khách", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/phong-khach-the-pavilion.jpg" },
  { label: "Phòng ngủ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/phong-ngu-the-pavilion.jpg.jpg" },
  { label: "Ban công căn hộ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/ban-cong-can-ho-the-pavilion.jpg" },
  { label: "View từ căn hộ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/view-tu-can-ho-the-pavilion.jpg" },
];

export function TheOceanViewZone() {
  return (
    <div id="the-ocean-view" className="anchor-section">
      <OceanViewSpotlight />
      <SoloImage
        src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-ocean-view/tong-mat-bang-the-ocean-view.jpg"
        alt="Tổng mặt bằng The Ocean View"
      />
      <div id="the-zenpark" className="anchor-section">
        <TowerSpotlight
          projectId="the-zenpark"
          image="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/can-ho-the-zenpark.jpg"
        />
        <SoloImage
          src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/tong-mat-bang-the-zenpark-vinhomes-ocean-park.jpg"
          alt="Tổng mặt bằng The Zenpark"
        />
        <SoloImage
          src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zenpark/vi-tri-the-zenpark-vinhomes-ocean-park.jpg"
          alt="Vị trí The Zenpark"
        />
        <PriceTable projectId="the-zenpark" />
        <FloorPlanTabs title="Mặt bằng The Zenpark" tabs={ZENPARK_FLOOR_PLANS} />
        <LayoutGallery title="Layout căn hộ The Zenpark" layouts={ZENPARK_LAYOUTS} />
        <AmenityPhotoBanner
          title="Tiện ích & Nội thất The Zenpark"
          paragraphs={[
            "Tiểu khu căn hộ phong cách Nhật Bản với hệ tiện ích nội khu lấy cảm hứng từ vườn thiền: cổng Tori, cầu Nhật, vườn Nhật cùng bể bơi 4 mùa và khu thể thao dành cho cư dân.",
          ]}
          photos={ZENPARK_AMENITIES}
        />
      </div>
      <div id="the-pavilion" className="anchor-section">
        <TowerSpotlight
          projectId="the-pavilion"
          image="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/phoi-canh-the-pavilion-vinhomes-ocean-park.jpg"
        />
        <SoloImage
          src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/tong-mat-bang-the-pavilion-vinhomes-ocean-park.jpg"
          alt="Tổng mặt bằng The Pavilion"
        />
        <SoloImage
          src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-pavilion/vi-tri-the-pavilion.jpg"
          alt="Vị trí The Pavilion"
        />
        <PriceTable projectId="the-pavilion" />
        <FloorPlanTabs title="Mặt bằng The Pavilion" tabs={PAVILION_FLOOR_PLANS} />
        <LayoutGallery title="Layout căn hộ The Pavilion" layouts={PAVILION_LAYOUTS} />
        <AmenityPhotoBanner
          title="Tiện ích & Nội thất The Pavilion"
          paragraphs={[
            "Tiểu khu căn hộ phong cách Singapore với cảnh quan vườn nhiệt đới, hồ cảnh quan và bể trị liệu nội khu, cùng tiêu chuẩn nội thất bàn giao được minh họa qua các hình ảnh dưới đây.",
          ]}
          photos={PAVILION_AMENITIES}
        />
      </div>
    </div>
  );
}
