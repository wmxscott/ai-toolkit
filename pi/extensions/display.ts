/**
 * display: framed code blocks for Pi assistant responses.
 *
 * Adapted from pix-display by xynogen, specifically its code-block renderer:
 * https://github.com/xynogen/pix-mono/tree/main/packages/pix-display
 * Pi's native Markdown renderer still provides syntax highlighting; this
 * extension replaces the fence rows with a language-labeled frame.
 *
 * MIT License
 *
 * Copyright (c) 2026 xynogen
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
import {
	AssistantMessageComponent,
	type ExtensionAPI,
	type Theme,
} from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

const OPENING_FENCE_RE = /^```([^`]*)$/;
const CLOSING_FENCE_RE = /^```\s*$/;
const DEFAULT_LABEL = "code";
const ANSI_RE = /\x1b\[[0-?]*[ -/]*[@-~]/g;
const BACKGROUND_ANSI_RE = /\x1b\[(?:4[0-9]|48)(?:;[^m]*)?m/g;
const OSC_RE = /\x1b\][^\x07]*(?:\x07|\x1b\\)/g;
const PATCHED = Symbol.for("ai-toolkit:display:code-block-renderer");

type CodeFrameTheme = Pick<Theme, "bold" | "fg">;

type PatchablePrototype = {
	[PATCHED]?: boolean;
	render(width: number): string[];
};

let activeTheme: CodeFrameTheme | undefined;

function plainText(line: string): string {
	return line.replace(OSC_RE, "").replace(ANSI_RE, "");
}

function oscSequences(line: string): string {
	return line.match(OSC_RE)?.join("") ?? "";
}

function leadingSpaces(line: string): number {
	return plainText(line).match(/^ */)?.[0].length ?? 0;
}

function stripLayoutWhitespace(line: string, count: number): string {
	let remaining = count;
	return line
		.replace(OSC_RE, "")
		.replace(BACKGROUND_ANSI_RE, "")
		.replace(/^(?:\x1b\[[0-?]*[ -/]*[@-~]| )+/, (prefix) =>
			prefix.replace(/ /g, (space) => {
				if (remaining <= 0) return space;
				remaining--;
				return "";
			}),
		)
		.replace(/ +$/, "");
}

function fenceLabel(line: string): string | undefined {
	const match = plainText(line).trim().match(OPENING_FENCE_RE);
	if (!match) return undefined;
	const info = (match[1] ?? "").trim();
	return info.split(/\s+/, 1)[0] || DEFAULT_LABEL;
}

function topRule(
	width: number,
	language: string,
	theme: CodeFrameTheme,
): string {
	const available = Math.max(1, width - 4);
	const displayLanguage = truncateToWidth(language, available, "…");
	const label = theme.bold(theme.fg("accent", ` ${displayLanguage} `));
	const ruleWidth = Math.max(0, width - visibleWidth(label) - 2);
	return `${theme.fg("borderMuted", "──")}${label}${theme.fg("borderMuted", "─".repeat(ruleWidth))}`;
}

function bottomRule(width: number, theme: CodeFrameTheme): string {
	return theme.fg("borderMuted", "─".repeat(width));
}

function bodyLine(line: string, width: number, layoutIndent: number): string {
	return truncateToWidth(stripLayoutWhitespace(line, layoutIndent), width, "…");
}

/** Replace native Markdown fence rows with a themed code frame. */
export function renderCodeFences(
	lines: string[],
	width: number,
	theme: CodeFrameTheme,
): string[] {
	if (width < 12) return lines;

	const out = [...lines];
	for (let start = 0; start < out.length; start++) {
		const language = fenceLabel(out[start] ?? "");
		if (!language) continue;

		let end = start + 1;
		while (
			end < out.length &&
			!CLOSING_FENCE_RE.test(plainText(out[end] ?? "").trim())
		) {
			end++;
		}
		if (end >= out.length) continue;

		const body = out.slice(start + 1, end);
		const bodyIndents: number[] = [];
		for (const line of body) {
			const plain = plainText(line);
			if (plain.trim().length > 0) bodyIndents.push(leadingSpaces(line));
		}
		const bodyIndent = bodyIndents.length > 0 ? Math.min(...bodyIndents) : 0;
		const framed: string[] = [];

		framed.push(
			`${oscSequences(out[start] ?? "")}${topRule(width, language, theme)}`,
		);
		for (let index = start + 1; index < end; index++) {
			framed.push(
				`${oscSequences(out[index] ?? "")}${bodyLine(out[index] ?? "", width, bodyIndent)}`,
			);
		}
		framed.push(`${oscSequences(out[end] ?? "")}${bottomRule(width, theme)}`);

		out.splice(start, end - start + 1, ...framed);
		start += framed.length - 1;
	}
	return out;
}

function patchAssistantRenderer(): void {
	const prototype = AssistantMessageComponent.prototype as PatchablePrototype;
	if (prototype[PATCHED]) return;

	const nativeRender = prototype.render;
	prototype.render = function renderWithCodeFrames(width: number): string[] {
		const lines = nativeRender.call(this, width);
		return activeTheme ? renderCodeFences(lines, width, activeTheme) : lines;
	};
	prototype[PATCHED] = true;
}

export default function displayExtension(pi: ExtensionAPI): void {
	patchAssistantRenderer();
	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode === "tui") activeTheme = ctx.ui.theme;
	});
}
