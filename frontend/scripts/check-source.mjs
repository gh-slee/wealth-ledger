import ts from "typescript";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "..");
const cjk =
  /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]/u;
let failures = 0,
  files = 0;
function walk(directory) {
  for (const item of readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, item.name);
    if (item.isDirectory()) walk(file);
    else if (/\.tsx?$/.test(file)) {
      files++;
      const source = readFileSync(file, "utf8");
      const ast = ts.createSourceFile(
        file,
        source,
        ts.ScriptTarget.Latest,
        true,
        file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
      );
      const comments = new Set();
      function visit(node) {
        if (ts.isIdentifier(node) && cjk.test(node.text)) {
          console.error(
            path.relative(root, file) +
              ": canonical identifiers must be English",
          );
          failures++;
        }
        for (const range of [
          ...(ts.getLeadingCommentRanges(source, node.pos) ?? []),
          ...(ts.getTrailingCommentRanges(source, node.end) ?? []),
        ]) {
          if (
            !comments.has(range.pos) &&
            cjk.test(source.slice(range.pos, range.end))
          ) {
            console.error(
              path.relative(root, file) +
                ": canonical comments must be English",
            );
            failures++;
          }
          comments.add(range.pos);
        }
        ts.forEachChild(node, visit);
      }
      visit(ast);
    }
  }
}
walk(path.join(root, "src"));
walk(path.join(root, "tests"));
console.log(
  JSON.stringify({
    files,
    violations: failures,
    scope:
      "TypeScript comments and identifiers; intentional localized string values excluded",
  }),
);
process.exitCode = failures ? 1 : 0;
