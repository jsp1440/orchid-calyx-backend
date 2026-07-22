import type { AuthCredentials, BackendPlant, ConservatoryContext, PlantCreateInput, PlantView } from "./domain";
import { toPlantView } from "./domain";

export class ApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly recoverable = true) {
    super(message);
  }
}

export interface ConservatoryApi {
  authenticate(): Promise<void>;
  listPlants(): Promise<PlantView[]>;
  getPlant(plantId: string): Promise<PlantView>;
  addPlant(input: PlantCreateInput): Promise<PlantView>;
  resolveQr(identifier: string): Promise<PlantView>;
}

export class ExistingCalyxAdapter implements ConservatoryApi {
  constructor(
    private readonly baseUrl: string,
    private readonly credentials: AuthCredentials,
    private readonly context: ConservatoryContext,
    private readonly request: typeof fetch = fetch,
  ) {}

  private headers(): HeadersInit {
    return {
      "Content-Type": "application/json",
      ...(this.credentials.kind === "api-key"
        ? { "X-API-Key": this.credentials.value }
        : { Authorization: `Bearer ${this.credentials.value}` }),
    };
  }

  private async response<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.request(`${this.baseUrl}${path}`, {
      ...init,
      credentials: "include",
      headers: { ...this.headers(), ...(init?.headers || {}) },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: response.statusText }));
      throw new ApiError(response.status, String(body.detail || "Backend request failed"), response.status < 500);
    }
    return response.json() as Promise<T>;
  }

  async authenticate(): Promise<void> {
    await this.response("/api/implementation-planning/health");
  }

  async listPlants(): Promise<PlantView[]> {
    await this.authenticate();
    const records = await this.response<BackendPlant[]>(`/judging/events/${encodeURIComponent(this.context.eventId)}/plants`);
    return records.map((record) => toPlantView(record));
  }

  async getPlant(plantId: string): Promise<PlantView> {
    await this.authenticate();
    return toPlantView(await this.response<BackendPlant>(`/judging/plants/${encodeURIComponent(plantId)}`));
  }

  async addPlant(input: PlantCreateInput): Promise<PlantView> {
    const existing = await this.listPlants();
    const duplicate = existing.find((plant) => plant.displayName.localeCompare(input.name.trim(), undefined, { sensitivity: "base" }) === 0);
    if (duplicate) throw new ApiError(409, `A plant named “${duplicate.displayName}” already exists in this collection.`);
    const record = await this.response<BackendPlant>(`/judging/events/${encodeURIComponent(this.context.eventId)}/plants`, {
      method: "POST",
      body: JSON.stringify({
        exhibitor_id: this.context.exhibitorId,
        category_id: this.context.categoryId,
        name: input.name.trim(),
        notes: input.notes?.trim() || null,
      }),
    });
    return toPlantView(record);
  }

  async resolveQr(identifier: string): Promise<PlantView> {
    const normalized = decodeQrIdentifier(identifier);
    return this.getPlant(normalized);
  }
}

export function decodeQrIdentifier(raw: string): string {
  const value = raw.trim();
  if (!value) throw new ApiError(422, "Enter or scan a QR identifier.");
  try {
    const url = new URL(value);
    const match = url.pathname.match(/\/plants\/([^/]+)$/);
    if (match) return decodeURIComponent(match[1]);
  } catch {
    // Plain backend identifiers are valid.
  }
  const prefixed = value.match(/^(?:calyx:plant:|plant:)(.+)$/i);
  return (prefixed?.[1] || value).trim();
}

export const missingBuild091Endpoints = Object.freeze([
  "/api/conservatory/collections",
  "/api/conservatory/collections/{collection_id}/plants",
  "/api/conservatory/plants/{plant_id}",
  "/api/conservatory/qr/resolve",
  "/api/conservatory/search",
]);
