// OpenCode plugin: adds the skills of every ai-toolkit plugin that supports OpenCode to
// `skills.paths`. The list is `pi.skills` in package.json, since Pi and OpenCode both load
// plain skills and nothing else from this repository.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function skillDirs() {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  return (manifest.pi?.skills ?? []).map((dir) => path.resolve(root, dir));
}

async function AiToolkitPlugin() {
  return {
    async config(config) {
      // OpenCode 2 replaced `skills.paths` with a list; leave that shape alone.
      if (Array.isArray(config.skills)) return;
      config.skills ??= {};
      config.skills.paths ??= [];
      for (const dir of skillDirs()) {
        if (!config.skills.paths.includes(dir)) config.skills.paths.push(dir);
      }
    },
  };
}

export default { id: "ai-toolkit", server: AiToolkitPlugin };
