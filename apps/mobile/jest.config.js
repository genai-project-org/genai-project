module.exports = {
  preset: 'jest-expo',
  // Standard Expo/jest-expo transformIgnorePatterns override (copied from
  // the installed jest-expo@57's own preset — see node_modules/jest-expo/
  // jest-preset.js). Expo/RN packages ship untranspiled ESM/Flow/JSX and
  // must be *allowed through* the transformer rather than ignored; anything
  // starting with these prefixes (react-native, @react-native*, expo,
  // @expo*, react-navigation, etc.) is matched by name-prefix, so this also
  // covers react-native-purchases, react-native-reanimated,
  // react-native-worklets, expo-iap, and friends without listing each one.
  // We restate it explicitly here (rather than relying only on the preset
  // default) so it's visible/tunable as the app's own dependency set grows.
  transformIgnorePatterns: [
    '/node_modules/(?!(.pnpm|react-native|@react-native|@react-native-community|expo|@expo|@expo-google-fonts|react-navigation|@react-navigation|@sentry/react-native|native-base|standard-navigation))',
    // Avoid double-transforming the reanimated babel plugin itself.
    '/node_modules/react-native-reanimated/plugin/',
    '/node_modules/@react-native/babel-preset/',
  ],
  collectCoverageFrom: [
    'src/**/*.{js,jsx}',
    '!src/**/*.test.{js,jsx}',
  ],
  testPathIgnorePatterns: ['/node_modules/', '/android/', '/ios/'],
  setupFiles: ['<rootDir>/jest.setup.js'],
  moduleNameMapper: {
    // lucide-react-native's package.json "exports" map exposes a
    // "react-native" condition that Jest's resolver picks up, pointing at
    // an untranspiled ESM (.mjs) build — force resolution to its plain CJS
    // build instead, which needs no transform at all.
    '^lucide-react-native$':
      '<rootDir>/node_modules/lucide-react-native/dist/cjs/lucide-react-native.js',
    // Same story for react-redux and its `immer` dependency (pulled in via
    // @reduxjs/toolkit) — both ship a "react-native" export condition
    // pointing at a `.legacy-esm.js` build that Jest's transformer never
    // sees (node_modules is untransformed by default), so plain `import`
    // syntax blows up. This only surfaced once a test actually exercised
    // react-redux/@reduxjs-toolkit directly (interviewSlice/
    // InterviewHomeScreen tests) — no earlier test imported the store.
    '^react-redux$': '<rootDir>/node_modules/react-redux/dist/cjs/index.js',
    '^immer$': '<rootDir>/node_modules/immer/dist/cjs/index.js',
  },
};
