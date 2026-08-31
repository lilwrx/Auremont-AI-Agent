// Display types for the Lookup page — an internal Sale tool for ONE mega-project (Vinhomes Ocean
// Park), browsed by product type (apartments/villas/shophouses), not across multiple projects.

export const PROJECT_ID = "vinhomes-ocean-park";

export interface CategorySummary {
  slug: string;
  name: string;
  priceFrom: string;
  priceTo: string;
  sizeFrom?: number;
  sizeTo?: number;
  typesCount: number;
  coverImage?: string;
  typeNames: string[];
}

export interface CategoryTypeRow {
  type: string;
  sizeRange: string;
  priceRange: string;
  description?: string;
  storeys?: string;
}

export interface CategoryDetail {
  slug: string;
  name: string;
  description: string;
  coverImage?: string;
  types: CategoryTypeRow[];
  amenities: string[];
  highlights: string[];
  gallery: string[];
}

/** Other sub-zones/phases of the mega-project — no dedicated data yet, shown as "coming soon". */
export interface UpcomingPhase {
  slug: string;
  name: string;
}

export const UPCOMING_PHASES: UpcomingPhase[] = [
  { slug: "ocean-park-2", name: "Ocean Park 2" },
  { slug: "ocean-park-3", name: "Ocean Park 3" },
];
