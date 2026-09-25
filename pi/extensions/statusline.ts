import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, relative, resolve } from "node:path";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import type {
	ExtensionAPI,
	ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";

type FooterFactory = Parameters<
	NonNullable<ExtensionContext["ui"]["setFooter"]>
>[0];

type GitInfo = {
	repo: string;
	branch: string;
	rel: string;
	added: number;
	deleted: number;
};

const ICON = {
	model: "",
	bolt: "",
	db: "",
	clock: "󱎫",
	dollar: "",
	calendar: "󱨲",
	git: "",
	branch: "",
	style: "󱔏",
};

const SEP = "  ·  ";
const RESET = "\x1b[0m";
const BOLD = "\x1b[1m";

type Palette = {
	lavender: string;
	sky: string;
	mint: string;
	gold: string;
	coral: string;
	rose: string;
	silver: string;
	muted: string;
	barOk: string;
	barWarn: string;
	barCrit: string;
	effortLow: string;
	effortMax: string;
};

function rgb(red: number, green: number, blue: number): string {
	return `\x1b[38;2;${red};${green};${blue}m`;
}

const DARK: Palette = {
	lavender: rgb(186, 187, 241),
	sky: rgb(153, 209, 219),
	mint: rgb(166, 209, 137),
	gold: rgb(229, 200, 144),
	coral: rgb(239, 159, 118),
	rose: rgb(234, 153, 156),
	silver: rgb(165, 173, 206),
	muted: rgb(115, 121, 148),
	barOk: rgb(129, 200, 190),
	barWarn: rgb(229, 200, 144),
	barCrit: rgb(231, 130, 132),
	effortLow: rgb(133, 193, 220),
	effortMax: rgb(231, 130, 132),
};

const LIGHT: Palette = {
	lavender: rgb(114, 135, 253),
	sky: rgb(4, 165, 229),
	mint: rgb(64, 160, 43),
	gold: rgb(223, 142, 29),
	coral: rgb(254, 100, 11),
	rose: rgb(230, 69, 83),
	silver: rgb(108, 111, 133),
	muted: rgb(140, 143, 161),
	barOk: rgb(23, 146, 153),
	barWarn: rgb(223, 142, 29),
	barCrit: rgb(210, 15, 57),
	effortLow: rgb(32, 159, 181),
	effortMax: rgb(210, 15, 57),
};

function palette(): Palette {
	try {
		return readFileSync(
			resolve(homedir(), ".local/share/theme-monitor/theme-change.trigger"),
			"utf8",
		).trim() === "light"
			? LIGHT
			: DARK;
	} catch {
		return DARK;
	}
}

function tildify(path: string): string {
	const home = homedir();
	return path === home || path.startsWith(`${home}/`)
		? `~${path.slice(home.length)}`
		: path;
}

function paint(color: string, text: string, bold = false): string {
	return `${bold ? BOLD : ""}${color}${text}${RESET}`;
}

function command(cwd: string, args: string[]): string {
	try {
		return execFileSync("git", args, {
			cwd,
			encoding: "utf8",
			stdio: ["ignore", "pipe", "ignore"],
			timeout: 500,
		}).trim();
	} catch {
		return "";
	}
}

function gitInfo(cwd: string): GitInfo | undefined {
	const root = command(cwd, ["rev-parse", "--show-toplevel"]);
	if (!root) return undefined;

	const stat = command(cwd, ["diff", "--shortstat", "HEAD"]);
	const added = Number(stat.match(/(\d+) insertion/)?.[1] ?? 0);
	const deleted = Number(stat.match(/(\d+) deletion/)?.[1] ?? 0);
	const untracked = command(cwd, [
		"ls-files",
		"--others",
		"--exclude-standard",
	]);
	let untrackedLines = 0;
	for (const file of untracked.split("\n").filter(Boolean)) {
		try {
			untrackedLines +=
				readFileSync(resolve(root, file), "utf8").split("\n").length - 1;
		} catch {
			// The file may disappear while the footer is rendering.
		}
	}

	const rel = relative(root, cwd);
	return {
		repo: basename(root),
		branch:
			command(cwd, ["branch", "--show-current"]) ||
			command(cwd, ["rev-parse", "--short", "HEAD"]),
		rel: rel === "." ? "" : rel,
		added: added + untrackedLines,
		deleted,
	};
}

function formatTokens(value: number): string {
	if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
	if (value >= 1_000) return `${Math.round(value / 1_000)}k`;
	return String(value);
}

function formatCost(value: number): string {
	if (value < 0.001) return "$0";
	if (value < 1) return `$${value.toFixed(3)}`;
	return `$${value.toFixed(2)}`;
}

function effort(level: string): string {
	return (
		(
			{
				low: "▁ low",
				medium: "▂ med",
				high: "▃ high",
				xhigh: "▅ xhigh",
				max: "█ max",
			} as Record<string, string>
		)[level] ?? level
	);
}

function effortColor(level: string, colors: Palette): string {
	return (
		(
			{
				low: colors.effortLow,
				medium: colors.gold,
				high: colors.coral,
				xhigh: colors.rose,
				max: colors.effortMax,
			} as Record<string, string>
		)[level] ?? colors.silver
	);
}

function usage(ctx: ExtensionContext) {
	const value = ctx.getContextUsage();
	const percent = value?.percent ?? 0;
	const window = value?.contextWindow ?? ctx.model?.contextWindow ?? 0;
	return {
		percent,
		window,
		tokens: value?.tokens ?? Math.round((percent / 100) * window),
	};
}

function sessionTotals(ctx: ExtensionContext) {
	let input = 0;
	let output = 0;
	let cost = 0;
	for (const entry of ctx.sessionManager.getBranch()) {
		if (entry.type !== "message" || entry.message.role !== "assistant")
			continue;
		const message = entry.message as AssistantMessage;
		input += message.usage.input;
		output += message.usage.output;
		cost += message.usage.cost.total;
	}
	return { input, output, cost };
}

export default function (pi: ExtensionAPI) {
	let startupTimer: NodeJS.Timeout | undefined;
	let installTimer: NodeJS.Timeout | undefined;

	pi.on("session_start", (_event, ctx) => {
		let tui: { requestRender(): void } | undefined;

		const footer: FooterFactory = (_tui, theme, footerData) => {
			tui = _tui;
			const unsubscribe = footerData.onBranchChange(() => tui?.requestRender());

			return {
				dispose: unsubscribe,
				invalidate() {},
				render(width: number): string[] {
					const colors = palette();
					const separator = `  ${colors.muted}·${RESET}  `;
					const cwd = ctx.cwd;
					const git = gitInfo(cwd);
					const line1Parts: string[] = [];
					if (git) {
						let repoPart = paint(
							colors.lavender,
							`${ICON.git} ${git.repo}`,
							true,
						);
						if (git.rel) repoPart += paint(colors.muted, `/${git.rel}`);
						line1Parts.push(repoPart);
						if (git.branch)
							line1Parts.push(
								paint(colors.gold, `${ICON.branch} ${git.branch}`),
							);
						if (git.added) line1Parts.push(paint(colors.mint, `+${git.added}`));
						if (git.deleted)
							line1Parts.push(paint(colors.barCrit, `-${git.deleted}`));
					} else {
						line1Parts.push(
							paint(colors.silver, tildify(cwd)),
						);
					}

					const model = ctx.model?.id ?? "no-model";
					const level = ctx.thinkingLevel ?? "off";
					const context = usage(ctx);
					let bar = "○";
					let contextColor: "success" | "warning" | "error" = "success";
					if (context.percent >= 85) {
						bar = "●";
						contextColor = "error";
					} else if (context.percent >= 60) {
						bar = "◕";
						contextColor = "warning";
					}
					let contextBarColor = colors.barOk;
					if (contextColor === "warning") contextBarColor = colors.barWarn;
					if (contextColor === "error") contextBarColor = colors.barCrit;
					const contextTotal =
						context.tokens == null
							? `?/${formatTokens(context.window)}`
							: `(${formatTokens(context.tokens)}/${formatTokens(context.window)})`;
					const contextPart =
						paint(contextBarColor, `${ICON.db} ${bar} `) +
						paint(contextBarColor, `${context.percent.toFixed(0)}%`, true) +
						`  ${colors.muted}${contextTotal}${RESET}`;
					const line2Parts = [
						paint(colors.lavender, `${ICON.model} ${model}`, true),
						level !== "off"
							? paint(
									effortColor(level, colors),
									`${ICON.bolt} ${effort(level)}`,
									true,
								)
							: "",
						contextPart,
					].filter(Boolean);

					const totals = sessionTotals(ctx);
					const line3Parts = [
						paint(
							colors.sky,
							`${ICON.clock} ${formatTokens(totals.input)}↑ ${formatTokens(totals.output)}↓`,
						),
						paint(colors.mint, `${ICON.dollar} ${formatCost(totals.cost)}`),
						paint(colors.sky, `${ICON.calendar} session`),
					];

					const lines = [
						line1Parts.join(separator),
						line2Parts.join(separator),
						line3Parts.join(separator),
					];
					return lines.map((line) => truncateToWidth(line, width, ""));
				},
			};
		};

		const installFooter = () => {
			try {
				ctx.ui.setFooter(footer);
				tui?.requestRender();
			} catch {
				// Pi invalidates the old context during /reload or session replacement.
			}
		};

		// pi-claude-code-tui restores Pi's default footer from its session_start
		// handler. Install ours both immediately and after startup handlers finish.
		installFooter();
		if (startupTimer) clearInterval(startupTimer);
		startupTimer = setInterval(installFooter, 250);
		installTimer = setTimeout(() => {
			if (startupTimer) clearInterval(startupTimer);
			startupTimer = undefined;
		}, 10_000);

		pi.registerCommand("statusline", {
			description: "Install the custom statusline footer",
			handler: async (_args, commandCtx) => {
				commandCtx.ui.setFooter(footer);
				tui?.requestRender();
				commandCtx.ui.notify("Custom statusline enabled", "info");
			},
		});

		const refresh = () => {
			installFooter();
			tui?.requestRender();
		};
		pi.on("message_update", refresh);
		pi.on("message_end", refresh);
		pi.on("model_select", refresh);
		pi.on("thinking_level_select", refresh);
		pi.on("turn_end", refresh);
		pi.on("agent_start", refresh);
	});

	pi.on("session_shutdown", () => {
		if (startupTimer) clearInterval(startupTimer);
		if (installTimer) clearTimeout(installTimer);
		startupTimer = undefined;
		installTimer = undefined;
	});
}
