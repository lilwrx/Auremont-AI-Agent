import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchCategoryDetail,
  fetchAllProjects,
  type ProjectListItem,
} from "../../api/projects";
import type { CategoryDetail } from "../../types/project";
import { CATALOG } from "../../types/catalog";
import { GroupCard } from "../../components/GroupCard";
// Layout primitives and zone data now live under inventory/ so the category page
// and the per-zone pages render from one shared source instead of two copies.
import { AmenityPhotoBanner, IntroCarousel, PinnedLocationMap, type ImageTab } from "./inventory/shared";
import { zonesInCategory, type ZoneMeta } from "./inventory/registry";
import { SHOP_TMDV_PROJECTS, SHOP_TMDV_SALES_POLICIES } from "./inventory/zones/shop-tmdv";
import {
  ArrowLeftIcon,
  BuildingHomeIcon,
  CheckIcon,
  LoaderIcon,
  SearchIcon,
  SparkleIcon,
} from "../../components/Icons";

// categorySlug in the URL is derived from the `category` field in pricing (via
// backend slugify, e.g. "Shophouse" -> "shophouse") — it must match
// CatalogCategory.slug in catalog.ts exactly, otherwise the group lookup fails.
const CATEGORY_SLUG_TO_CATALOG_SLUG: Record<string, string> = {
  "chung-cu": "chung-cu",
  "biet-thu": "biet-thu",
  shophouse: "shophouse",
};

// Dedicated background image for the "Chung cư" (apartment) banner, per spec —
// not fetched from the API like other category types.
const CHUNG_CU_BANNER_IMAGE = "/the-paris-background.jpg";

// Auto-rotating background slides for the "Chung cư" page banner — 4 images per
// spec, already available on MinIO from the-london/the-paris/the-zurich projects.
const CHUNG_CU_BANNER_SLIDES = [
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-london/phong-dance-phan-khu-the-london-vinhomes-ocean-park.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-london/phong-giai-tri-phan-khu-the-london-vinhomes-ocean-park.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-paris/gym-ngoai-troi-phan-khu-paris-ocean-park.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/canh-quan-the-zurich.jpg",
];

// Auto-rotating background slides for the "Biệt thự" (villa) page banner — 3
// images per spec, already available on MinIO from the hai-au/ngoc-trai projects.
const BIET_THU_BANNER_SLIDES = [
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/lien-ke-vinhomes-ocean-park.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinhomes-ocean-park-shop-house.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/song-lap-hai-au.jpg",
];

// Auto-rotating background slides for the "Shophouse" page banner — 1
// representative exterior photo per shop row (SH09/SB11A/HA08/BH9B), already
// available from the crawled data.
const SHOPHOUSE_BANNER_SLIDES = [
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/shop-tmdv-sh09.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sb11a/shop-tmdv-sb11a-vinhomes-ocean-park.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-ha08/shop-thuong-mai-dich-vu-ha08-vinhomes-ocean-park.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-bh9b/shop-thuong-mai-dich-vu-bien-ho-9b-vinhomes-ocean-park.jpg",
];

// 4 auto-rotating images for the "Chung cư" tab's intro section.
const CHUNG_CU_INTRO_IMAGES = [
  "/masterise-vinhomes-ocean-park-night.jpg",
  "/masteri-grand-coast-bg-homepage.jpg",
  "/saphire-vinhomes-ocean-park-night.jpg",
  "/san-choi-the-pavilion.jpg",
];

// Position (as % of image width/height) of each colored zone on
// cac-phan-khu-chung-cu-vinhomes-ocean-park.jpg — this source image has no labels,
// so coordinates are visually estimated against each zone's center, not a survey.
const CHUNG_CU_LOCATIONS = [
  { number: 1, name: "The Sapphire", left: "32%", top: "48%" },
  { number: 2, name: "The Ocean View", left: "41%", top: "17%" },
  { number: 3, name: "The Metropolitan", left: "22%", top: "30%" },
  { number: 4, name: "Masteri Waterfront", left: "44%", top: "43%" },
];

function LocationMap() {
  return (
    <PinnedLocationMap
      image="/cac-phan-khu-chung-cu-vinhomes-ocean-park.jpg"
      alt="Vị trí các phân khu Chung cư Vinhomes Ocean Park"
      pins={CHUNG_CU_LOCATIONS}
      title="Vị trí các phân khu Chung cư Vinhomes Ocean Park"
    />
  );
}

// Yellow "OVERALL VILLA ZONE MASTER PLAN" banner using the exact reference
// mockup provided by the user (numbered pins already on the mockup) — pin
// coordinates are read directly from the pin positions in that same mockup (no
// longer estimated against a different image as before), per the mapping:
// 1 Ngọc Trai, 2 San Hô, 3 Hải Âu, 4 Sao Biển.
const VILLA_LOCATIONS = [
  { number: 1, name: "Ngọc Trai", left: "34%", top: "43%" },
  { number: 2, name: "San Hô", left: "40%", top: "20%" },
  { number: 3, name: "Hải Âu", left: "24%", top: "16%" },
  { number: 4, name: "Sao Biển", left: "14%", top: "34%" },
];

function VillaLocationMap() {
  return (
    <section className="villa-map-banner">
      <h3 className="villa-map-banner-title">Tổng mặt bằng các phân khu Biệt thự</h3>
      <div className="location-map-wrap">
        <img
          src="https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/tong-the-vinhomes-ocean-park.jpg"
          alt="Tổng mặt bằng các phân khu Biệt thự Vinhomes Ocean Park"
          className="location-map-img"
        />
        {VILLA_LOCATIONS.map((loc) => (
          <span key={loc.name} className="villa-map-pin" style={{ left: loc.left, top: loc.top }}>
            {loc.number}
            <span className="villa-map-pin-tooltip">{loc.name}</span>
          </span>
        ))}
      </div>
    </section>
  );
}

// 4 images "anh-biet-thu-1..4" using the exact file names requested — used as a
// gallery: the first image is the default large image; hovering/clicking one of
// the 4 thumbnails swaps in the corresponding large image (see VillaOverviewIntro).
const VILLA_OVERVIEW_PHOTOS = [
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/anh-biet-thu-1.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/anh-biet-thu-2.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/anh-biet-thu-3.jpg",
  "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/anh-biet-thu-4.jpg",
];

// The text content here (scale/handover/legal figures) is NOT sourced from the
// crawled data (hai_au.json/ngoc_trai.json/sao_bien.json have no unit counts or
// groundbreaking year) — it is hand-typed, transcribed verbatim from a reference
// mockup screenshot provided earlier, since no API field carries these figures.
function VillaOverviewIntro() {
  const [activePhoto, setActivePhoto] = useState(0);

  return (
    <section className="section-block intro-grid">
      <div className="intro-text">
        <h3 className="intro-title">
          <span className="intro-title-bar" />
          Tổng quan biệt thự Vinhomes Ocean Park
        </h3>
        <p className="page-sub" style={{ maxWidth: "none" }}>
          <strong>Quy mô số lượng:</strong> khoảng 3.500 căn.
        </p>
        <p className="page-sub" style={{ maxWidth: "none" }}>
          <strong>Các loại hình phát triển:</strong> Biệt thự đơn lập, song lập, liền kề, shophouse và shop thương
          mại dịch vụ.
        </p>
        <p className="page-sub" style={{ maxWidth: "none", marginBottom: 4 }}>
          <strong>Các phân khu biệt thự:</strong>
        </p>
        <ul className="zone-spotlight-list">
          <li>
            <strong>Ngọc Trai:</strong> 458 căn, phân khu đóng, có chốt an ninh tại cổng vào.
          </li>
          <li>
            <strong>San Hô:</strong> 329 căn, phân khu mở.
          </li>
          <li>
            <strong>Hải Âu:</strong> 512 căn, phân khu mở.
          </li>
          <li>
            <strong>Sao Biển:</strong> 788 căn, phân khu mở.
          </li>
          <li>
            <strong>Shop thương mại dịch vụ:</strong> khoảng 1.500 căn.
          </li>
        </ul>
        <p className="page-sub" style={{ maxWidth: "none" }}>
          <strong>Khởi công:</strong> từ năm 2018.
        </p>
        <p className="page-sub" style={{ maxWidth: "none" }}>
          <strong>Bàn giao:</strong> từ cuối năm 2019.
        </p>
        <p className="page-sub" style={{ maxWidth: "none", marginBottom: 4 }}>
          <strong>Pháp lý:</strong>
        </p>
        <ul className="zone-spotlight-list">
          <li>Biệt thự, liền kề và shophouse: Không thời hạn.</li>
          <li>Shop thương mại dịch vụ: 50 năm.</li>
        </ul>
      </div>
      <div>
        <div className="location-map-wrap" style={{ marginBottom: 10 }}>
          <img
            src={VILLA_OVERVIEW_PHOTOS[activePhoto]}
            alt="Biệt thự Vinhomes Ocean Park"
            className="location-map-img"
          />
        </div>
        <div className="layout-gallery" style={{ gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
          {VILLA_OVERVIEW_PHOTOS.map((src, i) => (
            <button
              key={src}
              type="button"
              className={`layout-gallery-card layout-gallery-card--thumb ${i === activePhoto ? "layout-gallery-card--active" : ""}`}
              onMouseEnter={() => setActivePhoto(i)}
              onClick={() => setActivePhoto(i)}
            >
              <img src={src} alt="Biệt thự Vinhomes Ocean Park" />
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

// The amenity-photo banners below replace the default "Highlights"/"Amenities"
// chip list on the Chung cư and Biệt thự tabs, per the mockup provided by the
// user. Images are real, already available from the crawled data (Senique Hanoi
// + Zurich + London + Ngọc Trai), not invented.

// Amenities shared across the whole Ocean Park district (education, healthcare,
// entertainment) — real photos taken from The Senique Hanoi's crawled image set
// (the project with the most complete district-amenity photo set), reused for
// every Chung cư zone.
const DISTRICT_AMENITY_PHOTOS: ImageTab[] = [
  { label: "Vincom Mega Mall", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/tttm-vincom-mega-mall-ocean-park.jpg" },
  { label: "Phòng khám Vinmec", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/vinmec-ocean-park.jpg" },
  { label: "Hồ Ngọc Trai", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/ho-ngoc-trai-vinhomes-ocean-park.jpg" },
  { label: "Biển nhân tạo Crystal Lagoon", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/bien-crystal-largoon.jpg" },
  { label: "Hệ thống giáo dục Vinschool", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/giao-duc-ocean-park.jpg" },
  { label: "Đại học VinUni", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/dai-hoc-vinuni.jpg" },
];

// Representative in-tower amenities for apartment buildings (gym/yoga/pool/
// indoor kids' play area/community room/dance room) — real photos from Zurich +
// London, used generically for the Chung cư tab (not tied to one specific
// project since this section sits at the category level).
const TOWER_AMENITY_PHOTOS: ImageTab[] = [
  { label: "Phòng gym", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/phong-gym-the-zurich.jpg" },
  { label: "Phòng yoga", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/phong-yoga-the-zurich.jpg" },
  { label: "Bể bơi khoáng nóng", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/be-boi-thermal-bath-the-zurich.jpg" },
  { label: "Khu vui chơi trẻ em trong nhà", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/khu-vui-choi-trong-nha-tre-e-the-zurich.jpg" },
  { label: "Phòng sinh hoạt cộng đồng", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-zurich/phong-sinh-hoat-cong-dong-the-zurich.jpg" },
  { label: "Phòng dance / aerobic", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-london/phong-dance-phan-khu-the-london-vinhomes-ocean-park.jpg" },
];

// Amenities & services specific to the Villa tab — uses photos from the Ngọc
// Trai sub-zone's crawled image set (these fit better as district-wide amenity
// photos, and don't overlap with the ones used for Chung cư).
const BIET_THU_AMENITY_PHOTOS: ImageTab[] = [
  { label: "Vincom Mega Mall", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vincom-mega-mall-768x768.jpg" },
  { label: "Đại học VinUni", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinuni-768x768-1.jpg" },
  { label: "Hệ thống giáo dục Vinschool", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinschool-1-705x705.jpg" },
  { label: "Bệnh viện Vinmec", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinmec-768x768-1.jpg" },
  { label: "Vườn nướng BBQ", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vuong-nuong-bbq-705x705.jpg" },
  { label: "Công viên & khu gym ngoài trời", src: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/cong-vien-gym-768x768-2-705x705.jpg" },
];

function CategoryBanner({ category }: { category: CategoryDetail }) {
  const bannerSlides =
    category.name === "Chung cư"
      ? CHUNG_CU_BANNER_SLIDES
      : category.name === "Biệt thự"
        ? BIET_THU_BANNER_SLIDES
        : category.name === "Shophouse"
          ? SHOPHOUSE_BANNER_SLIDES
          : null;
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (!bannerSlides) return;
    const timer = setInterval(() => {
      setActive((i) => (i + 1) % bannerSlides.length);
    }, 4500);
    return () => clearInterval(timer);
  }, [bannerSlides]);

  const singleImage = bannerSlides ? null : category.coverImage ?? category.gallery[0] ?? null;

  return (
    <div className="detail-banner">
      {bannerSlides ? (
        <>
          {bannerSlides.map((src, i) => (
            <div
              key={src}
              className={`detail-banner-slide ${i === active ? "detail-banner-slide--active" : ""}`}
              style={{ backgroundImage: `url(${src})` }}
            />
          ))}
          <div className="detail-banner-dots">
            {bannerSlides.map((_, i) => (
              <button
                key={i}
                type="button"
                aria-label={`Ảnh ${i + 1}`}
                className={`detail-banner-dot ${i === active ? "detail-banner-dot--active" : ""}`}
                onClick={() => setActive(i)}
              />
            ))}
          </div>
        </>
      ) : (
        singleImage && (
          <div
            className="detail-banner-slide detail-banner-slide--active"
            style={{ backgroundImage: `url(${singleImage})` }}
          />
        )
      )}
      <div className="detail-banner-scrim" />

      <BuildingHomeIcon size={40} className="detail-banner-icon" />
      <div className="detail-banner-content">
        <h1 className="detail-banner-title">{category.name}</h1>
      </div>
    </div>
  );
}

// Card linking to a zone's own page. Mirrors GroupCard's markup so both grids
// share the existing .project-card styling instead of needing new CSS.
function ZoneCard({ zone }: { zone: ZoneMeta }) {
  return (
    <Link to={`/inventory/${zone.categorySlug}/${zone.slug}`} className="project-card">
      <div
        className="project-card-media"
        style={{ backgroundImage: `url(${zone.cover})`, backgroundSize: "cover", backgroundPosition: "center" }}
      />
      <div className="project-card-body">
        <h3 className="project-card-title">{zone.name}</h3>
        <p className="project-card-desc">{zone.tagline}</p>
      </div>
    </Link>
  );
}

// Grid of every zone in the current category. Zones each own a page now, so the
// category page only advertises them; the registry keeps this list in sync with
// the router without this file knowing any zone's content.
function ZoneGrid({ categorySlug }: { categorySlug: string }) {
  const zones = zonesInCategory(categorySlug);
  if (zones.length === 0) return null;

  return (
    <section className="section-block">
      <h3 className="section-title">Các phân khu ({zones.length})</h3>
      <div className="inv-grid">
        {zones.map((z) => (
          <ZoneCard key={z.slug} zone={z} />
        ))}
      </div>
    </section>
  );
}

export function CategoryDetailPage() {
  const { categorySlug } = useParams();
  const [category, setCategory] = useState<CategoryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState<ProjectListItem[]>([]);

  useEffect(() => {
    if (!categorySlug) return;
    setLoading(true);
    fetchCategoryDetail(categorySlug)
      .then(setCategory)
      .catch(() => setCategory(null))
      .finally(() => setLoading(false));
  }, [categorySlug]);

  useEffect(() => {
    fetchAllProjects()
      .then(setProjects)
      .catch(() => setProjects([]));
  }, []);

  const projectsById = new Map(projects.map((p) => [p.id, p]));
  const catalogCategorySlug = categorySlug ? CATEGORY_SLUG_TO_CATALOG_SLUG[categorySlug] : undefined;
  const catalogCategory = CATALOG[0].categories.find((c) => c.slug === catalogCategorySlug);

  if (loading) {
    return (
      <div className="page">
        <div className="empty-state">
          <LoaderIcon size={26} className="icon-spin" />
          <p className="empty-state-text empty-state-text--spaced">
            Đang tải bảng giá...
          </p>
        </div>
      </div>
    );
  }

  if (!category) {
    return (
      <div className="page">
        <div className="empty-state">
          <div className="empty-state-icon">
            <SearchIcon size={26} />
          </div>
          <p className="empty-state-title">Không tìm thấy loại hình này</p>
          <p className="empty-state-text">Đường dẫn có thể không đúng.</p>
          <Link to="/home" className="btn btn-primary" style={{ marginTop: 16 }}>
            Về trang chủ
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="page inv-page">
      <CategoryBanner category={category} />

      <Link to="/home" className="detail-back">
        <ArrowLeftIcon size={15} />
        Trang chủ
      </Link>

      <div className="inv-main">
          {category.name === "Chung cư" ? (
            <section className="section-block intro-grid">
              <div className="intro-text">
                <h3 className="intro-title">
                  <span className="intro-title-bar" />
                  {category.name} Vinhomes Ocean Park
                </h3>
                <p className="page-sub" style={{ maxWidth: "none" }}>
                  {category.description}
                </p>
              </div>
              <IntroCarousel images={CHUNG_CU_INTRO_IMAGES} />
            </section>
          ) : (
            <section className="section-block">
              <h3 className="section-title">Giới thiệu</h3>
              <p className="page-sub" style={{ maxWidth: "none" }}>
                {category.description}
              </p>
            </section>
          )}

          {category.name === "Chung cư" && category.types.length > 0 && (
            <section className="pricing-hero">
              <div className="pricing-hero-bg" style={{ backgroundImage: `url(${CHUNG_CU_BANNER_IMAGE})` }} />
              <div className="pricing-card">
                <h3 className="pricing-card-title">Diện tích và giá bán</h3>
                <div className="pricing-table">
                  {category.types.map((t) => (
                    <div key={t.type} className="pricing-table-row">
                      <span className="pricing-table-name">{t.type}</span>
                      <span className="pricing-table-size">{t.sizeRange}</span>
                      <span className="pricing-table-price">{t.priceRange}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}

          {category.name === "Chung cư" && (
            <>
              <LocationMap />
              <ZoneGrid categorySlug="chung-cu" />
            </>
          )}

          {category.name === "Biệt thự" && (
            <>
              <VillaOverviewIntro />
              <VillaLocationMap />
              <div className="section-divider">
                <span>Thiết kế các loại biệt thự</span>
              </div>
              <ZoneGrid categorySlug="biet-thu" />
              <AmenityPhotoBanner
                title="Hệ thống Tiện ích & Dịch vụ"
                paragraphs={[
                  "Khu biệt thự Vinhomes Ocean Park sở hữu hệ sinh thái tiện ích và dịch vụ mang thương hiệu Vinhomes vô cùng đa dạng và đẳng cấp — từ giáo dục, chăm sóc sức khỏe đến vui chơi, giải trí và thể dục thể thao.",
                ]}
                photos={BIET_THU_AMENITY_PHOTOS}
                fit="contain"
              />
            </>
          )}

          {category.name === "Shophouse" && (
            <>
              <section className="section-block intro-grid">
                <div className="intro-text">
                  <h3 className="intro-title">
                    <span className="intro-title-bar" />
                    Shop thương mại dịch vụ Vinhomes Ocean Park
                  </h3>
                  <p className="page-sub" style={{ maxWidth: "none" }}>
                    Hệ thống Shop thương mại dịch vụ (Shop TMDV) gồm 4 dãy — San Hô 09 (SH09), Sao Biển 11A (SB11A),
                    Hải Âu 08 (HA08) và Biển Hồ 9B (BH9B) — với tổng cộng{" "}
                    <strong>{SHOP_TMDV_PROJECTS.reduce((sum, p) => sum + p.overview.totalUnits, 0)} căn</strong>,
                    đồng bộ 4 tầng nổi + 1 tum, mặt tiền rộng và cửa kính lớn, nằm rải khắp các phân khu để phục vụ
                    lượng lớn cư dân hiện hữu của Vinhomes Ocean Park.
                  </p>
                  <ul className="zone-spotlight-list">
                    {SHOP_TMDV_PROJECTS.map((p) => (
                      <li key={p.code}>
                        <strong>{p.code}:</strong> {p.overview.totalUnits} căn, diện tích đất {p.overview.landArea}.
                      </li>
                    ))}
                  </ul>
                  <p className="page-sub" style={{ maxWidth: "none", marginBottom: 4 }}>
                    <strong>Chính sách bán hàng chung (áp dụng cả 4 dãy):</strong>
                  </p>
                  <ul className="zone-spotlight-list">
                    {SHOP_TMDV_SALES_POLICIES.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                </div>
                <IntroCarousel images={SHOPHOUSE_BANNER_SLIDES} />
              </section>

              <ZoneGrid categorySlug="shophouse" />
            </>
          )}

          {catalogCategory &&
            catalogCategory.groups.length > 0 &&
            category.name !== "Chung cư" &&
            category.name !== "Biệt thự" &&
            category.name !== "Shophouse" && (
            <section className="section-block">
              <h3 className="section-title">Các phân khu ({catalogCategory.groups.length})</h3>
              <p className="page-sub" style={{ maxWidth: "none", marginTop: -6, marginBottom: 14 }}>
                Xem chi tiết từng phân khu/dự án con thuộc {category.name.toLowerCase()}.
              </p>
              <div className="inv-grid">
                {catalogCategory.groups.map((g) => (
                  <GroupCard key={g.slug} group={g} projectsById={projectsById} />
                ))}
              </div>
            </section>
          )}

          {category.name === "Chung cư" ? (
            <>
              <AmenityPhotoBanner
                title="Hệ tiện ích đẳng cấp sẵn có của Khu đô thị Ocean Park"
                paragraphs={[
                  "Mọi phân khu căn hộ tại Vinhomes Ocean Park đều thừa hưởng trọn vẹn hệ sinh thái tiện ích sẵn có của Đại đô thị — từ giáo dục, chăm sóc sức khỏe đến vui chơi, giải trí và thể dục thể thao.",
                ]}
                photos={DISTRICT_AMENITY_PHOTOS}
              />
              <AmenityPhotoBanner
                title="Tiện ích nội khu tiêu biểu"
                paragraphs={[
                  "Bên cạnh hệ tiện ích toàn khu đô thị, mỗi tòa căn hộ còn có tầng tiện ích riêng phục vụ cư dân: phòng gym, yoga, bể bơi, khu vui chơi trẻ em, phòng sinh hoạt cộng đồng...",
                ]}
                photos={TOWER_AMENITY_PHOTOS}
              />
            </>
          ) : category.name === "Biệt thự" || category.name === "Shophouse" ? null : (
            <>
              {category.highlights.length > 0 && (
                <section className="section-block">
                  <h3 className="section-title">Điểm nổi bật</h3>
                  <p className="page-sub" style={{ maxWidth: "none", marginTop: -6, marginBottom: 14 }}>
                    Những dấu ấn quy mô lớn nhất của toàn khu đô thị Vinhomes Ocean Park.
                  </p>
                  <div className="detail-amenities">
                    {category.highlights.map((h) => (
                      <span key={h} className="detail-amenity-chip">
                        <SparkleIcon size={13} />
                        {h}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {category.amenities.length > 0 && (
                <section>
                  <h3 className="section-title">Tiện ích</h3>
                  <p className="page-sub" style={{ maxWidth: "none", marginTop: -6, marginBottom: 14 }}>
                    Danh mục đầy đủ tiện ích trong khuôn viên dự án, dùng chung cho mọi loại hình.
                  </p>
                  <div className="detail-amenities">
                    {category.amenities.map((a) => (
                      <span key={a} className="detail-amenity-chip">
                        <CheckIcon size={13} />
                        {a}
                      </span>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
      </div>
    </div>
  );
}
