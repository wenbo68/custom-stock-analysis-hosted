import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import './App.css';
import { UiLanguageToggle } from './components/i18n/UiLanguageToggle';
import { ThemeToggle } from './components/theme/ThemeToggle';
import { CurrentUserProvider } from './contexts/CurrentUserContext';
import { UiLanguageProvider } from './contexts/UiLanguageContext';
import TieredAltPage from './pages/TieredAltPage';

function App() {
  return (
    <UiLanguageProvider>
      <CurrentUserProvider>
      <BrowserRouter>
        <div className="min-h-screen bg-background text-foreground">
          <header className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 pt-4 md:px-6 lg:px-8">
            <span className="text-sm font-semibold tracking-wide text-gray-400">
              Custom Stock Analysis
            </span>
            <div className="flex items-center gap-2">
              <UiLanguageToggle />
              <ThemeToggle />
            </div>
          </header>
          <Routes>
            <Route path="/" element={<TieredAltPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </BrowserRouter>
      </CurrentUserProvider>
    </UiLanguageProvider>
  );
}

export default App;
