// Pi's side of switchboard (https://github.com/wmxscott/switchboard): forwards Pi's lifecycle
// events to `switchboard hook --agent pi <event>`, with `{"event": ..., ...fields}` on stdin.
// The CLI decides what each one means for the tmux pane.
import { spawn } from "node:child_process";
import { accessSync, constants } from "node:fs";
import { homedir } from "node:os";
import { delimiter, join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TIMEOUT_MS = 5_000;
const DRAIN_MS = 1_000;
const MAX_QUEUED = 64;
const PLANNOTATOR: [string, string][] = [
	["plannotator:session-opened", "plannotator_opened"],
	["plannotator:session-closed", "plannotator_closed"],
];

type Queue = { tail: Promise<void>; size: number };

// One queue per process, not per extension instance, so calls stay in order across /reload.
const QUEUE = Symbol.for("ai-toolkit:switchboard:queue");
const store = globalThis as typeof globalThis & { [QUEUE]?: Queue };
const queue: Queue = (store[QUEUE] ??= { tail: Promise.resolve(), size: 0 });

// Pi started from a GUI app may have a PATH without Homebrew on it.
// SWITCHBOARD_HOOK_FALLBACK_PATH replaces these locations, for tests.
function searchPath(): string[] {
	const fallback =
		process.env.SWITCHBOARD_HOOK_FALLBACK_PATH ??
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
		const path = join(dir, "switchboard");
		try {
			accessSync(path, constants.X_OK);
			return path;
		} catch {}
	}
	return null;
}

// Resolves when the CLI has exited or failed to start, and never rejects.
function run(cli: string, event: string, input: string): Promise<void> {
	return new Promise((resolve) => {
		let done = false;
		const finish = () => {
			if (done) return;
			done = true;
			resolve();
		};
		try {
			// Detached, so Ctrl+C in the TUI doesn't reach it and it outlives Pi's exit.
			const child = spawn(cli, ["hook", "--agent", "pi", event], {
				stdio: ["pipe", "ignore", "ignore"],
				detached: true,
				timeout: TIMEOUT_MS,
				killSignal: "SIGKILL",
			});
			// Not `once`: a second "error", say from the timeout's kill, would throw unheard.
			child.on("error", finish);
			child.on("close", finish);
			child.stdin?.on("error", () => {});
			child.stdin?.end(input);
			child.unref();
		} catch {
			finish();
		}
	});
}

function send(cli: string, event: string, fields: object = {}) {
	if (queue.size >= MAX_QUEUED) return;
	const input = JSON.stringify({ event, ...fields });
	queue.size++;
	queue.tail = queue.tail
		.then(() => run(cli, event, input))
		.then(() => {
			queue.size--;
		});
}

function drain(): Promise<void> {
	return new Promise((resolve) => {
		const timer = setTimeout(resolve, DRAIN_MS);
		void queue.tail.then(() => {
			clearTimeout(timer);
			resolve();
		});
	});
}

export default function (pi: ExtensionAPI) {
	// Set at session_start, and only for a terminal UI in a tmux pane that isn't a
	// pi-subagents child, which inherits the parent's TMUX_PANE.
	let cli: string | null = null;

	pi.on("session_start", (event, ctx) => {
		try {
			cli = null;
			const env = process.env;
			if (!env.TMUX_PANE || env.PI_SUBAGENT_CHILD === "1" || ctx.mode !== "tui") return;
			cli = findCli();
			if (cli) send(cli, "session_start", { reason: event.reason, idle: ctx.isIdle() });
		} catch {}
	});

	pi.on("agent_start", () => {
		try {
			if (cli) send(cli, "agent_start");
		} catch {}
	});

	pi.on("ui_prompt_start", (event) => {
		try {
			if (cli) send(cli, "ui_prompt_start", { kind: event.kind });
		} catch {}
	});

	pi.on("ui_prompt_end", () => {
		try {
			if (cli) send(cli, "ui_prompt_end");
		} catch {}
	});

	for (const [channel, name] of PLANNOTATOR) {
		pi.events.on(channel, (data) => {
			try {
				const id = (data as { id?: unknown } | null)?.id;
				if (cli && typeof id === "string" && id) send(cli, name, { id });
			} catch {}
		});
	}

	pi.on("agent_settled", (event) => {
		try {
			if (cli) send(cli, "agent_settled", { aborted: event.aborted });
		} catch {}
	});

	pi.on("session_shutdown", (event) => {
		try {
			if (!cli) return;
			send(cli, "session_shutdown", { reason: event.reason });
			if (event.reason === "quit") return drain();
		} catch {}
	});
}
