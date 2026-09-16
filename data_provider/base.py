# -*- coding: utf-8 -*-
"""
===================================
数据源基类与管理器
===================================

设计模式：策略模式 (Strategy Pattern)
- BaseFetcher: 抽象基类，定义统一的日线接口
- DataFetcherManager: 策略管理器，实现自动切换

防封禁策略：
1. 每个 Fetcher 内置流控逻辑
2. 失败自动切换到下一个数据源
3. 指数退避重试机制

This package serves one job for the tiered-analysis app: daily OHLCV bars
for A-share (cn), Hong Kong (hk) and US symbols, plus the market-tag and
symbol-classification helpers that ride along with it.
"""

import logging
import random
import time
from threading import RLock
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict

import pandas as pd
from src.services.market_symbol_utils import is_suffix_market_symbol
from .circuit_breaker import CircuitBreaker
from .us_index_mapping import is_us_index_code, is_us_stock_code


# 配置日志
logger = logging.getLogger(__name__)


# === 标准化列名定义 ===
STANDARD_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']


def unwrap_exception(exc: Exception) -> Exception:
    """
    Follow chained exceptions and return the deepest non-cyclic cause.
    """
    current = exc
    visited = set()

    while current is not None and id(current) not in visited:
        visited.add(id(current))
        next_exc = current.__cause__ or current.__context__
        if next_exc is None:
            break
        current = next_exc

    return current


def summarize_exception(exc: Exception) -> Tuple[str, str]:
    """
    Build a stable summary for logs while preserving the application-layer message.
    """
    root = unwrap_exception(exc)
    error_type = type(root).__name__
    message = str(exc).strip() or str(root).strip() or error_type
    return error_type, " ".join(message.split())


def normalize_stock_code(stock_code: str) -> str:
    """
    Normalize stock code by stripping exchange prefixes/suffixes.

    Accepted formats and their normalized results:
    - '600519'      -> '600519'   (already clean)
    - 'SH600519'    -> '600519'   (strip SH prefix)
    - 'SH.600519'   -> '600519'   (strip SH. prefix)
    - 'SZ000001'    -> '000001'   (strip SZ prefix)
    - 'SS600519'    -> '600519'   (strip legacy Yahoo Shanghai prefix)
    - 'SZ.000001'   -> '000001'   (strip SZ. prefix)
    - 'BJ920748'    -> '920748'   (strip BJ prefix, BSE)
    - 'BJ.920748'   -> '920748'   (strip BJ. prefix, BSE)
    - 'sh600519'    -> '600519'   (case-insensitive)
    - '600519.SH'   -> '600519'   (strip .SH suffix)
    - '000001.SZ'   -> '000001'   (strip .SZ suffix)
    - '920748.BJ'   -> '920748'   (strip .BJ suffix, BSE)
    - 'HK00700'     -> 'HK00700'  (keep HK prefix for HK stocks)
    - '1810.HK'     -> 'HK01810'  (normalize HK suffix to canonical prefix form)
    - '7203.T'      -> '7203.T'   (keep Japan Yahoo suffix form)
    - '005930.KS'   -> '005930.KS' (keep Korea Yahoo suffix form)
    - '2330.TW'     -> '2330.TW'  (keep Taiwan TWSE Yahoo suffix form)
    - '6505.TWO'    -> '6505.TWO' (keep Taiwan TPEx Yahoo suffix form)
    - 'AAPL'        -> 'AAPL'     (keep US stock ticker as-is)

    This function is applied at the DataProviderManager layer so that
    all individual fetchers receive a clean 6-digit code (for A-shares/ETFs).
    """
    code = stock_code.strip()
    upper = code.upper()

    # Normalize HK prefix to a canonical 5-digit form (e.g. hk1810 -> HK01810)
    if upper.startswith('HK') and not upper.startswith('HK.'):
        candidate = upper[2:]
        if candidate.isdigit() and 1 <= len(candidate) <= 5:
            return f"HK{candidate.zfill(5)}"

    # Strip SH/SZ/SS prefix (e.g. SH600519 -> 600519, SS600519 -> 600519)
    if upper.startswith(('SH', 'SZ', 'SS')) and not upper.startswith(('SH.', 'SZ.', 'SS.')):
        candidate = code[2:]
        # Only strip if the remainder looks like a valid numeric code
        if candidate.isdigit() and len(candidate) in (5, 6):
            return candidate

    # Strip dotted SH/SZ/SS prefix (e.g. SH.600519 -> 600519)
    if upper.startswith(('SH.', 'SZ.', 'SS.')):
        candidate = code[3:]
        if candidate.isdigit() and len(candidate) in (5, 6):
            return candidate

    # Strip BJ prefix (e.g. BJ920748 -> 920748)
    if upper.startswith('BJ') and not upper.startswith('BJ.'):
        candidate = code[2:]
        if candidate.isdigit() and len(candidate) == 6:
            return candidate

    # Strip dotted BJ prefix (e.g. BJ.920748 -> 920748)
    if upper.startswith('BJ.'):
        candidate = code[3:]
        if candidate.isdigit() and len(candidate) == 6:
            return candidate

    # Strip .SH/.SZ/.BJ suffix (e.g. 600519.SH -> 600519, 920748.BJ -> 920748)
    # while preserving explicit Yahoo suffix forms for JP/KR/TW.
    if '.' in code:
        base, suffix = code.rsplit('.', 1)
        if suffix.upper() == 'T' and base.isdigit() and len(base) in (4, 5):
            return f"{base}.{suffix.upper()}"
        if suffix.upper() in ('KS', 'KQ') and base.isdigit() and len(base) == 6:
            return f"{base}.{suffix.upper()}"
        if suffix.upper() in ('TW', 'TWO') and base.isdigit() and 4 <= len(base) <= 6:
            return f"{base}.{suffix.upper()}"
        if suffix.upper() == 'HK' and base.isdigit() and 1 <= len(base) <= 5:
            return f"HK{base.zfill(5)}"
        if base.upper() in ('SH', 'SS', 'SZ', 'BJ') and suffix.isdigit():
            return suffix
        if suffix.upper() in ('SH', 'SZ', 'SS', 'BJ') and base.isdigit():
            return base

    return code


ETF_PREFIXES = ("51", "52", "56", "58", "15", "16", "18")


def _is_us_market(code: str) -> bool:
    """判断是否为美股/美股指数代码（不含中文前后缀）。"""
    normalized = (code or "").strip().upper()
    return is_us_index_code(normalized) or is_us_stock_code(normalized)


def _is_hk_market(code: str) -> bool:
    """
    判定是否为港股代码。

    支持 `HK00700` 及纯 5 位数字形式（A 股 ETF/股票常见为 6 位）。
    """
    normalized = (code or "").strip().upper()
    if normalized.endswith(".HK"):
        base = normalized[:-3]
        return base.isdigit() and 1 <= len(base) <= 5
    if normalized.startswith("HK"):
        digits = normalized[2:]
        return digits.isdigit() and 1 <= len(digits) <= 5
    if normalized.isdigit() and len(normalized) == 5:
        return True
    return False


def _is_jp_market(code: str) -> bool:
    """判定是否为日本 Yahoo Finance suffix 代码（如 7203.T）。"""
    return is_suffix_market_symbol(code, "jp")


def _is_kr_market(code: str) -> bool:
    """判定是否为韩国 Yahoo Finance suffix 代码（如 005930.KS / 035720.KQ）。"""
    return is_suffix_market_symbol(code, "kr")


def _is_tw_market(code: str) -> bool:
    """判定是否为台湾 Yahoo Finance suffix 代码（TWSE 上市 2330.TW / TPEx 上柜 6505.TWO）。

    台股 base 为 4-6 位（普通股 4 位，ETF/其他至 6 位，如 00878 / 006208）。
    仅带 .TW/.TWO 后缀的代码才识别为台股，裸 6 位代码仍按 A 股语义处理。
    """
    return is_suffix_market_symbol(code, "tw")


def _is_etf_code(code: str) -> bool:
    """判定 A 股 ETF 基金代码（保守规则）。"""
    normalized = normalize_stock_code(code)
    return (
        normalized.isdigit()
        and len(normalized) == 6
        and normalized.startswith(ETF_PREFIXES)
    )


def _market_tag(code: str) -> str:
    """返回市场标签: cn/us/hk/jp/kr/tw."""
    if _is_us_market(code):
        return "us"
    if _is_hk_market(code):
        return "hk"
    if _is_jp_market(code):
        return "jp"
    if _is_kr_market(code):
        return "kr"
    if _is_tw_market(code):
        return "tw"
    return "cn"


def is_bse_code(code: str) -> bool:
    """
    Check if the code is a Beijing Stock Exchange (BSE) A-share code.

    BSE rules (2026):
    - New format (2024+): 92xxxx main trading codes
    - Historical ranges: 43xxxx, 83xxxx, 87xxxx, 88xxxx
    - Special instruments: 81xxxx convertible bonds, 82xxxx preferred shares
    - Subscription codes: 889xxx
    Note: 900xxx are Shanghai B-shares and must return False.
    """
    c = (code or "").strip().split(".")[0]
    if len(c) != 6 or not c.isdigit():
        return False

    if c.startswith("900"):
        return False

    return c.startswith(("92", "43", "81", "82", "83", "87", "88"))


class DataFetchError(Exception):
    """数据获取异常基类"""
    pass


class RateLimitError(DataFetchError):
    """API 速率限制异常"""
    pass


class BaseFetcher(ABC):
    """
    数据源抽象基类

    职责：
    1. 定义统一的日线获取接口
    2. 提供数据标准化方法

    子类实现：
    - _fetch_raw_data(): 从具体数据源获取原始数据
    - _normalize_data(): 将原始数据转换为标准格式
    """

    name: str = "BaseFetcher"
    priority: int = 99  # 优先级数字越小越优先
    allow_empty_daily_data: bool = False

    @abstractmethod
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从数据源获取原始数据（子类必须实现）

        Args:
            stock_code: 股票代码，如 '600519', '000001'
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期，格式 'YYYY-MM-DD'

        Returns:
            原始数据 DataFrame（列名因数据源而异）
        """
        pass

    @abstractmethod
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化数据列名（子类必须实现）

        将不同数据源的列名统一为：
        ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        """
        pass

    def get_daily_data(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30
    ) -> pd.DataFrame:
        """
        获取日线数据（统一入口）

        流程：
        1. 计算日期范围
        2. 调用子类获取原始数据
        3. 标准化列名
        4. 数据清洗

        Args:
            stock_code: 股票代码
            start_date: 开始日期（可选）
            end_date: 结束日期（可选，默认今天）
            days: 获取天数（当 start_date 未指定时使用）

        Returns:
            标准化的 DataFrame
        """
        # 计算日期范围
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        if start_date is None:
            # 默认获取最近 30 个交易日（按日历日估算，多取一些）
            start_dt = datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days * 2)
            start_date = start_dt.strftime('%Y-%m-%d')

        request_start = time.time()
        logger.info(f"[{self.name}] 开始获取 {stock_code} 日线数据: 范围={start_date} ~ {end_date}")

        try:
            # Step 1: 获取原始数据
            raw_df = self._fetch_raw_data(stock_code, start_date, end_date)

            if raw_df is None:
                raise DataFetchError(f"[{self.name}] 未获取到 {stock_code} 的数据")
            if raw_df.empty:
                elapsed = time.time() - request_start
                logger.info(
                    f"[{self.name}] {stock_code} 返回空日线结果: 范围={start_date} ~ {end_date}, "
                    f"elapsed={elapsed:.2f}s"
                )
                if self.allow_empty_daily_data:
                    return pd.DataFrame(columns=STANDARD_COLUMNS)
                raise DataFetchError(f"[{self.name}] 未获取到 {stock_code} 的数据")

            # Step 2: 标准化列名
            df = self._normalize_data(raw_df, stock_code)

            # Step 3: 数据清洗
            df = self._clean_data(df)

            elapsed = time.time() - request_start
            logger.info(
                f"[{self.name}] {stock_code} 获取成功: 范围={start_date} ~ {end_date}, "
                f"rows={len(df)}, elapsed={elapsed:.2f}s"
            )
            return df

        except Exception as e:
            elapsed = time.time() - request_start
            error_type, error_reason = summarize_exception(e)
            logger.error(
                f"[{self.name}] {stock_code} 获取失败: 范围={start_date} ~ {end_date}, "
                f"error_type={error_type}, elapsed={elapsed:.2f}s, reason={error_reason}"
            )
            raise DataFetchError(f"[{self.name}] {stock_code}: {error_reason}") from e

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        数据清洗

        处理：
        1. 确保日期列格式正确
        2. 数值类型转换
        3. 去除空值行
        4. 按日期排序
        """
        df = df.copy()

        # 确保日期列为 datetime 类型
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])

        # 数值列类型转换
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 去除关键列为空的行
        df = df.dropna(subset=['close', 'volume'])

        # 按日期升序排序
        df = df.sort_values('date', ascending=True).reset_index(drop=True)

        return df

    @staticmethod
    def random_sleep(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """
        智能随机休眠（Jitter）

        防封禁策略：模拟人类行为的随机延迟
        在请求之间加入不规则的等待时间
        """
        sleep_time = random.uniform(min_seconds, max_seconds)
        logger.debug(f"随机休眠 {sleep_time:.2f} 秒...")
        time.sleep(sleep_time)


class DataFetcherManager:
    """
    数据源策略管理器

    职责：
    1. 管理多个数据源（按优先级排序）
    2. 自动故障切换（Failover）
    3. 提供统一的日线获取接口

    切换策略：
    - 优先使用高优先级数据源
    - 失败后自动切换到下一个
    - 所有数据源都失败时抛出异常
    """

    _DAILY_MARKET_FETCHER_SUPPORT = {
        "EfinanceFetcher": {"cn"},
        "TencentFetcher": {"cn"},
        "AkshareFetcher": {"cn", "hk"},
        "YfinanceFetcher": {"cn", "hk", "us", "jp", "kr", "tw"},
        "FinnhubFetcher": {"us"},
        "AlphaVantageFetcher": {"us"},
    }
    _daily_source_health = CircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)

    def __init__(self, fetchers: Optional[List[BaseFetcher]] = None):
        """
        初始化管理器

        Args:
            fetchers: 数据源列表（可选，默认按优先级自动创建）
        """
        self._fetchers: List[BaseFetcher] = []
        self._fetchers_lock = RLock()
        self._fetchers_by_name: Dict[str, BaseFetcher] = {}
        self._fetcher_call_locks: Dict[int, RLock] = {}
        self._fetcher_call_locks_lock = RLock()

        if fetchers:
            # 按优先级排序
            self._fetchers = sorted(fetchers, key=lambda f: f.priority)
            self._refresh_fetcher_indexes_locked()
        else:
            self._init_default_fetchers()

    def _ensure_concurrency_guards(self) -> None:
        """Lazily initialize thread-safety primitives for test scaffolds using __new__."""
        if not hasattr(self, "_fetchers_lock") or self._fetchers_lock is None:
            self._fetchers_lock = RLock()
        if not hasattr(self, "_fetchers_by_name") or self._fetchers_by_name is None:
            self._fetchers_by_name = {}
        if not hasattr(self, "_fetcher_call_locks") or self._fetcher_call_locks is None:
            self._fetcher_call_locks = {}
        if not hasattr(self, "_fetcher_call_locks_lock") or self._fetcher_call_locks_lock is None:
            self._fetcher_call_locks_lock = RLock()

    def _get_fetchers_snapshot(self) -> List[BaseFetcher]:
        self._ensure_concurrency_guards()
        with self._fetchers_lock:
            return list(getattr(self, "_fetchers", []))

    def _refresh_fetcher_indexes_locked(self) -> None:
        self._fetchers_by_name = {fetcher.name: fetcher for fetcher in self._fetchers}

    @staticmethod
    def _call_availability_probe(fetcher: BaseFetcher, probe_name: str, capability: str) -> Optional[bool]:
        probe = getattr(fetcher, probe_name, None)
        if not callable(probe):
            return None
        try:
            if probe_name == "is_available_for_request":
                return bool(probe(capability))
            return bool(probe())
        except TypeError:
            return bool(probe())
        except Exception as exc:
            logger.debug(
                "[数据源可用性] %s.%s 检查失败(capability=%s): %s",
                fetcher.name,
                probe_name,
                capability or "default",
                exc,
            )
            return False

    @classmethod
    def _is_fetcher_available(cls, fetcher: BaseFetcher, capability: str = "") -> bool:
        for probe_name in ("is_available_for_request", "is_available", "_is_available"):
            result = cls._call_availability_probe(fetcher, probe_name, capability)
            if result is not None:
                return result
        return True

    def _get_fetcher_call_lock(self, fetcher: BaseFetcher) -> RLock:
        self._ensure_concurrency_guards()
        fetcher_id = id(fetcher)
        with self._fetcher_call_locks_lock:
            lock = self._fetcher_call_locks.get(fetcher_id)
            if lock is None:
                lock = RLock()
                self._fetcher_call_locks[fetcher_id] = lock
            return lock

    def _call_fetcher_method(self, fetcher: BaseFetcher, method_name: str, *args, **kwargs):
        """Serialize shared fetcher state access through manager-owned per-instance locks."""
        method = getattr(fetcher, method_name)
        with self._get_fetcher_call_lock(fetcher):
            return method(*args, **kwargs)

    @classmethod
    def _filter_daily_fetchers_for_market(
        cls,
        fetchers: List[BaseFetcher],
        market: str,
    ) -> List[BaseFetcher]:
        """Skip built-in daily fetchers that are known not to support a market."""

        kept: List[BaseFetcher] = []
        skipped: List[str] = []
        for fetcher in fetchers:
            supported = cls._DAILY_MARKET_FETCHER_SUPPORT.get(fetcher.name)
            if supported is not None and market not in supported:
                skipped.append(fetcher.name)
            else:
                kept.append(fetcher)

        if skipped:
            logger.info(
                "[数据源路由] %s 日线跳过不支持的数据源: %s",
                market,
                ", ".join(skipped),
            )
        return kept

    @classmethod
    def _filter_fetchers_by_capability(
        cls,
        fetchers: List[BaseFetcher],
        capability: str,
    ) -> List[BaseFetcher]:
        """Skip request-time unavailable fetchers before entering route-specific loops."""
        kept: List[BaseFetcher] = []
        skipped: List[str] = []

        for fetcher in fetchers:
            if cls._is_fetcher_available(fetcher, capability=capability):
                kept.append(fetcher)
            else:
                skipped.append(fetcher.name)

        if skipped:
            logger.info(
                "[数据源路由] %s 跳过暂不可用的数据源: %s",
                capability or "request",
                ", ".join(skipped),
            )

        return kept

    @classmethod
    def _daily_health_key(cls, fetcher: BaseFetcher, market: str) -> str:
        return f"daily_data:{market}:{fetcher.name}"

    @classmethod
    def _is_daily_source_available(
        cls,
        fetcher: BaseFetcher,
        market: str,
    ) -> bool:
        key = cls._daily_health_key(fetcher, market)
        if cls._daily_source_health.is_available(key):
            return True
        logger.info(
            "[数据源健康度] %s 日线跳过短期熔断的数据源: %s",
            market,
            fetcher.name,
        )
        return False

    @staticmethod
    def _daily_source_unavailable_error(fetcher: BaseFetcher) -> str:
        return f"[{fetcher.name}] (CircuitOpen) 数据源短期熔断"

    @classmethod
    def _record_daily_source_success(cls, fetcher: BaseFetcher, market: str) -> None:
        cls._daily_source_health.record_success(cls._daily_health_key(fetcher, market))

    @classmethod
    def _record_daily_source_failure(cls, fetcher: BaseFetcher, market: str, error: str) -> None:
        cls._daily_source_health.record_failure(cls._daily_health_key(fetcher, market), error=error)

    @classmethod
    def reset_daily_source_health(cls) -> None:
        """Reset daily source health state for tests/admin diagnostics."""
        cls._daily_source_health.reset()

    def _init_default_fetchers(self) -> None:
        """
        初始化默认数据源列表

        - 未配置 API key 的可选数据源不实例化，避免反复探测无效源
        - 默认优先级：
          0. EfinanceFetcher (Priority 0) - 最高优先级
          0. TencentFetcher (Priority 0) - 同优先级，排在 Efinance 之后
          1. AkshareFetcher (Priority 1)
          4. YfinanceFetcher (Priority 4)
          可选：FinnhubFetcher (Priority 2)、AlphaVantageFetcher (Priority 3) — 仅美股
        """
        from src.config import get_config
        from .efinance_fetcher import EfinanceFetcher
        from .tencent_fetcher import TencentFetcher
        from .akshare_fetcher import AkshareFetcher
        from .yfinance_fetcher import YfinanceFetcher
        config = get_config()
        # 创建所有数据源实例（优先级在各 Fetcher 的 __init__ 中确定）
        efinance = EfinanceFetcher()
        tencent = TencentFetcher()
        akshare = AkshareFetcher()
        yfinance = YfinanceFetcher()
        optional_fetchers: List[BaseFetcher] = []

        finnhub_api_key = (getattr(config, "finnhub_api_key", None) or "").strip()
        if finnhub_api_key:
            from .finnhub_fetcher import FinnhubFetcher
            optional_fetchers.append(FinnhubFetcher())
        else:
            logger.debug("[数据源初始化] 跳过未配置的 FinnhubFetcher")

        alphavantage_api_key = (getattr(config, "alphavantage_api_key", None) or "").strip()
        if alphavantage_api_key:
            from .alphavantage_fetcher import AlphaVantageFetcher
            optional_fetchers.append(AlphaVantageFetcher())
        else:
            logger.debug("[数据源初始化] 跳过未配置的 AlphaVantageFetcher")

        # 初始化数据源列表
        self._ensure_concurrency_guards()
        with self._fetchers_lock:
            self._fetchers = [
                efinance,
                tencent,
                akshare,
                yfinance,
                *optional_fetchers,
            ]

            # 按优先级排序（稳定排序，同优先级保持上面的初始化顺序）
            self._fetchers.sort(key=lambda f: f.priority)
            self._refresh_fetcher_indexes_locked()

        # 构建优先级说明
        priority_info = ", ".join([f"{f.name}(P{f.priority})" for f in self._get_fetchers_snapshot()])
        logger.info(f"已初始化 {len(self._fetchers)} 个数据源（按优先级）: {priority_info}")

    def add_fetcher(self, fetcher: BaseFetcher) -> None:
        """添加数据源并重新排序"""
        self._ensure_concurrency_guards()
        with self._fetchers_lock:
            self._fetchers.append(fetcher)
            self._fetchers.sort(key=lambda f: f.priority)
            self._refresh_fetcher_indexes_locked()

    def get_daily_data(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30
    ) -> Tuple[pd.DataFrame, str]:
        """
        获取日线数据（自动切换数据源）

        故障切换策略：
        1. 美股指数/美股股票直接路由到专用美股数据源
        2. 其他代码从最高优先级数据源开始尝试
        3. 捕获异常后自动切换到下一个
        4. 记录每个数据源的失败原因
        5. 所有数据源失败后抛出详细异常

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            days: 获取天数

        Returns:
            Tuple[DataFrame, str]: (数据, 成功的数据源名称)

        Raises:
            DataFetchError: 所有数据源都失败时抛出
        """
        # Normalize code (strip SH/SZ prefix etc.)
        stock_code = normalize_stock_code(stock_code)

        fetchers = self._get_fetchers_snapshot()
        errors = []
        request_start = time.time()

        # 快速路径：美股使用专用数据源路由；港股先过滤不支持港股日线的数据源
        is_us_index = is_us_index_code(stock_code)
        is_us = is_us_index or is_us_stock_code(stock_code)
        is_hk = (not is_us) and _is_hk_market(stock_code)
        is_jp = (not is_us) and (not is_hk) and _is_jp_market(stock_code)
        is_kr = (not is_us) and (not is_hk) and _is_kr_market(stock_code)
        is_tw = (not is_us) and (not is_hk) and _is_tw_market(stock_code)
        market = "us" if is_us else "hk" if is_hk else "jp" if is_jp else "kr" if is_kr else "tw" if is_tw else "cn"
        if market != "cn":
            fetchers = self._filter_daily_fetchers_for_market(fetchers, market)
        fetchers = self._filter_fetchers_by_capability(fetchers, capability="daily_data")
        total_fetchers = len(fetchers)

        if total_fetchers == 0:
            market_label = "美股指数" if is_us_index else "美股" if is_us else "港股" if is_hk else "台股" if is_tw else "A股"
            error_summary = f"{market_label} {stock_code} 获取失败:\n暂无可用数据源"
            logger.error(f"[数据源终止] {stock_code} 获取失败: {error_summary}")
            raise DataFetchError(error_summary)

        # 美股（含美股指数）使用专用路由；港股走下方通用数据源循环
        # Failover chain: Finnhub(P2) -> AlphaVantage(P3) -> Yfinance(P4)
        # US indices: Yfinance first (the API vendors do not serve index candles)
        if is_us:
            if is_us_index:
                source_order = ["YfinanceFetcher", "FinnhubFetcher"]
            else:
                source_order = ["FinnhubFetcher", "AlphaVantageFetcher", "YfinanceFetcher"]
            market_label = "美股指数" if is_us_index else "美股"

            for src_name in source_order:
                for attempt, fetcher in enumerate(fetchers, start=1):
                    if fetcher.name != src_name:
                        continue
                    if not self._is_daily_source_available(fetcher, market):
                        errors.append(self._daily_source_unavailable_error(fetcher))
                        break
                    try:
                        role = "首选" if src_name == source_order[0] else "兜底"
                        logger.info(
                            f"[数据源尝试 {attempt}/{total_fetchers}] [{fetcher.name}] "
                            f"{market_label} {stock_code} {role}路由..."
                        )
                        df = self._call_fetcher_method(
                            fetcher,
                            "get_daily_data",
                            stock_code=stock_code,
                            start_date=start_date,
                            end_date=end_date,
                            days=days,
                        )
                        if df is not None and not df.empty:
                            elapsed = time.time() - request_start
                            logger.info(
                                f"[数据源完成] {stock_code} 使用 [{fetcher.name}] 获取成功: "
                                f"rows={len(df)}, elapsed={elapsed:.2f}s"
                            )
                            self._record_daily_source_success(fetcher, market)
                            return df, fetcher.name
                        if df is not None and df.empty:
                            self._record_daily_source_success(fetcher, market)
                    except Exception as e:
                        error_type, error_reason = summarize_exception(e)
                        error_msg = f"[{fetcher.name}] ({error_type}) {error_reason}"
                        logger.warning(
                            f"[数据源失败 {attempt}/{total_fetchers}] [{fetcher.name}] {stock_code}: "
                            f"error_type={error_type}, reason={error_reason}"
                        )
                        self._record_daily_source_failure(fetcher, market, error_reason)
                        errors.append(error_msg)
                    break

            error_summary = f"{market_label} {stock_code} 获取失败:\n" + "\n".join(errors)
            elapsed = time.time() - request_start
            logger.error(f"[数据源终止] {stock_code} 获取失败: elapsed={elapsed:.2f}s\n{error_summary}")
            raise DataFetchError(error_summary)

        for attempt, fetcher in enumerate(fetchers, start=1):
            if not self._is_daily_source_available(fetcher, market):
                errors.append(self._daily_source_unavailable_error(fetcher))
                continue
            try:
                logger.info(f"[数据源尝试 {attempt}/{total_fetchers}] [{fetcher.name}] 获取 {stock_code}...")
                df = self._call_fetcher_method(
                    fetcher,
                    "get_daily_data",
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    days=days
                )

                if df is not None and not df.empty:
                    elapsed = time.time() - request_start
                    logger.info(
                        f"[数据源完成] {stock_code} 使用 [{fetcher.name}] 获取成功: "
                        f"rows={len(df)}, elapsed={elapsed:.2f}s"
                    )
                    self._record_daily_source_success(fetcher, market)
                    return df, fetcher.name
                if df is not None and df.empty:
                    self._record_daily_source_success(fetcher, market)

            except Exception as e:
                error_type, error_reason = summarize_exception(e)
                error_msg = f"[{fetcher.name}] ({error_type}) {error_reason}"
                logger.warning(
                    f"[数据源失败 {attempt}/{total_fetchers}] [{fetcher.name}] {stock_code}: "
                    f"error_type={error_type}, reason={error_reason}"
                )
                self._record_daily_source_failure(fetcher, market, error_reason)
                errors.append(error_msg)
                if attempt < total_fetchers:
                    next_fetcher = fetchers[attempt]
                    logger.info(f"[数据源切换] {stock_code}: [{fetcher.name}] -> [{next_fetcher.name}]")
                # 继续尝试下一个数据源
                continue

        # 所有数据源都失败
        error_summary = f"所有数据源获取 {stock_code} 失败:\n" + "\n".join(errors)
        elapsed = time.time() - request_start
        logger.error(f"[数据源终止] {stock_code} 获取失败: elapsed={elapsed:.2f}s\n{error_summary}")
        raise DataFetchError(error_summary)

    @property
    def available_fetchers(self) -> List[str]:
        """返回可用数据源名称列表"""
        return [f.name for f in self._get_fetchers_snapshot()]
