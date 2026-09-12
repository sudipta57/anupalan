// Anupalan mobile — eslint flat config.
// Enforced in CI (.github/workflows/ci.yml). See CLAUDE.md §5 for the TypeScript conventions.

const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');
const prettierConfig = require('eslint-config-prettier/flat');

module.exports = defineConfig([
  expoConfig,
  prettierConfig,
  {
    ignores: ['dist/*', 'node_modules/*', '.expo/*', 'android/*', 'ios/*', 'expo-env.d.ts'],
  },
  {
    // Flat config ignores /* eslint-env */ comments, so jest's globals are declared here.
    files: ['jest.setup.js'],
    languageOptions: {
      globals: { jest: 'readonly', module: 'writable', require: 'readonly' },
    },
  },
  {
    // CLAUDE.md §5: no `any` in src/api or src/domain.
    //
    // src/api is generated from the backend's OpenAPI schema and src/domain mirrors the Pydantic
    // schemas. An `any` in either is how the two sides silently drift apart — and a millimetre
    // or a paise value typed as `any` is exactly the bug that reaches a legal report. It is an
    // error here, not a warning, and it is not waivable with a disable comment.
    files: ['src/api/**/*.{ts,tsx}', 'src/domain/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unsafe-assignment': 'off', // needs type-aware linting; P3
    },
  },
  {
    files: ['src/api/**/*.{ts,tsx}', 'src/domain/**/*.{ts,tsx}'],
    linterOptions: {
      // A disable comment must not be how `any` gets into the contract layer.
      reportUnusedDisableDirectives: 'error',
    },
  },
]);
