// Single source of truth for "which zones exist and what renders them".
//
// Zones used to live as anchor sections inside one long CategoryDetailPage; each
// now has its own URL (/inventory/<category>/<zone>). Keeping the mapping here —
// rather than branching on category.name inside the page — means adding a zone is
// one entry plus one component file, and the navbar, the category listing and the
// router all stay in sync automatically.
import type { ReactElement } from "react";
import { LumiereOrientPearlZone } from "./zones/lumiere-orient-pearl";
import { TheMetropolitanZone } from "./zones/the-metropolitan";
import { TheOceanViewZone } from "./zones/the-ocean-view";
import { TheSapphireZone } from "./zones/the-sapphire";
import { TheSeniqueHanoiZone } from "./zones/the-senique-hanoi";
import { HaiAuZone } from "./zones/tieu-khu-hai-au";
import { NgocTraiZone } from "./zones/tieu-khu-ngoc-trai";
import { SaoBienZone } from "./zones/tieu-khu-sao-bien";
import { ShopTmdvZone } from "./zones/shop-tmdv";

export interface ZoneMeta {
  slug: string;
  /** Menu/card label. Matches CatalogGroup.name in types/catalog.ts. */
  name: string;
  /** Short line shown on the category page's zone cards. */
  tagline: string;
  /** Category this zone belongs to, matching CatalogCategory.slug. */
  categorySlug: string;
  /** Cover image for the zone card on the category page. */
  cover: string;
  /** Renders the zone's content on its own page. */
  render: () => ReactElement;
  /** Anchors rendered inside this zone's own page, for sub-zones that keep
   * scroll navigation within a single page (e.g. Metropolitan's 4 towers). */
  subAnchors?: { label: string; anchorId: string }[];
}

export const ZONES: ZoneMeta[] = [
  {
    slug: "lumiere-orient-pearl",
    name: "Lumiere Orient Pearl",
    tagline: "Kiến trúc lấy cảm hứng từ tàu lá cọ soi bóng mặt nước",
    categorySlug: "chung-cu",
    cover: "/lumiere-orient-pearl-bg-1.jpg",
    render: () => <LumiereOrientPearlZone />,
  },
  {
    slug: "the-metropolitan",
    name: "The Metropolitan",
    tagline: "Điểm đến thượng lưu quận Ocean — 4 tiểu khu, 15 tòa căn hộ",
    categorySlug: "chung-cu",
    cover: "/vi-tri-the-metropolitan-vinhomes-ocean-park.jpg",
    render: () => <TheMetropolitanZone />,
    subAnchors: [
      { label: "The Zurich", anchorId: "the-zurich" },
      { label: "The Beverly", anchorId: "the-beverly" },
      { label: "The London", anchorId: "the-london" },
      { label: "The Paris", anchorId: "the-paris" },
    ],
  },
  {
    slug: "the-ocean-view",
    name: "The Ocean View",
    tagline: "Thiên đường nghỉ dưỡng sinh thái — 3 tiểu khu, 12 tòa căn hộ",
    categorySlug: "chung-cu",
    cover: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-ocean-view/the-ocean-view.jpg",
    render: () => <TheOceanViewZone />,
    subAnchors: [
      { label: "The Zenpark", anchorId: "the-zenpark" },
      { label: "The Pavilion", anchorId: "the-pavilion" },
    ],
  },
  {
    slug: "the-sapphire",
    name: "The Sapphire",
    tagline: "Tâm điểm của thành phố biển hồ — 27 tòa căn hộ",
    categorySlug: "chung-cu",
    cover: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-sapphire/phan-khu-sapphire-vinhomes-ocean-park.jpg",
    render: () => <TheSapphireZone />,
    subAnchors: [
      { label: "The Sapphire 1", anchorId: "the-sapphire-1" },
      { label: "The Sapphire 2", anchorId: "the-sapphire-2" },
    ],
  },
  {
    slug: "the-senique-hanoi",
    name: "The Senique Hanoi",
    tagline: "Compound khép kín đầu tiên tại Ocean Park — 3 tòa, 2.152 căn",
    categorySlug: "chung-cu",
    cover: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/the-senique-hanoi/the-senique-hanoi-phoi-canh.jpg",
    render: () => <TheSeniqueHanoiZone />,
    subAnchors: [
      { label: "Tòa The Senique 1", anchorId: "the-senique-1" },
      { label: "Tòa The Senique 2", anchorId: "the-senique-2" },
    ],
  },
  {
    slug: "tieu-khu-ngoc-trai",
    name: "Tiểu khu Ngọc Trai",
    tagline: "Vị trí trung tâm - 'trái tim' của Vinhomes Ocean Park",
    categorySlug: "biet-thu",
    cover: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/ngoc-trai/vinhomes-ocean-park-ngoc-trai.jpg",
    render: () => <NgocTraiZone />,
  },
  {
    slug: "tieu-khu-hai-au",
    name: "Tiểu khu Hải Âu",
    tagline: "Thiết kế theo hình cánh chim Hải Âu",
    categorySlug: "biet-thu",
    cover: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/hai-au/vinhomes-ocean-park-hai-au.jpg",
    render: () => <HaiAuZone />,
  },
  {
    slug: "tieu-khu-sao-bien",
    name: "Tiểu khu Sao Biển",
    tagline: "Ôm trọn hồ điều hòa trung tâm 25ha",
    categorySlug: "biet-thu",
    cover: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/sao-bien/phoi-canh-sao-bien-vinhomes-ocean-park.jpg",
    render: () => <SaoBienZone />,
  },
  {
    slug: "shop-sh09",
    name: "Shop thương mại SH09",
    tagline: "Dãy shop thương mại dịch vụ San Hô 09",
    categorySlug: "shophouse",
    cover: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sh09/shop-tmdv-sh09.jpg",
    render: () => <ShopTmdvZone shopCode="SH09" />,
  },
  {
    slug: "shop-sb11a",
    name: "Shop thương mại SB11A",
    tagline: "Dãy shop thương mại dịch vụ Sao Biển 11A",
    categorySlug: "shophouse",
    cover: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-sb11a/shop-tmdv-sb11a-vinhomes-ocean-park.jpg",
    render: () => <ShopTmdvZone shopCode="SB11A" />,
  },
  {
    slug: "shop-ha08",
    name: "Shop thương mại HA08",
    tagline: "Dãy shop thương mại dịch vụ Hải Âu 08",
    categorySlug: "shophouse",
    cover: "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-ha08/shop-thuong-mai-dich-vu-ha08-vinhomes-ocean-park.jpg",
    render: () => <ShopTmdvZone shopCode="HA08" />,
  },
  {
    slug: "shop-bh9b",
    name: "Shop thương mại BH9B",
    tagline: "Dãy shop thương mại dịch vụ Biển Hồ 9B",
    categorySlug: "shophouse",
    cover:
      "https://pub-2b6dd93e8e8948099737838a9bf56770.r2.dev/shop-thuong-mai-bh9b/shop-thuong-mai-dich-vu-bien-ho-9b-vinhomes-ocean-park.jpg",
    render: () => <ShopTmdvZone shopCode="BH9B" />,
  },
];

export function findZone(categorySlug: string, zoneSlug: string): ZoneMeta | undefined {
  return ZONES.find((z) => z.categorySlug === categorySlug && z.slug === zoneSlug);
}

export function zonesInCategory(categorySlug: string): ZoneMeta[] {
  return ZONES.filter((z) => z.categorySlug === categorySlug);
}

/** Zone slugs that now have their own page, so the navbar can link straight to
 * them instead of falling back to an in-page anchor. */
export const ZONE_SLUGS = new Set(ZONES.map((z) => z.slug));
