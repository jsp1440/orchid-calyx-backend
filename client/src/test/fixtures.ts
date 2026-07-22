import type { PlantView } from "../domain";
import type { ConservatoryApi } from "../api";

export const orchid: PlantView = {id:"plant-1",displayName:"Cattleya labiata",acceptedScientificName:null,synonymStatus:"not-supplied",hybridNotation:null,authorship:null,uncertainIdentification:false,parentage:null,qrIdentifier:"calyx:plant:plant-1",photographs:[],notes:"North bench",location:null,collectionMetadata:{eventId:"event-1",exhibitorId:"owner-1",categoryId:"cat-1",createdAt:"2026-07-20T00:00:00Z"},provenance:[{source:"Calyx judging plant API",recordId:"plant-1",retrievedAt:"2026-07-21T00:00:00Z",statement:"Backend record"}],citations:[]};
export function fakeApi(overrides: Partial<ConservatoryApi> = {}): ConservatoryApi { return {authenticate:vi.fn().mockResolvedValue(undefined),listPlants:vi.fn().mockResolvedValue([orchid]),getPlant:vi.fn().mockResolvedValue(orchid),addPlant:vi.fn().mockResolvedValue(orchid),resolveQr:vi.fn().mockResolvedValue(orchid),...overrides}; }
