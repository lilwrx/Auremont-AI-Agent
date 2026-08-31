// Zone page for "The Metropolitan" (apartment group), extracted from the old
// single-scroll CategoryDetailPage. This zone keeps its 4 sub-zones (Zurich /
// Beverly / London / Paris) as anchor sections inside this single page, so the
// nav menu can still scroll to each of them.
import {
  AmenityPhotoBanner,
  FloorPlanTabs,
  PriceTable,
  SoloImage,
  TowerSpotlight,
  type ImageTab,
  type MapPin,
} from "../shared";

// Real floor-plan images for The Beverly's 4 towers — already on MinIO from when
// the "the-beverly" project images were uploaded.
const ZURICH_IMG = "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich";
const BEVERLY_IMG = "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-beverly";
const LONDON_IMG = "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-london";
const PARIS_IMG = "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-paris";

const ZURICH_FLOOR_PLANS: ImageTab[] = [
  { label: "Tổng mặt bằng", src: `${ZURICH_IMG}/tong-mat-bang-the-zurich-vinhomes-ocean-park.jpg` },
  { label: "Tòa ZR1", src: `${ZURICH_IMG}/mat-bang-toa-zr1-the-zurich-vinhomes-ocean-park.jpg` },
  { label: "Tòa ZR2", src: `${ZURICH_IMG}/mat-bang-toa-zr2-the-zurich-vinhomes-ocean-park.jpg` },
  { label: "Tòa ZR3 (tầng 10-12, 14-30)", src: `${ZURICH_IMG}/mat-bang-tang-10-12-va-14-30-toa-zr3-the-zurich.jpg` },
  { label: "Vị trí phân khu", src: `${ZURICH_IMG}/vi-tri-the-zurich.jpg` },
];

const ZURICH_AMENITY_PHOTOS: ImageTab[] = [
  { label: "Phòng xông hơi", src: `${ZURICH_IMG}/phong-xong-hoi-the-zurich.jpg` },
  { label: "Phòng giải trí", src: `${ZURICH_IMG}/phong-giai-tri-the-zurich.jpg` },
  { label: "Hồ cảnh quan", src: `${ZURICH_IMG}/ho-canh-quan-the-zurich.jpg` },
  { label: "Cảnh quan tháp đồng hồ", src: `${ZURICH_IMG}/canh-quan-thap-dong-ho-the-zurich.jpg` },
  { label: "Mặt ngoài toà căn hộ", src: `${ZURICH_IMG}/mat-ngoai-the-zurich.jpg` },
  { label: "Căn hộ mẫu", src: `${ZURICH_IMG}/can-ho-the-zurich-vinhomes-ocean-park.jpg` },
];

// The -260x185 variants are gallery thumbnails of images already listed here at
// full resolution, so only the full-size file is used.
const BEVERLY_AMENITY_PHOTOS: ImageTab[] = [
  { label: "Bể bơi Santa Monica", src: `${BEVERLY_IMG}/be-boi-santan-monica-the-beverly.jpg` },
  { label: "Bể cảnh quan phun nước", src: `${BEVERLY_IMG}/be-canh-quan-phun-nuoc-the-beverly.jpg` },
  { label: "Game room", src: `${BEVERLY_IMG}/game-room-the-beverly-vinhomes-ocean-park.jpg` },
  { label: "Gym & sauna", src: `${BEVERLY_IMG}/gym-sauna-the-beverly-vinhomes-ocean-park.jpg` },
  { label: "Kids corner", src: `${BEVERLY_IMG}/kids-corner-the-beverly-vinhomes-ocean-park.jpg` },
  { label: "Vườn đọc sách", src: `${BEVERLY_IMG}/vuon-doc-sach-the-beverly-vinhomes-ocean-park.jpg` },
  { label: "Sân chơi sắc màu", src: `${BEVERLY_IMG}/san-choi-sac-mau-the-beverly-ocean-park.jpg` },
  { label: "Nội thất căn hộ", src: `${BEVERLY_IMG}/noi-that-the-beverly.jpg` },
];

const BEVERLY_MASTER_PLANS: ImageTab[] = [
  { label: "Tổng mặt bằng phân khu", src: `${BEVERLY_IMG}/tong-mat-bang-phan-khu-the-beverly-ocean-park.jpg` },
  { label: "Mặt bằng tiện ích", src: `${BEVERLY_IMG}/tmb-tien-ich-the-beverly-vinhomes-ocean-park.jpg` },
];

const LONDON_AMENITY_PHOTOS: ImageTab[] = [
  { label: "Phòng karaoke", src: `${LONDON_IMG}/phong-karaoke-phan-khu-the-london-vinhomes-ocean-park.jpg` },
  { label: "Phòng tập gym", src: `${LONDON_IMG}/phong-tap-gym-phan-khu-the-london-vinhomes-ocean-park.jpg` },
  { label: "Phòng trẻ em", src: `${LONDON_IMG}/phong-tre-em-phan-khu-the-london-vinhomes-ocean-park.jpg` },
  { label: "Phối cảnh phân khu", src: `${LONDON_IMG}/phan-khu-the-london-rumor-3.jpg` },
];

const PARIS_MASTER_PLANS: ImageTab[] = [
  { label: "Mặt bằng tổng thể", src: `${PARIS_IMG}/mat-bang-tong-the-phan-khu-the-paris-vinhomes-ocean-park.jpg` },
  { label: "Tổng mặt bằng tiện ích", src: `${PARIS_IMG}/tong-mat-bang-tien-ich-the-paris-vinhomes-ocean-park-2048x1270.jpg` },
];

const PARIS_AMENITY_PHOTOS: ImageTab[] = [
  { label: "Quảng trường tháp Eiffel", src: `${PARIS_IMG}/quang-truong-thap-eiffel-phan-khu-paris-ocean-park.jpg` },
  { label: "Bể bơi", src: `${PARIS_IMG}/be-boi-phan-khu-paris-ocean-park.jpg` },
  { label: "Business lobby", src: `${PARIS_IMG}/business-lobby-the-paris-ocean-park.jpg` },
  { label: "Phòng gym (PR1)", src: `${PARIS_IMG}/phong-gym-toa-pr1-the-paris-ocean-park.jpg` },
  { label: "Phòng yoga (PR5)", src: `${PARIS_IMG}/phong-yoga-toa-pr5-the-paris-ocean-park.jpg` },
  { label: "Phòng pilates (PR5)", src: `${PARIS_IMG}/phong-pilates-toa-pr5-the-paris-ocean-park.jpg` },
  { label: "Phòng bida & game (PR5)", src: `${PARIS_IMG}/phong-bida-game-toa-pr5-the-paris-ocean-park.jpg` },
  { label: "Kid corner (PR1)", src: `${PARIS_IMG}/kid-corner-toa-pr1-the-paris-ocean-park.jpg` },
  { label: "Sân thể thao", src: `${PARIS_IMG}/san-the-thao-phan-khu-paris-ocean-park.jpg` },
  { label: "Royal Pavilion", src: `${PARIS_IMG}/royal-pavilion-the-paris-vinhomes-ocean-park.jpg` },
  { label: "Lounge âm nhạc", src: `${PARIS_IMG}/phong-tra-lounge-am-nhac-the-paris-ocean-park.jpg` },
  { label: "Tiểu cảnh phân khu", src: `${PARIS_IMG}/tieu-canh-phan-khu-paris-ocean-park.jpg` },
  { label: "Sân chơi trẻ em", src: `${PARIS_IMG}/san-choi-tre-em-phan-khu-paris-ocean-park.jpg` },
  { label: "Sảnh căn hộ (PR1)", src: `${PARIS_IMG}/sanh-can-ho-toa-pr1-the-paris-ocean-park.jpg` },
  { label: "Sảnh thang máy & hành lang", src: `${PARIS_IMG}/sanh-thang-may-hanh-lang-the-paris-ocean-park.jpg` },
];

const BEVERLY_FLOOR_PLANS: ImageTab[] = [
  { label: "Tòa BE1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-beverly/mat-bang-toa-be1-vinhomes-ocean-park-2048x1447.jpg" },
  { label: "Tòa BE2", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-beverly/mat-bang-tang-3-24-toa-be2-phan-khu-the-beverly-vinhomes-ocean-park-2048x1447.jpg" },
  { label: "Tòa BE3", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-beverly/mat-bang-tang-3-24-toa-be3-the-beverly-vinhomes-ocean-park-2048x1447.jpg" },
  { label: "Tòa BE4", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-beverly/mat-bang-toa-be4-the-beverly-vinhomes-ocean-park-2048x1447.jpg" },
];

// Real floor-plan images for The London's 3 towers — already on MinIO from when
// the "the-london" project images were uploaded.
const LONDON_FLOOR_PLANS: ImageTab[] = [
  {
    label: "Tòa LD1",
    src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-london/mat-bang-tang-10-29-toa-ld1-the-london-vinhomes-ocean-park-2048x1448.jpg",
  },
  {
    label: "Tòa LD2",
    src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-london/mat-bang-tang-5-26-toa-ld2-the-london-vinhomes-ocean-park-2048x1448.jpg",
  },
  {
    label: "Tòa LD3",
    src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-london/mat-bang-toa-ld3-vinhomes-ocean-park-2048x1439.jpg",
  },
];

// Real floor-plan images for 4 of The Paris's 5 towers, available on MinIO (no
// dedicated floor-plan image for PR6 in the provided image list).
const PARIS_FLOOR_PLANS: ImageTab[] = [
  { label: "Tòa PR1", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-paris/mat-bang-toa-pr1-the-paris-vinhomes-ocean-park-2048x1170.jpg" },
  { label: "Tòa PR2", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-paris/mat-bang-toa-pr2-the-paris-vinhomes-ocean-park-2048x1449.jpg" },
  { label: "Tòa PR3", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-paris/mat-bang-toa-pr3-phan-khu-the-paris-vinhomes-ocean-park-2048x1448.jpg" },
  { label: "Tòa PR5", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-paris/mat-bang-toa-pr5-the-paris-vinhomes-ocean-park-2048x1170.jpg" },
];

// Position of the 5 towers on vi-tri-the-paris-ocean-park-2048x1170.jpg —
// visually estimated, cross-checked against the labeled reference mockup
// (PR1..PR6, numbered 1-5 following the label order in the mockup:
// PR6=5, PR1=1, PR5=4, PR2=2, PR3=3).
const PARIS_LOCATIONS: MapPin[] = [
  { number: 1, name: "Tòa PR1", left: "40%", top: "46%" },
  { number: 2, name: "Tòa PR2", left: "45%", top: "53%" },
  { number: 3, name: "Tòa PR3", left: "29%", top: "62%" },
  { number: 4, name: "Tòa PR5", left: "22%", top: "55%" },
  { number: 5, name: "Tòa PR6", left: "24%", top: "44%" },
];

function ParisLocationMap() {
  return (
    <section className="section-block location-map-section--dark">
      <div className="location-map-wrap">
        <img
          src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-paris/vi-tri-the-paris-ocean-park-2048x1170.jpg"
          alt="Vị trí các tòa The Paris"
          className="location-map-img"
        />
        {PARIS_LOCATIONS.map((loc) => (
          <div key={loc.name} className="location-pin" style={{ left: loc.left, top: loc.top }}>
            <span className="location-pin-label">{loc.name}</span>
            <span className="location-pin-dot">{loc.number}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// "The Metropolitan" is a parent group (4 sub-zones: Beverly/London/Paris/
// Zurich), not a standalone project in the DB, so it CANNOT be fetched from the
// API — this copy is hand-written, based on verified real figures: Beverly 4
// towers (BE1-BE4), London 3 towers (LD1-LD3), Paris 5 towers (PR1,PR2,PR3,
// PR5,PR6), Zurich 3 towers (ZR1-ZR3) = 15 towers total, developer Vingroup +
// Mitsubishi Corporation (from the_beverly/the_zurich...json).
function MetropolitanSpotlight() {
  return (
    <section className="zone-spotlight zone-spotlight--dark">
      <h3 className="zone-spotlight-title zone-spotlight-title--light">Phân khu The Metropolitan</h3>
      <p className="zone-spotlight-subtitle zone-spotlight-subtitle--light">Điểm đến thượng lưu quận Ocean</p>
      <div className="zone-spotlight-grid">
        <div className="zone-spotlight-text zone-spotlight-text--light">
          <p className="page-sub zone-spotlight-text--light" style={{ maxWidth: "none" }}>
            <strong>The Metropolitan</strong> là phân khu căn hộ do <strong>Vingroup</strong> và{" "}
            <strong>Mitsubishi Corporation</strong> phát triển tại Vinhomes Ocean Park, mở bán tiếp theo phân khu The
            Ocean View.
          </p>
          <p className="page-sub zone-spotlight-text--light" style={{ maxWidth: "none" }}>
            Phân khu gồm <strong>4 tiểu khu</strong> với tổng cộng <strong>15 tòa</strong> căn hộ cao cấp:
          </p>
          <ul className="zone-spotlight-list zone-spotlight-list--light">
            <li>
              <strong>The Beverly:</strong> 4 tòa (BE1 – BE4)
            </li>
            <li>
              <strong>The London:</strong> 3 tòa (LD1 – LD3)
            </li>
            <li>
              <strong>The Paris:</strong> 5 tòa (PR1, PR2, PR3, PR5, PR6)
            </li>
            <li>
              <strong>The Zurich:</strong> 3 tòa (ZR1 – ZR3)
            </li>
          </ul>
          <p className="page-sub zone-spotlight-text--light" style={{ maxWidth: "none" }}>
            Căn hộ tại The Metropolitan có giá bán từ khoảng <strong>1,3 tỷ đồng</strong>, đa dạng loại hình từ
            Studio đến nhiều phòng ngủ, tuỳ theo từng tiểu khu.
          </p>
        </div>
        <div className="zone-spotlight-media">
          <img src="/the-metropolitan-vinhomes-ocean-park.jpg" alt="The Metropolitan" />
        </div>
      </div>
    </section>
  );
}

// Position of the 4 sub-zones on vi-tri-the-metropolitan-vinhomes-ocean-park.jpg
// — ONLY "The Zurich" is confirmed (matches the labeled reference mockup exactly).
// The other 3 (Beverly/London/Paris) would only be ESTIMATES based on the
// location description in the data (Beverly is central, Paris borders Zurich) —
// pending reconfirmation. Only "The Zurich" is kept here since it is the ONLY
// position that matches the reference mockup (the blue zone). The other 3
// (Beverly/London/Paris) have no confirmed position source, so they are
// deliberately NOT marked (to avoid showing wrong info) — to be added once more
// reliable data is available.
const METROPOLITAN_LOCATIONS: MapPin[] = [{ number: 1, name: "The Zurich", left: "72%", top: "34%" }];

// Position of "The Beverly" — matches the YELLOW zone in the reference mockup
// vi-tri-the-metropolitan-vinhomes-ocean-park.jpg (distinct from Zurich's blue
// zone). The marker follows the shared Auremont blue palette for UI consistency.
const BEVERLY_LOCATION: MapPin[] = [{ number: 2, name: "The Beverly", left: "62%", top: "42%", color: "#2e7bff" }];

function MetropolitanLocationMap({ locations = METROPOLITAN_LOCATIONS }: { locations?: MapPin[] }) {
  return (
    <section className="section-block location-map-section--dark">
      <div className="location-map-wrap">
        <img
          src="/vi-tri-the-metropolitan-vinhomes-ocean-park.jpg"
          alt="Vị trí các tiểu khu The Metropolitan"
          className="location-map-img"
        />
        {locations.map((loc) => (
          <div key={loc.name} className="location-pin" style={{ left: loc.left, top: loc.top }}>
            <span className="location-pin-label">{loc.name}</span>
            <span className="location-pin-dot" style={loc.color ? { background: loc.color } : undefined}>
              {loc.number}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

// All 9 real The Zurich unit images per the provided list. Size is only filled
// in once cross-checked against the real reference mockup; 2 files with no
// confirmed size (studio-zr2, 3-bed-zr1) are left blank per spec, not invented.
const ZURICH_LAYOUTS = [
  { label: "Căn Studio", size: "36m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/can-ho-studio-zr1-vinhomes-ocean-park.jpg" },
  { label: "Căn Studio", size: "", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/can-ho-studio-zr2-vinhomes-ocean-park.jpg" },
  { label: "Căn 1 ngủ", size: "47m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/can-ho-1-ngu-zr1-vinhomes-ocean-park.jpg" },
  { label: "Căn 1 ngủ", size: "47m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/can-ho-1-ngu-zr1-vinhomes-ocean-park-2.jpg" },
  { label: "Căn 1 ngủ", size: "47m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/can-ho-1-ngu-zr1-vinhomes-ocean-park-3.jpg" },
  { label: "Căn 2 ngủ", size: "54m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/can-ho-2-ngu-zr1-vinhomes-ocean-park.jpg" },
  { label: "Căn 2 ngủ", size: "74,3m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/can-ho-2-ngu-zr2-vinhomes-ocean-park.jpg" },
  { label: "Căn 3 ngủ", size: "", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/can-ho-3-ngu-zr1-vinhomes-ocean-park.jpg" },
  { label: "Căn 3 ngủ", size: "105m²", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/can-ho-3-ngu-zr2-vinhomes-ocean-park.jpg" },
];

// Kept local (not the shared LayoutGallery) because Zurich's labels carry a
// per-image size figure appended after the unit type.
function ZurichLayoutGallery() {
  return (
    <section className="section-block">
      <h3 className="pricing-card-title">Layout căn hộ The Zurich</h3>
      <div className="layout-gallery">
        {ZURICH_LAYOUTS.map((l, i) => (
          <div key={i} className="layout-gallery-card">
            <img src={l.src} alt={`${l.label} ${l.size}`} />
            <p>{l.size ? `${l.label} | ${l.size}` : l.label}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function TheMetropolitanZone() {
  return (
    <div id="the-metropolitan" className="anchor-section">
      <MetropolitanSpotlight />
      <MetropolitanLocationMap />
      <div id="the-zurich" className="anchor-section">
        <TowerSpotlight projectId="the-zurich" image={`${ZURICH_IMG}/3d-the-zurich-vinhomes-ocean-park.jpg`} />
        <PriceTable projectId="the-zurich" />
        <FloorPlanTabs title="Mặt bằng The Zurich" tabs={ZURICH_FLOOR_PLANS} />
        <ZurichLayoutGallery />
        <AmenityPhotoBanner
          title="Tiện ích nội khu The Zurich"
          paragraphs={["Tầng tiện ích riêng của mỗi toà kết hợp cùng cảnh quan hồ và tháp đồng hồ đặc trưng của phân khu."]}
          photos={ZURICH_AMENITY_PHOTOS}
        />
      </div>
      <div id="the-beverly" className="anchor-section">
        <MetropolitanLocationMap locations={BEVERLY_LOCATION} />
        <TowerSpotlight
          projectId="the-beverly"
          image="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-beverly/quang-truong-the-beverly.jpg"
        />
        <PriceTable projectId="the-beverly" />
        <FloorPlanTabs title="Mặt bằng The Beverly" tabs={BEVERLY_FLOOR_PLANS} />
        <FloorPlanTabs title="Tổng mặt bằng & Tiện ích The Beverly" tabs={BEVERLY_MASTER_PLANS} />
        <AmenityPhotoBanner
          title="Tiện ích nội khu The Beverly"
          paragraphs={["Bể bơi Santa Monica, game room, gym & sauna cùng chuỗi sân chơi và vườn đọc sách phục vụ cư dân bốn toà BE1 – BE4."]}
          photos={BEVERLY_AMENITY_PHOTOS}
        />
      </div>
      <div id="the-london" className="anchor-section">
        <section className="section-block">
          <div className="location-map-wrap">
            <img
              src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-london/phan-khu-the-london-rumor.jpg"
              alt="Phân khu The London"
              className="location-map-img"
            />
          </div>
        </section>
        <TowerSpotlight
          projectId="the-london"
          image="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-london/sanh-le-tan-phan-khu-london-vinhomes-ocean-park-710x375.jpg"
        />
        <PriceTable projectId="the-london" />
        <FloorPlanTabs title="Mặt bằng The London" tabs={LONDON_FLOOR_PLANS} />
        <SoloImage
          src={`${LONDON_IMG}/tong-mat-bang-the-london-vinhomes-ocean-park-full-2048x1387.jpg`}
          alt="Tổng mặt bằng The London"
        />
        <AmenityPhotoBanner
          title="Tiện ích nội khu The London"
          paragraphs={["Ba toà LD1 – LD3 chia sẻ hệ tiện ích gồm phòng gym, phòng karaoke và khu vui chơi trẻ em."]}
          photos={LONDON_AMENITY_PHOTOS}
        />
      </div>
      <div id="the-paris" className="anchor-section">
        <ParisLocationMap />
        <TowerSpotlight
          projectId="the-paris"
          image="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-paris/phoi-canh-phan-khu-the-paris-ocean-park.jpg"
        />
        <PriceTable projectId="the-paris" />
        <FloorPlanTabs title="Mặt bằng The Paris" tabs={PARIS_FLOOR_PLANS} />
        <FloorPlanTabs title="Tổng mặt bằng & Tiện ích The Paris" tabs={PARIS_MASTER_PLANS} />
        <AmenityPhotoBanner
          title="Tiện ích nội khu The Paris"
          paragraphs={["Quảng trường tháp Eiffel là điểm nhấn cảnh quan của phân khu, đi cùng chuỗi tiện ích thể thao và thư giãn bố trí theo từng toà."]}
          photos={PARIS_AMENITY_PHOTOS}
        />
      </div>
    </div>
  );
}
