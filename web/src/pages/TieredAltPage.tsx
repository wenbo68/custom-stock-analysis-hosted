import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import {
  tieredApi,
  type TieredDepth,
  type TieredDuplicateRun,
  type TieredMarketOpenGate,
  type TieredResult,
  type TieredRunSummary,
  type TieredSizingRequest,
} from '../api/tiered';
import { riskPctText } from '../components/tiered-alt/altFormat';
import { AltRunForm } from '../components/tiered-alt/AltRunForm';
import { AltRunHistory } from '../components/tiered-alt/AltRunHistory';
import { AltUserBlock } from '../components/tiered-alt/AltUserBlock';
import type { UserSettings } from '../api/settings';
import { useCurrentUser } from '../contexts/CurrentUserContext';
import { useUiLanguage } from '../contexts/UiLanguageContext';

const POLL_INTERVAL_MS = 5000;
const DEFAULT_TIER: TieredDepth = 1;
// Suggestions when nothing was remembered or configured — the user still
// sees and can remove/replace the pill before starting.
const DEFAULT_CAPITAL = '100000';
const DEFAULT_RISK_PCT = '1';
// Reward-to-risk ratio the plan aims for (owner decision, 2026-07-21):
// required like every other field, default 2. (There is no ownership
// input: held shares would belong to a future portfolio feature.)
const DEFAULT_REWARD = '2';
// Max hold time in weeks (owner decision 2026-08-08): required, default
// 2 — feeds the AI prompts, the report and the forward-test window.
const DEFAULT_HOLD_WEEKS = '2';

// Shared with the main tiered page so the values carry across both skins.
const SIZING_CAPITAL_STORAGE_KEY = 'tiered.sizing.capital';
const SIZING_RISK_PCT_STORAGE_KEY = 'tiered.sizing.riskPct';
const SIZING_REWARD_STORAGE_KEY = 'tiered.sizing.reward';
const HOLD_WEEKS_STORAGE_KEY = 'tiered.holdWeeks';

// The gate payload when the backend rejected the start because the
// ticker's market is inside the trading day (409 with the market_open
// code); null for every other error.
function marketOpenRejection(error: unknown): TieredMarketOpenGate | null {
  if (!axios.isAxiosError(error) || error.response?.status !== 409) {
    return null;
  }
  const detail = (
    error.response.data as {
      detail?: { code?: string; market?: string; session_open?: string; session_close?: string };
    } | undefined
  )?.detail;
  if (detail?.code !== 'market_open') {
    return null;
  }
  return {
    market: detail.market ?? null,
    sessionOpen: detail.session_open ?? null,
    sessionClose: detail.session_close ?? null,
  };
}

// The duplicate payload when the backend refused the start because the
// user's own unfinished run has the same ticker and inputs (409 with the
// duplicate_run code); null for every other error.
function duplicateRejection(error: unknown): TieredDuplicateRun | null {
  if (!axios.isAxiosError(error) || error.response?.status !== 409) {
    return null;
  }
  const detail = (
    error.response.data as {
      detail?: { code?: string; task_id?: string; status?: string };
    } | undefined
  )?.detail;
  if (detail?.code !== 'duplicate_run' || !detail.task_id) {
    return null;
  }
  return {
    taskId: detail.task_id,
    status:
      detail.status === 'running' ? 'running' : detail.status === 'waiting' ? 'waiting' : 'queued',
  };
}

function readStoredNumber(key: string): string | null {
  try {
    return window.localStorage.getItem(key) || null;
  } catch {
    return null;
  }
}

function storeNumber(key: string, value: string | null): void {
  try {
    if (value) {
      window.localStorage.setItem(key, value);
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    // storage unavailable (private mode) — the run still works
  }
}

// Alternate skin for tiered analysis, styled after showplayer.net. Two
// section cards with their titles sitting above: the new-run form
// (write-only fields + pills + Start) and the run history (filters +
// paged rows that expand into the full report).
const TieredAltPage = () => {
  const { t } = useUiLanguage();
  const { user, signOut } = useCurrentUser();
  // The sign-in callback lands on "/?login=failed" when consent was
  // denied or the provider errored; the user block words it.
  const loginFailed = useMemo(
    () => new URLSearchParams(window.location.search).get('login') === 'failed',
    [],
  );
  // The account section's stored settings, as last confirmed by the
  // server; null until loaded or when signed out.
  const [account, setAccount] = useState<UserSettings | null>(null);
  useEffect(() => {
    if (!user) {
      setAccount(null);
    }
  }, [user]);
  const [ticker, setTicker] = useState<string | null>(null);
  const [tier, setTier] = useState<TieredDepth | null>(DEFAULT_TIER);
  // Capital is in the ticker's own currency, so it stays empty until a
  // ticker is picked; capitalDefault is what it then auto-fills with.
  const [capital, setCapital] = useState<string | null>(null);
  const [capitalDefault, setCapitalDefault] = useState<string>(
    () => readStoredNumber(SIZING_CAPITAL_STORAGE_KEY) ?? DEFAULT_CAPITAL,
  );
  const [riskPct, setRiskPct] = useState<string | null>(
    () => readStoredNumber(SIZING_RISK_PCT_STORAGE_KEY) ?? DEFAULT_RISK_PCT,
  );
  const [reward, setReward] = useState<string | null>(
    () => readStoredNumber(SIZING_REWARD_STORAGE_KEY) ?? DEFAULT_REWARD,
  );
  const [hold, setHold] = useState<string | null>(
    () => readStoredNumber(HOLD_WEEKS_STORAGE_KEY) ?? DEFAULT_HOLD_WEEKS,
  );
  // Clock-gate popup: the 409 market_open payload while it's showing.
  const [gate, setGate] = useState<TieredMarketOpenGate | null>(null);
  // Duplicate-run popup: the 409 duplicate_run payload while it's showing.
  const [duplicate, setDuplicate] = useState<TieredDuplicateRun | null>(null);
  const [runs, setRuns] = useState<TieredRunSummary[]>([]);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, TieredResult>>({});
  const [detailError, setDetailError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Tier of runs this page started, so their rows show it while still
  // running (the backend only knows a run's tier once the report exists).
  const [pendingTiers, setPendingTiers] = useState<Record<string, TieredDepth>>({});
  const loadingDetailRef = useRef<string | null>(null);

  // Poll while anything is still in flight — queued and waiting runs
  // start by themselves, so they need the same polling as a running one.
  const anyRunning = useMemo(
    () =>
      runs.some(
        (run) => run.status === 'running' || run.status === 'queued' || run.status === 'waiting',
      ),
    [runs],
  );

  // Run history is per account: nothing to list while signed out, and a
  // sign-out clears what the previous account was looking at.
  const refreshRuns = useCallback(async () => {
    if (!user) {
      return;
    }
    try {
      const items = await tieredApi.listRuns();
      setRuns(items);
    } catch {
      // transient — next poll retries
    }
  }, [user]);

  useEffect(() => {
    if (user) {
      void refreshRuns();
    } else {
      setRuns([]);
      setExpandedTaskId(null);
      setDetails({});
    }
  }, [user, refreshRuns]);

  const handleSignOut = useCallback(async () => {
    await signOut();
    setSubmitError(null);
  }, [signOut]);

  // Server-side sizing defaults (.env) beat the built-in suggestions when
  // the browser has no remembered values of its own.
  useEffect(() => {
    void (async () => {
      try {
        const defaults = await tieredApi.sizingDefaults();
        const storedCapital = readStoredNumber(SIZING_CAPITAL_STORAGE_KEY);
        const defaultCapital = defaults.capital;
        if (storedCapital == null && defaultCapital != null) {
          setCapitalDefault(String(defaultCapital));
        }
        const storedRisk = readStoredNumber(SIZING_RISK_PCT_STORAGE_KEY);
        const defaultRisk = defaults.risk_fraction;
        if (storedRisk == null && defaultRisk != null) {
          setRiskPct((prev) =>
            prev === null || prev === DEFAULT_RISK_PCT ? riskPctText(defaultRisk) : prev,
          );
        }
        const storedReward = readStoredNumber(SIZING_REWARD_STORAGE_KEY);
        const defaultReward = defaults.reward_risk;
        if (storedReward == null && defaultReward != null) {
          setReward((prev) =>
            prev === null || prev === DEFAULT_REWARD ? String(defaultReward) : prev,
          );
        }
      } catch {
        // no defaults reachable — the built-in suggestions stand
      }
    })();
  }, []);

  useEffect(() => {
    if (!anyRunning) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshRuns();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [anyRunning, refreshRuns]);

  const expandedRun = useMemo(
    () => runs.find((run) => run.task_id === expandedTaskId) ?? null,
    [runs, expandedTaskId],
  );

  // Rows the backend can't tier yet (still running) get the tier this
  // page submitted them with.
  const annotatedRuns = useMemo(
    () =>
      runs.map((run) =>
        run.tier == null && pendingTiers[run.task_id]
          ? { ...run, tier: pendingTiers[run.task_id] }
          : run,
      ),
    [runs, pendingTiers],
  );

  // Fetch the full report the first time a finished run is expanded (a run
  // started as Running loads here too, the moment polling flips it to done).
  useEffect(() => {
    const taskId = expandedTaskId;
    if (!taskId || expandedRun?.status !== 'done' || details[taskId]) {
      return;
    }
    if (loadingDetailRef.current === taskId) {
      return;
    }
    loadingDetailRef.current = taskId;
    void (async () => {
      try {
        const run = await tieredApi.getRun(taskId);
        const result = run.result;
        if (result) {
          setDetails((prev) => ({ ...prev, [taskId]: result }));
          setDetailError(null);
        } else {
          setDetailError(run.error || t('tiered.error.title'));
        }
      } catch (error) {
        setDetailError(error instanceof Error ? error.message : String(error));
      } finally {
        loadingDetailRef.current = null;
      }
    })();
  }, [expandedTaskId, expandedRun?.status, details, t]);

  const handleToggle = useCallback((taskId: string) => {
    setDetailError(null);
    setExpandedTaskId((prev) => (prev === taskId ? null : taskId));
  }, []);

  // Capital follows the ticker: picking a ticker auto-fills capital with
  // the remembered/default amount; removing the ticker removes capital too
  // (the amount's currency belongs to that ticker's market).
  const handleTicker = useCallback(
    (value: string | null) => {
      setTicker(value);
      if (value === null) {
        setCapital(null);
      } else {
        setCapital((prev) => prev ?? capitalDefault);
      }
    },
    [capitalDefault],
  );

  const handleStart = useCallback(
    async (runAnyway = false) => {
      // The form popup enforces every field; this is the last-line guard.
      if (!ticker || tier === null || !capital || !riskPct || !reward || !hold || submitting || !user) {
        return;
      }
      setSubmitError(null);
      setGate(null);
      setDuplicate(null);
      setSubmitting(true);
      try {
        const sizing: TieredSizingRequest = {};
        const capitalValue = Number(capital);
        if (capital && Number.isFinite(capitalValue) && capitalValue > 0) {
          sizing.capital = capitalValue;
        }
        const pctValue = Number(riskPct);
        if (riskPct && Number.isFinite(pctValue) && pctValue > 0 && pctValue < 100) {
          sizing.risk_fraction = pctValue / 100;
        }
        const rewardValue = Number(reward);
        if (reward && Number.isFinite(rewardValue) && rewardValue > 1 && rewardValue <= 10) {
          sizing.reward_risk = rewardValue;
        }
        const tierUsed = tier ?? DEFAULT_TIER;
        const holdValue = Number(hold);
        const started = await tieredApi.start(
          ticker,
          tierUsed,
          Object.keys(sizing).length > 0 ? sizing : undefined,
          {
            ...(Number.isInteger(holdValue) && holdValue >= 1 && holdValue <= 4
              ? { holdWeeks: holdValue }
              : {}),
            ...(runAnyway ? { runAnyway: true } : {}),
          },
        );
        storeNumber(SIZING_CAPITAL_STORAGE_KEY, capital);
        storeNumber(SIZING_RISK_PCT_STORAGE_KEY, riskPct);
        storeNumber(SIZING_REWARD_STORAGE_KEY, reward);
        storeNumber(HOLD_WEEKS_STORAGE_KEY, hold);
        setCapitalDefault(capital);
        setTicker(null);
        setCapital(null);
        setPendingTiers((prev) => ({ ...prev, [started.task_id]: tierUsed }));
        // The new run is already in the backend list as Running; show it at
        // the top of the history, expanded, until polling flips it to done.
        await refreshRuns();
        setDetailError(null);
        setExpandedTaskId(started.task_id);
      } catch (error) {
        const rejection = marketOpenRejection(error);
        const duplicated = duplicateRejection(error);
        if (rejection) {
          // Clock gate: not an error — a choice. The popup offers
          // "run anyway" (analyze the previous completed session).
          setGate(rejection);
        } else if (duplicated) {
          // Same run already waiting or running: the Start popup says
          // so and the history shows that run.
          setDuplicate(duplicated);
          await refreshRuns();
          setDetailError(null);
          setExpandedTaskId(duplicated.taskId);
        } else {
          setSubmitError(error instanceof Error ? error.message : String(error));
        }
      } finally {
        setSubmitting(false);
      }
    },
    [ticker, submitting, tier, capital, riskPct, reward, hold, refreshRuns, user],
  );

  return (
    <main className="mx-auto flex min-h-full w-full max-w-7xl flex-col gap-6 px-4 pb-8 pt-4 md:px-6 lg:px-8">
      <section className="flex flex-col gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          {t('tiered.user.title')}
        </h2>
        <div className="rounded bg-gray-900 p-4 text-gray-400 sm:p-6">
          <AltUserBlock user={user} onSignOut={handleSignOut} loginFailed={loginFailed} onSettings={setAccount} />
        </div>
      </section>

      {/* The run sections only make sense with an account behind them
          (owner request 2026-09-15): signed out, the page is the sign-in
          block alone. */}
      {user ? (
        <>
        <section className="flex flex-col gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
            {t('tiered.altForm.title')}
          </h2>
          <div className="rounded bg-gray-900 p-4 text-gray-400 sm:p-6">
            <AltRunForm
              ticker={ticker}
              tier={tier}
              capital={capital}
              riskPct={riskPct}
              reward={reward}
              hold={hold}
              submitting={submitting}
              error={submitError}
              gate={gate}
              duplicate={duplicate}
              signedIn={Boolean(user)}
              hasMainLlm={Boolean(account?.llm_model)}
              hasLlmKey={Boolean(account?.llm_api_key.set)}
              onTicker={handleTicker}
              onTier={setTier}
              onCapital={setCapital}
              onRiskPct={setRiskPct}
              onReward={setReward}
              onHold={setHold}
              onStart={() => void handleStart()}
              onRunAnyway={() => void handleStart(true)}
              onGateClose={() => setGate(null)}
              onDuplicateClose={() => setDuplicate(null)}
            />
          </div>
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
            {t('tiered.history')}
          </h2>
          <div className="rounded bg-gray-900 p-4 text-gray-400 sm:p-6">
            <AltRunHistory
              runs={annotatedRuns}
              expandedTaskId={expandedTaskId}
              expandedResult={expandedTaskId ? (details[expandedTaskId] ?? null) : null}
              expandedError={detailError}
              onToggle={handleToggle}
            />
          </div>
        </section>
        </>
      ) : null}
    </main>
  );
};

export default TieredAltPage;
