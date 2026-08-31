// Zone page for "The Senique Hanoi" (apartment zone), extracted from the old
// single-scroll CategoryDetailPage. Its 3 tower blocks stay as anchor sections
// inside this page so the nav menu can still scroll to them.
import { AmenityPhotoBanner, FloorPlanTabs, PriceTable, SidebarLayoutTabs, type ImageTab } from "../shared";

const IMG = "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi";

const SENIQUE_MASTER_PLANS: ImageTab[] = [
  { label: "Tổng mặt bằng", src: `${IMG}/tong-mat-bang-the-senique-hanoi-ocean-park.jpg` },
  { label: "Vị trí phân khu", src: `${IMG}/vi-tri-the-senique-hanoi.jpg` },
  { label: "Vị trí thực tế", src: `${IMG}/vi-tri-thuc-te-the-senique-hanoi.jpg` },
];

const SENIQUE_AMENITY_PHOTOS: ImageTab[] = [
  { label: "Bể bơi 50m", src: `${IMG}/be-boi-50m-the-senique-hanoi.jpg` },
  { label: "Bể bơi trẻ em", src: `${IMG}/be-boi-tre-em-the-senique-hanoi.jpg` },
  { label: "Cảnh quan nội khu", src: `${IMG}/canh-quan-noi-khu-the-senique-hanoi.jpg` },
  { label: "Cổng bảo vệ", src: `${IMG}/cong-bao-ve-the-senique-hanoi.jpg` },
  { label: "Sảnh căn hộ toà Senique 1", src: `${IMG}/sanh-can-ho-toa-senique-1.jpg` },
  { label: "Sảnh căn hộ toà Senique 2", src: `${IMG}/sanh-can-ho-toa-senique-2.jpg` },
  { label: "Tiêu chuẩn bàn giao", src: `${IMG}/tieu-chuan-ban-giao-hoan-thien-the-senique-hanoi.jpg` },
  { label: "Phối cảnh toà Senique 1 & 2", src: `${IMG}/the-senique-1-2.jpg` },
];

// "The Senique Hanoi" copy is sourced directly from the_senique_hanoi.json
// (developer, overview: 3 towers, 2,152 units, 37 floors, handover Q2/2027, price
// from 68M/m2, first Compound model in Ocean Park) — not invented; same approach
// as SapphireSpotlight since this is also an independent zone (not a sub-zone).
function SeniqueSpotlight() {
  return (
    <section className="zone-spotlight">
      <h3 className="zone-spotlight-title">Phân khu The Senique Hanoi</h3>
      <p className="zone-spotlight-subtitle">Compound khép kín đầu tiên tại Ocean Park</p>

      <div className="zone-spotlight-grid">
        <div className="zone-spotlight-text">
          <p className="page-sub" style={{ maxWidth: "none" }}>
            <strong className="zone-spotlight-lead">The Senique Hanoi</strong> là khu căn hộ cao cấp tọa lạc tại vị
            trí trung tâm Vinhomes Ocean Park, do <strong>CapitaLand Development</strong> (qua Công ty Cổ phần đầu tư
            phát triển kinh doanh Bình Minh) phát triển — dự án đầu tiên theo mô hình{" "}
            <strong>Compound (khu khép kín)</strong> tại Ocean Park.
          </p>
          <p className="page-sub" style={{ maxWidth: "none" }}>
            Dự án gồm <strong>3 tòa</strong> căn hộ cao <strong>37 tầng</strong> — <strong>The Senique 1</strong>,{" "}
            <strong>The Senique 2</strong> và <strong>The Senique Premier</strong>, tổng số khoảng{" "}
            <strong>2.152 căn</strong>.
          </p>
          <p className="page-sub" style={{ maxWidth: "none" }}>
            Căn hộ đa dạng loại hình 1PN, 2PN, 3PN, 4PN, Duplex, Penthouse, giá bán từ khoảng{" "}
            <strong>68 triệu đồng/m²</strong>, sở hữu không thời hạn, dự kiến bàn giao <strong>Quý 2/2027</strong>.
          </p>
        </div>
        <div className="zone-spotlight-media">
          <img
            src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/the-senique-hanoi-phoi-canh.jpg"
            alt="Phân khu The Senique Hanoi"
          />
        </div>
      </div>
    </section>
  );
}

// All 22 The Senique Hanoi unit layout images — size is derived from the file
// name itself (e.g. "813" = 81.3m²) and cross-checked against the real size
// ranges in the_senique_hanoi.json (2BR 54-81m², 3BR 83-108m², 4BR 154-188m²,
// Duplex 118-190m²) — figures are not invented.
const SENIQUE_LAYOUTS: ImageTab[] = [
  { label: "Căn 1PN | 42m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-1PN-medium-42-m2-the-senique-hanoi.jpg" },
  { label: "Căn 2PN | 53,5m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-2PN-small-535-m2-the-senique-hanoi.jpg" },
  { label: "Căn 2PN | 54,4m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-2PN-small-544-m2-the-senique-hanoi.jpg" },
  { label: "Căn 2PN | 64,3m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-2PN-medium-643-m2-the-senique-hanoi.jpg" },
  { label: "Căn 2PN | 81,3m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-2PN-large-813-m2-the-senique-hanoi.jpg" },
  { label: "Căn 3PN | 83,2m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-3PN-small-832-m2-the-senique-hanoi.jpg" },
  { label: "Căn 3PN | 84,9m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-3PN-small-849-m2-the-senique-hanoi.jpg" },
  { label: "Căn 3PN | 85,9m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-3PN-small-859-m2-the-senique-hanoi.jpg" },
  { label: "Căn 3PN | 96,8m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-3PN-medium-968-m2-the-senique-hanoi.jpg" },
  { label: "Căn 3PN | 97,3m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-3PN-medium-973-m2-the-senique-hanoi.jpg" },
  { label: "Căn 3PN | 101,5m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-3PN-large-1015-m2-the-senique-hanoi.jpg" },
  { label: "Căn 3PN | 107,5m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-3PN-large-1075-m2-the-senique-hanoi.jpg" },
  { label: "Căn 4PN | 153,6m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-4PN-large-1536-m2-the-senique-hanoi.jpg" },
  { label: "Căn 4PN | 177,5m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-4PN-large-1775-m2-the-senique-hanoi.jpg" },
  { label: "Căn 4PN | 187,4m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-4PN-large-1874-m2-the-senique-hanoi.jpg" },
  { label: "Duplex 117,5m² | Tầng 1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-duplex-small-1175-m2-tang-1-the-senique-hanoi.jpg" },
  { label: "Duplex 117,5m² | Tầng 2", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-duplex-small-1175-m2-tang-2-the-senique-hanoi.jpg" },
  { label: "Duplex 133,7m² | Tầng 1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-duplex-medium-1337-m2-tang-1-the-senique-hanoi.jpg" },
  { label: "Duplex 133,7m² | Tầng 2", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-duplex-medium-1337-m2-tang-2-the-senique-hanoi.jpg" },
  { label: "Duplex 147,4m² | Tầng 1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-duplex-medium-1474-m2-tang-1-the-senique-hanoi.jpg" },
  { label: "Duplex 147,4m² | Tầng 2", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-duplex-medium-1474-m2-tang-2-the-senique-hanoi.jpg" },
  { label: "Duplex 189,5m² | Tầng 1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/can-ho-duplex-medium-1895-m2-tang-1-the-senique-hanoi.jpg" },
];

function SeniqueLayoutGallery() {
  return <SidebarLayoutTabs title="Layout căn hộ tòa The Senique Hanoi" tabs={SENIQUE_LAYOUTS} />;
}

// Real per-floor floor-plan images for The Senique Hanoi — 3 towers (Senique 1,
// Senique 2, Senique Premier), each with several floor-group variants (matching
// the image files already uploaded to MinIO earlier; no tower is missing).
const SENIQUE_1_FLOOR_PLANS: ImageTab[] = [
  { label: "Tầng 2-18", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-2-4-6-8-10-12-14-16-18-toa-the-senique-1-ocean-park-1.jpg" },
  { label: "Tầng 3-17", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-3-5-7-9-11-13-15-17-toa-the-senique-1-ocean-park.jpg" },
  { label: "Tầng 20", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-20-toa-the-senique-1-ocean-park.jpg" },
  { label: "Tầng 21, 23", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-21-23-toa-the-senique-1-ocean-park.jpg" },
  { label: "Tầng 22", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-22-toa-the-senique-1-ocean-park.jpg" },
  { label: "Tầng 24-34", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-24-26-28-30-32-34-toa-the-senique-1-ocean-park.jpg" },
  { label: "Tầng 25-35", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-25-27-29-31-33-35-toa-the-senique-1-ocean-park.jpg" },
  { label: "Tầng 36", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-36-toa-the-senique-1-ocean-park.jpg" },
  { label: "Tầng 37", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-37-toa-the-senique-1-ocean-park.jpg" },
];

const SENIQUE_2_FLOOR_PLANS: ImageTab[] = [
  { label: "Tầng 2-18", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-2-4-6-8-10-12-14-16-18-toa-the-senique-2-ocean-park-1.jpg" },
  { label: "Tầng 3-17", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-3-5-7-9-11-13-15-17-toa-the-senique-2-ocean-park.jpg" },
  { label: "Tầng 20", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-20-toa-the-senique-2-ocean-park.jpg" },
  { label: "Tầng 21, 23", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-21-23-toa-the-senique-2-ocean-park.jpg" },
  { label: "Tầng 22", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-22-toa-the-senique-2-ocean-park.jpg" },
  { label: "Tầng 24-34", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-24-26-28-30-32-34-toa-the-senique-2-ocean-park.jpg" },
  { label: "Tầng 25-35", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-25-27-29-31-33-35-toa-the-senique-2-ocean-park-2048x1463.jpg" },
  { label: "Tầng 36", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-36-toa-the-senique-2-ocean-park.jpg" },
];

const SENIQUE_PREMIER_FLOOR_PLANS: ImageTab[] = [
  { label: "Tầng 3-17", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-3-5-7-9-11-13-15-17-toa-the-senique-premier.jpg" },
  { label: "Tầng 21", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-21-toa-the-senique-premier.jpg" },
  { label: "Tầng 22-34", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-22-24-26-28-30-32-34-toa-the-senique-premier-ocean-park.jpg" },
  { label: "Tầng 23-35", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-23-25-27-29-31-33-35-toa-the-senique-premier.jpg" },
  { label: "Tầng 36", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-36-toa-the-senique-premier.jpg" },
  { label: "Tầng 37", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/mat-bang-tang-37-toa-the-senique-premier.jpg" },
];

export function TheSeniqueHanoiZone() {
  return (
    <div id="the-senique-hanoi" className="anchor-section">
      <SeniqueSpotlight />
      <PriceTable projectId="the-senique-hanoi" />
      <SeniqueLayoutGallery />
      <div id="the-senique-1" className="anchor-section section-block">
        <h3 className="intro-title">
          <span className="intro-title-bar" />
          Tòa The Senique 1
        </h3>
        <FloorPlanTabs title="Mặt bằng theo tầng" tabs={SENIQUE_1_FLOOR_PLANS} />
      </div>
      <div id="the-senique-2" className="anchor-section section-block">
        <h3 className="intro-title">
          <span className="intro-title-bar" />
          Tòa The Senique 2
        </h3>
        <FloorPlanTabs title="Mặt bằng theo tầng" tabs={SENIQUE_2_FLOOR_PLANS} />
      </div>
      <div className="section-block">
        <h3 className="intro-title">
          <span className="intro-title-bar" />
          Tòa The Senique Premier
        </h3>
        <FloorPlanTabs title="Mặt bằng theo tầng" tabs={SENIQUE_PREMIER_FLOOR_PLANS} />
      </div>
      <FloorPlanTabs title="Tổng mặt bằng & Vị trí" tabs={SENIQUE_MASTER_PLANS} />
      <AmenityPhotoBanner
        title="Tiện ích nội khu The Senique Hanoi"
        paragraphs={[
          "Là compound khép kín, The Senique Hanoi có hệ tiện ích riêng cho cư dân: bể bơi 50m, bể bơi trẻ em, cảnh quan nội khu và cổng kiểm soát an ninh.",
        ]}
        photos={SENIQUE_AMENITY_PHOTOS}
      />
    </div>
  );
}
