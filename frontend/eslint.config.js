import js from '@eslint/js'
import tsParser from '@typescript-eslint/parser'

export default [
  js.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { parser: tsParser, parserOptions: { ecmaFeatures: { jsx: true } } },
    rules: { 'no-unused-vars': 'off', 'no-undef': 'off' },
  },
  { ignores: ['dist/**', 'node_modules/**'] },
]
