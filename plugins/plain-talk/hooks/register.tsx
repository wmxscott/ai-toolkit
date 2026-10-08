import type { Register } from 'claude-code'

// Palette slot 13 (bright magenta) is the terminal theme's own colour; Claude Code's ANSI themes use it for pink.
// A name such as 'magentaBright' is drawn as a fixed colour instead, and the `ansi:` form is refused.
// Other surfaces have no terminal palette.
const color = (surface: string) => (surface === 'terminal' ? 'ansi256(13)' : '#ff69b4')

const RULES = `# How to talk to the user

The user reads your output while you work. Long text makes them lose track. Write for someone skimming.

## While working

- Say at most one short line between steps. Don't narrate what you are about to do.
- Don't report routine progress, files you read, or dead ends that didn't matter.

## Replies

- Start with a one-line TLDR (too long; didn't read): the answer or the outcome.
- Then short chunks: a few bullets, or two or three short sentences. No walls of text.
- Use simple, everyday words. Prefer plain wording over technical terms.
- The first time an acronym appears in a conversation, spell it out. The first time a jargon term appears, explain it in a few plain words. Don't repeat the explanation after that.
- Leave out what the user doesn't need to act on or understand the result.
- When a report or explanation is long, give the most important piece first and offer the rest. Don't hold up real work to ask, though.

## Flag what needs the user

When something needs the user's decision, approval, or action, or a step failed, or there is a risk the user should know about, put it in its own section with this exact header, alone on its line:

**Needs you**
- What it is, in one line, and what the user should do about it.

Use it only for those cases, never as decoration. Leave it out when nothing needs the user.

## End every reply with what's next

Finish with one line: \`Next:\` and what you need from the user, or \`Next: nothing needed from you\` and what you'll do or what's left.

## Example

> TLDR: Login bug fixed. The session token expired early because of a timezone mix-up.
>
> - Changed \`auth/session.ts\` to compare times in UTC (Coordinated Universal Time, the standard reference clock).
> - Tests pass.
>
> **Needs you**
> - The fix logs out everyone once when deployed. Okay to ship?
>
> Next: say yes to ship, or tell me to add a grace period first.`
const HEADER = /^[ \t>]*(?:[^\w\s*]{1,2}\s*)?\*{0,2}\s*(?:[^\w\s*]{1,2}\s*)?Needs you:?\s*\*{0,2}\s*$/m

export function split(text: string) {
  const match = HEADER.exec(text)
  if (!match) return null

  return {
    before: text.slice(0, match.index).trimEnd(),
    after: text.slice(match.index + match[0].length).replace(/^\n+/, ''),
  }
}

export const register: Register = on => {
  on('prompt.compose', async ($, e, next) => {
    const { sections } = await next(e)

    return { sections: [...sections, { id: 'plain-talk:rules', text: RULES, scope: 'session' }] }
  })

  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    if (e.props.isSummary) return next(e)

    const parts = split(e.props.text)
    if (!parts) return next(e)

    const { Box, Markdown, Text } = $.ui.resolve(e)

    return (
      <Box flexDirection="column">
        {parts.before && <Markdown text={parts.before} />}
        <Box marginTop={parts.before ? 1 : 0}>
          <Text color={color(e.surface)} bold>
            {'\uf11e Needs you'}
          </Text>
        </Box>
        {parts.after && <Markdown text={parts.after} />}
      </Box>
    )
  })
}
