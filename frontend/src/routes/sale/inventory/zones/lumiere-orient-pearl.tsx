// Zone page for "Lumière Orient Pearl" (apartment group), extracted from the old
// single-scroll CategoryDetailPage so each zone owns its own route.
import { AmenityPhotoBanner, FloorPlanTabs, PriceTable, type ImageTab } from "../shared";

const PALMA_IMG = "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-palma";

// Floor plans are grouped per tower because the two Palma towers do not share
// the same floor bands (Palma 1 has 6-17 / 18-21, Palma 2 has 6-18 / 19-21).
const PALMA_1_FLOOR_PLANS: ImageTab[] = [
  { label: "Tầng 2", src: `${PALMA_IMG}/mat-bang-tang-2-toa-palma-1-lumiere-orient-pearl.jpg` },
  { label: "Tầng 3-5", src: `${PALMA_IMG}/mat-bang-tang-3-5-toa-palma-1-lumiere-orient-pearl.jpg` },
  { label: "Tầng 6-17", src: `${PALMA_IMG}/mat-bang-tang-6-17-toa-palma-1-lumiere-orient-pearl.jpg` },
  { label: "Tầng 18-21", src: `${PALMA_IMG}/mat-bang-tang-18-21-toa-palma-1-lumiere-orient-pearl.jpg` },
  { label: "Tầng 22, 24, 26, 28", src: `${PALMA_IMG}/mat-bang-tang-22-24-26-28-toa-palma-1-lumiere-orient-pearl.jpg` },
  { label: "Tầng 23, 25, 27", src: `${PALMA_IMG}/mat-bang-tang-23-25-27-toa-palma-1-lumiere-orient-pearl.jpg` },
  { label: "Tầng 29", src: `${PALMA_IMG}/mat-bang-tang-29-toa-palma-1-lumiere-orient-pearl.jpg` },
];

const PALMA_2_FLOOR_PLANS: ImageTab[] = [
  { label: "Tầng 2", src: `${PALMA_IMG}/mat-bang-tang-2-toa-palma-2-lumiere-orient-pearl.jpg` },
  { label: "Tầng 3-5", src: `${PALMA_IMG}/mat-bang-tang-3-5-toa-palma-2-lumiere-orient-pearl.jpg` },
  { label: "Tầng 6-18", src: `${PALMA_IMG}/mat-bang-tang-6-18-toa-palma-2-lumiere-orient-pearl.jpg` },
  { label: "Tầng 19-21", src: `${PALMA_IMG}/mat-bang-tang-19-21-toa-palma-2-lumiere-orient-pearl.jpg` },
  { label: "Tầng 22, 24, 26, 28", src: `${PALMA_IMG}/mat-bang-tang-22-24-26-28-toa-palma-2-lumiere-orient-pearl.jpg` },
  { label: "Tầng 23, 25, 27", src: `${PALMA_IMG}/mat-bang-tang-23-25-27-toa-palma-2-lumiere-orient-pearl.jpg` },
  { label: "Tầng 29", src: `${PALMA_IMG}/mat-bang-tang-29-toa-palma-2-lumiere-orient-pearl.jpg` },
];

const PALMA_MASTER_PLANS: ImageTab[] = [
  { label: "Tổng mặt bằng", src: `${PALMA_IMG}/mat-bang-tong-the-lumiere-orient-pearl-2048x1025.jpg` },
  { label: "Mặt bằng tiện ích", src: `${PALMA_IMG}/mat-bang-tien-ich-lumiere-orient-pearl-2048x1448.jpg` },
  { label: "Vị trí các tòa", src: `${PALMA_IMG}/lumiere-orient-pearl-vi-tri-toa.jpg` },
];

const PALMA_RENDER_PHOTOS: ImageTab[] = [
  { label: "Phối cảnh The Palma", src: `${PALMA_IMG}/phoi-canh-the-palma.jpg` },
  { label: "Kiến trúc The Palma", src: `${PALMA_IMG}/kien-truc-the-palma.jpg` },
  { label: "Tổng thể The Palma", src: `${PALMA_IMG}/the-palma.jpg` },
  { label: "Lối vào sảnh tòa The Palma 1", src: `${PALMA_IMG}/loi-vao-sanh-toa-the-palma-1.jpg` },
];

// Lumière Orient Pearl / The Palma copy is sourced from the real "the-palma"
// project data (developer, overview, location_sides...) read earlier — not invented.
function LumiereOrientPearlSpotlight() {
  return (
    <section className="zone-spotlight">
      <h3 className="zone-spotlight-title">Phân khu Lumière Orient Pearl</h3>
      <p className="zone-spotlight-subtitle">Kiến trúc lấy cảm hứng từ tàu lá cọ soi bóng mặt nước</p>

      <div className="zone-spotlight-grid">
        <div className="zone-spotlight-text">
          <p className="page-sub" style={{ maxWidth: "none" }}>
            <strong className="zone-spotlight-lead">Lumière Orient Pearl</strong> là phân khu căn hộ do{" "}
            <strong>Masterise Homes</strong> phát triển tại Vinhomes Ocean Park. <strong>The Palma</strong> là dự án
            căn hộ đầu tiên ra mắt tại đây, thiết kế lấy cảm hứng từ sự riêng tư và tĩnh tại, kiến trúc gợi hình tàu
            lá cọ soi bóng trên mặt nước.
          </p>
          <p className="page-sub" style={{ maxWidth: "none" }}>
            Phân khu The Palma gồm <strong>02 tòa</strong> căn hộ (~1.140 căn), cao <strong>30 tầng</strong>, tầng
            tiện ích riêng tại tầng 1 và tầng 13, với 2 tòa:
          </p>
          <ul className="zone-spotlight-list">
            <li>
              <strong>The Palma 1:</strong> tòa tháp thứ nhất, tầng 2 – 30.
            </li>
            <li>
              <strong>The Palma 2:</strong> tòa tháp thứ hai, tầng 2 – 30.
            </li>
          </ul>
          <p className="page-sub" style={{ maxWidth: "none" }}>
            Căn hộ tại The Palma có diện tích từ khoảng <strong>28,6 – 93,9m²</strong> với đa dạng loại hình Studio,
            1PN, 1PN+, 2PN, 2PN+, 3PN, Duplex, Penthouse — giá bán từ khoảng <strong>3 tỷ đồng</strong>, dự kiến bàn
            giao Quý 3/2027.
          </p>
        </div>
        <div className="zone-spotlight-media">
          <img src="/lumiere-orient-pearl-bg-1.jpg" alt="Lumière Orient Pearl" />
        </div>
      </div>
    </section>
  );
}

export function LumiereOrientPearlZone() {
  return (
    <div id="lumiere-orient-pearl" className="anchor-section">
      <LumiereOrientPearlSpotlight />
      <PriceTable projectId="the-palma" />
      <FloorPlanTabs title="Tổng mặt bằng & Tiện ích Lumière Orient Pearl" tabs={PALMA_MASTER_PLANS} />
      <FloorPlanTabs title="Mặt bằng tòa The Palma 1" tabs={PALMA_1_FLOOR_PLANS} />
      <FloorPlanTabs title="Mặt bằng tòa The Palma 2" tabs={PALMA_2_FLOOR_PLANS} />
      <AmenityPhotoBanner
        title="Phối cảnh & Kiến trúc The Palma"
        paragraphs={[
          "Kiến trúc The Palma lấy cảm hứng từ tàu lá cọ soi bóng mặt nước, với hệ ban công uốn lượn và sảnh đón riêng cho từng tòa.",
        ]}
        photos={PALMA_RENDER_PHOTOS}
      />
    </div>
  );
}
