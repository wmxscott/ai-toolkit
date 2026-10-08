import { expect, test } from 'claude-code/testing'

const F = '\uf11e'
const props = (text: string) => ({ text, isFirstOfReply: true })

test('colors the Needs you header and keeps the text around it', async $ => {
  for (const surface of ['terminal', 'desktop'] as const) {
    const text = `TLDR: done.\n\n**Needs you**\n- Approve the deploy.\n\nNext: say yes.`
    const ui = await $.ui.mount({ plugin: 'plain-talk', surface, component: 'AssistantMessage', props: props(text) })

    const header = await ui.find({ type: 'Text', text: /Needs you/ })
    expect(header).toBeDefined()
    expect(await ui.findAll({ type: 'Markdown' })).toHaveLength(2)
    await ui.unmount()
  }
})

test('also matches a header with a leading icon', async $ => {
  const ui = await $.ui.mount({ plugin: 'plain-talk', surface: 'terminal', component: 'AssistantMessage', props: props(`Hi.\n\n${F} **Needs you**\n- Do it.`) })

  expect(await ui.find({ type: 'Text', text: /Needs you/ })).toBeDefined()
  await ui.unmount()
})

test('leaves replies without the header alone', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine drew this</Text>
  })
  const ui = await $.ui.mount({ plugin: 'plain-talk', surface: 'terminal', component: 'AssistantMessage', props: props('Just an answer.') })

  expect(await ui.find({ type: 'Text', text: /Needs you/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /engine drew/ })).toBeDefined()
  await ui.unmount()
})

test('adds the rules to the end of the system prompt', async ($, on) => {
  on('prompt.compose', () => ({ sections: [{ id: 'intro', text: 'You are Claude.', scope: 'shared' }] }))

  const { sections } = await $.prompt.compose({ model: 'm', promptModel: 'm', surfaces: ['terminal'], tools: [], outputStyle: null, traits: [] })

  expect(sections.map(s => s.id)).toEqual(['intro', 'plain-talk:rules'])
  expect(sections[1].text).toContain('**Needs you**')
  expect(sections[1].scope).toBe('session')
})
