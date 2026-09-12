/**
 * Jest setup.
 *
 * Two native modules need standing in for: MMKV is a Nitro module with no JS fallback, and
 * expo-localization reads the device. Both are mocked here rather than behind an abstraction in
 * app code — the test environment is a test concern, and `src/lib/storage.ts` stays honest
 * about using MMKV directly.
 *
 * The MMKV mock is **keyed by instance id**, because the app keeps preferences and the session in
 * separate instances precisely so that clearing one leaves the other alone. A single shared Map
 * here would let a bug that wipes both pass its test.
 */

jest.mock('react-native-mmkv', () => {
  const instances = new Map();

  const instanceFor = (id) => {
    let store = instances.get(id);
    if (!store) {
      store = new Map();
      instances.set(id, store);
    }
    return store;
  };

  return {
    createMMKV: ({ id } = {}) => {
      const store = instanceFor(id ?? 'default');

      return {
        getString: (key) => (store.has(key) ? store.get(key) : undefined),
        set: (key, value) => {
          store.set(key, String(value));
        },
        remove: (key) => store.delete(key),
        contains: (key) => store.has(key),
        clearAll: () => {
          store.clear();
          return true;
        },
      };
    },
  };
});

jest.mock('expo-localization', () => ({
  getLocales: () => [{ languageCode: 'en', languageTag: 'en-IN', regionCode: 'IN' }],
}));
