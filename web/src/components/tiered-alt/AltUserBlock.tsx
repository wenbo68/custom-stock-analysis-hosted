import { useEffect, useState, type ReactNode } from 'react';
import { LogOut } from 'lucide-react';
import { authApi, signInUrl, type CurrentUser, type SignInProvider } from '../../api/auth';
import {
  settingsApi,
  type DataKeyName,
  type ModelChoice,
  type UserSettings,
  type UserSettingsUpdate,
} from '../../api/settings';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { HelpTerm } from '../tiered/terms';
import { AltPill, AltPillRow, AltSelect, AltTextField } from './AltFields';
import { ALT_COLOR, TAG_BASE } from './altStyles';

export interface AltUserBlockProps {
  /** null = signed out; undefined = still asking the server. */
  user: CurrentUser | null | undefined;
  onSignOut: () => Promise<void>;
  /** True when the browser landed here after a failed sign-in. */
  loginFailed?: boolean;
  /** The stored settings as last confirmed by the server — the page
   *  uses them to tell, before a run starts, what is still missing. */
  onSettings?: (settings: UserSettings) => void;
}

// The data-source keys, in field order (owner request 2026-09-14).
const DATA_KEYS: DataKeyName[] = ['fred', 'finnhub', 'alphavantage'];
const DATA_KEY_FIELD: Record<DataKeyName, keyof UserSettingsUpdate> = {
  fred: 'fred_api_key',
  finnhub: 'finnhub_api_key',
  alphavantage: 'alphavantage_api_key',
};
// Where each data vendor hands out a key — the field title links there.
const DATA_KEY_URL: Record<DataKeyName, string> = {
  fred: 'https://fredaccount.stlouisfed.org/apikeys',
  finnhub: 'https://finnhub.io/dashboard',
  alphavantage: 'https://www.alphavantage.co/support/#api-key',
};
const DATA_KEY_HELP: Record<DataKeyName, UiTextKey> = {
  fred: 'tiered.help.fredKey',
  finnhub: 'tiered.help.finnhubKey',
  alphavantage: 'tiered.help.alphavantageKey',
};
const DATA_KEY_PILL: Record<DataKeyName, UiTextKey> = {
  fred: 'tiered.pill.fredKey',
  finnhub: 'tiered.pill.finnhubKey',
  alphavantage: 'tiered.pill.alphavantageKey',
};

// Field colors are positional in the shared palette, like the run form:
// pill N wears color N, and Save wears the next slot.
const TONE = {
  provider: ALT_COLOR[1],
  main: ALT_COLOR[2],
  sub: ALT_COLOR[3],
  llmKey: ALT_COLOR[4],
  fred: ALT_COLOR[5],
  finnhub: ALT_COLOR[6],
  alphavantage: ALT_COLOR[7],
};
// Sign-in buttons take the palette slots after the run form's fields.
const PROVIDER_TONE: Record<SignInProvider, string> = {
  google: ALT_COLOR[6],
  discord: ALT_COLOR[8],
};
const PILL_BUTTON = `${TAG_BASE} cursor-pointer gap-1.5 transition hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-50`;
// The fields share the run form's 6-per-row grid (owner request
// 2026-09-14); the seventh wraps onto a second line.
const FIELD_GRID = 'grid w-full grid-cols-2 gap-2 text-sm sm:grid-cols-6 sm:gap-3 md:gap-4';

// The block above New Run: who is signed in, which AI model answers, and
// whose keys pay. Every choice is saved the moment it is made (no Save
// step, owner request 2026-09-14) — a run started below uses whatever
// the pills show. Keys are write-only here — the server only ever shows
// back the last characters of what it holds.
export const AltUserBlock = ({ user, onSignOut, loginFailed = false, onSettings }: AltUserBlockProps) => {
  if (user === undefined) {
    return <LoadingLine />;
  }
  if (user === null) {
    return <SignedOut loginFailed={loginFailed} />;
  }
  return <SignedIn user={user} onSignOut={onSignOut} onSettings={onSettings} />;
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

interface FieldTitleProps {
  text: string;
  helpKey: UiTextKey;
  /** Where to get the thing — opens in a new tab on click. */
  href?: string;
}

// A field title in the run form's style: hover explains it, click opens
// the page where the key (or the provider's key) is issued.
const FieldTitle = ({ text, helpKey, href }: FieldTitleProps) => (
  <HelpTerm
    helpKey={helpKey}
    underline={false}
    label={
      href ? (
        <a href={href} target="_blank" rel="noreferrer" className="hover:underline">
          {text}
        </a>
      ) : (
        text
      )
    }
  />
);

interface DefaultPillProps {
  tone: string;
  children: ReactNode;
}

// A pill for a value the server supplies when the user brings none —
// nothing to remove, so it is not a button.
const DefaultPill = ({ tone, children }: DefaultPillProps) => (
  <span className={cn(TAG_BASE, tone)}>{children}</span>
);

interface SignedInProps {
  user: CurrentUser;
  onSignOut: () => Promise<void>;
  onSettings?: (settings: UserSettings) => void;
}

const SignedIn = ({ user, onSignOut, onSettings }: SignedInProps) => {
  const { t } = useUiLanguage();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

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

  // The page learns every confirmed state: the first load and each save.
  useEffect(() => {
    if (settings) {
      onSettings?.(settings);
    }
  }, [settings, onSettings]);

  // One change = one save; the server's answer is the new truth.
  const handleChange = async (update: UserSettingsUpdate) => {
    try {
      setSettings(await settingsApi.update(update));
      setSaveError(null);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {user.avatar_url ? (
            <img
              src={user.avatar_url}
              alt=""
              width={32}
              height={32}
              referrerPolicy="no-referrer"
              className="h-8 w-8 rounded-full"
            />
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
        <SettingsForm settings={settings} saveError={saveError} onChange={handleChange} />
      ) : loadError ? null : (
        <LoadingLine />
      )}
    </div>
  );
};

interface SettingsFormProps {
  settings: UserSettings;
  saveError: string | null;
  onChange: (update: UserSettingsUpdate) => Promise<void>;
}

// The seven write-only fields and their pills. A pill shows what the
// server holds; clicking it clears that value. Every change is saved at
// once, so what the pills show is what the next run uses.
const SettingsForm = ({ settings, saveError, onChange }: SettingsFormProps) => {
  const { t } = useUiLanguage();
  // A provider picked before any of its models — models pin the provider
  // themselves, so this only matters while both model fields are empty.
  const [providerPick, setProviderPick] = useState<string | null>(null);

  const modelById = (id: string | null | undefined): ModelChoice | null =>
    settings.models.find((choice) => choice.id === id) ?? null;
  const mainModel = modelById(settings.llm_model);
  const subModel = modelById(settings.llm_sub_model);
  const provider = mainModel?.provider ?? subModel?.provider ?? providerPick;
  const providerModel = settings.models.find((choice) => choice.provider === provider) ?? null;

  const providerOptions = settings.models
    .filter((choice, index, all) => all.findIndex((c) => c.provider === choice.provider) === index)
    .map((choice) => ({ value: choice.provider, label: choice.provider_label }));
  const modelOptions = settings.models
    .filter((choice) => !provider || choice.provider === provider)
    .map((choice) => ({ value: choice.id, label: choice.label }));

  const change = (update: UserSettingsUpdate) => void onChange(update);

  const commitProvider = (value: string) => {
    if (value === provider) {
      // Clicking the picked provider again (or its pill) clears it and
      // the models that pinned it.
      setProviderPick(null);
      change({ llm_model: '', llm_sub_model: '' });
      return;
    }
    setProviderPick(value);
    // One key pays for both models, so a model from another provider goes.
    const update: UserSettingsUpdate = {};
    if (mainModel && mainModel.provider !== value) {
      update.llm_model = '';
    }
    if (subModel && subModel.provider !== value) {
      update.llm_sub_model = '';
    }
    if (Object.keys(update).length > 0) {
      change(update);
    }
  };
  const commitModel = (field: 'llm_model' | 'llm_sub_model', value: string) => {
    const current = field === 'llm_model' ? mainModel : subModel;
    if (value === current?.id) {
      change({ [field]: '' });
      return;
    }
    const update: UserSettingsUpdate = { [field]: value };
    const other = field === 'llm_model' ? subModel : mainModel;
    const picked = modelById(value);
    if (other && picked && other.provider !== picked.provider) {
      update[field === 'llm_model' ? 'llm_sub_model' : 'llm_model'] = '';
    }
    change(update);
  };

  const keyUrl = providerModel?.key_url;

  return (
    <div className="flex w-full flex-col gap-4">
      <div className={FIELD_GRID}>
        <AltSelect
          label={<FieldTitle text={t('tiered.user.f.provider')} helpKey="tiered.help.llmProvider" href={keyUrl} />}
          options={providerOptions}
          selected={provider ? [provider] : undefined}
          placeholder={t('tiered.user.ph.provider')}
          onCommit={commitProvider}
        />
        <AltSelect
          label={<FieldTitle text={t('tiered.user.f.main')} helpKey="tiered.help.mainLlm" href={keyUrl} />}
          options={modelOptions}
          selected={mainModel ? [mainModel.id] : undefined}
          placeholder={t('tiered.user.ph.main')}
          onCommit={(value) => commitModel('llm_model', value)}
        />
        <AltSelect
          label={<FieldTitle text={t('tiered.user.f.sub')} helpKey="tiered.help.subLlm" href={keyUrl} />}
          options={modelOptions}
          selected={subModel ? [subModel.id] : undefined}
          placeholder={t('tiered.user.ph.sub')}
          onCommit={(value) => commitModel('llm_sub_model', value)}
        />
        <AltTextField
          label={<FieldTitle text={t('tiered.user.f.llmKey')} helpKey="tiered.help.llmKey" href={keyUrl} />}
          placeholder={t('tiered.user.ph.llmKey')}
          type="password"
          onCommit={(value) => change({ llm_api_key: value })}
        />
        {DATA_KEYS.map((name) => (
          <AltTextField
            key={name}
            label={
              <FieldTitle
                text={t(`tiered.user.f.${name}` as UiTextKey)}
                helpKey={DATA_KEY_HELP[name]}
                href={DATA_KEY_URL[name]}
              />
            }
            placeholder={t(`tiered.user.ph.${name}` as UiTextKey)}
            type="password"
            onCommit={(value) => change({ [DATA_KEY_FIELD[name]]: value })}
          />
        ))}
      </div>

      <AltPillRow>
        {provider ? (
          <AltPill tone={TONE.provider} onRemove={() => commitProvider(provider)}>
            {t('tiered.pill.llmProvider', { value: providerModel?.provider_label ?? provider })}
          </AltPill>
        ) : null}
        {mainModel ? (
          <AltPill tone={TONE.main} onRemove={() => change({ llm_model: '' })}>
            {t('tiered.pill.mainLlm', { value: mainModel.label })}
          </AltPill>
        ) : null}
        {subModel ? (
          <AltPill tone={TONE.sub} onRemove={() => change({ llm_sub_model: '' })}>
            {t('tiered.pill.subLlm', { value: subModel.label })}
          </AltPill>
        ) : null}
        {settings.llm_api_key.set ? (
          <AltPill tone={TONE.llmKey} onRemove={() => change({ llm_api_key: '' })}>
            {t('tiered.pill.llmKey', { value: settings.llm_api_key.hint ?? '' })}
          </AltPill>
        ) : null}
        {DATA_KEYS.map((name) => {
          const stored = settings.data_keys[name];
          return stored.set ? (
            <AltPill key={name} tone={TONE[name]} onRemove={() => change({ [DATA_KEY_FIELD[name]]: '' })}>
              {t(DATA_KEY_PILL[name], { value: stored.hint ?? '' })}
            </AltPill>
          ) : (
            <DefaultPill key={name} tone={TONE[name]}>
              {t(DATA_KEY_PILL[name], { value: t('tiered.user.default') })}
            </DefaultPill>
          );
        })}
      </AltPillRow>

      {saveError ? <p className="text-red-300">{t('tiered.user.saveError', { error: saveError })}</p> : null}
    </div>
  );
};
