// Building blocks shared by every zone page. They were previously nested inside
// the single 1866-line CategoryDetailPage; extracting them lets each zone live in
// its own file without duplicating the layout primitives.
import { Fragment, useEffect, useState } from "react";
import { fetchProjectDetail, type ProjectFullDetail } from "../../../api/projects";

export interface ImageTab {
  label: string;
  src: string;
}

export interface MapPin {
  number: number;
  name: string;
  left: string;
  top: string;
  /** Overrides the default pin colour, used where one pin must stand out from
   * the rest on the same map (e.g. the highlighted tower on Metropolitan). */
  color?: string;
}

export function IntroCarousel({ images }: { images: string[] }) {
  const [active, setActive] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActive((i) => (i + 1) % images.length);
    }, 3500);
    return () => clearInterval(timer);
  }, [images.length]);

  return (
    <div className="intro-carousel">
      {images.map((src, i) => (
        <img
          key={src}
          src={src}
          alt=""
          className={`intro-carousel-slide ${i === active ? "intro-carousel-slide--active" : ""}`}
        />
      ))}
    </div>
  );
}

// Floor-plan tab component — reused for Palma (2 towers), Beverly (4 towers),
// and other sub-zones going forward; just swap the title + tab list.
export function FloorPlanTabs({
  title,
  tabs,
  compact = false,
}: {
  title: string;
  tabs: ImageTab[];
  /** true = cap the image height, for location/rendering images that are
   * unusually wide or tall, to avoid taking up too much vertical space
   * (e.g. Ngọc Trai's "Location & Rendering" section). */
  compact?: boolean;
}) {
  const [active, setActive] = useState(0);

  return (
    <section className="floor-plan-tabs">
      <h3 className="floor-plan-tabs-title">{title}</h3>
      <div className="floor-plan-tabs-nav">
        {tabs.map((t, i) => (
          <button
            key={t.label}
            type="button"
            className={`floor-plan-tab ${active === i ? "floor-plan-tab--active" : ""}`}
            onClick={() => setActive(i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="floor-plan-tabs-body">
        <img
          src={tabs[active].src}
          alt={`Mặt bằng ${tabs[active].label}`}
          className={compact ? "floor-plan-tabs-img floor-plan-tabs-img--compact" : "floor-plan-tabs-img"}
        />
      </div>
    </section>
  );
}

// The layout images already contain full info (unit type, tower, floor, unit
// count, usable/construction area) plus a key plan baked in — only the display
// layout needs to switch to a vertical sidebar (more compact than the old 3-column
// grid); no extra data is needed.
export function SidebarLayoutTabs({ title, tabs }: { title: string; tabs: ImageTab[] }) {
  const [active, setActive] = useState(0);

  return (
    <section className="section-block">
      <h3 className="pricing-card-title">{title}</h3>
      <div className="layout-sidebar">
        <div className="layout-sidebar-nav">
          {tabs.map((t, i) => (
            <button
              key={i}
              type="button"
              className={`layout-sidebar-tab ${active === i ? "layout-sidebar-tab--active" : ""}`}
              onClick={() => setActive(i)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="layout-sidebar-body">
          <img src={tabs[active].src} alt={tabs[active].label} />
        </div>
      </div>
    </section>
  );
}

// Unit layout images shown as a plain grid, for zones whose layouts carry no
// per-image size figure (Zenpark, Pavilion, Zurich).
export function LayoutGallery({ title, layouts }: { title: string; layouts: ImageTab[] }) {
  return (
    <section className="section-block">
      <h3 className="pricing-card-title">{title}</h3>
      <div className="layout-gallery">
        {layouts.map((l, i) => (
          <div key={i} className="layout-gallery-card">
            <img src={l.src} alt={l.label} />
            <p>{l.label}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

// Pricing read live from the API (not hardcoded) — shares the same logic as the
// project detail page (fetchProjectDetail).
export function PriceTable({ projectId }: { projectId: string }) {
  const [detail, setDetail] = useState<ProjectFullDetail | null>(null);

  useEffect(() => {
    fetchProjectDetail(projectId)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [projectId]);

  if (!detail || detail.pricing.length === 0) return null;

  // Most projects have one flat list of tiers. A project whose pricing spans more than
  // one tiểu khu (The Sapphire: Sapphire 1 + Sapphire 2) repeats the same apartment types
  // once per sub-zone — without a group label those read as duplicate, unexplained rows
  // ("Studio" appearing twice with two different size ranges). Only add the extra
  // sub-heading when it is actually needed, so every other project's table is unchanged.
  const subZones = Array.from(new Set(detail.pricing.map((p) => p.subZone).filter((v): v is string => Boolean(v))));
  const showSubZoneGroups = subZones.length > 1;

  return (
    <section className="price-table-brown">
      <h3 className="price-table-brown-title">Bảng giá {detail.name}</h3>
      <p className="price-table-brown-note">
        Bảng giá {detail.name} dưới đây chỉ là <strong>khoảng giá Min – Max</strong> được chủ đầu tư công bố để Quý
        khách hàng cân đối đưa ra quyết định đặt chỗ. Giá bán chi tiết từng căn hộ sẽ phụ thuộc vào vị trí tòa,
        khoảng tầng, hướng ban công, thời điểm ra hàng và sẽ chỉ được công bố tại thời điểm ra mắt chính thức dự án.
      </p>
      <div className="price-table-brown-wrap">
        <div className="price-table-brown-row price-table-brown-row--head">
          <span>Loại hình</span>
          <span>Diện tích</span>
          <span>Giá bán</span>
        </div>
        {detail.pricing.map((p, i) => {
          const startsNewGroup = showSubZoneGroups && p.subZone && detail.pricing[i - 1]?.subZone !== p.subZone;
          return (
            <Fragment key={`${p.subZone ?? ""}-${p.apartmentType}-${i}`}>
              {startsNewGroup && <div className="price-table-brown-subzone">{p.subZone}</div>}
              <div className="price-table-brown-row">
                <span>{p.apartmentType}</span>
                <span>{p.sizeRange}</span>
                <span>{p.priceRange}</span>
              </div>
            </Fragment>
          );
        })}
      </div>
    </section>
  );
}

// An image with numbered pins overlaid at percentage positions. Pin coordinates
// are visually estimated against each zone's centre — the source images carry no
// labels, so they are not survey-accurate.
export function PinnedLocationMap({
  image,
  alt,
  pins,
  title,
  variant = "plain",
}: {
  image: string;
  alt: string;
  pins: MapPin[];
  title?: string;
  /** "dark" for the dark-themed tower maps (Metropolitan/Paris), "banner" for
   * the yellow villa master-plan banner, "plain" for a bare section block. */
  variant?: "plain" | "dark" | "banner";
}) {
  const wrapperClass =
    variant === "banner" ? "villa-map-banner" : `section-block ${variant === "dark" ? "location-map-section--dark" : ""}`;
  const titleClass = variant === "banner" ? "villa-map-banner-title" : "location-map-title";

  return (
    <section className={wrapperClass}>
      {title && <h3 className={titleClass}>{title}</h3>}
      <div className="location-map-wrap">
        <img src={image} alt={alt} className="location-map-img" />
        {pins.map((loc) => (
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

// A single full-width image, used where a zone shows a master plan or landscape
// shot with no pins or tabs attached.
export function SoloImage({ src, alt }: { src: string; alt: string }) {
  return (
    <section className="section-block">
      <div className="location-map-wrap">
        <img src={src} alt={alt} className="location-map-img" />
      </div>
    </section>
  );
}

// Dark banner marking the start of a new zone/sub-zone (reuses the dark theme
// already built for MetropolitanSpotlight) — placed at the TOP of each sub-zone
// or shop-row block so users can tell zones apart while scrolling, without
// re-theming the content below (which keeps its light background, avoiding a
// full re-theme of FloorPlanTabs/PriceTable etc. for a dark background).
export function ZoneHeaderBanner({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="zone-spotlight--dark zone-header-banner">
      <h3 className="zone-spotlight-title zone-spotlight-title--light">{title}</h3>
      {subtitle && <p className="zone-spotlight-subtitle zone-spotlight-subtitle--light">{subtitle}</p>}
    </div>
  );
}

// Spotlight for a sub-zone (unlike Lumière/Metropolitan, which are zones) —
// reuses the real "detail.description" from the API instead of hand-written copy,
// since the API description is already thorough (closely matches the reference
// source). Reused for Beverly/London/Paris below by swapping projectId + image.
export function TowerSpotlight({
  projectId,
  image,
  oval = true,
  hideImage = false,
}: {
  projectId: string;
  image: string;
  /** false = plain rounded-corner rectangular image, smaller than the oval —
   * used when a separate location/rendering image block already follows right
   * below (e.g. Ngọc Trai), where an oval would look redundant. */
  oval?: boolean;
  /** true = hide the image block on the right, showing only the intro text. */
  hideImage?: boolean;
}) {
  const [detail, setDetail] = useState<ProjectFullDetail | null>(null);

  useEffect(() => {
    fetchProjectDetail(projectId)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [projectId]);

  if (!detail) return null;

  return (
    <section
      className={
        hideImage ? "zone-spotlight-grid zone-spotlight-grid--solo section-block" : "zone-spotlight-grid section-block"
      }
    >
      <div className="intro-text">
        <h3 className="intro-title">
          <span className="intro-title-bar" />
          Tiểu khu {detail.name}
        </h3>
        <p className="page-sub" style={{ maxWidth: "none" }}>
          {detail.description}
        </p>
      </div>
      {!hideImage && (
        <div className={oval ? "zone-spotlight-media" : "zone-spotlight-media zone-spotlight-media--rect"}>
          <img src={image} alt={detail.name} />
        </div>
      )}
    </section>
  );
}

export function AmenityPhotoBanner({
  title,
  paragraphs,
  photos,
  fit = "cover",
}: {
  title: string;
  paragraphs: string[];
  photos: ImageTab[];
  /** "contain" for graphic/poster-style images with text close to the edge
   * (e.g. the Villa photo set) — "cover" (default) crops to fill the frame,
   * which suits real photographs. */
  fit?: "cover" | "contain";
}) {
  return (
    <section className="amenity-banner">
      <div className="amenity-banner-head">
        <h3 className="amenity-banner-title">{title}</h3>
        {paragraphs.map((p, i) => (
          <p key={i} className="amenity-banner-text">
            {p}
          </p>
        ))}
      </div>
      <div className="amenity-banner-grid">
        {photos.map((p) => (
          <div key={p.label} className={`amenity-banner-card ${fit === "contain" ? "amenity-banner-card--contain" : ""}`}>
            <img src={p.src} alt={p.label} />
            <p>{p.label}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
