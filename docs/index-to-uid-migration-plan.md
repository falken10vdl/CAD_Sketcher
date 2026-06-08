# Index-to-UID Migration Plan (Design Proposal)

While investigating [issue #544](https://github.com/hlorus/CAD_Sketcher/issues/544) it was found that drivers currently bind to collection-index RNA paths (for example `...constraints.distance[2].value` or entity list item paths). Any operation that changes collection ordering can break or silently rebind drivers to the wrong logical item.

## Proposal
1. Add and persist stable IDs for all driver-relevant items.
   - Constraints: `constraint_uid` (new field to be added).
   - Entities: `entity_uid` (new field to be added).
2. Expose stable scene-level driver endpoints keyed by UID.
3. Bind UI driverable fields to UID endpoints (not collection indices).
4. Sync UID endpoint values into runtime properties before solve/update.
5. Keep migration for a compatibility window, then retire old migration code.

## Data Model
- Each constraint and entity carries a stable string UID field (`constraint_uid`, `entity_uid`), stored as a `StringProperty` on the item itself.
- Driverable values are exposed via a dedicated `PropertyGroup` nested on `Scene.sketcher`:
  - Constraints: `scene.sketcher.constraint_values[uid].value`
  - Entities: `scene.sketcher.entity_values[uid].co` (or other driverable props such as `.location`)
- Driver targets point to those paths directly.
- Identity fields are persistent, assigned at creation, and never derived from collection position.

## Benefits Beyond Driver Stability
- **Undo/redo correctness** — Blender restores PropertyGroup state by collection position. After undoing a delete, a constraint reappears at an index that may not match what operators expected. UIDs make post-undo lookups correct regardless of collection state.
- **Operator robustness** — Operators that resolve a constraint or entity by index at invoke time can find a different item (or nothing) by execute time if another operator ran between. UID-based resolution eliminates this race.
- **Copy/paste across scenes** — The current `fix_pointers` pass only remaps entity pointer fields. Constraints have no stable identity to carry across a paste. With UIDs, paste payloads carry identity and constraints can be matched to their logical counterparts.
- **Logging and debugging** — Index-based output like `"Delete: distance[2]"` is ambiguous after any reorder. UID-based output is unambiguous and traceable across the full item lifecycle.
- **Testing** — Test assertions that rely on collection indices are fragile and break on any internal reorder. UID-based assertions survive across test steps.
- **Future extensibility** — Stable UIDs are a prerequisite for external references from scripting APIs, BCF integration, or collaboration features where tools outside Blender need to refer to specific items reliably.

## Migration Strategy
### Phase 1: Introduce Migration
- On load/versioning, if UID fields are missing:
  - Generate deterministic persistent UIDs for constraints/entities.
  - Seed UID-backed driver values from current property values.
- Stamp file/addon schema version after successful migration.

### Phase 2: Compatibility Window
- Keep migration active for `N` releases.
- Emit clear warnings for legacy schema during migration?

### Phase 3: Deprecation
- Define minimum supported schema version.
- If file is older than the floor, fail with actionable message.
- Remove obsolete migration branches/code.

Cheers!
