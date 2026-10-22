import { useCallback, useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';

type Theme = 'light' | 'dark';
const THEME_KEY = 'uet_rps_theme';
const SIDEBAR_KEY = 'uet_rps_sidebar_collapsed';

function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null;
  }
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#f3f7fb' : '#101018');
}

export function initTheme() {
  applyTheme(storedTheme() ?? systemTheme());
}

export function ThemeToggle({ className = '', showLabel = false }: { className?: string; showLabel?: boolean }) {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'));

  useEffect(() => {
    if (storedTheme()) return;
    const media = window.matchMedia('(prefers-color-scheme: light)');
    const onChange = () => { if (!storedTheme()) { const next = systemTheme(); setTheme(next); applyTheme(next); } };
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  const toggle = () => {
    const next: Theme = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
    applyTheme(next);
    try { window.localStorage.setItem(THEME_KEY, next); } catch { /* storage unavailable */ }
  };

  const label = theme === 'light' ? 'Chuyển sang chế độ tối' : 'Chuyển sang chế độ sáng';
  return (
    <button type="button" className={`theme-toggle ${className}`} onClick={toggle} aria-label={label} title={label} data-tip={label}>
      {theme === 'light' ? <Moon size={17} /> : <Sun size={17} />}
      {showLabel && <span className="nav-label">{theme === 'light' ? 'Chế độ tối' : 'Chế độ sáng'}</span>}
    </button>
  );
}

export function useSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return window.localStorage.getItem(SIDEBAR_KEY) === '1'; } catch { return false; }
  });
  const toggle = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try { window.localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0'); } catch { /* storage unavailable */ }
      return next;
    });
  }, []);
  return [collapsed, toggle] as const;
}
