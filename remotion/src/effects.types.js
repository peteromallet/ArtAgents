// Sprint 5 back-compat shim — the canonical types live in
// `@banodoco/timeline-composition/typescript/src/effects-types.ts` (also
// re-exported via `@banodoco/timeline-composition/theme-api`).
//
// Workspace primitives at `effects/`, `animations/`, `transitions/` still
// import from the deep relative path `../../tools/remotion/src/effects.types`.
// Migrating them is out-of-scope for Sprint 5 (those are workspace-shared,
// not theme-package content). This re-export keeps them resolving.
export * from '@banodoco/timeline-composition/theme-api';
