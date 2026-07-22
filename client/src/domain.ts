export type AuthCredentials =
  | { kind: "api-key"; value: string }
  | { kind: "bearer"; value: string };

export interface ConservatoryContext {
  eventId: string;
  exhibitorId: string;
  categoryId: string;
}

export interface BackendPlant {
  id: string;
  exhibitor_id: string;
  judging_event_id: string;
  category_id: string;
  name: string | null;
  qr_code: string | null;
  notes: string | null;
  created_at: string;
}

export interface PlantView {
  id: string;
  displayName: string;
  acceptedScientificName: string | null;
  synonymStatus: "not-supplied";
  hybridNotation: string | null;
  authorship: string | null;
  uncertainIdentification: boolean;
  parentage: string | null;
  qrIdentifier: string | null;
  photographs: readonly string[];
  notes: string | null;
  location: string | null;
  collectionMetadata: {
    eventId: string;
    exhibitorId: string;
    categoryId: string;
    createdAt: string;
  };
  provenance: readonly ProvenanceRecord[];
  citations: readonly Citation[];
}

export interface ProvenanceRecord {
  source: string;
  recordId: string;
  retrievedAt: string;
  statement: string;
}

export interface Citation {
  label: string;
  source: string;
}

export interface PlantCreateInput {
  name: string;
  notes?: string;
}

export interface CollectionQuery {
  query: string;
  categoryId?: string;
  sort: "name-asc" | "name-desc" | "newest" | "oldest";
  page: number;
  pageSize: number;
}

export interface CollectionResult {
  items: PlantView[];
  total: number;
  page: number;
  pageSize: number;
}

export function toPlantView(plant: BackendPlant, retrievedAt = new Date().toISOString()): PlantView {
  const displayName = plant.name?.trim() || "Unidentified orchid";
  const uncertain = !plant.name || /(?:^|\s)(?:cf\.|aff\.|sp\.|unknown|uncertain)(?:\s|$)/i.test(displayName);
  return {
    id: plant.id,
    displayName,
    acceptedScientificName: null,
    synonymStatus: "not-supplied",
    hybridNotation: displayName.includes("×") || /\bx\b/i.test(displayName) ? displayName : null,
    authorship: null,
    uncertainIdentification: uncertain,
    parentage: null,
    qrIdentifier: plant.qr_code,
    photographs: [],
    notes: plant.notes,
    location: null,
    collectionMetadata: {
      eventId: plant.judging_event_id,
      exhibitorId: plant.exhibitor_id,
      categoryId: plant.category_id,
      createdAt: plant.created_at,
    },
    provenance: [
      {
        source: "Calyx judging plant API",
        recordId: plant.id,
        retrievedAt,
        statement: "Unmodified collection record fields from the existing backend.",
      },
    ],
    citations: [],
  };
}

export function filterAndPage(plants: PlantView[], query: CollectionQuery): CollectionResult {
  const needle = query.query.trim().toLocaleLowerCase();
  const filtered = plants.filter((plant) => {
    const matchesText = !needle || [plant.displayName, plant.notes || "", plant.hybridNotation || ""]
      .some((value) => value.toLocaleLowerCase().includes(needle));
    return matchesText && (!query.categoryId || plant.collectionMetadata.categoryId === query.categoryId);
  });
  const sorted = [...filtered].sort((left, right) => {
    if (query.sort === "newest" || query.sort === "oldest") {
      const delta = Date.parse(left.collectionMetadata.createdAt) - Date.parse(right.collectionMetadata.createdAt);
      return query.sort === "newest" ? -delta : delta;
    }
    const delta = left.displayName.localeCompare(right.displayName);
    return query.sort === "name-desc" ? -delta : delta;
  });
  const page = Math.max(1, query.page);
  const start = (page - 1) * query.pageSize;
  return { items: sorted.slice(start, start + query.pageSize), total: sorted.length, page, pageSize: query.pageSize };
}
