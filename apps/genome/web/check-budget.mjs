// Frame budget in CI (interface-spec Rule 6.12): a second atlas, a stray
// heavyweight dependency or an accidental asset must FAIL the build, not
// degrade quietly. The gate is total JS shipped to the canvas.
import { readdirSync, statSync } from "fs";
const BUDGET_KB = 1400;
let total = 0;
for (const f of readdirSync("dist/assets")) {
  if (f.endsWith(".js")) total += statSync(`dist/assets/${f}`).size;
}
const kb = Math.round(total / 1024);
if (kb > BUDGET_KB) {
  console.error(`frame budget FAILED: ${kb}KB of JS > ${BUDGET_KB}KB`);
  process.exit(1);
}
console.log(`frame budget ok: ${kb}KB of JS <= ${BUDGET_KB}KB`);
