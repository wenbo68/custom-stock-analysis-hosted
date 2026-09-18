import apiClient from './index';

// A stored key, as the server shows it back: never the value, only
// whether one is set and its last characters.
export type KeyStatus = { set: boolean; hint: string | null };

export type DataKeyName = 'finnhub' | 'alphavantage' | 'fred';

export type ModelChoice = {
  id: string;
  label: string;
  provider: string;
  provider_label: string;
  key_url: string;
};

/** What picking a provider fills the two model fields with. */
export type ModelPair = { main: string; sub: string };

export type UserSettings = {
  /** A brand-new account comes with the default provider's pair; once
   *  removed, a model stays removed (null). */
  llm_model: string | null;
  /** The cheaper model for screening chores; null = the main model. */
  llm_sub_model: string | null;
  llm_api_key: KeyStatus;
  data_keys: Record<DataKeyName, KeyStatus>;
  models: ModelChoice[];
  /** Per provider id, its default pair. */
  defaults: Record<string, ModelPair>;
};

// Absent = unchanged, "" = clear the key (or model).
export type UserSettingsUpdate = {
  llm_model?: string;
  llm_sub_model?: string;
  llm_api_key?: string;
  finnhub_api_key?: string;
  alphavantage_api_key?: string;
  fred_api_key?: string;
};

export const settingsApi = {
  get: async (): Promise<UserSettings> => {
    const response = await apiClient.get<UserSettings>('/api/v1/settings/me');
    return response.data;
  },

  update: async (update: UserSettingsUpdate): Promise<UserSettings> => {
    const response = await apiClient.put<UserSettings>('/api/v1/settings/me', update);
    return response.data;
  },
};
