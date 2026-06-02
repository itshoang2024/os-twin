# Domain Pack Authoring Rules

Domain packs are installable ontology modules that extend a namespace profile without mutating core semantics. A pack manifest must include `pack_id`, `name`, `version`, `compatible_profile_versions`, `concept_types`, `relationship_types`, `aliases`, `metadata_fields`, `validation_rules`, `fixtures`, and `migration_notes`.

## Compatibility

- Set `compatible_profile_versions` to exact profile versions or major wildcards such as `1.x`.
- Packs are validated before installation; conflicts are returned as structured ontology issues and nothing is saved when an error is present.
- A pack must not redefine existing relationship, concept, metadata, alias, or validation-rule definitions unless the definition is identical.
- Core system relationship types such as default `enables` cannot be changed by packs. Create a new relationship type or alias instead.

## Uninstall behavior

Uninstall marks the pack lifecycle record as `disabled` and removes pack-owned additions from the active profile. Additions remain active when another installed pack still defines or depends on them. Core profile relationships, aliases, and metadata are preserved.

## Built-in seed packs

The backend ships deterministic seed manifests for `financial-services`, `technology-saas`, `retail-consumer`, `public-sector`, and `esg` under `knowledge/ontology/packs/defaults/`.

## API workflow

1. `GET /api/knowledge/ontology/packs` lists installable manifests.
2. `POST /api/knowledge/namespaces/{namespace}/ontology/packs/validate` previews compatibility and merged profile.
3. `POST /api/knowledge/namespaces/{namespace}/ontology/packs/install` installs or upgrades the pack and records namespace state.
4. `GET /api/knowledge/namespaces/{namespace}/ontology/packs` lists installed/disabled lifecycle records.
5. `POST /api/knowledge/namespaces/{namespace}/ontology/packs/uninstall` disables the pack and safely removes pack-owned additions.
