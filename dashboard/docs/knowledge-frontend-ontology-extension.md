# Frontend Ontology Extension Guide

The Knowledge UI is profile-driven. Avoid hardcoded TypeScript enums for ontology concepts, relationships, layers, abstraction levels, packs, or candidate states unless they are pure UI fallbacks.

## Runtime data sources

| Hook/component | Backend source | Use |
|---|---|---|
| `useOntologyProfile(namespace)` | `/api/knowledge/namespaces/{namespace}/ontology/profile` | Editable profile, concept labels, relation metadata, aliases, validation rules. |
| `useOntologyPacks(namespace)` | `/api/knowledge/ontology/packs` and `/api/knowledge/namespaces/{namespace}/ontology/packs` | Available and installed pack state. |
| `useOntologyCandidates(namespace, status)` | `/api/knowledge/namespaces/{namespace}/ontology/candidates` | Review queue and candidate state filters. |
| `useKnowledgeExplorer(namespace)` | `/api/knowledge/namespaces/{namespace}/explorer/*` | Nexus and Enterprise Map graph seed/expand/search/detail data. |
| `EnterpriseMapPanel` | Explorer + ontology hooks | Lane rendering, filters, relation styles, detail drawer, and fallback fixture view. |

## Adding a new ontology-driven UI control

1. Read choices from `profile.concept_types`, `profile.relationship_types`, `profile.layers`, `profile.abstraction_levels`, or installed pack state.
2. Preserve legacy namespaces by accepting `profile === null` and using empty/default UI state.
3. Include `data-testid` on controls that are part of QA release gates.
4. Treat candidate state as live review data, not a static frontend enum.
5. Use relation metadata (`family`, `style`, `inverse`, `weight`) to style edges rather than checking literal relation names.

## Enterprise Map extension points

- **Lane mode** supports layer, abstraction level, concept type, and pack grouping.
- **Filters** include pack ID, layer, abstraction level, concept type, relationship family, lifecycle state, owner, and candidate state.
- **Edge styles** are derived from ontology relationship metadata; new relationship types should render without component code changes.
- **Detail drawer** groups incoming/outgoing relationships and displays inverse labels, validation issues, metadata, and source citations.
- **Fallback data** exists only for empty/demo rendering. Do not make production behavior depend on fixture nodes.

## QA notes

Frontend regression should run against both a legacy namespace with no saved profile and a profile-enabled namespace. For manual QA, start the frontend from `fe/` with `bun run dev` and test at `http://localhost:3000`.
