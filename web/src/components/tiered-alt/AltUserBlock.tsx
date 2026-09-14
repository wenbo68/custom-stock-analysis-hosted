import { useEffect, useMemo, useState } from 'react';
import { LogOut, Save } from 'lucide-react';
import { authApi, signInUrl, type CurrentUser, type SignInProvider } from '../../api/auth';
import {
  settingsApi,
  type DataKeyName,
  type UserSettings,
  type UserSettingsUpdate,
} from '../../api/settings';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { ALT_COLOR, TAG_BASE } from './altStyles';

export interface AltUserBlockProps {
  /** null = signed out; undefined = still asking the server. */
  user: CurrentUser | null | undefined;
  onSignOut: () => Promise<void>;
  /** True when the browser landed here after a failed sign-in. */
  loginFailed?: boolean;
}

const DATA_KEYS: DataKeyName[] = ['finnhub', 'alphavantage', 'fred'];
const DATA_KEY_FIELD: Record<DataKeyName, keyof UserSettingsUpdate> = {
  finnhub: 'finnhub_api_key',
  alphavantage: 'alphavantage_api_key',
  fred: 'fred_api_key',
};
// Sign-in buttons take the palette slots after the run form's fields.
const PROVIDER_TONE: Record<SignInProvider, string> = {
  google: ALT_COLOR[6],
  discord: ALT_COLOR[8],
};
const PILL_BUTTON = `${TAG_BASE} cursor-pointer gap-1.5 transition hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-50`;
const INPUT =
  'w-full min-w-0 rounded bg-gray-800 px-3 py-2 text-gray-300 placeholder-gray-500 outline-none';

// The block above New Run: who is signed in, which AI model answers, and
// whose keys pay. Keys are write-only here — the server only ever shows
// back the last characters of what it holds.
export const AltUserBlock = ({ user, onSignOut, loginFailed = false }: AltUserBlockProps) => {
  if (user === undefined) {
    return <LoadingLine />;
  }
  if (user === null) {
    return <SignedOut loginFailed={loginFailed} />;
  }
  return <SignedIn user={user} onSignOut={onSignOut} />;
};

const LoadingLine = () => {
  const { t } = useUiLanguage();
  return <p className="text-sm text-gray-500">{t('tiered.user.loading')}</p>;
};

const SignedOut = ({ loginFailed }: { loginFailed: boolean }) => {
  const { t } = useUiLanguage();
  const [providers, setProviders] = useState<SignInProvider[] | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setProviders(await authApi.providers());
      } catch {
        setProviders([]);
      }
    })();
  }, []);

  return (
    <div className="flex flex-col gap-3 text-sm">
      <p>{t('tiered.user.intro')}</p>
      {loginFailed ? <p className="text-red-300">{t('tiered.user.loginFailed')}</p> : null}
      {providers === null ? null : providers.length === 0 ? (
        <p className="text-amber-300">{t('tiered.user.noProviders')}</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {providers.map((provider) => (
            <a key={provider} href={signInUrl(provider)} className={cn(PILL_BUTTON, PROVIDER_TONE[provider])}>
              {t('tiered.user.signInWith', {
                provider: t(`tiered.user.provider.${provider}` as UiTextKey),
              })}
            </a>
          ))}
        </div>
      )}
    </div>
  );
};

type SaveState = { kind: 'idle' } | { kind: 'saving' } | { kind: 'saved' } | { kind: 'error'; message: string };

const SignedIn = ({ user, onSignOut }: { user: CurrentUser; onSignOut: () => Promise<void> }) => {
  const { t } = useUiLanguage();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // What the user typed but has not saved yet: absent = unchanged,
  // "" = remove the stored key on save.
  const [draft, setDraft] = useState<UserSettingsUpdate>({});
  const [save, setSave] = useState<SaveState>({ kind: 'idle' });

  useEffect(() => {
    void (async () => {
      try {
        setSettings(await settingsApi.get());
        setLoadError(null);
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : String(error));
      }
    })();
  }, []);

  const modelId = draft.llm_model ?? settings?.llm_model ?? '';
  const model = useMemo(
    () => settings?.models.find((choice) => choice.id === modelId) ?? null,
    [settings, modelId],
  );
  const isDirty = Object.keys(draft).length > 0;
  const isReady = Boolean(settings?.llm_model && settings?.llm_api_key.set);

  const setField = (field: keyof UserSettingsUpdate, value: string | undefined) => {
    setSave({ kind: 'idle' });
    setDraft((prev) => {
      const next = { ...prev };
      if (value === undefined) {
        delete next[field];
      } else {
        next[field] = value;
      }
      return next;
    });
  };

  const handleSave = async () => {
    if (!isDirty) {
      return;
    }
    setSave({ kind: 'saving' });
    try {
      setSettings(await settingsApi.update(draft));
      setDraft({});
      setSave({ kind: 'saved' });
    } catch (error) {
      setSave({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    }
  };

  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {user.avatar_url ? (
            <img src={user.avatar_url} alt="" width={32} height={32} className="h-8 w-8 rounded-full" />
          ) : (
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-800 font-semibold text-gray-300">
              {(user.display_name || user.email || '?').slice(0, 1).toUpperCase()}
            </span>
          )}
          <div className="flex flex-col">
            <span className="font-semibold text-gray-200">{user.display_name || user.email}</span>
            {user.display_name && user.email ? (
              <span className="text-xs text-gray-500">{user.email}</span>
            ) : null}
          </div>
        </div>
        <button type="button" onClick={() => void onSignOut()} className={cn(PILL_BUTTON, ALT_COLOR.gray)}>
          <LogOut className="h-3 w-3" />
          {t('tiered.user.signOut')}
        </button>
      </div>

      {loadError ? <p className="text-red-300">{loadError}</p> : null}
      {settings ? (
        <>
          <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-2">
              <span className="font-semibold text-gray-300">{t('tiered.user.model')}</span>
              <select
                value={modelId}
                onChange={(event) => setField('llm_model', event.target.value)}
                className={INPUT}
              >
                <option value="" disabled>
                  {t('tiered.user.modelPh')}
                </option>
                {settings.models.map((choice) => (
                  <option key={choice.id} value={choice.id}>
                    {choice.label} · {choice.provider_label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-2">
              <span className="flex items-center justify-between font-semibold text-gray-300">
                <span>
                  {t('tiered.user.llmKey', { provider: model?.provider_label ?? 'AI' })}
                </span>
                {model ? (
                  <a
                    href={model.key_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-normal text-sky-300 underline decoration-dotted underline-offset-2"
                  >
                    {t('tiered.user.getKey')}
                  </a>
                ) : null}
              </span>
              <input
                type="password"
                autoComplete="off"
                value={draft.llm_api_key ?? ''}
                onChange={(event) => setField('llm_api_key', event.target.value || undefined)}
                placeholder={
                  settings.llm_api_key.set
                    ? t('tiered.user.keySaved', { hint: settings.llm_api_key.hint ?? '' })
                    : t('tiered.user.keyPh')
                }
                aria-label={t('tiered.user.llmKey', { provider: model?.provider_label ?? 'AI' })}
                className={INPUT}
              />
            </label>
          </div>

          <details className="rounded bg-gray-900/60 px-4 py-3">
            <summary className="cursor-pointer text-xs font-semibold text-gray-300">
              {t('tiered.user.dataKeys')}
            </summary>
            <p className="mt-2 text-xs text-gray-500">{t('tiered.user.dataKeysHelp')}</p>
            <div className="mt-3 flex flex-col gap-3">
              {DATA_KEYS.map((name) => {
                const field = DATA_KEY_FIELD[name];
                const status = settings.data_keys[name];
                const pendingRemoval = draft[field] === '';
                const label = t(`tiered.user.key.${name}` as UiTextKey);
                return (
                  <div key={name} className="grid grid-cols-1 items-center gap-2 sm:grid-cols-[8rem_1fr_auto]">
                    <span className="font-semibold text-gray-300">{label}</span>
                    <input
                      type="password"
                      autoComplete="off"
                      value={draft[field] || ''}
                      onChange={(event) => setField(field, event.target.value || undefined)}
                      placeholder={
                        pendingRemoval
                          ? t('tiered.user.willRemove')
                          : status.set
                            ? t('tiered.user.keySaved', { hint: status.hint ?? '' })
                            : t('tiered.user.usingDefault')
                      }
                      aria-label={label}
                      className={INPUT}
                    />
                    {status.set && !pendingRemoval ? (
                      <button
                        type="button"
                        onClick={() => setField(field, '')}
                        className={cn(PILL_BUTTON, ALT_COLOR[1])}
                      >
                        {t('tiered.user.remove')}
                      </button>
                    ) : (
                      <span />
                    )}
                  </div>
                );
              })}
            </div>
          </details>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={!isDirty || save.kind === 'saving'}
              className={cn(PILL_BUTTON, ALT_COLOR[7])}
            >
              <Save className="h-3 w-3" />
              {t('tiered.user.save')}
            </button>
            {save.kind === 'saved' ? <span className="text-emerald-300">{t('tiered.user.saved')}</span> : null}
            {save.kind === 'error' ? (
              <span className="text-red-300">{t('tiered.user.saveError', { error: save.message })}</span>
            ) : null}
          </div>

          {isReady ? (
            <p className="text-emerald-300">
              {t('tiered.user.ready', {
                model: settings.models.find((c) => c.id === settings.llm_model)?.label ?? settings.llm_model ?? '',
                hint: settings.llm_api_key.hint ?? '',
              })}
            </p>
          ) : (
            <p className="text-amber-300">{t('tiered.user.notReady')}</p>
          )}
        </>
      ) : loadError ? null : (
        <LoadingLine />
      )}
    </div>
  );
};
