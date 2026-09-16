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
  { id: 'gemini/gemini-3.8-flash', label: 'Gemini 3.8 Flash', provider: 'gemini',
    provider_label: 'Google Gemini', key_url: 'https://aistudio.google.com/apikey' },
  { id: 'openai/gpt-5.6-luna', label: 'GPT-5.6 Luna', provider: 'openai',
    provider_label: 'OpenAI', key_url: 'https://platform.openai.com/api-keys' },
  { id: 'openai/gpt-5.6-sol', label: 'GPT-5.6 Sol', provider: 'openai',
    provider_label: 'OpenAI', key_url: 'https://platform.openai.com/api-keys' },
];

const emptySettings = (): UserSettings => ({
  llm_model: null,
  llm_sub_model: null,
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

// The server's answer to an update: the same view with the given fields
// applied, keys masked to their last four characters the way the API does.
const applied = (base: UserSettings, update: Record<string, string>): UserSettings => {
  const masked = (value: string) => ({ set: value !== '', hint: value ? `••••${value.slice(-4)}` : null });
  const next = { ...base, data_keys: { ...base.data_keys } };
  for (const [field, value] of Object.entries(update)) {
    if (field === 'llm_model' || field === 'llm_sub_model') {
      next[field] = value || null;
    } else if (field === 'llm_api_key') {
      next.llm_api_key = masked(value);
    } else {
      next.data_keys[field.replace('_api_key', '') as keyof typeof next.data_keys] = masked(value);
    }
  }
  return next;
};

// Wires the update mock to a running copy of the settings, like the server.
const serverWith = (initial: UserSettings) => {
  let current = initial;
  vi.mocked(settingsApi.get).mockResolvedValue(current);
  vi.mocked(settingsApi.update).mockImplementation(async (update) => {
    current = applied(current, update as Record<string, string>);
    return current;
  });
};

describe('AltUserBlock signed in', () => {
  beforeEach(() => {
    vi.mocked(settingsApi.get).mockReset();
    vi.mocked(settingsApi.update).mockReset();
  });

  it('shows the provider photo without sending a referrer (Google rejects it)', async () => {
    serverWith(emptySettings());
    const { container } = renderBlock({
      user: { ...user, avatar_url: 'https://lh3.googleusercontent.com/a/photo=s96-c' },
    });
    await screen.findByText('Ada');
    const img = container.querySelector('img');
    expect(img).toHaveAttribute('src', 'https://lh3.googleusercontent.com/a/photo=s96-c');
    expect(img).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('shows stored keys as pills, the rest as defaults, and says a run is not possible yet', async () => {
    serverWith(emptySettings());
    renderBlock({ user });
    expect(await screen.findByText('Ada')).toBeInTheDocument();
    // the stored AlphaVantage key shows only its hint, never its value
    expect(screen.getByRole('button', { name: /AlphaVantage key: ••••av99|AlphaVantage 密钥: ••••av99/ })).toBeInTheDocument();
    expect(screen.getByText(/FRED key: default|FRED 密钥: 默认/)).toBeInTheDocument();
    expect(screen.getByText(/FinnHub key: default|FinnHub 密钥: 默认/)).toBeInTheDocument();
    // nothing to press: every change saves itself
    expect(screen.queryByRole('button', { name: /Save|保存/ })).toBeNull();
  });

  it('lays out the seven fields as write-only boxes in field order', async () => {
    serverWith(emptySettings());
    renderBlock({ user });
    await screen.findByText('Ada');
    const placeholders = screen
      .getAllByRole('textbox')
      .concat(screen.getAllByPlaceholderText(/key\.\.\.|密钥…/))
      .map((box) => box.getAttribute('placeholder'));
    expect(placeholders).toEqual([
      'Enter LLM provider...',
      'Enter main LLM...',
      'Enter sub LLM...',
      'Enter LLM key...',
      'Enter FRED key...',
      'Enter FinnHub key...',
      'Enter AlphaVantage key...',
    ]);
    // keys are typed hidden
    expect(screen.getByPlaceholderText('Enter LLM key...')).toHaveAttribute('type', 'password');
  });

  it('explains a field on hover and links its title to where the key is issued', async () => {
    serverWith(emptySettings());
    renderBlock({ user });
    await screen.findByText('Ada');
    const fred = screen.getByRole('link', { name: /FRED API key|FRED API 密钥/ });
    expect(fred).toHaveAttribute('href', 'https://fredaccount.stlouisfed.org/apikeys');
    expect(fred).toHaveAttribute('target', '_blank');
    fireEvent.mouseEnter(fred.parentElement as HTMLElement);
    expect(await screen.findByRole('tooltip')).toHaveTextContent(/Federal Reserve|美联储/);
    // no provider picked yet: the LLM titles have nothing to link to
    expect(screen.queryByRole('link', { name: /LLM provider API key|LLM 提供商 API 密钥/ })).toBeNull();
  });

  it('picking a provider narrows the models; every choice becomes a pill and is saved at once', async () => {
    serverWith(emptySettings());
    renderBlock({ user });
    await screen.findByText('Ada');

    fireEvent.focus(screen.getByPlaceholderText('Enter LLM provider...'));
    fireEvent.click(screen.getByRole('button', { name: 'OpenAI' }));
    expect(screen.getByRole('button', { name: /LLM provider: OpenAI|LLM 提供商: OpenAI/ })).toBeInTheDocument();
    // a provider alone is nothing to store
    expect(settingsApi.update).not.toHaveBeenCalled();
    // the LLM titles now open the chosen provider's key page
    expect(screen.getByRole('link', { name: /LLM provider API key|LLM 提供商 API 密钥/ })).toHaveAttribute(
      'href', 'https://platform.openai.com/api-keys',
    );

    fireEvent.focus(screen.getByPlaceholderText('Enter main LLM...'));
    expect(screen.queryByRole('button', { name: 'Gemini 3.8 Flash' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'GPT-5.6 Luna' }));
    expect(await screen.findByRole('button', { name: /Main LLM: GPT-5.6 Luna|主 LLM: GPT-5.6 Luna/ })).toBeInTheDocument();
    expect(settingsApi.update).toHaveBeenLastCalledWith({ llm_model: 'openai/gpt-5.6-luna' });

    fireEvent.focus(screen.getByPlaceholderText('Enter sub LLM...'));
    // the main LLM list closes on a short timer, so its GPT-5.6 Sol may still be up
    fireEvent.click(screen.getAllByRole('button', { name: 'GPT-5.6 Sol' }).at(-1) as HTMLElement);
    expect(await screen.findByRole('button', { name: /Sub LLM: GPT-5.6 Sol$|副 LLM: GPT-5.6 Sol$/ })).toBeInTheDocument();
    expect(settingsApi.update).toHaveBeenLastCalledWith({ llm_sub_model: 'openai/gpt-5.6-sol' });

    const keyBox = screen.getByPlaceholderText('Enter LLM key...');
    fireEvent.change(keyBox, { target: { value: 'sk-secret-1234' } });
    fireEvent.keyDown(keyBox, { key: 'Enter' });
    // the box clears and the pill shows only the tail of the key
    expect(keyBox).toHaveValue('');
    expect(await screen.findByRole('button', { name: /LLM key: ••••1234|LLM 密钥: ••••1234/ })).toBeInTheDocument();
    expect(settingsApi.update).toHaveBeenLastCalledWith({ llm_api_key: 'sk-secret-1234' });
    expect(screen.queryByText(/sk-secret-1234/)).toBeNull();
  });

  it('reports the stored settings to the page after loading and after every change', async () => {
    serverWith(emptySettings());
    const onSettings = vi.fn();
    renderBlock({ user, onSettings });
    await waitFor(() =>
      expect(onSettings).toHaveBeenLastCalledWith(expect.objectContaining({ llm_model: null })),
    );

    fireEvent.focus(screen.getByPlaceholderText('Enter main LLM...'));
    fireEvent.click(screen.getByRole('button', { name: 'Gemini 3.8 Flash' }));
    await waitFor(() =>
      expect(onSettings).toHaveBeenLastCalledWith(expect.objectContaining({ llm_model: 'gemini/gemini-3.8-flash' })),
    );
  });

  it('clicking a stored key pill clears that key on the server, nothing else', async () => {
    serverWith(emptySettings());
    renderBlock({ user });
    await screen.findByText('Ada');

    fireEvent.click(screen.getByRole('button', { name: /AlphaVantage key: ••••av99|AlphaVantage 密钥: ••••av99/ }));
    expect(await screen.findByText(/AlphaVantage key: default|AlphaVantage 密钥: 默认/)).toBeInTheDocument();
    expect(settingsApi.update).toHaveBeenCalledTimes(1);
    expect(settingsApi.update).toHaveBeenCalledWith({ alphavantage_api_key: '' });
  });

  it('switching provider drops a stored main LLM from the other provider', async () => {
    serverWith({ ...emptySettings(), llm_model: 'gemini/gemini-3.8-flash' });
    renderBlock({ user });
    await screen.findByText('Ada');
    expect(screen.getByRole('button', { name: /LLM provider: Google Gemini|LLM 提供商: Google Gemini/ })).toBeInTheDocument();

    fireEvent.focus(screen.getByPlaceholderText('Enter LLM provider...'));
    fireEvent.click(screen.getByRole('button', { name: 'OpenAI' }));
    await waitFor(() => expect(settingsApi.update).toHaveBeenCalledWith({ llm_model: '' }));
    expect(screen.queryByRole('button', { name: /Main LLM:|主 LLM:/ })).toBeNull();
    expect(screen.getByRole('button', { name: /LLM provider: OpenAI|LLM 提供商: OpenAI/ })).toBeInTheDocument();
  });

  it('shows the save error instead of hiding it', async () => {
    vi.mocked(settingsApi.get).mockResolvedValue(emptySettings());
    vi.mocked(settingsApi.update).mockRejectedValue(new Error('server has no APP_ENCRYPTION_KEY'));
    renderBlock({ user });
    await screen.findByText('Ada');
    fireEvent.focus(screen.getByPlaceholderText('Enter main LLM...'));
    fireEvent.click(screen.getByRole('button', { name: 'Gemini 3.8 Flash' }));
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
