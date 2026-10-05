// Shared render helper for component tests: wraps a component with the same
// providers App.jsx sets up (Redux store, router) so components that read
// from `useSelector`/`useDispatch` or `react-router-dom` hooks work as they
// would in the real app, without needing to mount the whole <App />.
import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import authReducer from '@/store/slices/authSlice';
import uiReducer from '@/store/slices/uiSlice';
import interviewReducer from '@/store/slices/interviewSlice';

export function makeTestStore(preloadedState) {
  return configureStore({
    reducer: { auth: authReducer, ui: uiReducer, interview: interviewReducer },
    preloadedState,
  });
}

export function renderWithProviders(
  ui,
  {
    preloadedState,
    store = makeTestStore(preloadedState),
    route = '/',
    routerProps = {},
    ...renderOptions
  } = {},
) {
  function Wrapper({ children }) {
    return (
      <Provider store={store}>
        <MemoryRouter initialEntries={[route]} {...routerProps}>
          {children}
        </MemoryRouter>
      </Provider>
    );
  }
  return { store, ...render(ui, { wrapper: Wrapper, ...renderOptions }) };
}
