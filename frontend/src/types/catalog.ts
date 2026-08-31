// Catalog hierarchy, matching the real website's menu (vinhomeoceanpark.com.vn):
// Ocean Park (1/2/3) -> product type (apartments/villas/shophouses) -> group/sub-zone -> sub-project.
//
// `projectId` on a sub-project points to the real id in the `projects` DB table once data exists.
// A group/sub-project without a `projectId` is shown as "no data yet" rather than hidden, per the
// requirement that empty pages stay visible while waiting for data to be filled in later.

export interface CatalogProject {
  name: string;
  projectId?: string;
}

export interface CatalogGroup {
  slug: string;
  name: string;
  projects: CatalogProject[];
}

export interface CatalogCategory {
  slug: string;
  name: string;
  groups: CatalogGroup[];
}

export interface CatalogMegaProject {
  slug: string;
  name: string;
  available: boolean;
  categories: CatalogCategory[];
}

export const CATALOG: CatalogMegaProject[] = [
  {
    slug: "ocean-park-1",
    name: "Vinhomes Ocean Park",
    available: true,
    categories: [
      {
        slug: "chung-cu",
        name: "Chung cư",
        groups: [
          {
            slug: "lumiere-orient-pearl",
            name: "Lumiere Orient Pearl",
            projects: [{ name: "The Palma", projectId: "the-palma" }],
          },
          {
            slug: "the-metropolitan",
            name: "The Metropolitan",
            projects: [
              { name: "The Beverly", projectId: "the-beverly" },
              { name: "The London", projectId: "the-london" },
              { name: "The Paris", projectId: "the-paris" },
              { name: "The Zurich", projectId: "the-zurich" },
            ],
          },
          {
            slug: "the-ocean-view",
            name: "The Ocean View",
            projects: [
              { name: "The Pavilion", projectId: "the-pavilion" },
              { name: "The Zenpark", projectId: "the-zenpark" },
            ],
          },
          {
            slug: "the-sapphire",
            name: "The Sapphire",
            projects: [{ name: "The Sapphire", projectId: "the-sapphire" }],
          },
          {
            slug: "the-senique-hanoi",
            name: "The Senique Hanoi",
            projects: [{ name: "The Senique Hanoi", projectId: "the-senique-hanoi" }],
          },
        ],
      },
      {
        slug: "biet-thu",
        name: "Biệt thự",
        groups: [
          {
            slug: "tieu-khu-ngoc-trai",
            name: "Tiểu khu Ngọc Trai",
            projects: [{ name: "Tiểu khu Ngọc Trai", projectId: "ngoc-trai" }],
          },
          {
            slug: "tieu-khu-hai-au",
            name: "Tiểu khu Hải Âu",
            projects: [{ name: "Tiểu khu Hải Âu", projectId: "hai-au" }],
          },
          {
            slug: "tieu-khu-sao-bien",
            name: "Tiểu khu Sao Biển",
            projects: [{ name: "Tiểu khu Sao Biển", projectId: "sao-bien" }],
          },
        ],
      },
      {
        // Slug MUST match slugify(pricing.category) = slugify("Shophouse") on the
        // backend ("shophouse") so fetchCategoryDetail finds the right category —
        // using "shop-tmdv" here would make the detail page always 404.
        slug: "shophouse",
        name: "Shop TMDV",
        groups: [
          {
            slug: "shop-sh09",
            name: "Shop thương mại SH09",
            projects: [{ name: "Shop thương mại SH09", projectId: "shop-thuong-mai-sh09" }],
          },
          {
            slug: "shop-sb11a",
            name: "Shop thương mại SB11A",
            projects: [{ name: "Shop thương mại SB11A", projectId: "shop-thuong-mai-sb11a" }],
          },
          {
            slug: "shop-ha08",
            name: "Shop thương mại HA08",
            projects: [{ name: "Shop thương mại HA08", projectId: "shop-thuong-mai-ha08" }],
          },
          {
            slug: "shop-bh9b",
            name: "Shop thương mại BH9B",
            projects: [{ name: "Shop thương mại BH9B", projectId: "shop-thuong-mai-bh9b" }],
          },
        ],
      },
    ],
  },
  {
    slug: "ocean-park-2",
    name: "Ocean Park 2",
    available: false,
    categories: [
      {
        slug: "chung-cu",
        name: "Chung cư",
        groups: [
          { slug: "masteri-grand-coast", name: "Masteri Grand Coast", projects: [{ name: "Masteri Grand Coast" }] },
          { slug: "imperia-ocean-city", name: "Imperia Ocean City", projects: [{ name: "Imperia Ocean City" }] },
          { slug: "lumiere-springbay", name: "LUMIÈRE SpringBay", projects: [{ name: "LUMIÈRE SpringBay" }] },
          { slug: "masteri-trinity-square", name: "Masteri Trinity Square", projects: [{ name: "Masteri Trinity Square" }] },
        ],
      },
      {
        slug: "phan-khu-biet-thu",
        name: "Phân khu biệt thự",
        groups: [
          { slug: "dao-dua", name: "Phân khu Đảo Dừa", projects: [{ name: "Phân khu Đảo Dừa" }] },
          { slug: "co-xanh", name: "Phân khu Cọ Xanh", projects: [{ name: "Phân khu Cọ Xanh" }] },
          { slug: "hai-au-op2", name: "Phân khu Hải Âu", projects: [{ name: "Phân khu Hải Âu" }] },
          { slug: "sao-bien-op2", name: "Phân khu Sao Biển", projects: [{ name: "Phân khu Sao Biển" }] },
          { slug: "kinh-do-anh-sang", name: "Phân khu Kinh Đô Ánh Sáng", projects: [{ name: "Phân khu Kinh Đô Ánh Sáng" }] },
          { slug: "san-ho", name: "Phân khu San Hô", projects: [{ name: "Phân khu San Hô" }] },
          { slug: "cha-la", name: "Phân khu Chà Là", projects: [{ name: "Phân khu Chà Là" }] },
          { slug: "ngoc-trai-op2", name: "Phân khu Ngọc Trai", projects: [{ name: "Phân khu Ngọc Trai" }] },
          { slug: "little-hong-kong", name: "Little Hong Kong", projects: [{ name: "Little Hong Kong" }] },
        ],
      },
    ],
  },
  {
    slug: "ocean-park-3",
    name: "Ocean Park 3",
    available: false,
    categories: [
      {
        slug: "phan-khu",
        name: "Phân khu",
        groups: [
          { slug: "the-spark", name: "Phân khu The Spark", projects: [{ name: "Phân khu The Spark" }] },
          { slug: "the-flow", name: "Phân khu The Flow", projects: [{ name: "Phân khu The Flow" }] },
          { slug: "the-vision", name: "Phân khu The Vision", projects: [{ name: "Phân khu The Vision" }] },
          { slug: "masteri-era-landmark", name: "Masteri Era Landmark", projects: [{ name: "Masteri Era Landmark" }] },
          { slug: "the-fullton", name: "The Fullton", projects: [{ name: "The Fullton" }] },
          { slug: "thoi-dai", name: "Phân khu Thời Đại", projects: [{ name: "Phân khu Thời Đại" }] },
          { slug: "pho-bien", name: "Phân khu Phố Biển", projects: [{ name: "Phân khu Phố Biển" }] },
          { slug: "vinh-thien-duong", name: "Phân khu Vịnh Thiên Đường", projects: [{ name: "Phân khu Vịnh Thiên Đường" }] },
          { slug: "vinh-tay", name: "Phân khu Vịnh Tây", projects: [{ name: "Phân khu Vịnh Tây" }] },
          { slug: "anh-duong", name: "Phân khu Ánh Dương", projects: [{ name: "Phân khu Ánh Dương" }] },
          { slug: "vinh-xanh", name: "Phân khu Vịnh Xanh", projects: [{ name: "Phân khu Vịnh Xanh" }] },
          { slug: "dao-ngoc", name: "Phân khu Đảo Ngọc", projects: [{ name: "Phân khu Đảo Ngọc" }] },
        ],
      },
    ],
  },
];

export function findMegaProject(slug: string): CatalogMegaProject | undefined {
  return CATALOG.find((m) => m.slug === slug);
}

export function findGroup(groupSlug: string): { mega: CatalogMegaProject; category: CatalogCategory; group: CatalogGroup } | undefined {
  for (const mega of CATALOG) {
    for (const category of mega.categories) {
      const group = category.groups.find((g) => g.slug === groupSlug);
      if (group) return { mega, category, group };
    }
  }
  return undefined;
}

export function findProjectEntry(projectId: string): { group: CatalogGroup; project: CatalogProject } | undefined {
  for (const mega of CATALOG) {
    for (const category of mega.categories) {
      for (const group of category.groups) {
        const project = group.projects.find((p) => p.projectId === projectId);
        if (project) return { group, project };
      }
    }
  }
  return undefined;
}
