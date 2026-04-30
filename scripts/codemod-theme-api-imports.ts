#!/usr/bin/env -S npx --yes tsx
/**
 * Sprint 4 codemod: rewrite theme-component imports off the deep
 * relative path `../../../../tools/remotion/src/{effects.types,lib/animations,ThemeContext}`
 * onto the new stable sub-path `@banodoco/timeline-composition/theme-api`.
 *
 * Idempotent: re-running on already-migrated files is a no-op.
 *
 * Scope: walks `themes/<id>/` for any `.ts`/`.tsx` file. Only `themes/2rp/`
 * and `themes/arca-gidan/` exist today (verified pre-sprint); the script
 * is generic so future themes pick it up automatically.
 *
 * Run from anywhere — paths are resolved against the workspace root,
 * computed by walking up from this file.
 *
 *   npx tsx tools/scripts/codemod-theme-api-imports.ts
 */

import {readdirSync, readFileSync, writeFileSync, statSync} from "node:fs";
import {dirname, join, resolve} from "node:path";
import {fileURLToPath} from "node:url";

// __dirname for ESM
const __dirname_ = dirname(fileURLToPath(import.meta.url));
// tools/scripts/ → workspace root is two parents up
const WORKSPACE_ROOT = resolve(__dirname_, "..", "..");
const THEMES_DIR = join(WORKSPACE_ROOT, "themes");
const TARGET_PACKAGE = "@banodoco/timeline-composition/theme-api";

// Source modules we re-export under theme-api. The codemod merges
// imports from these source modules into a single
// `@banodoco/timeline-composition/theme-api` import per file.
const SOURCE_MODULES = new Set([
  "effects.types",
  "lib/animations",
  "ThemeContext",
]);

type ImportClause = {
  isTypeOnly: boolean;
  named: Array<{name: string; alias?: string; isTypeOnly: boolean}>;
  defaultName?: string;
  namespaceName?: string;
};

function listFiles(dir: string): string[] {
  const out: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const entry of entries) {
    if (entry.startsWith(".")) continue;
    if (entry === "node_modules") continue;
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      out.push(...listFiles(full));
    } else if (stat.isFile() && (entry.endsWith(".ts") || entry.endsWith(".tsx"))) {
      out.push(full);
    }
  }
  return out;
}

/** Match `from '..../tools/remotion/src/<module>'` capture the module slug. */
const SOURCE_REGEX = /(from\s+['"])((?:\.\.\/)+)tools\/remotion\/src\/(effects\.types|lib\/animations|ThemeContext)(['"])/g;

function parseImportClause(clauseText: string): ImportClause | null {
  // clauseText is everything between `import` and `from`, trimmed.
  // Forms:
  //   * "X"  (default)
  //   * "X, { a, b }"
  //   * "{ a, b }"
  //   * "type { a, b }"
  //   * "* as Ns"
  // We support a pragmatic subset; complex shapes fall back to no-op.
  const text = clauseText.trim();
  let isTypeOnly = false;
  let rest = text;
  if (rest.startsWith("type ")) {
    isTypeOnly = true;
    rest = rest.slice(5).trim();
  }
  if (rest.startsWith("* as ")) {
    return {isTypeOnly, named: [], namespaceName: rest.slice(5).trim()};
  }
  let defaultName: string | undefined;
  let namedSection = rest;
  if (!rest.startsWith("{")) {
    // default import (possibly followed by `, { named }`)
    const commaIdx = rest.indexOf(",");
    if (commaIdx === -1) {
      defaultName = rest.trim();
      namedSection = "";
    } else {
      defaultName = rest.slice(0, commaIdx).trim();
      namedSection = rest.slice(commaIdx + 1).trim();
    }
  }
  const named: ImportClause["named"] = [];
  if (namedSection.startsWith("{")) {
    const closeIdx = namedSection.lastIndexOf("}");
    if (closeIdx === -1) return null;
    const inner = namedSection.slice(1, closeIdx);
    for (const raw of inner.split(",")) {
      const segment = raw.trim();
      if (!segment) continue;
      let segIsType = false;
      let body = segment;
      if (body.startsWith("type ")) {
        segIsType = true;
        body = body.slice(5).trim();
      }
      const asMatch = /^(\S+)\s+as\s+(\S+)$/.exec(body);
      if (asMatch) {
        named.push({name: asMatch[1], alias: asMatch[2], isTypeOnly: segIsType});
      } else {
        named.push({name: body, isTypeOnly: segIsType});
      }
    }
  }
  return {isTypeOnly, named, defaultName};
}

function renderClause(clause: ImportClause): string {
  const parts: string[] = [];
  if (clause.namespaceName) {
    parts.push(`* as ${clause.namespaceName}`);
  } else {
    if (clause.defaultName) parts.push(clause.defaultName);
    if (clause.named.length > 0) {
      const inner = clause.named
        .map((n) => {
          const prefix = n.isTypeOnly ? "type " : "";
          return n.alias ? `${prefix}${n.name} as ${n.alias}` : `${prefix}${n.name}`;
        })
        .join(", ");
      parts.push(`{${inner}}`);
    }
  }
  const head = clause.isTypeOnly ? "import type " : "import ";
  return `${head}${parts.join(", ")} from '${TARGET_PACKAGE}'`;
}

function mergeClauses(clauses: ImportClause[]): ImportClause {
  // We intentionally do NOT split a merged clause into type-only +
  // value-only. We tag individual named imports with `isTypeOnly` and
  // emit a single non-type-only import whose named entries carry the
  // `type` keyword where needed. That shape is the canonical one used
  // throughout the existing themes/ codebase.
  const merged: ImportClause = {isTypeOnly: false, named: []};
  const seen = new Set<string>();
  for (const c of clauses) {
    if (c.namespaceName) {
      // Conservative: bail out — merged form can't represent multiple namespaces.
      throw new Error("namespace import cannot be merged");
    }
    if (c.defaultName) {
      if (merged.defaultName && merged.defaultName !== c.defaultName) {
        throw new Error("conflicting default imports");
      }
      merged.defaultName = c.defaultName;
    }
    for (const n of c.named) {
      const key = `${n.name}::${n.alias ?? ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      merged.named.push({...n, isTypeOnly: n.isTypeOnly || c.isTypeOnly});
    }
  }
  return merged;
}

type ImportMatch = {
  fullStatement: string;
  clauseText: string;
  start: number;
  end: number;
};

function findImports(text: string): ImportMatch[] {
  const out: ImportMatch[] = [];
  // Match a single import statement against the deep relative path. We
  // anchor on the start-of-line + `import` keyword and forbid `;` inside
  // the clause portion so the non-greedy quantifier can't span multiple
  // statements. Multiline flag enables `^` per line.
  const re = /^\s*import\s+([^;]*?)\s+from\s+['"]((?:\.\.\/)+tools\/remotion\/src\/(?:effects\.types|lib\/animations|ThemeContext))['"];?\s*$/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    out.push({
      fullStatement: m[0],
      clauseText: m[1],
      start: m.index,
      end: m.index + m[0].length,
    });
  }
  return out;
}

function migrate(text: string): {next: string; changed: boolean} {
  const imports = findImports(text);
  if (imports.length === 0) return {next: text, changed: false};

  const clauses: ImportClause[] = [];
  for (const imp of imports) {
    const parsed = parseImportClause(imp.clauseText);
    if (!parsed) {
      console.warn(`  warn: could not parse clause "${imp.clauseText.slice(0, 60)}…", skipping file`);
      return {next: text, changed: false};
    }
    clauses.push(parsed);
  }

  let merged: ImportClause;
  try {
    merged = mergeClauses(clauses);
  } catch (err) {
    console.warn(`  warn: cannot merge imports (${(err as Error).message}), skipping file`);
    return {next: text, changed: false};
  }

  // Build the replacement: insert the merged import at the position of
  // the first match; remove all match ranges (in reverse).
  const sorted = [...imports].sort((a, b) => b.start - a.start);
  let next = text;
  for (const imp of sorted) {
    next = next.slice(0, imp.start) + next.slice(imp.end);
  }
  const insertion = renderClause(merged) + ";";
  // Re-find first import position from original text — after deletes, the
  // first match's `start` remains valid because we deleted in reverse.
  const firstStart = imports[0].start;
  next = next.slice(0, firstStart) + insertion + next.slice(firstStart);

  return {next, changed: next !== text};
}

function isAlreadyMigrated(text: string): boolean {
  return text.includes(`from '${TARGET_PACKAGE}'`) || text.includes(`from "${TARGET_PACKAGE}"`);
}

function main(): void {
  console.log(`Codemod: theme-api imports → ${TARGET_PACKAGE}`);
  console.log(`Workspace root: ${WORKSPACE_ROOT}`);
  console.log(`Themes dir: ${THEMES_DIR}`);
  const files = listFiles(THEMES_DIR);
  console.log(`Discovered ${files.length} TypeScript file(s) under themes/.`);

  let migrated = 0;
  let alreadyDone = 0;
  let unchanged = 0;

  for (const file of files) {
    const text = readFileSync(file, "utf8");
    const had = SOURCE_REGEX.test(text);
    SOURCE_REGEX.lastIndex = 0;
    if (!had) {
      if (isAlreadyMigrated(text)) {
        alreadyDone += 1;
      } else {
        unchanged += 1;
      }
      continue;
    }
    const {next, changed} = migrate(text);
    if (!changed) {
      unchanged += 1;
      continue;
    }
    writeFileSync(file, next, "utf8");
    migrated += 1;
    console.log(`  rewrote: ${file.replace(WORKSPACE_ROOT + "/", "")}`);
  }

  console.log("");
  console.log(`Summary:`);
  console.log(`  migrated:        ${migrated}`);
  console.log(`  already migrated: ${alreadyDone}`);
  console.log(`  unchanged:       ${unchanged}`);

  // Idempotency assertion: re-scan and fail loudly if any deep relative
  // import survived in the search list.
  const remaining: string[] = [];
  for (const file of listFiles(THEMES_DIR)) {
    const text = readFileSync(file, "utf8");
    if (SOURCE_REGEX.test(text)) {
      remaining.push(file);
    }
    SOURCE_REGEX.lastIndex = 0;
  }
  if (remaining.length > 0) {
    console.error("");
    console.error(`✗ Migration incomplete — files still importing the old path:`);
    for (const r of remaining) console.error(`  ${r}`);
    process.exit(1);
  }
  console.log(`✓ No deep relative ../../../../tools/remotion/src/{effects.types,lib/animations,ThemeContext} imports remain in themes/.`);
}

main();
