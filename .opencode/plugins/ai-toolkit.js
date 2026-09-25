// OpenCode plugin: registers the skills of every ai-toolkit plugin that supports OpenCode.
// The list is `pi.skills` in package.json, since Pi and OpenCode both load plain skills and
// nothing else from this repository.
//
// OpenCode 1 calls `server` and reads the skill directories from `skills.paths` in its
// config. OpenCode 2 calls `setup`, whose skill domain takes one skill at a time.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function skillDirs() {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  return (manifest.pi?.skills ?? []).map((dir) => path.resolve(root, dir));
}

// Frontmatter here is single-line `key: value` pairs; the repository's tests hold every
// portable skill to that.
function readSkill(file) {
  const match = fs
    .readFileSync(file, "utf8")
    .match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) return undefined;
  const fields = {};
  for (const line of match[1].split(/\r?\n/)) {
    const field = line.match(/^([\w-]+):\s*(.*)$/);
    if (field) fields[field[1]] = field[2].trim();
  }
  const id = path.basename(path.dirname(file));
  return {
    id,
    name: fields.name || id,
    ...(fields.description ? { description: fields.description } : {}),
    path: file,
    content: match[2],
  };
}

function skills() {
  return skillDirs().flatMap((dir) =>
    fs.existsSync(dir)
      ? fs
          .readdirSync(dir, { withFileTypes: true })
          .filter((entry) => entry.isDirectory())
          .map((entry) => path.join(dir, entry.name, "SKILL.md"))
          .filter((file) => fs.existsSync(file))
          .map(readSkill)
          .filter(Boolean)
      : [],
  );
}

async function server() {
  return {
    async config(config) {
      if (Array.isArray(config.skills)) return;
      config.skills ??= {};
      config.skills.paths ??= [];
      for (const dir of skillDirs()) {
        if (!config.skills.paths.includes(dir)) config.skills.paths.push(dir);
      }
    },
  };
}

async function setup(ctx) {
  // OpenCode 1 (1.18.32) never calls this, but a host without a skill domain must not break it.
  if (typeof ctx?.skill?.transform !== "function") return;
  await ctx.skill.transform((editor) => {
    // A throw escaping the editor disables the whole plugin, so a rejected skill only
    // skips itself.
    for (const skill of skills()) {
      try {
        editor.add(skill);
      } catch (error) {
        console.error(`[ai-toolkit] OpenCode rejected skill ${skill.id}:`, error);
      }
    }
  });
}

export default { id: "ai-toolkit", server, setup };
