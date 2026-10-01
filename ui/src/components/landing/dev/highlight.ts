/**
 * A deliberately small syntax highlighter for the landing page's few-line
 * snippets. It knows comments, strings, numbers and keywords — enough to make
 * a snippet read like code, without shipping a real grammar engine.
 */

export type Lang = 'python' | 'js' | 'go' | 'shell' | 'json'
export type TokenKind = 'plain' | 'comment' | 'string' | 'keyword' | 'number' | 'prompt' | 'fn'
export type Token = [text: string, kind: TokenKind]

const keywords: Record<Lang, string[]> = {
  python: ['import', 'from', 'as', 'with', 'def', 'return', 'if', 'else', 'for', 'in', 'not', 'None', 'True', 'False', 'await', 'async'],
  js: ['import', 'from', 'const', 'let', 'await', 'async', 'new', 'return', 'if', 'else', 'function', 'export', 'default'],
  go: ['package', 'import', 'func', 'return', 'if', 'else', 'var', 'err', 'nil', 'defer', 'go', 'range', 'for'],
  shell: [],
  json: ['true', 'false', 'null'],
}

const commentPattern: Record<Lang, string> = {
  python: '#.*',
  js: '//.*',
  go: '//.*',
  shell: '#.*',
  json: '(?!)',
}

function tokenizeLine(line: string, lang: Lang): Token[] {
  if (lang === 'shell' && line.startsWith('$ ')) {
    const rest = line.slice(2)
    const comment = rest.indexOf('  #')
    const command = comment >= 0 ? rest.slice(0, comment) : rest
    const tokens: Token[] = [['$ ', 'prompt'], [command, 'fn']]
    if (comment >= 0) tokens.push([rest.slice(comment), 'comment'])
    return tokens
  }
  if (lang === 'shell') {
    return [[line, line.trimStart().startsWith('#') ? 'comment' : 'plain']]
  }

  const kw = keywords[lang].join('|')
  const pattern = new RegExp(
    [
      `(?<comment>${commentPattern[lang]})`,
      '(?<string>"(?:[^"\\\\]|\\\\.)*"|\'(?:[^\'\\\\]|\\\\.)*\'|`[^`]*`)',
      kw ? `(?<keyword>\\b(?:${kw})\\b)` : '(?<keyword>(?!))',
      '(?<number>\\b\\d+(?:\\.\\d+)?\\b)',
      '(?<fn>\\b[A-Za-z_]\\w*(?=\\())',
    ].join('|'),
    'g',
  )

  const tokens: Token[] = []
  let last = 0
  for (const match of line.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > last) tokens.push([line.slice(last, index), 'plain'])
    const kind = (Object.entries(match.groups ?? {}).find(([, v]) => v !== undefined)?.[0] ?? 'plain') as TokenKind
    tokens.push([match[0], kind])
    last = index + match[0].length
  }
  if (last < line.length) tokens.push([line.slice(last), 'plain'])
  return tokens
}

export function highlight(code: string, lang: Lang): Token[][] {
  return code.split('\n').map((line) => tokenizeLine(line, lang))
}
