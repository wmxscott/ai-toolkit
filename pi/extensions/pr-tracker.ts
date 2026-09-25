// Pi's side of the pr-tracker plugin (plugins/pr-tracker): the hooks Claude Code and Codex
// run from hooks/hooks.json, as Pi events. Each one pipes a Claude-shaped payload to
// `pr-tracker hook <mode> --agent pi`, which records PRs and returns queued events.
import { spawn } from "node:child_process";
import { accessSync, constants } from "node:fs";
import { homedir } from "node:os";
import { delimiter, join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TIMEOUT_MS = 10_000;

type HookOutput = {
	systemMessage?: unknown;
	hookSpecificOutput?: { additionalContext?: unknown };
};

// Pi started from a GUI app may have a PATH without Homebrew on it.
// PR_TRACKER_HOOK_FALLBACK_PATH replaces these locations, for tests.
function searchPath(): string[] {
	const fallback =
		process.env.PR_TRACKER_HOOK_FALLBACK_PATH ??
		[
			"/opt/homebrew/bin",
			"/usr/local/bin",
			"/home/linuxbrew/.linuxbrew/bin",
			join(homedir(), ".local/bin"),
		].join(delimiter);
	return [process.env.PATH ?? "", fallback]
		.join(delimiter)
		.split(delimiter)
		.filter(Boolean);
}

function findCli(): string | null {
	for (const dir of searchPath()) {
		const path = join(dir, "pr-tracker");
		try {
			accessSync(path, constants.X_OK);
			return path;
		} catch {}
	}
	return null;
}

function runHook(
	cli: string,
	mode: "post-bash" | "stop",
	payload: object,
): Promise<HookOutput | undefined> {
	return new Promise((resolve) => {
		let stdout = "";
		try {
			const child = spawn(cli, ["hook", mode, "--agent", "pi"], {
				stdio: ["pipe", "pipe", "ignore"],
				timeout: TIMEOUT_MS,
			});
			child.on("error", () => resolve(undefined));
			child.stdout.setEncoding("utf8");
			child.stdout.on("data", (chunk: string) => {
				stdout += chunk;
			});
			child.on("close", () => {
				try {
					resolve(stdout.trim() ? JSON.parse(stdout) : undefined);
				} catch {
					resolve(undefined);
				}
			});
			child.stdin.on("error", () => {});
			child.stdin.end(JSON.stringify(payload));
		} catch {
			resolve(undefined);
		}
	});
}

function text(content: readonly { type: string; text?: string }[]): string {
	return content
		.map((part) => (part.type === "text" ? (part.text ?? "") : ""))
		.join("");
}

export default function (pi: ExtensionAPI) {
	// Looked up once per session: a missing CLI then costs nothing per call.
	let cli: string | null | undefined;
	const lookup = () => (cli === undefined ? (cli = findCli()) : cli);

	pi.on("session_start", () => {
		cli = undefined;
	});

	pi.on("tool_result", async (event, ctx) => {
		try {
			if (event.toolName !== "bash") return;
			const path = lookup();
			if (!path) return;
			const output = await runHook(path, "post-bash", {
				session_id: ctx.sessionManager.getSessionId(),
				cwd: ctx.cwd,
				hook_event_name: "PostToolUse",
				tool_name: "Bash",
				tool_input: { command: String(event.input.command ?? "") },
				tool_response: text(event.content),
			});
			const context = output?.hookSpecificOutput?.additionalContext;
			if (typeof context !== "string" || !context) return;
			return {
				content: [...event.content, { type: "text", text: `\n\n${context}` }],
			};
		} catch {
			return;
		}
	});

	pi.on("agent_settled", async (_event, ctx) => {
		try {
			const path = lookup();
			if (!path) return;
			const output = await runHook(path, "stop", {
				session_id: ctx.sessionManager.getSessionId(),
				cwd: ctx.cwd,
				hook_event_name: "Stop",
			});
			const message = output?.systemMessage;
			if (typeof message === "string" && message) ctx.ui.notify(message, "info");
		} catch {}
	});
}
