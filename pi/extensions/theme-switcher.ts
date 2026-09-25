import { readFileSync, watch, type FSWatcher } from "node:fs";
import { homedir } from "node:os";
import { dirname, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TRIGGER_FILE = resolve(
	homedir(),
	".local/share/theme-monitor/theme-change.trigger",
);
const THEME_BY_MODE = {
	dark: "catppuccin-macchiato",
	light: "catppuccin-latte",
} as const;

type ThemeMode = keyof typeof THEME_BY_MODE;

function readThemeMode(): ThemeMode {
	try {
		return readFileSync(TRIGGER_FILE, "utf8").trim() === "light"
			? "light"
			: "dark";
	} catch {
		return "dark";
	}
}

export default function (pi: ExtensionAPI) {
	let watcher: FSWatcher | undefined;
	let poller: NodeJS.Timeout | undefined;
	let debounce: NodeJS.Timeout | undefined;
	let activeMode: ThemeMode | undefined;
	let sessionId = 0;

	pi.on("session_start", (_event, ctx) => {
		const thisSession = ++sessionId;

		const applyTheme = () => {
			if (thisSession !== sessionId) return;
			try {
				const mode = readThemeMode();
				if (mode === activeMode) return;

				const result = ctx.ui.setTheme(THEME_BY_MODE[mode]);
				if (result.success) {
					activeMode = mode;
					ctx.ui.notify(`Theme: ${THEME_BY_MODE[mode]}`, "info");
				}
			} catch {
				// The context becomes stale during /reload and session replacement.
			}
		};

		const scheduleApply = () => {
			if (debounce) clearTimeout(debounce);
			debounce = setTimeout(() => {
				debounce = undefined;
				applyTheme();
			}, 50);
		};

		applyTheme();

		try {
			watcher = watch(dirname(TRIGGER_FILE), (_eventType, filename) => {
				if (!filename || filename.toString() === "theme-change.trigger")
					scheduleApply();
			});
		} catch {
			// Polling below keeps this working if the directory watcher is unavailable.
		}

		// The theme monitor may replace the trigger file, which some watcher
		// implementations report as a rename. Polling makes replacement reliable.
		poller = setInterval(applyTheme, 1000);
	});

	pi.on("session_shutdown", () => {
		sessionId++;
		watcher?.close();
		watcher = undefined;
		if (poller) clearInterval(poller);
		poller = undefined;
		if (debounce) clearTimeout(debounce);
		debounce = undefined;
	});
}
