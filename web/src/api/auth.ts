import apiClient from './index';

// The signed-in person, as GET /api/auth/me returns it (null when nobody is).
export type CurrentUser = {
  id: number;
  provider: string;
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
};

export type SignInProvider = 'google' | 'discord';

// Sign-in is a full-page trip to the provider: the browser navigates to
// this URL, approves, and lands back on "/" with the session cookie set.
export const signInUrl = (provider: SignInProvider): string => `/api/auth/login/${provider}`;

export const authApi = {
  providers: async (): Promise<SignInProvider[]> => {
    const response = await apiClient.get<{ providers: SignInProvider[] }>('/api/auth/providers');
    return response.data.providers;
  },

  me: async (): Promise<CurrentUser | null> => {
    const response = await apiClient.get<{ user: CurrentUser | null }>('/api/auth/me');
    return response.data.user;
  },

  logout: async (): Promise<void> => {
    await apiClient.post('/api/auth/logout');
  },
};
