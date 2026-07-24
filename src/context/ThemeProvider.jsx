import { useEffect } from 'react';
import { useSelector } from 'react-redux';

export default function ThemeProvider({ children }) {
  const theme = useSelector((s) => s.ui.theme);

  useEffect(() => {
    const root = document.documentElement;
    const apply = (mode) => {
      if (mode === 'dark') root.classList.add('dark');
      else root.classList.remove('dark');
    };
    if (theme === 'system') {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      apply(mq.matches ? 'dark' : 'light');
      const listener = (e) => apply(e.matches ? 'dark' : 'light');
      mq.addEventListener('change', listener);
      return () => mq.removeEventListener('change', listener);
    }
    apply(theme);
  }, [theme]);

  return children;
}
