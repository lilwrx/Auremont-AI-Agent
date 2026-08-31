import { api } from "./client";
import { PROJECT_ID, type CategoryDetail, type CategorySummary } from "../types/project";

// ---- Condensed list of ALL projects (used by the multi-project catalog page) ----

export interface ProjectListItem {
  id: string;
  name: string;
  location: string | null;
  type: string;
  priceFrom: string | null;
  coverImage: string | null;
}

interface ApiProjectListItem {
  id: string;
  name: string;
  location: string | null;
  type: string;
  price_from: string | null;
  cover_image: string | null;
}

export async function fetchAllProjects(): Promise<ProjectListItem[]> {
  const rows = await api.get<ApiProjectListItem[]>("/projects");
  return rows.map((r) => ({
    id: r.id,
    name: r.name,
    location: r.location,
    type: r.type,
    priceFrom: r.price_from,
    coverImage: r.cover_image,
  }));
}

interface ApiCategorySummary {
  slug: string;
  name: string;
  price_from: string;
  price_to: string;
  size_from: number | null;
  size_to: number | null;
  types_count: number;
  cover_image: string | null;
  type_names: string[];
}

interface ApiCategoryTypeRow {
  type: string;
  size_range: string;
  price_range: string;
  description: string | null;
  storeys: string | null;
}

interface ApiAmenity {
  id: string;
  name: string;
  category: string;
  description?: string | null;
}

interface ApiCategoryDetail {
  slug: string;
  name: string;
  description: string;
  cover_image: string | null;
  types: ApiCategoryTypeRow[];
  amenities: ApiAmenity[];
  highlights: string[];
  gallery: string[];
}

function toSummary(row: ApiCategorySummary): CategorySummary {
  return {
    slug: row.slug,
    name: row.name,
    priceFrom: row.price_from,
    priceTo: row.price_to,
    sizeFrom: row.size_from ?? undefined,
    sizeTo: row.size_to ?? undefined,
    typesCount: row.types_count,
    coverImage: row.cover_image ?? undefined,
    typeNames: row.type_names,
  };
}

function toDetail(row: ApiCategoryDetail): CategoryDetail {
  return {
    slug: row.slug,
    name: row.name,
    description: row.description,
    coverImage: row.cover_image ?? undefined,
    types: row.types.map((t) => ({
      type: t.type,
      sizeRange: t.size_range,
      priceRange: t.price_range,
      description: t.description ?? undefined,
      storeys: t.storeys ?? undefined,
    })),
    amenities: row.amenities.map((a) => a.name),
    highlights: row.highlights,
    gallery: row.gallery,
  };
}

export async function fetchCategories(): Promise<CategorySummary[]> {
  const rows = await api.get<ApiCategorySummary[]>(`/projects/${PROJECT_ID}/categories`);
  return rows.map(toSummary);
}

export async function fetchCategoryDetail(slug: string): Promise<CategoryDetail> {
  const row = await api.get<ApiCategoryDetail>(`/projects/${PROJECT_ID}/categories/${slug}`);
  return toDetail(row);
}

export interface ProjectOverview {
  name: string;
  description: string;
  highlights: string[];
  gallery: string[];
}

interface ApiProjectDetail {
  name: string;
  description: string | null;
  highlights: string[];
  gallery: string[];
}

export async function fetchProjectOverview(): Promise<ProjectOverview> {
  const row = await api.get<ApiProjectDetail>(`/projects/${PROJECT_ID}`);
  return {
    name: row.name,
    description: row.description ?? "",
    highlights: row.highlights,
    gallery: row.gallery,
  };
}

// ---- Detail page for one real sub-project (The Beverly, The Sapphire...) ----
// Unlike fetchCategoryDetail/fetchProjectOverview (which always use the fixed
// PROJECT_ID "vinhomes-ocean-park"), this is the ONLY function that takes a dynamic
// projectId — used for individual sub-projects in the multi-project catalog.

export interface ProjectPricingRow {
  category: string;
  apartmentType: string;
  sizeRange: string;
  priceRange: string;
  description?: string;
  storeys?: string;
  sizeMinSqm?: number;
  sizeMaxSqm?: number;
  /** Which tiểu khu this tier belongs to (e.g. "Sapphire 1" vs "Sapphire 2") — only
   * present for a project whose pricing spans more than one sub-zone. Lets PriceTable
   * group rows instead of showing two unlabelled "Studio"/"1PN"/... sets back to back. */
  subZone?: string;
}

export interface ProjectFullDetail {
  id: string;
  name: string;
  location: string | null;
  description: string | null;
  type: string;
  priceFrom: string | null;
  coverImage: string | null;
  developer: string | null;
  highlights: string[];
  pricing: ProjectPricingRow[];
  amenities: string[];
  gallery: string[];
  contact: { hotline?: string; phone?: string; business_hours?: string } | null;
}

interface ApiPricingRow {
  category?: string;
  apartment_type?: string;
  sub_zone?: string | null;
  size_min_sqm?: number | null;
  size_max_sqm?: number | null;
  size_note?: string | null;
  price_min?: number | null;
  price_max?: number | null;
  price_note?: string | null;
  description?: string | null;
  storeys?: string | null;
}

interface ApiAmenityRow {
  name: string;
}

interface ApiFullProjectDetail {
  id: string;
  name: string;
  location: string | null;
  description: string | null;
  type: string;
  price_from: string | null;
  cover_image: string | null;
  developer: string | null;
  highlights: string[];
  pricing: ApiPricingRow[];
  amenities: ApiAmenityRow[];
  gallery: string[];
  contact: { hotline?: string; phone?: string; business_hours?: string } | null;
}

function billions(value: number): string {
  return `${(value / 1_000_000_000).toFixed(1)} tỷ`;
}

function toPricingRow(row: ApiPricingRow): ProjectPricingRow {
  const sizeRange =
    row.size_min_sqm != null && row.size_max_sqm != null
      ? `${row.size_min_sqm} - ${row.size_max_sqm} m²`
      : row.size_note ?? "—";
  const priceRange =
    row.price_min != null && row.price_max != null
      ? `${billions(row.price_min)} - ${billions(row.price_max)}`
      : row.price_note ?? "Liên hệ";
  return {
    category: row.category ?? "",
    apartmentType: row.apartment_type ?? "",
    sizeRange,
    priceRange,
    description: row.description ?? undefined,
    storeys: row.storeys ?? undefined,
    sizeMinSqm: row.size_min_sqm ?? undefined,
    sizeMaxSqm: row.size_max_sqm ?? undefined,
    subZone: row.sub_zone ?? undefined,
  };
}

export async function fetchProjectDetail(projectId: string): Promise<ProjectFullDetail> {
  const row = await api.get<ApiFullProjectDetail>(`/projects/${projectId}`);
  return {
    id: row.id,
    name: row.name,
    location: row.location,
    description: row.description,
    type: row.type,
    priceFrom: row.price_from,
    coverImage: row.cover_image,
    developer: row.developer,
    highlights: row.highlights,
    pricing: row.pricing.map(toPricingRow),
    amenities: row.amenities.map((a) => a.name),
    gallery: row.gallery,
    contact: row.contact,
  };
}

// ---- Citation click-through: temporary signed link to the original file ----

export async function fetchDocumentViewUrl(documentId: number): Promise<string> {
  const { url } = await api.get<{ url: string }>(`/projects/documents/${documentId}/view-url`);
  return url;
}
