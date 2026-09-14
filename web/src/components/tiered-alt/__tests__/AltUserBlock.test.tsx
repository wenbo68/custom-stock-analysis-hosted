import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UserSettings } from '../../../api/settings';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltUserBlock } from '../AltUserBlock';

vi.mock('../../../api/auth', async () => {
  const actual = await vi.importActual<typeof import('../../../api/auth')>('../../../api/auth');
  return {
    ...actual,
    authApi: { providers: vi.fn(), me: vi.fn(), logout: vi.fn() },
  };
});
vi.mock('../../../api/settings', () => ({
  settingsApi: { get: vi.fn(), update: vi.fn() },
}));

import { authApi } from '../../../api/auth';
import { settingsApi } from '../../../api/settings';

const models = [
  { id: 'gemini/gemini-2.5-flash', label: 'Gemini 2.5 Flash', provider: 'gemini',
    provider_label: 'Google Gemini', key_url: 'https://aistudio.google.com/apikey' },
  { id: 'openai/gpt-4o-mini', label: 'GPT-4o mini', provider: 'openai',
    provider_label: 'OpenAI', key_url: 'https://platform.openai.com/api-keys' },
];

const emptySettings = (): UserSettings => ({
  llm_model: null,
  llm_api_key: { set: false, hint: null },
  data_keys: {
    finnhub: { set: false, hint: null },
    alphavantage: { set: true, hint: '••••av99' },
    fred: { set: false, hint: null },
  },
  models,
});

const user = { id: 1, provider: 'google', email: 'ada@example.com', display_name: 'Ada', avatar_url: null };

const renderBlock = (props: Partial<Parameters<typeof AltUserBlock>[0]> = {}) =>
  render(
    <UiLanguageProvider>
      <AltUserBlock user={null} onSignOut={vi.fn()} {...props} />
    </UiLanguageProvider>,
  );

describe('AltUserBlock signed out', () => {
  beforeEach(() => {
    vi.mocked(authApi.providers).mockReset();
  });

  it('offers one sign-in link per configured provider', async () => {
    vi.mocked(authApi.providers).mockResolvedValue(['google', 'discord']);
    renderBlock();
    const google = await screen.findByRole('link', { name: /Google/ });
    expect(google).toHaveAttribute('href', '/api/auth/login/google');
    expect(screen.getByRole('link', { name: /Discord/ })).toHaveAttribute('href', '/api/auth/login/discord');
  });

  it('says so when the server has no provider configured', async () => {
    vi.mocked(authApi.providers).mockResolvedValue([]);
    renderBlock();
    expect(await screen.findByText(/not configured|尚未配置/)).toBeInTheDocument();
  });

  it('reports a failed sign-in', async () => {
    vi.mocked(authApi.providers).mockResolvedValue(['google']);
    renderBlock({ loginFailed: true });
    expect(await screen.findByText(/did not complete|未完成/)).toBeInTheDocument();
  });
});

describe('AltUserBlock signed in', () => {
  beforeEach(() => {
    vi.mocked(settingsApi.get).mockReset();
    vi.mocked(settingsApi.update).mockReset();
  });

  it('loads the masked settings and says a run is not possible yet', async () => {
    vi.mocked(settingsApi.get).mockResolvedValue(emptySettings());
    renderBlock({ user });
    expect(await screen.findByText('Ada')).toBeInTheDocument();
    expect(screen.getByText(/Pick a model and add its key|先选择模型/)).toBeInTheDocument();
    // the stored AlphaVantage key shows only its hint, never its value
    expect(screen.getByPlaceholderText(/••••av99/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Save|保存/ })).toBeDisabled();
  });

  it('saves only what changed and then reports ready', async () => {
    vi.mocked(settingsApi.get).mockResolvedValue(emptySettings());
    vi.mocked(settingsApi.update).mockResolvedValue({
      ...emptySettings(),
      llm_model: 'openai/gpt-4o-mini',
      llm_api_key: { set: true, hint: '••••1234' },
    });
    renderBlock({ user });
    await screen.findByText('Ada');

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'openai/gpt-4o-mini' } });
    fireEvent.change(screen.getByLabelText(/OpenAI API key|OpenAI API 密钥/), {
      target: { value: 'sk-secret-1234' },
    });
    // the key link follows the chosen model's provider
    expect(screen.getByRole('link', { name: /Get a key|获取密钥/ })).toHaveAttribute(
      'href', 'https://platform.openai.com/api-keys',
    );
    fireEvent.click(screen.getByRole('button', { name: /Save|保存/ }));

    await waitFor(() =>
      expect(settingsApi.update).toHaveBeenCalledWith({
        llm_model: 'openai/gpt-4o-mini',
        llm_api_key: 'sk-secret-1234',
      }),
    );
    expect(await screen.findByText(/Ready: GPT-4o mini|可以开始：GPT-4o mini/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/••••1234/)).toBeInTheDocument();
  });

  it('removing a data key sends an empty string for that key only', async () => {
    vi.mocked(settingsApi.get).mockResolvedValue(emptySettings());
    vi.mocked(settingsApi.update).mockResolvedValue(emptySettings());
    renderBlock({ user });
    await screen.findByText('Ada');

    fireEvent.click(screen.getByRole('button', { name: /Remove|移除/ }));
    fireEvent.click(screen.getByRole('button', { name: /Save|保存/ }));

    await waitFor(() =>
      expect(settingsApi.update).toHaveBeenCalledWith({ alphavantage_api_key: '' }),
    );
  });

  it('shows the save error instead of hiding it', async () => {
    vi.mocked(settingsApi.get).mockResolvedValue(emptySettings());
    vi.mocked(settingsApi.update).mockRejectedValue(new Error('server has no APP_ENCRYPTION_KEY'));
    renderBlock({ user });
    await screen.findByText('Ada');
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'gemini/gemini-2.5-flash' } });
    fireEvent.click(screen.getByRole('button', { name: /Save|保存/ }));
    expect(await screen.findByText(/APP_ENCRYPTION_KEY/)).toBeInTheDocument();
  });

  it('signs out through the callback', async () => {
    vi.mocked(settingsApi.get).mockResolvedValue(emptySettings());
    const onSignOut = vi.fn().mockResolvedValue(undefined);
    renderBlock({ user, onSignOut });
    await screen.findByText('Ada');
    fireEvent.click(screen.getByRole('button', { name: /Sign out|退出登录/ }));
    expect(onSignOut).toHaveBeenCalled();
  });
});
