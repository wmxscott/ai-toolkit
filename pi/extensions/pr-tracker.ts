// Pi's side of the pr-tracker plugin (plugins/pr-tracker): the hooks Claude Code and Codex
// run from hooks/hooks.json, as Pi events. Each one pipes a Claude-shaped payload to
// `pr-tracker hook`, which records PRs and returns queued events.
import { spawn } from "node:child_process";
import { accessSync, constants } from "node:fs";
import { homedir } from "node:os";
import { delimiter, join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const TIMEOUT_MS = 10_000;
const POLL_MS = 30_000;
// As long as the plugin's `hook wait --for 3540`.
const WAIT_MS = 3_540_000;
const MESSAGE_TYPE = "pr-tracker";
const AS_PI = ["--agent", "pi"];
// `hook stop` hands events to the agent, rather than only showing them, for claude alone,
// and `hook wait` runs for no one else. Pi can continue a run and wake an idle one, so it
// asks `stop` as claude. Stop records nothing, so the session keeps its pi label.
const STOP = ["stop", "--agent", "claude"];

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

function runHook(cli: string, args: string[], payload: object): Promise<HookOutput | undefined> {
	return new Promise((resolve) => {
		let stdout = "";
		try {
			const child = spawn(cli, ["hook", ...args], {
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

function forAgent(output: HookOutput | undefined): string | undefined {
	const context = output?.hookSpecificOutput?.additionalContext;
	return typeof context === "string" && context ? context : undefined;
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
	let running = false;
	// Claude's stop_hook_active: this run already continued once for pr-tracker.
	let continued = false;
	// The run reached agent_before_settle as completed. An aborted run skips that event.
	let completed = false;
	let timer: ReturnType<typeof setTimeout> | undefined;
	let generation = 0;

	const session = (ctx: ExtensionContext) => ({
		session_id: ctx.sessionManager.getSessionId(),
		cwd: ctx.cwd,
	});

	const stopPolling = () => {
		generation++;
		clearTimeout(timer);
		timer = undefined;
	};

	// Claimed events are delivered even if a run has started since: into that run.
	const wake = (context: string) => {
		try {
			pi.sendMessage(
				{ customType: MESSAGE_TYPE, content: context, display: true },
				{ triggerTurn: !running },
			);
		} catch {}
	};

	// Claude Code's `hook wait`: after a run, wake the idle session for failing checks or a
	// review decision. Only in modes that stay open after a run.
	const poll = (ctx: ExtensionContext) => {
		stopPolling();
		const path = lookup();
		if (!path || (ctx.mode !== "tui" && ctx.mode !== "rpc")) return;
		const current = generation;
		const payload = { ...session(ctx), hook_event_name: "Stop" };
		const end = Date.now() + WAIT_MS;
		const tick = async () => {
			const context = forAgent(await runHook(path, STOP, payload));
			if (context) {
				if (current === generation) stopPolling();
				wake(context);
			} else if (current === generation && Date.now() < end) {
				schedule();
			}
		};
		const schedule = () => {
			timer = setTimeout(tick, POLL_MS);
			timer.unref?.();
		};
		schedule();
	};

	pi.on("session_start", () => {
		cli = undefined;
		running = continued = completed = false;
		stopPolling();
	});

	pi.on("session_shutdown", () => {
		stopPolling();
	});

	pi.on("before_agent_start", async (_event, ctx) => {
		running = true;
		stopPolling();
		try {
			const path = lookup();
			if (!path) return;
			const context = forAgent(
				await runHook(path, AS_PI, { ...session(ctx), hook_event_name: "UserPromptSubmit" }),
			);
			if (!context) return;
			return { message: { customType: MESSAGE_TYPE, content: context, display: true } };
		} catch {
			return;
		}
	});

	pi.on("agent_start", () => {
		running = true;
		completed = false;
		stopPolling();
	});

	pi.on("tool_result", async (event, ctx) => {
		try {
			const path = lookup();
			if (!path) return;
			const output = await runHook(path, AS_PI, {
				...session(ctx),
				hook_event_name: event.isError ? "PostToolUseFailure" : "PostToolUse",
				tool_name: event.toolName,
				tool_input: event.input,
				[event.isError ? "error" : "tool_response"]: text(event.content),
			});
			const context = forAgent(output);
			if (!context) return;
			return {
				content: [...event.content, { type: "text", text: `\n\n${context}` }],
			};
		} catch {
			return;
		}
	});

	pi.on("agent_before_settle", async (event, ctx) => {
		try {
			completed = event.outcome === "completed";
			const path = lookup();
			if (!path) return;
			const output = await runHook(path, STOP, {
				...session(ctx),
				hook_event_name: "Stop",
				stop_hook_active: continued || !completed,
			});
			const context = forAgent(output);
			if (context) {
				continued = true;
				return {
					entries: [
						...event.entries,
						{ type: "custom_message", customType: MESSAGE_TYPE, content: context, display: true },
					],
					continue: true,
				};
			}
			const message = output?.systemMessage;
			if (typeof message === "string" && message) ctx.ui.notify(message, "info");
		} catch {}
	});

	pi.on("agent_settled", (_event, ctx) => {
		const idle = completed;
		running = continued = completed = false;
		try {
			if (idle) poll(ctx);
		} catch {}
	});
}
