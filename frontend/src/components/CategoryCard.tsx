import { Link } from "react-router-dom";
import type { CategorySummary } from "../types/project";
import { BuildingHomeIcon } from "./Icons";

// Dedicated image for the "Apartments" card per requirement — not fetched from the API like the others.
const CHUNG_CU_IMAGE = "/masteri-grand-coast-bg-homepage.jpg";

// "Shophouse" is the pricing category's real name (the slug/routing everywhere else keys off
// it, so that stays untouched) but it lumps together nhà phố thương mại and "Shop thương mại
// dịch vụ" units — the card should read "Shop TMDV" instead. The project's own gallery has no
// shop photo (that data lives under the SH09/SB11A/HA08/BH9B sub-projects instead), so this
// borrows one real photo from there rather than showing the wrong picture or a placeholder.
const SHOPHOUSE_DISPLAY_NAME = "Shop TMDV";
const SHOPHOUSE_IMAGE = "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/sanho_anh_thuc_te_1.jpg";

export function CategoryCard({ category }: { category: CategorySummary }) {
  const isShophouse = category.slug === "shophouse";
  const displayName = isShophouse ? SHOPHOUSE_DISPLAY_NAME : category.name;
  const coverImage = category.slug === "chung-cu" ? CHUNG_CU_IMAGE : isShophouse ? SHOPHOUSE_IMAGE : category.coverImage;

  const media = coverImage ? undefined : { background: "linear-gradient(135deg, #0050ef, #0a2e7a)" };

  const sizeLabel =
    category.sizeFrom != null && category.sizeTo != null ? `${category.sizeFrom} - ${category.sizeTo} m²` : null;

  return (
    <Link to={`/inventory/${category.slug}`} className="project-card">
      <div className="project-card-media" style={media}>
        {coverImage ? (
          <img src={coverImage} className="project-card-image" alt={displayName} />
        ) : (
          <BuildingHomeIcon size={30} className="project-card-media-icon" />
        )}
      </div>
      <div className="project-card-body">
        <div className="project-card-meta">
          {sizeLabel && <span className="project-card-location">{sizeLabel}</span>}
        </div>
        <h3 className="project-card-title">{displayName}</h3>
        <div className="project-card-footer">
          <div>
            <span className="project-card-price-label">Khoảng giá</span>
            <strong className="project-card-price">
              {category.priceFrom} - {category.priceTo}
            </strong>
          </div>
        </div>
      </div>
    </Link>
  );
}
