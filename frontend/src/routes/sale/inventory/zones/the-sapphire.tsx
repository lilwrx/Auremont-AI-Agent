// Zone page for "The Sapphire" (apartment zone), extracted from the old
// single-scroll CategoryDetailPage.
import { AmenityPhotoBanner, FloorPlanTabs, PriceTable, type ImageTab } from "../shared";

const IMG = "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-sapphire";

// "The Sapphire" copy follows the mockup provided by the user (longer than the
// short "description" in the_sapphire.json) — Sapphire is a top-level zone (not
// a sub-zone of another), so it uses the "zone-spotlight" style with a centered
// heading like OceanViewSpotlight, plus a CTA button, rather than TowerSpotlight.
function SapphireSpotlight() {
  return (
    <section className="zone-spotlight">
      <h3 className="zone-spotlight-title">Phân khu The Sapphire</h3>
      <p className="zone-spotlight-subtitle">Tâm điểm của thành phố biển hồ</p>

      <div className="zone-spotlight-grid">
        <div className="zone-spotlight-text">
          <p className="page-sub" style={{ maxWidth: "none" }}>
            <strong className="zone-spotlight-lead">The Sapphire</strong> Vinhomes Ocean Park là phân khu căn hộ
            được mở bán đầu tiên của dự án, chính vì vậy mà hiện tại các tòa căn hộ Sapphire đã đạt tỉ lệ lấp kín
            khoảng <strong>70 – 80%</strong>. Sở hữu vị trí trung tâm của dự án, The Sapphire là tâm điểm của nhịp
            sống hiện đại năng động, là tâm điểm cảnh quan với bộ đôi Biển – Hồ và là tâm điểm vị trí — nơi cư dân có
            thể dễ dàng kết nối muôn nơi với các trục đường huyết mạch.
          </p>
          <p className="page-sub" style={{ maxWidth: "none" }}>
            Phân khu The Sapphire bao gồm <strong>27 tòa</strong> căn hộ cao từ 26 – 28 tầng với 2 tiểu khu là:
          </p>
          <ul className="zone-spotlight-list">
            {/* Real jump targets for the chat's listing cards (PropertyListingCarousel.tsx)
                and the navbar's zone sub-menu (see subAnchors in registry.tsx) — Sapphire
                has no separate S1/S2 page section, so this intro line is the closest
                honest anchor to each sub-tower. */}
            <li id="the-sapphire-1">
              <strong>The Sapphire 1 (S1):</strong> 11 tòa căn hộ đánh số từ S1.01 đến S1.12.
            </li>
            <li id="the-sapphire-2">
              <strong>The Sapphire 2 (S2):</strong> 16 tòa căn hộ đánh số từ S2.01 đến S2.19.
            </li>
          </ul>
          <p className="page-sub" style={{ maxWidth: "none" }}>
            Các căn hộ tại phân khu The Sapphire là phân khúc căn hộ có giá bán thấp nhất tại dự án Vinhomes Ocean
            Park, chỉ khoảng <strong>30 – 40 triệu/m²</strong> với tiêu chuẩn bàn giao nội thất tiêu chuẩn. Căn hộ có
            diện tích từ khoảng 25 – 98,5m² với các loại hình căn hộ Studio, 1 ngủ, 1 ngủ + 1, 2 ngủ, 2 ngủ + 1 và 3
            ngủ.
          </p>
        </div>
        <div className="zone-spotlight-media">
          <img
            src={`${IMG}/phan-khu-sapphire-vinhomes-ocean-park.jpg`}
            alt="Phân khu The Sapphire"
          />
        </div>
      </div>
    </section>
  );
}

// Only towers with a real source image are listed: S1 has 12 towers and S2 has 19,
// but the crawl covers 8 of S1 and none of S2. Listing the rest would imply floor
// plans the Sale rep cannot actually show a customer.
const SAPPHIRE_FLOOR_PLANS: ImageTab[] = [
  { label: "Khu Sapphire 1", src: `${IMG}/mat-bang-khu-sapphire-1-vinhomes-ocean-park.jpg` },
  { label: "Tòa S1.02", src: `${IMG}/mat-bang-toa-S1-02-vinhomes-ocean-park.jpg` },
  { label: "Tòa S1.05", src: `${IMG}/mat-bang-toa-S1-05-vinhomes-ocean-park.jpg` },
  { label: "Tòa S1.06", src: `${IMG}/mat-bang-toa-S1.06.jpg` },
  { label: "Tòa S1.07", src: `${IMG}/mat-bang-toa-s1-07-vinhomes-ocean-park.jpg` },
  { label: "Tòa S1.08", src: `${IMG}/mat-bang-toa-S1.08.jpg` },
  { label: "Tòa S1.09", src: `${IMG}/mat-bang-toa-s1-09-sapphire-1.jpg` },
  { label: "Tòa S1.10", src: `${IMG}/mat-bang-toa-S1.10.jpg` },
  { label: "Tòa S1.11", src: `${IMG}/mat-bang-toa-S1.11.jpg` },
  { label: "Tòa S1.12", src: `${IMG}/mat-bang-toa-S1.12-final.jpg` },
  { label: "Khu Sapphire 2", src: `${IMG}/mat-bang-khu-sapphire-2-vinhomes-ocean-park.jpg` },
];

const SAPPHIRE_LANDSCAPE_PHOTOS: ImageTab[] = [
  { label: "Ngọn hải đăng", src: `${IMG}/ngon-hai-dang-vinhomes-ocean-park.jpg` },
  ...[1, 2, 3, 5, 6, 7, 8, 9, 10, 11].map((n) => ({
    label: `Công viên ${n}`,
    src: `${IMG}/park-${n}-vinhomes-ocean-park.jpg`,
  })),
];

export function TheSapphireZone() {
  return (
    <div id="the-sapphire" className="anchor-section">
      <SapphireSpotlight />
      <PriceTable projectId="the-sapphire" />
      <FloorPlanTabs title="Mặt bằng The Sapphire" tabs={SAPPHIRE_FLOOR_PLANS} />
      <AmenityPhotoBanner
        title="Cảnh quan & Tiện ích The Sapphire"
        paragraphs={[
          "Hệ thống công viên chủ đề và cảnh quan ven hồ bao quanh các tòa căn hộ Sapphire, phục vụ cư dân trong bán kính đi bộ.",
        ]}
        photos={SAPPHIRE_LANDSCAPE_PHOTOS}
      />
    </div>
  );
}
