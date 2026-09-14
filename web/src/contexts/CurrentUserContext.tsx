import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { authApi, type CurrentUser } from '../api/auth';

type CurrentUserState = {
  /** null = signed out; undefined = not known yet (first load). */
  user: CurrentUser | null | undefined;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
};

const fallback: CurrentUserState = {
  user: undefined,
  refresh: async () => undefined,
  signOut: async () => undefined,
};

const CurrentUserContext = createContext<CurrentUserState>(fallback);

// Who is signed in, asked once from the server when the app loads. The
// session lives in an HttpOnly cookie the page cannot read, so the
// server is the only source of truth.
export const CurrentUserProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<CurrentUser | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setUser(await authApi.me());
    } catch {
      setUser(null);
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo(() => ({ user, refresh, signOut }), [user, refresh, signOut]);
  return <CurrentUserContext.Provider value={value}>{children}</CurrentUserContext.Provider>;
};

// eslint-disable-next-line react-refresh/only-export-components -- useCurrentUser is a hook, co-located for context access
export const useCurrentUser = () => useContext(CurrentUserContext);
