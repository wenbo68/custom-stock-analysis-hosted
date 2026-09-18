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
  { id: 'gemini/gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite', provider: 'gemini',
    provider_label: 'Google Gemini', key_url: 'https://aistudio.google.com/apikey' },
  { id: 'openai/gpt-5.6-sol', label: 'GPT-5.6 Sol', provider: 'openai',
    provider_label: 'OpenAI', key_url: 'https://platform.openai.com/api-keys' },
  { id: 'openai/gpt-5.6-terra', label: 'GPT-5.6 Terra', provider: 'openai',
    provider_label: 'OpenAI', key_url: 'https://platform.openai.com/api-keys' },
  { id: 'openai/gpt-5.6-luna', label: 'GPT-5.6 Luna', provider: 'openai',
    provider_label: 'OpenAI', key_url: 'https://platform.openai.com/api-keys' },
];
const defaults = {
  gemini: { main: 'gemini/gemini-3.8-flash', sub: 'gemini/gemini-3.5-flash-lite' },
  openai: { main: 'openai/gpt-5.6-terra', sub: 'openai/gpt-5.6-luna' },
};

// A fresh account as the server shows it: on the default Gemini pair,
// no LLM key yet, one data key stored.
const freshSettings = (): UserSettings => ({
  llm_model: defaults.gemini.main,
  llm_sub_model: defaults.gemini.sub,
  llm_api_key: { set: false, hint: null },
  data_keys: {
    finnhub: { set: false, hint: null },
    alphavantage: { set: true, hint: '••••av99' },
    fred: { set: false, hint: null },
  },
  models,
  defaults,
});

// The colored title above a field: the nearest bold wrapper around its
// text (the tooltip and link sit in between).
const titleOf = (text: RegExp) => screen.getByText(text).closest('.font-semibold') as HTMLElement;

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
    serverWith(freshSettings());
    const { container } = renderBlock({
      user: { ...user, avatar_url: 'https://lh3.googleusercontent.com/a/photo=s96-c' },
    });
    await screen.findByText('Ada');
    const img = container.querySelector('img');
    expect(img).toHaveAttribute('src', 'https://lh3.googleusercontent.com/a/photo=s96-c');
    expect(img).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('a fresh account is on the Gemini pair, with only the LLM key still to fill in', async () => {
    serverWith(freshSettings());
    renderBlock({ user });
    expect(await screen.findByText('Ada')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /LLM provider: Google Gemini|LLM 提供商: Google Gemini/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Main LLM: Gemini 3.8 Flash|主 LLM: Gemini 3.8 Flash/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Sub LLM: Gemini 3.5 Flash-Lite|副 LLM: Gemini 3.5 Flash-Lite/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /LLM key:|LLM 密钥:/ })).toBeNull();
    // the defaults are the server's answer, nothing was saved for them
    expect(settingsApi.update).not.toHaveBeenCalled();
    // the LLM titles link to Gemini's key page from the start
    expect(screen.getByRole('link', { name: /LLM provider API key|LLM 提供商 API 密钥/ })).toHaveAttribute(
      'href', 'https://aistudio.google.com/apikey',
    );
    // the stored AlphaVantage key shows only its hint, never its value
    expect(screen.getByRole('button', { name: /AlphaVantage key: ••••av99|AlphaVantage 密钥: ••••av99/ })).toBeInTheDocument();
    expect(screen.getByText(/FRED key: default|FRED 密钥: 默认/)).toBeInTheDocument();
    expect(screen.getByText(/FinnHub key: default|FinnHub 密钥: 默认/)).toBeInTheDocument();
    // nothing to press: every change saves itself
    expect(screen.queryByRole('button', { name: /Save|保存/ })).toBeNull();
  });

  it('lays out the seven fields as write-only boxes in field order', async () => {
    serverWith(freshSettings());
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
    serverWith(freshSettings());
    renderBlock({ user });
    await screen.findByText('Ada');
    const fred = screen.getByRole('link', { name: /FRED API key|FRED API 密钥/ });
    expect(fred).toHaveAttribute('href', 'https://fredaccount.stlouisfed.org/apikeys');
    expect(fred).toHaveAttribute('target', '_blank');
    fireEvent.mouseEnter(fred.parentElement as HTMLElement);
    expect(await screen.findByRole('tooltip')).toHaveTextContent(/Federal Reserve|美联储/);
  });

  it('colors the title of a set field like its pill and leaves an unset one gray', async () => {
    serverWith(freshSettings());
    renderBlock({ user });
    await screen.findByText('Ada');
    // provider, main and sub are set from the start (the default pair)
    expect(titleOf(/^LLM provider$|^LLM 提供商$/)).toHaveClass('text-red-300');
    expect(titleOf(/^Main LLM$|^主 LLM$/)).toHaveClass('text-orange-300');
    expect(titleOf(/^Sub LLM$|^副 LLM$/)).toHaveClass('text-amber-300');
    // the data keys always have a pill (the server's default one when the
    // user brings none), so their titles are always colored
    expect(titleOf(/^AlphaVantage API key$|^AlphaVantage API 密钥$/)).toHaveClass('text-blue-300');
    expect(titleOf(/^FRED API key$|^FRED API 密钥$/)).toHaveClass('text-emerald-300');
    expect(titleOf(/^FinnHub API key$|^FinnHub API 密钥$/)).toHaveClass('text-sky-300');
    // no LLM key yet: the one gray title
    expect(titleOf(/^LLM provider API key$|^LLM 提供商 API 密钥$/)).toHaveClass('text-gray-300');

    const keyBox = screen.getByPlaceholderText('Enter LLM key...');
    fireEvent.change(keyBox, { target: { value: 'sk-secret-1234' } });
    fireEvent.keyDown(keyBox, { key: 'Enter' });
    await screen.findByRole('button', { name: /LLM key: ••••1234|LLM 密钥: ••••1234/ });
    expect(titleOf(/^LLM provider API key$|^LLM 提供商 API 密钥$/)).toHaveClass('text-lime-300');
    // clearing the main LLM grays its title again
    fireEvent.click(screen.getByRole('button', { name: /Main LLM: Gemini 3.8 Flash|主 LLM: Gemini 3.8 Flash/ }));
    await waitFor(() => expect(titleOf(/^Main LLM$|^主 LLM$/)).toHaveClass('text-gray-300'));
  });

  it('picking a provider saves its default pair at once and narrows the models to it', async () => {
    serverWith(freshSettings());
    renderBlock({ user });
    await screen.findByText('Ada');

    fireEvent.focus(screen.getByPlaceholderText('Enter LLM provider...'));
    fireEvent.click(screen.getByRole('button', { name: 'OpenAI' }));
    // both models move to OpenAI's defaults in one save
    expect(settingsApi.update).toHaveBeenCalledTimes(1);
    expect(settingsApi.update).toHaveBeenCalledWith({
      llm_model: 'openai/gpt-5.6-terra', llm_sub_model: 'openai/gpt-5.6-luna',
    });
    expect(await screen.findByRole('button', { name: /LLM provider: OpenAI|LLM 提供商: OpenAI/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Main LLM: GPT-5.6 Terra|主 LLM: GPT-5.6 Terra/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Sub LLM: GPT-5.6 Luna|副 LLM: GPT-5.6 Luna/ })).toBeInTheDocument();
    // the LLM titles now open the chosen provider's key page
    expect(screen.getByRole('link', { name: /LLM provider API key|LLM 提供商 API 密钥/ })).toHaveAttribute(
      'href', 'https://platform.openai.com/api-keys',
    );

    // a model can still be swapped one at a time, within the provider
    fireEvent.focus(screen.getByPlaceholderText('Enter main LLM...'));
    expect(screen.queryByRole('button', { name: 'Gemini 3.8 Flash' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'GPT-5.6 Sol' }));
    expect(await screen.findByRole('button', { name: /Main LLM: GPT-5.6 Sol|主 LLM: GPT-5.6 Sol/ })).toBeInTheDocument();
    expect(settingsApi.update).toHaveBeenLastCalledWith({ llm_model: 'openai/gpt-5.6-sol' });

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
    serverWith(freshSettings());
    const onSettings = vi.fn();
    renderBlock({ user, onSettings });
    await waitFor(() =>
      expect(onSettings).toHaveBeenLastCalledWith(expect.objectContaining({ llm_model: 'gemini/gemini-3.8-flash' })),
    );

    fireEvent.focus(screen.getByPlaceholderText('Enter main LLM...'));
    fireEvent.click(screen.getByRole('button', { name: 'Gemini 3.5 Flash-Lite' }));
    await waitFor(() =>
      expect(onSettings).toHaveBeenLastCalledWith(expect.objectContaining({ llm_model: 'gemini/gemini-3.5-flash-lite' })),
    );
  });

  it('clicking a stored key pill clears that key on the server, nothing else', async () => {
    serverWith(freshSettings());
    renderBlock({ user });
    await screen.findByText('Ada');

    fireEvent.click(screen.getByRole('button', { name: /AlphaVantage key: ••••av99|AlphaVantage 密钥: ••••av99/ }));
    expect(await screen.findByText(/AlphaVantage key: default|AlphaVantage 密钥: 默认/)).toBeInTheDocument();
    expect(settingsApi.update).toHaveBeenCalledTimes(1);
    expect(settingsApi.update).toHaveBeenCalledWith({ alphavantage_api_key: '' });
  });

  it('the default LLM pills can be removed like any other, and then stay gone', async () => {
    serverWith(freshSettings());
    renderBlock({ user });
    await screen.findByText('Ada');

    // the provider pill takes both models with it
    fireEvent.click(screen.getByRole('button', { name: /LLM provider: Google Gemini|LLM 提供商: Google Gemini/ }));
    await waitFor(() => expect(settingsApi.update).toHaveBeenCalledWith({ llm_model: '', llm_sub_model: '' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /LLM provider:|LLM 提供商:/ })).toBeNull());
    expect(screen.queryByRole('button', { name: /Main LLM:|主 LLM:/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Sub LLM:|副 LLM:/ })).toBeNull();
    expect(titleOf(/^LLM provider$|^LLM 提供商$/)).toHaveClass('text-gray-300');
    expect(titleOf(/^Main LLM$|^主 LLM$/)).toHaveClass('text-gray-300');
    // with no provider, every model is on offer again
    fireEvent.focus(screen.getByPlaceholderText('Enter main LLM...'));
    expect(screen.getByRole('button', { name: 'Gemini 3.8 Flash' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'GPT-5.6 Sol' })).toBeInTheDocument();
  });

  it('clearing one model keeps the other and the provider it pins', async () => {
    serverWith({ ...freshSettings(), llm_model: 'openai/gpt-5.6-sol', llm_sub_model: 'openai/gpt-5.6-luna' });
    renderBlock({ user });
    await screen.findByText('Ada');

    fireEvent.click(screen.getByRole('button', { name: /Main LLM: GPT-5.6 Sol|主 LLM: GPT-5.6 Sol/ }));
    await waitFor(() => expect(settingsApi.update).toHaveBeenCalledWith({ llm_model: '' }));
    expect(screen.queryByRole('button', { name: /Main LLM:|主 LLM:/ })).toBeNull();
    expect(screen.getByRole('button', { name: /Sub LLM: GPT-5.6 Luna|副 LLM: GPT-5.6 Luna/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /LLM provider: OpenAI|LLM 提供商: OpenAI/ })).toBeInTheDocument();
  });

  it('shows the save error instead of hiding it', async () => {
    vi.mocked(settingsApi.get).mockResolvedValue(freshSettings());
    vi.mocked(settingsApi.update).mockRejectedValue(new Error('server has no APP_ENCRYPTION_KEY'));
    renderBlock({ user });
    await screen.findByText('Ada');
    fireEvent.focus(screen.getByPlaceholderText('Enter main LLM...'));
    fireEvent.click(screen.getByRole('button', { name: 'Gemini 3.5 Flash-Lite' }));
    expect(await screen.findByText(/APP_ENCRYPTION_KEY/)).toBeInTheDocument();
  });

  it('signs out through the callback', async () => {
    vi.mocked(settingsApi.get).mockResolvedValue(freshSettings());
    const onSignOut = vi.fn().mockResolvedValue(undefined);
    renderBlock({ user, onSignOut });
    await screen.findByText('Ada');
    fireEvent.click(screen.getByRole('button', { name: /Sign out|退出登录/ }));
    expect(onSignOut).toHaveBeenCalled();
  });
});
