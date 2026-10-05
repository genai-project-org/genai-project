/**
 * Global Jest setup for all test files.
 */

// react-native-safe-area-context ships an official Jest mock, but its
// `jest/mock.tsx` only sets a default export bundling the hooks
// (useSafeAreaInsets, useSafeAreaFrame, ...). Consumer code in this app
// uses named imports (`import { useSafeAreaInsets } from '...'`), which
// need those hooks to be top-level named exports of the module — so we
// spread the mock's default export back onto the module root here rather
// than pointing a plain moduleNameMapper straight at the file.
jest.mock('react-native-safe-area-context', () => {
  const mock = require('react-native-safe-area-context/jest/mock').default;
  return { __esModule: true, ...mock };
});

// react-native-reanimated 4 (react-native-worklets backend) calls into a
// native worklets module at import time (`NativeWorklets.loadUnpackers()`),
// which doesn't exist under plain Jest — nothing in this app hit that path
// before (no prior test imported anything reanimated-dependent), but the
// new Mock Interview screens/components use it directly for avatar/border/
// score-reveal animations. Reanimated ships an official JS-only mock for
// exactly this.
jest.mock('react-native-reanimated', () => require('react-native-reanimated/mock'));
