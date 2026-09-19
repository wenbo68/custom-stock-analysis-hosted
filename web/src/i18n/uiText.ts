export type UiLanguage = 'zh' | 'en';

const zh = {

  'language.current': '中文',
  'language.short.en': 'EN',
  'language.short.zh': '中',
  'language.toggle': '切换界面语言',
  'language.uiLanguage': '界面语言',

  'theme.dark': '深色',
  'theme.light': '浅色',
  'theme.menu': '主题模式',
  'theme.system': '跟随系统',
  'theme.theme': '主题',
  'theme.toggle': '切换主题',

  'tiered.altForm.market.cn': 'A 股',
  'tiered.altForm.market.hk': '港股',
  'tiered.altForm.market.jp': '日股',
  'tiered.altForm.market.kr': '韩股',
  'tiered.altForm.market.tw': '台股',
  'tiered.altForm.market.us': '美股',

  'tiered.queued':
    '排队等待空闲名额。服务器同时只运行少量分析，轮到时会自动开始，无需再点开始。',
  'tiered.running': '分析中（约 2-5 分钟：抓取数据、检索新闻、AI 综合）…',
  'tiered.error.title': '分析失败',
  'tiered.score': '评分',
  'tiered.levels.entry': '买入',
  'tiered.levels.stopLoss': '止损',
  'tiered.levels.takeProfit': '目标',
  'tiered.dimension.technicals': '技术面',
  'tiered.dimension.fundamentals': '基本面',
  'tiered.dimension.macro_economy': '宏观经济',
  'tiered.dimension.positioning': '持仓结构',
  'tiered.dimension.company_news': '公司新闻',
  'tiered.dimension.world_news': '世界新闻',
  'tiered.warnings': '警告',
  // 数据说明弹窗的固定关键词表（2026-07-24）：每条说明以其中一个开头，
  // 由 altWarningText.ts 按规则确定，不由 AI 生成。盈亏比一条复用
  // 交易计划警告弹窗的 'tiered.alt.warnKey.reward_below_goal'。
  'tiered.note.key.missingData': '数据缺失',
  'tiered.note.key.fetchFailed': '抓取失败',
  'tiered.note.key.citations': '引用无效',
  'tiered.note.key.aiReply': 'AI 回复无效',
  'tiered.note.key.levels': '价位问题',
  'tiered.note.key.outlook': '无展望',
  'tiered.note.key.vote': '投票问题',
  'tiered.note.key.debate': '证据不足',
  'tiered.note.key.riskCheck': '计划复核未完成',
  'tiered.note.key.settings': '设置无效',
  'tiered.note.key.newsCap': '新闻已截断',
  // 无规则匹配时的兜底关键词——所有用户可见的“数据说明”一律叫
  // “警告”（所有者要求 2026-08-25）。
  'tiered.note.key.other': '未知问题',
  'tiered.alt.summaryGroup': '总结',
  'tiered.note.barsLoadFailed': '日线行情加载失败，因此所有技术面数字都无法计算。',
  'tiered.note.yahooSummaryFailed': 'Yahoo Finance 摘要页加载失败，相关字段为空。',
  'tiered.note.holdersFailed': '大型基金持仓名单加载失败，前十大集中度及其数据日期为空。',
  'tiered.note.insiderFetchFailed': '内部人买卖申报加载失败，内部人交易各行为空。',
  'tiered.note.optionsFetchFailed': '期权数据加载失败，期权各行为空。',
  'tiered.note.earningsDateFailed': '下一次季度财报日期查询失败，依赖该日期的字段为空。',
  'tiered.note.earningsHistoryFailed': '历史季度财报记录加载失败，超预期次数与历史财报日涨跌为空。',
  'tiered.note.reactionBarsFailed': '用于测算历史财报日股价反应的行情加载失败，相关行为空。',
  'tiered.note.epsTrendFailed': '分析师盈利预期历史加载失败，30 天预期变化一行为空。',
  'tiered.note.epsRevisionsFailed': '分析师预期调整人数加载失败，30 天上调/下调人数两行为空。',
  'tiered.note.releaseCalendarFailed': '{label} 的发布日历加载失败，其下次发布日期为空。',
  'tiered.note.benchmarkBarsFailed': '大盘指数行情加载失败，无法将本股与大盘比较。',
  'tiered.note.sectorBarsFailed': '行业基金（{ticker}）行情加载失败，行业对比各行为空。',
  'tiered.note.providerCrashed': '{dimension} 数据采集出现异常，本次运行缺少整个板块。',
  'tiered.note.debateCallFailed': '分析师辩论的 AI 调用失败，本次运行没有展望。',
  'tiered.note.planReviewCallFailed': '交易计划复核的 AI 调用失败，沿用计算出的原始计划。',
  'tiered.note.planReviewSkipped': '交易计划复核需要的 AI 密钥未配置，沿用计算出的原始计划。',
  'tiered.note.insufficientHistory': '该股票只有 {bars} 天行情，少于指标所需的 {min} 天，技术面分析已跳过。',
  'tiered.note.shortDailyHistory': '只取到 {bars} 天行情（整年约 {year} 个交易日），因此一年高点、低点和区间反映的是现有历史，而非完整一年。',
  'tiered.note.shortWeeklyHistory': '只取到 {bars} 周行情（周线分析需要 {target} 周），周线趋势不可靠。',
  'tiered.note.benchmarkNotConfigured': '该市场未配置大盘指数，无法将本股与大盘比较。',
  'tiered.note.benchmarkShort': '大盘指数只有 {bars} 天历史，不足以判断大盘趋势或比较涨跌幅。',
  'tiered.note.benchmarkShortRegime': '大盘指数没有大盘趋势判断所需的 200 天历史。',
  'tiered.note.noImpliedVol': '期权交易所未公布 30 天预期波动数据，隐含波动率一行为空。',
  'tiered.note.noOptionsStockPrice': '期权交易所未公布股价，无法计算预期财报日涨跌幅。',
  'tiered.note.reportDateUnknown': '下一次季度财报日期未知，无法计算预期财报日涨跌幅。',
  'tiered.note.reportDateUnreadable': '下一次季度财报日期返回的格式系统无法识别，无法计算预期财报日涨跌幅。',
  'tiered.note.reportTooFarExact': '下一次季度财报在 {days} 天以后——超过了 {max} 天。那么远的期权价格主要反映日常波动而非财报本身，因此不显示财报日涨跌幅。',
  'tiered.note.ratioMissingIngredient': '该比值需要 {field}，本次运行中该字段为空。',
  'tiered.alt.noteF.daysUntilReport': '距下次季度财报的天数',
  'tiered.note.noAtmQuotes': '财报后首个到期日的平值期权没有可用报价，无法计算预期财报日涨跌幅。',
  'tiered.note.noPostReportExpiry': '已取到的期权到期日均早于下一次财报，无法计算预期财报日涨跌幅。',
  'tiered.note.noListedOptions': '该股票没有挂牌期权，没有期权数据可显示。',
  'tiered.note.noShortInterest': 'Yahoo Finance 未公布该股票的做空数据，做空各行为空。',
  'tiered.note.noOwnership': 'Yahoo Finance 未公布该股票的持股数据，持股各行为空。',
  'tiered.note.noEarningsHistory': '未取到该股票的历史季度财报记录，超预期次数与历史财报日涨跌为空。',
  'tiered.note.tooFewReports': '已加载的行情区间内只有 {count} 次历史财报，不足以求财报日平均涨跌幅。',
  'tiered.note.fredKeyMissing': '经济数据服务（FRED）未配置访问密钥，无法加载经济数据。',
  'tiered.note.noReleaseDate': '{label} 尚未公布下一次发布日期。',
  'tiered.note.fomcTableExhausted': '内置的美联储议息会议日期表已用尽，下一次利率决议日期为空。',
  'tiered.note.sectorUnknown': '该公司所属行业未知，行业对比各行为空。',
  'tiered.note.sectorNoEtf': '该公司所属行业尚未配置对应的行业基金（目前仅支持美股行业），行业对比各行为空。',
  'tiered.note.sectorNeedsBenchmark': '行业对比以大盘涨跌幅为基准，而该数据缺失，行业对比各行为空。',
  'tiered.note.sectorShort': '行业基金（{ticker}）只有 {bars} 天历史，不足以比较涨跌幅，行业对比各行为空。',
  'tiered.note.noClosePrice': '没有收盘价，无法计算交易计划。',
  'tiered.note.noEntryAnchor': '买入价所依据的价格——50 日均线、200 日均线、最近支撑位——都不可用，无法计算交易计划。',
  'tiered.note.noTechnicalsForLevels': '缺少技术面数据，无法计算交易计划。',
  'tiered.note.duplicateAdjust': 'AI 对{level}提出了两次调整，保留第一次，忽略第二次。',
  'tiered.note.planAdjustDropped': 'AI 对{level}提出的调整无法在报告中找到数据依据，该调整已丢弃。',
  'tiered.note.planReplyProblem': 'AI 的计划复核回复中有系统无法使用的内容，该部分已忽略。',
  'tiered.note.planNoConverge': 'AI 提出的每一次调整都未通过风险检查，全部丢弃，沿用计算出的原始计划。',
  'tiered.note.noGradableFields': '没有可供分析师评分的报告字段，本次运行没有展望。',
  'tiered.note.noEvidenceToVote': '没有报告数据送达分析师，无内容可判断，请重新运行该股票。',
  'tiered.note.rewardRiskDefaulted': '盈亏比设置必须大于 1，所填数值已忽略，改用默认值。',
  'tiered.note.adjustUnknownLevel': 'AI 提出的调整对象不属于交易计划中的任何价位，已忽略。',
  'tiered.note.downtrend': '收盘价已到 50 日均线或以下——逆势低吸的下行风险更高。',
  'tiered.note.trendCheckSkipped': '缺少 50 日均线数据，趋势检查已跳过。',
  'tiered.note.summaryLinksDropped':
    '总结中有引用经多次修正仍未通过代码校验——相关数值仍然展示，但没有链接。',
  'tiered.note.optionsOiMissing':
    '数据源返回的期权未平仓量缺失或为零——Put/Call 未平仓比和总未平仓量留空，不显示误导性的 0。',
  'tiered.note.optionsVolumeMissing':
    '数据源返回的期权成交量缺失或为零——Put/Call 成交量比留空，不显示误导性的 0。',
  'tiered.note.insiderRowsMissing':
    'Yahoo 没有返回任何内部人交易记录——无法区分“确实没人交易”和“数据缺失”，因此内部人板块留空。',
  // 新闻筛选各阶段（评分/合并/排序/摘要）失败时的降级说明——每一步
  // 失败都只降低卡片质量，绝不丢新闻。
  'tiered.note.newsJudgeFailed':
    'AI 给每条新闻评相关性和重要性的回复缺失或无法解读，所有文章未经评分全部保留。',
  'tiered.note.newsJudgeMissing':
    'AI 的新闻评分回复漏掉了 {count} 条文章——这些文章未经评分而保留。',
  'tiered.note.newsGroupFailed':
    'AI 用来把同一事件的多篇报道合并成一条的回复缺失或无法解读，因此没有做合并——同一件事可能重复出现。',
  'tiered.note.newsGroupPartial':
    'AI 的同事件合并回复漏掉了 {count} 条文章——这些文章各自作为独立事件保留。',
  'tiered.note.newsRankFailed':
    'AI 按重要性给事件排序的回复缺失或无法解读，事件改按重要性得分顺序展示。',
  'tiered.note.newsRankPartial':
    'AI 的排序回复漏掉了 {count} 个事件——这些事件按重要性得分顺序排在末尾。',
  'tiered.note.newsSummaryFailed':
    'AI 写一句话摘要的回复缺失或无法解读，改为显示新闻源自带的原文摘要。',
  'tiered.note.newsSummaryMissing':
    'AI 的摘要回复漏掉了 {count} 条文章——这些条目显示新闻源自带的原文摘要。',
  'tiered.note.newsTrimmed':
    '新闻高峰期：符合条件的事件超过卡片上限，排名在前 {max} 之外的 {count} 个事件未展示。',
  'tiered.group.trend': '价格与趋势',
  'tiered.group.momentum': '动量',
  'tiered.group.volatility': '波动与区间',
  'tiered.group.structure': '价格结构',
  'tiered.group.volume': '成交量',
  'tiered.group.meta': '数据与评分',
  'tiered.group.reportInfo': '报告信息',
  'tiered.group.earnings': '财报',
  'tiered.group.other': '其他',
  'tiered.note.fetchFailed': '一篇新闻（{domain}）未能下载，因此没有采用。',
  'tiered.note.fundamentalsUnavailable': '美国证监会（SEC）官方财报数据未能加载，部分基本面数字可能缺失。',
  'tiered.note.valuationUnavailable': '来自 Yahoo Finance 的估值指标未能加载。',
  'tiered.note.macroUnavailable': '一项经济指标（{series}）未能从 FRED 数据库加载。',
  'tiered.note.indicatorNoHistory': '价格历史不足，无法计算该数值。',
  'tiered.note.macroFieldMissing': '数据源返回的数据不足，无法计算该数值。',
  'tiered.note.adjustmentRejected': 'AI 想微调{level}，但建议不符合规则，已保留公式算出的数字。',
  'tiered.note.stopFallback': '公式算出的止损价不可用，改用了基于波动幅度（ATR）的止损。',
  'tiered.note.noAtrStop': '缺少波动幅度数据（ATR），无法计算止损价。',
  'tiered.note.noAtrStopTarget': '缺少波动幅度数据（ATR），止损价和目标价都无法计算。',
  'tiered.note.noEntryNoStop': '没有可用的买入价，因此无法设置止损。',
  'tiered.note.summaryFailed': '裁判的文字总结生成失败——公式算出的展望不受影响。',
  'tiered.note.badSetting': '有一项仓位设置不是数字，已忽略。',
  'tiered.help.entry': '理想买入价。\n通常靠近支撑位——此前买盘出现过的价位。',
  'tiered.help.stopLoss': '止损位。\n跌到这里说明判断错了——在此卖出可控制亏损。',
  'tiered.help.takeProfit': '目标位。\n分析建议在此卖出、锁定收益。',
  'tiered.empty': '输入股票代码开始一次分层分析。',
  'tiered.history': '运行历史',
  'tiered.status.queued': '排队中',
  'tiered.status.queuedAt': '排队中（{position}）',
  'tiered.status.running': '分析中',
  'tiered.status.done': '已完成',
  'tiered.status.failed': '失败',
  'tiered.help.depth':
    '层级 1（初步分析）：四份数据报告加一次 AI 展望。\n层级 2（深度分析）：跳过单次 AI 展望，改由两位分析师逐条列证据、投票定分——更慢但更扎实。\n（层级 3 已下线。）',
  'tiered.llmUsage': '本次运行 LLM 调用 {calls} 次（{tokens} tokens）',
  'tiered.llmUsageShared':
    '本次运行 LLM 调用 {calls} 次（{tokens} tokens），并基于另一次运行的 {sharedCalls} 次调用（{sharedTokens} tokens）',
  'tiered.help.llmUsage':
    '本次运行发起的 LLM 调用次数（每次即向大语言模型 API 发起一次请求）与 token 总量（token 是计费单位）。\n点击可展开每次调用的提示词与回复。\n展望来自共享运行时，那次运行的调用也会列出，并标为“另一次运行”。\n层级 1 的展望由产品内置流程完成，不计入。',
  'tiered.transcript.call': '第 {n} 次调用',
  'tiered.transcript.owner': '所属运行',
  'tiered.transcript.ownerThisRun': '本次运行',
  'tiered.transcript.ownerAnotherRun': '另一次运行',
  'tiered.transcript.for': '用于',
  'tiered.transcript.llm': 'llm',
  'tiered.transcript.time': '耗时',
  'tiered.transcript.tokens': 'tokens',
  'tiered.transcript.loading': '加载中…',
  'tiered.transcript.error': '无法加载对话记录：{error}',
  'tiered.transcript.empty': '该运行的对话记录已过期（保留 14 天）。',
  'tiered.transcript.prompt': '提示词',
  'tiered.transcript.reply': '回复',
  'tiered.transcript.failed': '调用失败：{error}',
  'tiered.transcript.noReply': '（无回复）',
  'tiered.alt.kind.formula': '公式',
  'tiered.alt.kind.adjustment': '调整',
  'tiered.alt.kind.whyBlank': '为何为空',
  'tiered.alt.kind.warnings': '警告',
  'tiered.alt.blankFallback': '本次运行中该字段没有数值——计算它所需的数据不可用。',
  'tiered.levelModal.noBase': '本次运行缺少计算该价位所需的数据，没有公式基准。',
  'tiered.levelModal.references': '参考依据',
  'tiered.help.debate':
    '两位分析师各自独立通读四份报告，列出全部看多与看空证据；一次合并调用把两份清单对齐去重。\n每条证据引用的数值都由代码逐一校验：数值必须与报告显示的完全一致、且出现在句子里；不合格的引用会退回给 AI 修正（最多 3 次），仍失败的整条划线剔除。\n每条证据按多数票决定去留（最多 3 票）：作者自动算一张有效票，两位分析师都独立列出的证据直接确认；只有一位列出的证据由复核 AI 投第二票；1 比 1 平局时由决胜票裁定。\n代码按看多/看空条数算出得分——AI 不经手任何数字。',
  'tiered.debate.noOutlook': '辩论未产生展望——请重新运行（详见警告）。',
  'tiered.tree.bullish': '看多',
  'tiered.tree.bearish': '看空',
  'tiered.tree.valid': '有效',
  'tiered.tree.invalid': '无效',
  'tiered.tree.scores': '评分',
  'tiered.tree.finalScore': '最终展望分',
  'tiered.tree.transcript': '详情',
  'tiered.tree.howItWorks': '规则说明',
  'tiered.tree.explain1': '两个 AI 各自独立通读四份报告，分别列出全部看多与看空证据。',
  'tiered.tree.explain2':
    '代码逐条核对引用的数值；不合格的引用退回修正，仍失败的整条划线剔除，不计入任何得分。',
  'tiered.tree.explain3':
    '两份清单合并。两个 AI 都列出的证据已经达成一致——无需再检查，因此没有任何检查标记。',
  'tiered.tree.explain4': '只有一个 AI 列出的证据由另一个 AI 检查——即证据后的 ✓ 或 ✗；点击标记可查看理由。',
  'tiered.tree.explain5': '若该检查为无效，该证据 1 比 1 平票，再由一个 AI 投出决胜票——即第二个标记。',
  'tiered.tree.explain6': '带有两个 ✗ 的证据被否决并划线；未划线的证据全部计入。',
  'tiered.tree.explain7': '最终得分 = 10 × 看多条数 ÷ 存活总条数：低于 4 卖出，4–6 持有，高于 6 买入。',
  'tiered.tree.codeCheck': '代码检查结果',
  'tiered.note.listerDegradedRole': '{role}——评分表连续不合规，本次只使用另一位分析师的评分表。',
  'tiered.note.sheetsVoided': '两位分析师的评分表连续不合规——深度分析作废。',
  'tiered.note.noOutlook': '深度分析未能得出展望——请重新运行该股票。',
  'tiered.note.checkDegraded': '复核投票连续不合规——各条证据仅按作者一票计入。',
  'tiered.note.tiebreakDegraded': '决胜投票连续不合规——平票的证据按未决处理，不计入得分。',
  'tiered.note.voteDiscarded': '一张投票的引用经多次修正仍未通过代码校验——该票作废。',
  'tiered.note.unresolved': '某条证据 1 比 1 平票且没有决胜票——按未决处理，不计入得分。',
  'tiered.note.allConfirmed': '每条证据都被两位分析师独立列出——无需复核投票。',
  'tiered.note.struckBullet':
    '某条证据的引用经 3 次修正仍未通过代码校验——该条已划线剔除，不计入任何得分。',
  'tiered.note.fixRoundLost': '一次引用修正回复不可读——浪费了一轮修正机会。',
  'tiered.note.stageRetriedRole': '{role}——第一次回复不合规，重试一次后通过。',
  'tiered.note.stageInvalidRole': '{role}——重试后回复仍不合规。',
  'tiered.role.checkRound': '复核投票',
  'tiered.role.decidingRound': '决胜投票',
  'tiered.role.reportOutline': '报告撰写',
  'tiered.role.newsJudge': '新闻相关性判定',
  'tiered.role.newsGrouping': '同一事件新闻归并',
  'tiered.role.newsRanking': '新闻重要性排序',
  'tiered.role.newsSummary': '新闻摘要撰写',
  'tiered.note.emptyLedger': '没有可计入的证据，最终得分默认取中性 5。',
  'tiered.note.thinBase': '守方最初的证据大多未能成立——权重建立在较薄的证据基础上。',
  'tiered.help.debateScore':
    '投票得出的最终展望分，满分 10，保留两位小数。\n0 = 强烈看空，5 = 中性，10 = 强烈看多。\n低于 4 看空，4–6 中性，高于 6 看多。\n完全由代码算出：得分 = 10 × 看多证据的权重和 ÷ 全部证据的权重和，只统计经受住检验的证据——见「详情」底部的「评分」。',
  'tiered.help.sizing':
    '固定算术，无 AI 参与。\n每个数字都能点击跳到它在本报告中出现的位置。\n结果向下取整为整数股，单只股票最多占用本金的 25%。',
  'tiered.altForm.ticker': '代码',
  'tiered.altForm.tier': '层级',
  'tiered.altForm.capital': '本金',
  'tiered.altForm.capitalCurrency': '本金: {currency}',
  'tiered.altForm.risk': '单笔风险: %',
  'tiered.altForm.title': '发起分析',
  'tiered.user.title': '账户',
  'tiered.user.loading': '加载中…',
  'tiered.user.signInWith': '使用 {provider} 登录',
  'tiered.user.provider.google': 'Google',
  'tiered.user.provider.discord': 'Discord',
  'tiered.user.noProviders': '此服务器尚未配置登录方式。',
  'tiered.user.loginFailed': '登录未完成，请重试。',
  'tiered.user.signOut': '退出登录',
  'tiered.user.f.provider': 'LLM 提供商',
  'tiered.user.f.main': '主 LLM',
  'tiered.user.f.sub': '副 LLM',
  'tiered.user.f.llmKey': 'LLM 提供商 API 密钥',
  'tiered.user.f.fred': 'FRED API 密钥',
  'tiered.user.f.finnhub': 'FinnHub API 密钥',
  'tiered.user.f.alphavantage': 'AlphaVantage API 密钥',
  'tiered.user.ph.provider': '输入 LLM 提供商…',
  'tiered.user.ph.main': '输入主 LLM…',
  'tiered.user.ph.sub': '输入副 LLM…',
  'tiered.user.ph.llmKey': '输入 LLM 密钥…',
  'tiered.user.ph.fred': '输入 FRED 密钥…',
  'tiered.user.ph.finnhub': '输入 FinnHub 密钥…',
  'tiered.user.ph.alphavantage': '输入 AlphaVantage 密钥…',
  'tiered.user.default': '默认',
  'tiered.pill.llmProvider': 'LLM 提供商: {value}',
  'tiered.pill.mainLlm': '主 LLM: {value}',
  'tiered.pill.subLlm': '副 LLM: {value}',
  'tiered.pill.llmKey': 'LLM 密钥: {value}',
  'tiered.pill.fredKey': 'FRED 密钥: {value}',
  'tiered.pill.finnhubKey': 'FinnHub 密钥: {value}',
  'tiered.pill.alphavantageKey': 'AlphaVantage 密钥: {value}',
  'tiered.help.llmProvider':
    'AI 由哪家公司提供。\n选定后两个模型字段会填入该公司的默认模型，且只列出它的模型。\n点击标题打开它的密钥页面。',
  'tiered.help.mainLlm': '负责分析的模型。\n越强的模型每次运行费用越高。',
  'tiered.help.subLlm':
    '可选：用更便宜的模型做新闻筛选（判断一篇新闻是否与公司相关）。\n须与主 LLM 同一提供商。\n留空则由主 LLM 完成。',
  'tiered.help.llmKey':
    '你在该提供商的密钥，运行费用由它支付。\n加密保存，只回显最后 4 位。\n点击标题打开获取密钥的页面。',
  'tiered.help.fredKey':
    '可选。FRED 是美联储的经济数据库（利率、通胀）。\n留空则使用服务器默认密钥。\n点击标题打开获取密钥的页面。',
  'tiered.help.finnhubKey':
    '可选。FinnHub 提供行情、公司资料和新闻。\n留空则使用服务器默认密钥。\n点击标题打开获取密钥的页面。',
  'tiered.help.alphavantageKey':
    '可选。AlphaVantage 提供历史行情和基本面数据。\n留空则使用服务器默认密钥。\n点击标题打开获取密钥的页面。',
  'tiered.user.saveError': '保存失败：{error}',
  'tiered.user.signInFirst': '请先登录再发起分析。',
  'tiered.altForm.start': '开始',
  'tiered.altForm.noticeTitle': '提示',
  'tiered.altForm.needTickerFirst': '请先选择股票代码——本金使用该股票所在市场的货币。',
  'tiered.altForm.errorTitle': '错误',
  'tiered.altForm.missingIntro': '以下必填项尚未填写：',
  'tiered.altForm.duplicateRunning':
    '完全相同的 {ticker} 分析正在运行（本金、单笔风险、盈亏比、最长持有、层级都一样），已在下方运行历史中展开。请等它完成，或改动其中一项后再开始。',
  'tiered.altForm.duplicateQueued':
    '完全相同的 {ticker} 分析已在排队（本金、单笔风险、盈亏比、最长持有、层级都一样），已在下方运行历史中展开。它会自动开始；请等它完成，或改动其中一项后再开始。',
  'tiered.altForm.req.ticker': '代码',
  'tiered.altForm.req.tier': '层级',
  'tiered.altForm.req.capital': '本金',
  'tiered.altForm.req.risk': '单笔风险',
  'tiered.altForm.req.reward': '盈亏比',
  'tiered.altForm.req.hold': '最长持有',
  'tiered.altForm.req.mainLlm': '主 LLM',
  'tiered.altForm.req.llmKey': 'LLM 提供商 API 密钥',
  'tiered.altForm.tierOption1': '1：初步分析',
  'tiered.altForm.tierOption2': '2：深度分析',
  'tiered.altForm.tickerPh': '输入代码…',
  'tiered.altForm.tierPh': '输入层级…',
  'tiered.altForm.capitalPh': '输入本金…',
  'tiered.altForm.riskPh': '输入风险…',
  'tiered.altForm.reward': '盈亏比: x',
  'tiered.altForm.rewardPh': '输入盈亏比…',
  'tiered.altForm.lowRewardWarn':
    '盈亏比低于 1.5 意味着交易几乎不足以覆盖风险——常见要求至少 1.5×。本次运行仍会按你的 {value}× 目标进行。',
  'tiered.help.reward':
    '你要求这份计划的盈亏比（潜在盈利是风险的几倍）。必填，默认 2。\n目标价 = 入场价 + 盈亏比 × 风险；若上方阻力把目标压到低于你要求的倍数，计划会附警告（低于 1.5 的硬下限则直接不给计划）。',
  'tiered.altForm.hold': '最长持有: 周',
  'tiered.altForm.holdPh': '输入最长持有…',
  'tiered.help.hold':
    '你计划最长持有这笔交易多久。必填，默认 2 周。\n同一个数字会同时交给 AI（判断哪些证据在这个时间范围内重要）、显示在报告里、并作为前向测试的评分窗口——AI、你和测试始终对齐同一个时间范围。',
  'tiered.altForm.marketOpenTitle': '市场交易中',
  'tiered.altForm.marketOpenTrading':
    '{market}正在交易。本应用只分析已收盘的完整交易日，今天还没有可分析的数据。',
  'tiered.altForm.marketOpenHours':
    '今日交易时段：{open}–{close}（市场当地时间），相当于你时区的 {openLocal}–{closeLocal}。',
  'tiered.altForm.marketOpenMixedData':
    '「仍要运行」将分析上一个完整交易日：技术面报告只使用截至该日收盘的数据，但新闻等其他数据可能是实时的——报告内部可能混合两个时点的数据，出现不一致。',
  'tiered.altForm.marketOpenBestWindow':
    '另外，即使已收盘，数据源也可能落后实时数据最多 30 分钟，且一次运行本身需要时间——建议在收盘 30 分钟后、下次开盘 30 分钟前使用本应用。',
  'tiered.altForm.runAnyway': '仍要运行',
  'tiered.pill.ticker': '代码: {value}',
  'tiered.pill.tier': '层级: {value}',
  'tiered.pill.capital': '本金: {value} {currency}',
  'tiered.pill.risk': '单笔风险: {value}%',
  'tiered.pill.reward': '盈亏比: {value}×',
  'tiered.pill.hold': '最长持有: {value} 周',
  'tiered.pill.capitalMin': '本金下限: {value}',
  'tiered.pill.capitalMax': '本金上限: {value}',
  'tiered.pill.riskMin': '单笔风险下限: {value}%',
  'tiered.pill.riskMax': '单笔风险上限: {value}%',
  'tiered.pill.dateMin': '日期下限: {value}',
  'tiered.pill.dateMax': '日期上限: {value}',
  'tiered.pill.rewardMin': '盈亏比下限: {value}×',
  'tiered.pill.rewardMax': '盈亏比上限: {value}×',
  'tiered.altFilter.tickerPh': '输入代码…',
  'tiered.altFilter.capital': '本金',
  'tiered.altFilter.risk': '单笔风险: %',
  'tiered.altFilter.date': '日期: yyyy/mm/dd',
  'tiered.altFilter.tier': '层级',
  'tiered.altFilter.tierPh': '输入层级…',
  'tiered.altFilter.holdPh': '输入最长持有…',
  'tiered.altFilter.reward': '盈亏比: ×',
  'tiered.altFilter.min': '下限',
  'tiered.altFilter.max': '上限',
  'tiered.altHistory.shares': '{value} 股',
  'tiered.altHistory.tier': '层级 {value}',
  'tiered.altHistory.hold': '{value} 周',
  // 运行列表的表头（各列含义）。
  'tiered.altHistory.h.ticker': '代码',
  'tiered.altHistory.h.capital': '本金',
  'tiered.altHistory.h.risk': '单笔风险',
  'tiered.altHistory.h.reward': '盈亏比',
  'tiered.altHistory.h.hold': '最长持有',
  'tiered.altHistory.h.tier': '层级',
  'tiered.altHistory.h.status': '状态',
  'tiered.altHistory.h.outlook': '展望',
  'tiered.altHistory.h.date': '日期',
  'tiered.altHistory.first': '第一页',
  'tiered.altHistory.prev': '上一页',
  'tiered.altHistory.next': '下一页',
  'tiered.altHistory.last': '最后一页',
  'tiered.altHistory.none': '没有符合筛选的运行',
  'tiered.altHistory.loading': '加载报告…',
  'tiered.alt.dimensionsTitle': '数据报告',
  'tiered.alt.eventsNone': '近 {count} 天内无记录',
  'tiered.alt.eventsNoneGeneric': '暂无记录',
  'tiered.alt.eventsWindow': '近 {count} 天',
  'tiered.alt.tier2Title': '深度分析',
  'tiered.alt.rewardBelowGoal':
    '本计划的盈亏比为 {ratio}，低于你要求的 {goal}×——上方阻力压低了目标价。',
  'tiered.alt.roundLevelTitle': '整数关口',
  'tiered.alt.roundLevelBody':
    '{value} 是当前价下方最近的整数价位。它不来自任何数据行——由代码当场算出：挂单常聚集在整数价位，形成较弱的支撑。',
  'tiered.alt.f.capital': '本金',
  'tiered.alt.f.risk': '单笔风险',
  'tiered.alt.f.entry': '入场价',
  'tiered.alt.f.stop': '止损价',
  'tiered.alt.sources': '来源',
  'tiered.alt.levels.computed': '计算值',
  'tiered.alt.levels.adjusted': '调整值',
  'tiered.alt.levels.keep': '不变',
  'tiered.levels.shares': '股数',
  'tiered.alt.levels.warnings': '警告',
  'tiered.alt.warn.none': '无',
  'tiered.alt.warn.downtrend':
    '收盘价（{close}）不高于 60 日均线（{sma60}）——股票处于中期下行趋势，此时入场是逆势买入，进一步下跌的风险更高。',
  'tiered.alt.warn.downtrend_50':
    '收盘价（{close}）不高于 50 日均线（{sma50}）——股票处于中期下行趋势，此时入场是逆势买入，进一步下跌的风险更高。',
  'tiered.alt.warn.earnings_soon':
    '距下次财报仅 {days} 天（{date}），在典型波段持仓期内。技术面判断扛不住财报：一次公告就可能让价格跳空越过任何止损。建议财报前离场，或按跳空风险缩小仓位。',
  'tiered.alt.warn.macro_event_soon':
    '距{event}仅 {days} 天（{date}），在典型波段持仓期内。这是市场层面的跳空风险：一个数字可能让所有股票同时跳动。建议届时缩小仓位，或按跳空风险规划止损。',
  'tiered.alt.warnEvent.rate_decision': '下次官方利率决议',
  'tiered.alt.warnEvent.inflation_data': '下次通胀数据发布',
  'tiered.alt.warnEvent.employment_data': '下次就业数据发布',
  'tiered.alt.warn.gap_atr':
    '若隔夜消息导致跳空低开，开盘价比止损（{stop}）再低 1 个 ATR（{atr}），落在 {atrOpen}——止损单会在该价成交，亏损 {atrLoss}，比计划的 {planned} 多亏 {atrExtra}。',
  'tiered.alt.warn.gap_worst':
    '若重演过去一年最差单日（{worstDayPct}%），开盘价将落在 {worstOpen}，跌破止损（{stop}）——在该价卖出亏损 {worstLoss}，比计划的 {planned} 多亏 {worstExtra}。',
  // 警告公式弹窗里各计算值的名称（也用作公式文字行的变量名）。
  'tiered.alt.warnF.gapOpen': '跳空开盘价',
  'tiered.alt.warnF.gapLoss': '跳空亏损',
  'tiered.alt.warnF.plannedLoss': '计划亏损',
  'tiered.alt.warnF.worstOpen': '最差单日开盘价',
  'tiered.alt.warnF.worstLoss': '最差单日亏损',
  'tiered.alt.warnF.ratio': '盈亏比',
  'tiered.alt.f.shares': '股数',
  'tiered.alt.f.target': '目标价',
  // 每条风险文案开头的固定关键词（由代码根据检查项 id 决定，非 AI 生成）。
  'tiered.alt.warnKey.downtrend': '逆势',
  'tiered.alt.warnKey.earnings_soon': '财报临近',
  'tiered.alt.warnKey.macro_event_soon': '宏观事件临近',
  'tiered.alt.warnKey.gap_atr': '隔夜跳空风险',
  'tiered.alt.warnKey.gap_worst': '最差单日跳空风险',
  'tiered.alt.warnKey.reward_below_goal': '盈亏比偏低',
  'tiered.alt.checkKey.downtrend': '逆势',
  'tiered.alt.checkKey.liquidity': '流动性',
  'tiered.alt.checkKey.volatility': '波动',
  'tiered.alt.checkKey.stop_vs_support': '支撑位',
  'tiered.alt.reviewFail.title': '为什么维持原计算值',
  'tiered.alt.reviewFail.intro':
    'AI 尝试调整了这份方案，但每次调整后仍有风控检查未通过，因此放弃全部调整，维持按公式计算的方案。',
  'tiered.alt.reviewFail.round': '第 {round} 轮调整后仍触发：{checks}',
  'tiered.help.capital': '你的交易本金，货币跟随股票所在市场。\n股数计算以它为起点。\n会记住，供下次运行使用。',
  'tiered.help.riskPct': '单笔交易你最多接受亏掉本金的百分之几。\n常见为 1-2%。',

  // ---- 展望改版（outlook redesign）----
  'tiered.alt.tier1Title': '初步分析',
  'tiered.alt.outlook': '展望',
  'tiered.alt.action': '操作',
  'tiered.alt.actionRatio': '当前盈亏比为 {ratio}',
  'tiered.outlook.bullish': '看多',
  'tiered.outlook.neutral': '中性',
  'tiered.outlook.bearish': '看空',
  'tiered.outlook.unknown': '失败',
  'tiered.action.enter': '现在买入',
  'tiered.action.enter_later': '稍后再买',
  'tiered.action.no_trade': '不交易',
  'tiered.action.unknown': '重跑——本次运行未产生展望',
  'tiered.help.outlook':
    '「展望」是对这只股票本身的判断（看多 / 中性 / 看空），与你是否持有无关。\n「操作」由代码根据展望推出：看多→现在买入（交易计划的盈亏比达到你设定的目标）或稍后再买（低于目标）；中性或看空→不交易。',
  'tiered.help.action':
    '由固定代码规则从展望推出的个人操作建议。\n看多时分两种：交易计划的实际盈亏比达到你设定的目标→「现在买入」；被上方阻力等因素压到低于目标→「稍后再买」（等更好的价位再入场）。',
  'tiered.alt.staleNote': '本报告来自之前的交易日——请重跑一次以获得最新计划。',
  'tiered.alt.planTitle': '交易计划',
  'tiered.help.plan':
    '由固定公式从价格数据算出的计划价位（不经 AI）。\n显示内容随「操作」变化：买入→完整价位表；继续持有→仅结构性止损位；不交易 / 清仓→无价位。',
  'tiered.altFilter.status': '状态',
  'tiered.altFilter.statusPh': '输入状态…',
  'tiered.pill.status': '状态: {value}',
  'tiered.altFilter.outlook': '展望',
  'tiered.altFilter.outlookPh': '输入展望…',
  'tiered.pill.outlook': '展望：{value}',

  'tiered.tree.bullishWeight': '看多权重和',
  'tiered.tree.totalWeight': '总权重和',

  // ---- 层级 2 详情（v11：1-5 评分 + 评分理由）----
  'tiered.tree.explainWeights5':
    '每位 AI 还会给每条证据打 1-5 的重要性评分（1 = 非常次要，5 = 非常重要）；证据的最终分是所有评分的中位数，总分按它加权：10 × 看多证据的权重和 ÷ 全部证据的权重和。点击分数或勾叉可看理由。',
  'tiered.tree.lister': '列出者 {n}',
  'tiered.tree.checker': '核查员 {n}',
  'tiered.tree.validityLine': '结果：{value}',
  'tiered.tree.reasonPrefix': '理由：',
  'tiered.tree.scoreLine': '评分：{value}',
  'tiered.tree.scoresList': '各方评分：{value}',
  'tiered.tree.medianTitle': '显著性评分',
  'tiered.tree.medianLine': '中位数：{value}',

} as const;

export type UiTextKey = keyof typeof zh;

const en: Record<UiTextKey, string> = {

  'language.current': 'English',
  'language.short.en': 'EN',
  'language.short.zh': '中',
  'language.toggle': 'Switch UI language',
  'language.uiLanguage': 'UI language',

  'theme.dark': 'Dark',
  'theme.light': 'Light',
  'theme.menu': 'Theme mode',
  'theme.system': 'System',
  'theme.theme': 'Theme',
  'theme.toggle': 'Toggle theme',

  'tiered.altForm.market.cn': 'A-shares',
  'tiered.altForm.market.hk': 'Hong Kong',
  'tiered.altForm.market.jp': 'Japan',
  'tiered.altForm.market.kr': 'Korea',
  'tiered.altForm.market.tw': 'Taiwan',
  'tiered.altForm.market.us': 'US',

  'tiered.queued':
    'Waiting for a free slot. The server runs only a few analyses at a time; this one starts by itself when its turn comes — no need to press Start again.',
  'tiered.running': 'Running (2-5 min: fetching data, searching news, AI synthesis)…',
  'tiered.error.title': 'Analysis failed',
  'tiered.score': 'Score',
  'tiered.levels.entry': 'Entry',
  'tiered.levels.stopLoss': 'Stop loss',
  'tiered.levels.takeProfit': 'Target',
  'tiered.dimension.technicals': 'Technicals',
  'tiered.dimension.fundamentals': 'Fundamentals',
  'tiered.dimension.macro_economy': 'Macro economy',
  'tiered.dimension.positioning': 'Positioning',
  'tiered.dimension.company_news': 'Company news',
  'tiered.dimension.world_news': 'World news',
  'tiered.warnings': 'Warnings',
  // The warnings modal's fixed keyword list (2026-07-24): every note
  // leads with one of these, picked per rule in altWarningText.ts —
  // never AI-generated. The reward-ratio note reuses the plan-warnings
  // keyword 'tiered.alt.warnKey.reward_below_goal'.
  'tiered.note.key.missingData': 'Missing data',
  'tiered.note.key.fetchFailed': 'Failed fetch',
  'tiered.note.key.citations': 'Invalid citation',
  'tiered.note.key.aiReply': 'Unusable AI reply',
  'tiered.note.key.levels': 'Price level problem',
  'tiered.note.key.outlook': 'No outlook',
  'tiered.note.key.vote': 'Vote problem',
  'tiered.note.key.debate': 'No usable evidence',
  'tiered.note.key.riskCheck': 'Unfinished plan review',
  'tiered.note.key.settings': 'Invalid setting',
  'tiered.note.key.newsCap': 'Trimmed news',
  // The fallback keyword when no rule matches — every user-facing
  // "data note" reads "warning" (owner request 2026-08-25).
  'tiered.note.key.other': 'Unknown problem',
  'tiered.alt.summaryGroup': 'Summary',
  // Audit 2026-08-08: plain-English wording for notes that used to reach
  // the screen as raw backend text (exception reprs, variable names).
  'tiered.note.barsLoadFailed':
    'The daily price history could not be loaded, so none of the technical numbers could be worked out.',
  'tiered.note.yahooSummaryFailed':
    'The Yahoo Finance summary page failed to load, so the fields it feeds are blank.',
  'tiered.note.holdersFailed':
    'The list of large fund holders failed to load, so the top-10 concentration figure and its as-of date are blank.',
  'tiered.note.insiderFetchFailed':
    'The insider buy-and-sell filings failed to load, so the insider-trading rows are blank.',
  'tiered.note.optionsFetchFailed':
    'The options data failed to load, so the options rows are blank.',
  'tiered.note.earningsDateFailed':
    'The lookup for the next quarterly-report date failed, so anything depending on that date is blank.',
  'tiered.note.earningsHistoryFailed':
    'The record of past quarterly reports failed to load, so the beat count and past report-day moves are blank.',
  'tiered.note.reactionBarsFailed':
    'The price history needed to measure how the stock moved on past report days failed to load, so those rows are blank.',
  'tiered.note.epsTrendFailed':
    'The history of analyst earnings estimates failed to load, so the 30-day estimate-change row is blank.',
  'tiered.note.epsRevisionsFailed':
    'The analyst revision counts failed to load, so the 30-day increased/decreased analyst rows are blank.',
  'tiered.note.releaseCalendarFailed':
    'The publication calendar for {label} failed to load, so its next release date is blank.',
  'tiered.note.benchmarkBarsFailed':
    'The market index’s price history failed to load, so this stock could not be compared against the market.',
  'tiered.note.sectorBarsFailed':
    'The price history for the sector fund ({ticker}) failed to load, so the sector-comparison rows are blank.',
  'tiered.note.providerCrashed':
    'The {dimension} data collector hit an unexpected error, so that whole section is missing from this run.',
  'tiered.note.debateCallFailed':
    'The AI call for the analyst debate failed, so this run has no outlook.',
  'tiered.note.planReviewCallFailed':
    'The AI call for the plan review failed, so the computed plan stands as it is.',
  'tiered.note.planReviewSkipped':
    'The plan review needs an AI key that is not configured, so the computed plan stands as it is.',
  'tiered.note.insufficientHistory':
    'This stock has only {bars} days of price history — fewer than the {min} days the indicators need — so the technical read was skipped.',
  'tiered.note.shortDailyHistory':
    'Only {bars} days of price history were available (a full year is about {year} trading days), so the one-year high, low and range describe the history that exists, not a full year.',
  'tiered.note.shortWeeklyHistory':
    'Only {bars} weeks of price history were available (the weekly read wants {target}), so the weekly trend is not reliable.',
  'tiered.note.benchmarkNotConfigured':
    'No market index is set up for this market, so the stock could not be compared against the market.',
  'tiered.note.benchmarkShort':
    'The market index has only {bars} days of history — too little to judge the market trend or compare returns.',
  'tiered.note.benchmarkShortRegime':
    'The market index does not have the 200 days of history the market-trend read needs.',
  'tiered.note.noImpliedVol':
    'The options exchange published no 30-day expected-swing figure, so the implied-volatility row is blank.',
  'tiered.note.noOptionsStockPrice':
    'The options exchange published no stock price, so the expected report-day move could not be worked out.',
  'tiered.note.reportDateUnknown':
    'The date of the next quarterly report is unknown, so the expected report-day move could not be worked out.',
  'tiered.note.reportDateUnreadable':
    'The next quarterly report date came back in a form the system could not read, so the expected report-day move could not be worked out.',
  'tiered.note.reportTooFarExact':
    'The next quarterly report is {days} days away — more than {max}. Option prices that far out mostly price ordinary day-to-day movement rather than the report, so no report-day move is shown.',
  'tiered.note.ratioMissingIngredient':
    'The ratio needs {field}, which is blank this run.',
  'tiered.alt.noteF.daysUntilReport': 'Days until next quarterly report',
  'tiered.note.noAtmQuotes':
    'There were no usable buy/sell quotes on the first options contract expiring after the report, so the expected report-day move could not be worked out.',
  'tiered.note.noPostReportExpiry':
    'None of the options expiry dates that were loaded falls after the next report, so the expected report-day move could not be worked out.',
  'tiered.note.noListedOptions':
    'This stock has no listed options, so there are no options rows to show.',
  'tiered.note.noShortInterest':
    'Yahoo Finance published no short-selling figures for this stock, so the short-interest rows are blank.',
  'tiered.note.noOwnership':
    'Yahoo Finance published no ownership figures for this stock, so the ownership rows are blank.',
  'tiered.note.noEarningsHistory':
    'No records of past quarterly reports came back for this stock, so the beat count and past report-day move rows are blank.',
  'tiered.note.tooFewReports':
    'Only {count} past reports fall inside the loaded price history — too few to average how the stock moves on report day.',
  'tiered.note.fredKeyMissing':
    'The economy-data service (FRED) has no access key configured, so no economy numbers could be loaded.',
  'tiered.note.noReleaseDate':
    'No future release date for {label} has been published yet.',
  'tiered.note.fomcTableExhausted':
    'The built-in list of Federal Reserve interest-rate meeting dates has run past its last entry, so the next rate-decision date is blank.',
  'tiered.note.sectorUnknown':
    'This company’s sector (its industry family) is unknown, so the sector-comparison rows are blank.',
  'tiered.note.sectorNoEtf':
    'This company’s sector has no matching sector fund set up yet (US sectors only for now), so the sector-comparison rows are blank.',
  'tiered.note.sectorNeedsBenchmark':
    'The sector comparison is measured against the market’s return, and that is missing, so the sector rows are blank.',
  'tiered.note.sectorShort':
    'The sector fund ({ticker}) has only {bars} days of history — too little to compare returns — so the sector rows are blank.',
  'tiered.note.noClosePrice':
    'No closing price was available, so no trade plan could be worked out.',
  'tiered.note.noEntryAnchor':
    'None of the prices the entry anchors to — the 50-day average, the 200-day average, or the nearest support level — were available, so no trade plan could be worked out.',
  'tiered.note.noTechnicalsForLevels':
    'The technical data is missing, so no trade plan could be worked out.',
  'tiered.note.duplicateAdjust':
    'The AI proposed two changes to the {level}; the first was kept and the second ignored.',
  'tiered.note.planAdjustDropped':
    'The AI’s proposed change to the {level} could not back its numbers with anything in the report, so the change was dropped.',
  'tiered.note.planReplyProblem':
    'The AI’s plan-review reply contained something the system could not use, so that part was ignored.',
  'tiered.note.planNoConverge':
    'Every change the AI proposed still tripped a risk check, so all of them were discarded and the plain computed plan stands.',
  'tiered.note.noGradableFields':
    'No report fields were available for the analysts to grade, so this run has no outlook.',
  'tiered.note.noEvidenceToVote':
    'No report data reached the analysts, so there was nothing to judge. Re-run this stock.',
  'tiered.note.rewardRiskDefaulted':
    'The reward-to-risk setting must be above 1. The value given was ignored and the default was used instead.',
  'tiered.note.adjustUnknownLevel':
    'The AI proposed a change to something that is not one of the plan’s levels, so it was ignored.',
  'tiered.note.downtrend':
    'The close is at or below its 50-day average — a pullback buy against the trend carries extra downside risk.',
  'tiered.note.trendCheckSkipped': 'The 50-day average was unavailable, so the trend check was skipped.',
  'tiered.note.summaryLinksDropped':
    'Some summary citations failed the code checks even after fixes — those values still show, but without links.',
  'tiered.note.optionsOiMissing':
    'Options open interest came back missing or zero at the source — the put/call OI ratio and total are left blank rather than showing a misleading 0.',
  'tiered.note.optionsVolumeMissing':
    'Options volume came back missing or zero at the source — the put/call volume ratio is left blank rather than showing a misleading 0.',
  'tiered.note.insiderRowsMissing':
    'Yahoo returned no insider transaction rows at all — that is indistinguishable from a data outage, so the insider block is left blank instead of claiming zero activity.',
  // News-screen stage degradations (judge/group/rank/summarize) — every
  // failure lowers the card's polish, never drops news.
  'tiered.note.newsJudgeFailed':
    'The AI reply that rates each news article’s relevance and importance was missing or unreadable, so every article was kept unrated.',
  'tiered.note.newsJudgeMissing':
    'The AI’s news-rating reply skipped {count} article(s) — those were kept unrated.',
  'tiered.note.newsGroupFailed':
    'The AI reply that merges articles covering the same story was missing or unreadable, so no merging was done — the same story may appear more than once.',
  'tiered.note.newsGroupPartial':
    'The AI’s story-merging reply skipped {count} article(s) — those stay as separate items.',
  'tiered.note.newsRankFailed':
    'The AI reply that orders events by importance was missing or unreadable, so events are shown in importance-score order instead.',
  'tiered.note.newsRankPartial':
    'The AI’s ranking reply skipped {count} event(s) — those were placed last, in importance-score order.',
  'tiered.note.newsSummaryFailed':
    'The AI reply that writes the one-sentence summaries was missing or unreadable, so the news feed’s own wording is shown instead.',
  'tiered.note.newsSummaryMissing':
    'The AI’s summary reply skipped {count} article(s) — those show the news feed’s own wording.',
  'tiered.note.newsTrimmed':
    'Busy news window: more events qualified than the card can show — the {count} ranked below the top {max} were left off.',
  'tiered.group.trend': 'Price & trend',
  'tiered.group.momentum': 'Momentum',
  'tiered.group.volatility': 'Volatility & range',
  'tiered.group.structure': 'Price structure',
  'tiered.group.volume': 'Volume',
  'tiered.group.meta': 'Data & score',
  'tiered.group.reportInfo': 'Report info',
  'tiered.group.earnings': 'Earnings',
  'tiered.group.other': 'Other',
  'tiered.note.fetchFailed': 'One news article ({domain}) couldn’t be downloaded, so it wasn’t used.',
  'tiered.note.fundamentalsUnavailable':
    'Official U.S. filings data (SEC) couldn’t be loaded, so some fundamentals figures may be missing.',
  'tiered.note.valuationUnavailable': 'Valuation ratios from Yahoo Finance couldn’t be loaded.',
  'tiered.note.macroUnavailable':
    'One economic indicator ({series}) couldn’t be loaded from the FRED database.',
  'tiered.note.indicatorNoHistory':
    'There was not enough price history to compute this value.',
  'tiered.note.macroFieldMissing':
    'The data source did not return enough data to compute this value.',
  'tiered.note.adjustmentRejected':
    'The AI wanted to tweak the {level}, but its suggestion broke the rules, so the formula’s number was kept.',
  'tiered.note.stopFallback':
    'The formula’s stop-loss price wasn’t usable, so a volatility-based (ATR) stop was used instead.',
  'tiered.note.noAtrStop': 'No volatility data (ATR) was available, so no stop-loss price could be computed.',
  'tiered.note.noAtrStopTarget':
    'No volatility data (ATR) was available, so neither the stop-loss nor the target price could be computed.',
  'tiered.note.noEntryNoStop': 'There is no usable entry price, so no stop-loss could be set.',
  'tiered.note.summaryFailed':
    'The judge’s written summary couldn’t be produced — the computed outlook is unaffected.',
  'tiered.note.badSetting': 'One sizing setting isn’t a number and was ignored.',
  'tiered.help.entry':
    'Ideal buy price.\nUsually near a support level — a price where buyers stepped in before.',
  'tiered.help.stopLoss':
    'Safety exit.\nA fall to here means the idea was wrong — selling caps the loss.',
  'tiered.help.takeProfit': 'Profit target.\nWhere the analysis suggests selling to lock in gains.',
  'tiered.empty': 'Enter a ticker to start a tiered analysis.',
  'tiered.history': 'Run history',
  'tiered.status.queued': 'Queued',
  'tiered.status.queuedAt': 'Queued ({position})',
  'tiered.status.running': 'Running',
  'tiered.status.done': 'Done',
  'tiered.status.failed': 'Failed',
  'tiered.help.depth':
    'Tier 1 (preliminary analysis): the four data reports plus one AI outlook.\nTier 2 (deep analysis): skips the single AI outlook — two analysts list the evidence and every bullet is voted on instead. Slower, more thorough.\n(Tier 3 is retired.)',
  'tiered.llmUsage': 'This run used {calls} LLM calls ({tokens} tokens)',
  'tiered.llmUsageShared':
    'This run used {calls} LLM calls ({tokens} tokens) and builds on top of {sharedCalls} LLM calls ({sharedTokens} tokens) from another run',
  'tiered.help.llmUsage':
    'LLM calls this run made (each one is a request to the language-model API), and their total tokens (the billing unit).\nClick to see every prompt and reply.\nWhen the outlook came from a shared run, that run’s calls are listed too, marked as another run’s.\nThe tier-1 outlook runs in the product’s built-in flow and is not counted.',
  'tiered.transcript.call': 'Call {n}',
  'tiered.transcript.owner': 'owner',
  'tiered.transcript.ownerThisRun': 'this run',
  'tiered.transcript.ownerAnotherRun': 'another run',
  'tiered.transcript.for': 'for',
  'tiered.transcript.llm': 'llm',
  'tiered.transcript.time': 'time',
  'tiered.transcript.tokens': 'tokens',
  'tiered.transcript.loading': 'Loading…',
  'tiered.transcript.error': 'Could not load the transcript: {error}',
  'tiered.transcript.empty': 'This run’s transcript has expired (kept 14 days).',
  'tiered.transcript.prompt': 'Prompt',
  'tiered.transcript.reply': 'Reply',
  'tiered.transcript.failed': 'Call failed: {error}',
  'tiered.transcript.noReply': '(no reply)',
  'tiered.alt.kind.formula': 'formula',
  'tiered.alt.kind.adjustment': 'adjustment',
  'tiered.alt.kind.whyBlank': 'why blank',
  'tiered.alt.kind.warnings': 'warnings',
  'tiered.alt.blankFallback':
    'This field has no value in this run — the data needed to compute it was unavailable.',
  'tiered.levelModal.noBase':
    'This run lacked the data needed to compute this level, so there is no formula base.',
  'tiered.levelModal.references': 'References',
  'tiered.help.debate':
    'Two analysts independently read the four reports and each lists ALL the evidence — bullish and bearish; a merge call lines the two lists up.\nCode verifies every cited value: it must match the report’s displayed number exactly and appear in the sentence; failed citations go back to the AI to fix (up to 3 times), and bullets still broken are crossed out and dropped.\nEach bullet lives or dies by majority vote (at most 3 votes): its author counts as one valid vote, so a bullet both analysts listed independently is confirmed on the spot; a checker AI casts the second vote on single-author bullets; a deciding vote breaks 1-1 ties.\nCode counts the surviving bullish vs bearish bullets into the score — no AI touches the numbers.',
  'tiered.debate.noOutlook':
    'The debate produced no outlook — re-run the stock (see Warnings).',
  'tiered.tree.bullish': 'bullish',
  'tiered.tree.bearish': 'bearish',
  'tiered.tree.valid': 'valid',
  'tiered.tree.invalid': 'invalid',
  'tiered.tree.scores': 'Scores',
  'tiered.tree.finalScore': 'final outlook score',
  'tiered.tree.transcript': 'Details',
  'tiered.tree.howItWorks': 'How this works',
  'tiered.tree.explain1':
    'Two AIs read the four reports independently and each lists every piece of bullish and bearish evidence.',
  'tiered.tree.explain2':
    'Code verifies every cited number against the reports; failed citations go back to be fixed, and bullets that cannot be fixed are crossed out and count toward nothing.',
  'tiered.tree.explain3':
    'The two lists are merged. A bullet listed by BOTH AIs is already agreed on — it needs no further checking, so it carries no check marks.',
  'tiered.tree.explain4':
    'A bullet only one AI listed is checked by another AI — the ✓ or ✗ after it; click the mark to read the reasoning.',
  'tiered.tree.explain5':
    'If that check says invalid, the bullet is tied 1-1 and one more AI casts the deciding vote — the second mark.',
  'tiered.tree.explain6':
    'A bullet with two ✗ loses the vote and is crossed out; everything not crossed out counts.',
  'tiered.tree.explain7':
    'The final score is 10 × bullish ÷ total surviving bullets: below 4 sell, 4–6 hold, above 6 buy.',
  'tiered.tree.codeCheck': 'code check result',
  'tiered.note.listerDegradedRole':
    '{role} — the grade sheet kept coming back invalid; this run used the other analyst’s sheet only.',
  'tiered.note.sheetsVoided':
    'Both analysts kept returning invalid grade sheets — the deep analysis was voided.',
  'tiered.note.noOutlook':
    'The deep analysis produced no outlook — re-run the stock.',
  'tiered.note.checkDegraded':
    'The check round kept coming back invalid — bullets were counted on their author’s vote alone.',
  'tiered.note.tiebreakDegraded':
    'The deciding round kept coming back invalid — tied bullets were treated as unresolved and left out of the score.',
  'tiered.note.voteDiscarded':
    'A vote’s citations still failed the code check after the fix attempts — that vote was discarded.',
  'tiered.note.unresolved':
    'A bullet was tied 1-1 with no deciding vote — it was treated as unresolved and left out of the score.',
  'tiered.note.allConfirmed':
    'Every bullet was listed independently by both analysts — no check votes were needed.',
  'tiered.note.struckBullet':
    'A bullet’s citations still failed the code check after 3 fix attempts — it is crossed out and counts toward nothing.',
  'tiered.note.fixRoundLost': 'A citation-fix reply was unreadable — that fix round was lost.',
  'tiered.note.stageRetriedRole':
    '{role} — the first reply was invalid; the retry succeeded.',
  'tiered.note.stageInvalidRole':
    '{role} — the reply was still invalid after a retry.',
  'tiered.role.checkRound': 'Check vote',
  'tiered.role.decidingRound': 'Deciding vote',
  'tiered.role.reportOutline': 'Report writer',
  'tiered.role.newsJudge': 'News relevance judge',
  'tiered.role.newsGrouping': 'Same-story news grouping',
  'tiered.role.newsRanking': 'News importance ranking',
  'tiered.role.newsSummary': 'News summary writer',
  'tiered.note.emptyLedger': 'No evidence survived to weigh, so the final score defaults to neutral 5.',
  'tiered.note.thinBase':
    'Most of the defender’s initial evidence did not survive — the weight rests on a thin base.',
  'tiered.help.debateScore':
    'The vote’s final outlook score, out of 10, at two decimals.\n0 = strongly bearish, 5 = neutral, 10 = strongly bullish.\nBelow 4 bearish, 4–6 neutral, above 6 bullish.\nPure code: 10 × the bullish bullets’ weight ÷ all bullets’ weight, over only the evidence that survived checking. See Scores at the bottom of Details.',
  'tiered.help.sizing':
    'Fixed arithmetic, no AI.\nEvery number links to where it appears in this report.\nThe result is rounded down to whole shares, and one stock may use at most 25% of capital.',
  'tiered.altForm.ticker': 'Ticker',
  'tiered.altForm.tier': 'Tier',
  'tiered.altForm.capital': 'Capital',
  'tiered.altForm.capitalCurrency': 'Capital: {currency}',
  'tiered.altForm.risk': 'Risk: %',
  'tiered.altForm.title': 'New run',
  'tiered.user.title': 'Your account',
  'tiered.user.loading': 'Loading…',
  'tiered.user.signInWith': 'Sign in with {provider}',
  'tiered.user.provider.google': 'Google',
  'tiered.user.provider.discord': 'Discord',
  'tiered.user.noProviders': 'Sign-in is not configured on this server.',
  'tiered.user.loginFailed': 'Sign-in did not complete. Try again.',
  'tiered.user.signOut': 'Sign out',
  'tiered.user.f.provider': 'LLM provider',
  'tiered.user.f.main': 'Main LLM',
  'tiered.user.f.sub': 'Sub LLM',
  'tiered.user.f.llmKey': 'LLM provider API key',
  'tiered.user.f.fred': 'FRED API key',
  'tiered.user.f.finnhub': 'FinnHub API key',
  'tiered.user.f.alphavantage': 'AlphaVantage API key',
  'tiered.user.ph.provider': 'Enter LLM provider...',
  'tiered.user.ph.main': 'Enter main LLM...',
  'tiered.user.ph.sub': 'Enter sub LLM...',
  'tiered.user.ph.llmKey': 'Enter LLM key...',
  'tiered.user.ph.fred': 'Enter FRED key...',
  'tiered.user.ph.finnhub': 'Enter FinnHub key...',
  'tiered.user.ph.alphavantage': 'Enter AlphaVantage key...',
  'tiered.user.default': 'default',
  'tiered.pill.llmProvider': 'LLM provider: {value}',
  'tiered.pill.mainLlm': 'Main LLM: {value}',
  'tiered.pill.subLlm': 'Sub LLM: {value}',
  'tiered.pill.llmKey': 'LLM key: {value}',
  'tiered.pill.fredKey': 'FRED key: {value}',
  'tiered.pill.finnhubKey': 'FinnHub key: {value}',
  'tiered.pill.alphavantageKey': 'AlphaVantage key: {value}',
  'tiered.help.llmProvider':
    'The company whose AI answers your runs.\nPicking one fills both model fields with its defaults and narrows the lists to its models.\nClick the title to open its key page.',
  'tiered.help.mainLlm': 'The model that does the analysis.\nStronger models cost more per run.',
  'tiered.help.subLlm':
    'Optional: a cheaper model for the news screen (is this article about the company?).\nMust be from the same provider as the main LLM.\nEmpty = the main LLM does it.',
  'tiered.help.llmKey':
    'Your key from that provider; it pays for the run.\nStored encrypted, shown back as its last 4 characters only.\nClick the title to open the page where you get one.',
  'tiered.help.fredKey':
    'Optional. FRED is the US Federal Reserve’s economic database (rates, inflation).\nEmpty = the server’s default key.\nClick the title to open the page where you get one.',
  'tiered.help.finnhubKey':
    'Optional. FinnHub supplies prices, company facts and news.\nEmpty = the server’s default key.\nClick the title to open the page where you get one.',
  'tiered.help.alphavantageKey':
    'Optional. AlphaVantage supplies price history and fundamentals.\nEmpty = the server’s default key.\nClick the title to open the page where you get one.',
  'tiered.user.saveError': 'Could not save: {error}',
  'tiered.user.signInFirst': 'Sign in before starting a run.',
  'tiered.altForm.start': 'Start',
  'tiered.altForm.noticeTitle': 'Heads up',
  'tiered.altForm.needTickerFirst':
    'Pick a ticker first — capital is in the currency of the ticker’s market.',
  'tiered.altForm.errorTitle': 'Error',
  'tiered.altForm.missingIntro': 'These required fields are not filled in:',
  'tiered.altForm.duplicateRunning':
    'An identical {ticker} run is already running (same capital, risk, reward ratio, max hold and tier). It is expanded in the run history below. Wait for it to finish, or change one of the inputs.',
  'tiered.altForm.duplicateQueued':
    'An identical {ticker} run is already waiting in the queue (same capital, risk, reward ratio, max hold and tier). It is expanded in the run history below and starts by itself. Wait for it, or change one of the inputs.',
  'tiered.altForm.req.ticker': 'Ticker',
  'tiered.altForm.req.tier': 'Tier',
  'tiered.altForm.req.capital': 'Capital',
  'tiered.altForm.req.risk': 'Risk',
  'tiered.altForm.req.reward': 'Reward ratio',
  'tiered.altForm.req.hold': 'Max hold',
  'tiered.altForm.req.mainLlm': 'Main LLM',
  'tiered.altForm.req.llmKey': 'LLM provider API key',
  'tiered.altForm.tierOption1': '1: preliminary analysis',
  'tiered.altForm.tierOption2': '2: deep analysis',
  'tiered.altForm.tickerPh': 'Enter ticker...',
  'tiered.altForm.tierPh': 'Enter tier...',
  'tiered.altForm.capitalPh': 'Enter capital...',
  'tiered.altForm.riskPh': 'Enter risk...',
  'tiered.altForm.reward': 'Reward: x',
  'tiered.altForm.rewardPh': 'Enter ratio...',
  'tiered.altForm.lowRewardWarn':
    'A reward-to-risk ratio below 1.5 means the trade barely pays for its risk — 1.5× is the common minimum. The run will still use your {value}× target.',
  'tiered.help.reward':
    'The reward-to-risk ratio you ask the plan for (how many times the accepted risk the potential profit should be). Required; the default is 2.\nTarget = entry + ratio × risk. If overhead resistance caps the target below your ratio, the plan carries a warning (below the 1.5 hard floor, no plan is issued at all).',
  'tiered.altForm.hold': 'Max hold: weeks',
  'tiered.altForm.holdPh': 'Enter max hold...',
  'tiered.help.hold':
    'The longest you plan to hold the trade. Required; the default is 2 weeks.\nThe same number goes to the AI (to judge which evidence matters at this timescale), onto the report, and into the forward test as the grading window — the AI, you and the testing stay on one page.',
  'tiered.altForm.marketOpenTitle': 'Market is open',
  'tiered.altForm.marketOpenTrading':
    'The {market} market is trading right now. This app only analyzes completed trading days, so today has no data to analyze yet.',
  'tiered.altForm.marketOpenHours':
    'Today’s session: {open}–{close} market local time, which is {openLocal}–{closeLocal} on your clock.',
  'tiered.altForm.marketOpenMixedData':
    '“Run anyway” analyzes the previous completed trading day: the technicals report will only use data up to that day’s close, but news and other sources may be live — so the report can mix data from two different points in time.',
  'tiered.altForm.marketOpenBestWindow':
    'Also, even after the close, data sources can lag live data by up to 30 minutes, and a run itself takes a while — so the best time to use the app is from 30 minutes after the close until 30 minutes before the next open.',
  'tiered.altForm.runAnyway': 'Run anyway',
  'tiered.pill.ticker': 'Ticker: {value}',
  'tiered.pill.tier': 'Tier: {value}',
  'tiered.pill.capital': 'Capital: {value} {currency}',
  'tiered.pill.risk': 'Risk: {value}%',
  'tiered.pill.reward': 'Reward: {value}×',
  'tiered.pill.hold': 'Max hold: {value}w',
  'tiered.pill.capitalMin': 'Capital Min: {value}',
  'tiered.pill.capitalMax': 'Capital Max: {value}',
  'tiered.pill.riskMin': 'Risk Min: {value}%',
  'tiered.pill.riskMax': 'Risk Max: {value}%',
  'tiered.pill.dateMin': 'Date Min: {value}',
  'tiered.pill.dateMax': 'Date Max: {value}',
  'tiered.pill.rewardMin': 'Reward Min: {value}×',
  'tiered.pill.rewardMax': 'Reward Max: {value}×',
  'tiered.altFilter.tickerPh': 'Enter ticker...',
  'tiered.altFilter.capital': 'Capital',
  'tiered.altFilter.risk': 'Risk: %',
  'tiered.altFilter.date': 'Date: yyyy/mm/dd',
  'tiered.altFilter.tier': 'Tier',
  'tiered.altFilter.tierPh': 'Enter tier...',
  'tiered.altFilter.holdPh': 'Enter max hold...',
  'tiered.altFilter.reward': 'Reward: ×',
  'tiered.altFilter.min': 'Min',
  'tiered.altFilter.max': 'Max',
  'tiered.altHistory.shares': '{value} shares',
  'tiered.altHistory.tier': 'Tier {value}',
  'tiered.altHistory.hold': '{value}w',
  // The run list's column-name header row.
  'tiered.altHistory.h.ticker': 'Ticker',
  'tiered.altHistory.h.capital': 'Capital',
  'tiered.altHistory.h.risk': 'Risk',
  'tiered.altHistory.h.reward': 'Reward',
  'tiered.altHistory.h.hold': 'Max hold',
  'tiered.altHistory.h.tier': 'Tier',
  'tiered.altHistory.h.status': 'Status',
  'tiered.altHistory.h.outlook': 'Outlook',
  'tiered.altHistory.h.date': 'Date',
  'tiered.altHistory.first': 'First page',
  'tiered.altHistory.prev': 'Previous page',
  'tiered.altHistory.next': 'Next page',
  'tiered.altHistory.last': 'Last page',
  'tiered.altHistory.none': 'No runs match these filters',
  'tiered.altHistory.loading': 'Loading report…',
  'tiered.alt.dimensionsTitle': 'Data reports',
  'tiered.alt.eventsNone': 'None in the last {count} days',
  'tiered.alt.eventsNoneGeneric': 'None found',
  'tiered.alt.eventsWindow': 'last {count} days',
  'tiered.alt.tier2Title': 'Deep analysis',
  'tiered.alt.rewardBelowGoal':
    'This plan’s reward-to-risk is {ratio}, below your {goal}× goal — overhead resistance caps the target.',
  'tiered.alt.roundLevelTitle': 'Round level',
  'tiered.alt.roundLevelBody':
    '{value} is the nearest round price below the current price. It comes from no data row — the code computes it on the spot: crowd orders cluster at round numbers, forming a weak support.',
  'tiered.alt.f.capital': 'capital',
  'tiered.alt.f.risk': 'risk per trade',
  'tiered.alt.f.entry': 'entry',
  'tiered.alt.f.stop': 'stop loss',
  'tiered.alt.sources': 'Sources',
  'tiered.alt.levels.computed': 'Computed',
  'tiered.alt.levels.adjusted': 'Adjusted',
  'tiered.alt.levels.keep': 'keep',
  'tiered.levels.shares': 'Shares',
  'tiered.alt.levels.warnings': 'Warnings',
  'tiered.alt.warn.none': 'none',
  'tiered.alt.warn.downtrend':
    'The close ({close}) is at or below its 60-day average ({sma60}) — the stock is in a medium-term downtrend, so entering here is buying against the trend and carries extra risk of further downside.',
  'tiered.alt.warn.downtrend_50':
    'The close ({close}) is at or below its 50-day average ({sma50}) — the stock is in a medium-term downtrend, so entering here is buying against the trend and carries extra risk of further downside.',
  'tiered.alt.warn.earnings_soon':
    'The next earnings report is {days} day(s) away ({date}) — inside a typical swing hold. Technicals do not survive earnings: one announcement can gap the price past any stop. Plan to exit before the report, or size for the gap.',
  'tiered.alt.warn.macro_event_soon':
    'The {event} is {days} day(s) away ({date}) — inside a typical swing hold. This is market-wide gap risk: one number can move every stock at once. Plan smaller size around it, or size the stop for the gap.',
  'tiered.alt.warnEvent.rate_decision': 'next official interest rate decision',
  'tiered.alt.warnEvent.inflation_data': 'next inflation data release',
  'tiered.alt.warnEvent.employment_data': 'next employment data release',
  'tiered.alt.warn.gap_atr':
    'If overnight news gaps the open 1 ATR ({atr}) below your stop ({stop}), it opens at {atrOpen}; the stop order sells there — a {atrLoss} loss, {atrExtra} more than the {planned} you planned.',
  'tiered.alt.warn.gap_worst':
    'If the stock repeats its worst day of the past year ({worstDayPct}%), the open lands at {worstOpen}, past your stop ({stop}) — selling there loses {worstLoss}, {worstExtra} more than the {planned} you planned.',
  // Names of the warning popup's computed values (also the variable
  // names in their formula word-lines).
  'tiered.alt.warnF.gapOpen': 'gapped open',
  'tiered.alt.warnF.gapLoss': 'gap loss',
  'tiered.alt.warnF.plannedLoss': 'planned loss',
  'tiered.alt.warnF.worstOpen': 'worst-day open',
  'tiered.alt.warnF.worstLoss': 'worst-day loss',
  'tiered.alt.warnF.ratio': 'reward-to-risk',
  'tiered.alt.f.shares': 'shares',
  'tiered.alt.f.target': 'target',
  // The fixed keyword each risk line opens with (code-picked from the
  // check id, never AI-written).
  'tiered.alt.warnKey.downtrend': 'Downtrend',
  'tiered.alt.warnKey.earnings_soon': 'Earnings soon',
  'tiered.alt.warnKey.macro_event_soon': 'Macro event soon',
  'tiered.alt.warnKey.gap_atr': 'Overnight gap risk',
  'tiered.alt.warnKey.gap_worst': 'Worst-day gap risk',
  'tiered.alt.warnKey.reward_below_goal': 'Low reward ratio',
  'tiered.alt.checkKey.downtrend': 'Downtrend',
  'tiered.alt.checkKey.liquidity': 'Liquidity',
  'tiered.alt.checkKey.volatility': 'Volatility',
  'tiered.alt.checkKey.stop_vs_support': 'Support',
  'tiered.alt.reviewFail.title': 'Why the plan keeps its computed numbers',
  'tiered.alt.reviewFail.intro':
    'The AI tried adjusting this plan, but every attempt still tripped a risk check, so all adjustments were discarded and the formula-computed plan stands.',
  'tiered.alt.reviewFail.round': 'Round {round} still flagged: {checks}',
  'tiered.help.capital':
    'The money you trade with, in the ticker’s own currency.\nThe shares computation starts from it.\nRemembered for your next run.',
  'tiered.help.riskPct':
    'The most you accept losing on one trade, as a percent of capital.\n1–2% is common.',

  // ---- Outlook redesign ----
  'tiered.alt.tier1Title': 'Preliminary analysis',
  'tiered.alt.outlook': 'Outlook',
  'tiered.alt.action': 'Action',
  'tiered.alt.actionRatio': 'current reward-to-risk ratio is {ratio}',
  'tiered.outlook.bullish': 'Bullish',
  'tiered.outlook.neutral': 'Neutral',
  'tiered.outlook.bearish': 'Bearish',
  'tiered.outlook.unknown': 'Failed',
  'tiered.action.enter': 'Buy now',
  'tiered.action.enter_later': 'Buy later',
  'tiered.action.no_trade': 'No trade',
  'tiered.action.unknown': 'Re-run — this run produced no usable outlook',
  'tiered.help.outlook':
    'The outlook is the judgment on the stock itself (bullish / neutral / bearish), regardless of whether you hold it.\nThe action is derived by code from the outlook: bullish → buy now (the trade plan’s reward-to-risk meets your goal) or buy later (it falls short); neutral or bearish → no trade.',
  'tiered.help.action':
    'Your personal instruction, derived by fixed code rules from the outlook.\nBullish splits in two: the trade plan’s actual reward-to-risk ratio reaches the goal you set → “Buy now”; it falls short (e.g. overhead resistance caps the target) → “Buy later” (wait for a better price before entering).',
  'tiered.alt.staleNote':
    'This report is from a previous trading day — re-run for a fresh plan.',
  'tiered.alt.planTitle': 'Trade plan',
  'tiered.help.plan':
    'The plan levels a fixed formula computed from the price data (no AI).\nWhat shows depends on the Action: buy → the full levels table; keep holding → the structural stop only; no trade / sell → no levels.',
  'tiered.altFilter.status': 'Status',
  'tiered.altFilter.statusPh': 'Enter status...',
  'tiered.pill.status': 'Status: {value}',
  'tiered.altFilter.outlook': 'Outlook',
  'tiered.altFilter.outlookPh': 'Enter outlook...',
  'tiered.pill.outlook': 'Outlook: {value}',

  'tiered.tree.bullishWeight': 'bullish weight',
  'tiered.tree.totalWeight': 'total weight',

  // ---- Tier-2 details (v11: 1-5 scores + score reasons) ----
  'tiered.tree.explainWeights5':
    'Each AI also rates every bullet’s importance 1-5 (1 = very minor, 5 = very important); a bullet’s final score is the median of its ratings, and the total score is weighted by it: 10 × the bullish bullets’ weight ÷ all bullets’ weight. Click a score or a mark for the reasoning.',
  'tiered.tree.lister': 'Lister {n}',
  'tiered.tree.checker': 'Checker {n}',
  'tiered.tree.validityLine': 'result: {value}',
  'tiered.tree.reasonPrefix': 'reason:',
  'tiered.tree.scoreLine': 'score: {value}',
  'tiered.tree.scoresList': 'Scores: {value}',
  'tiered.tree.medianTitle': 'Significance Score',
  'tiered.tree.medianLine': 'Median: {value}',

};

export const UI_TEXT: Record<UiLanguage, Record<UiTextKey, string>> = {
  zh,
  en,
};

export type UiTextParams = Record<string, string | number>;

export function formatUiText(template: string, params?: UiTextParams): string {
  if (!params) {
    return template;
  }

  return template.replace(/\{(\w+)\}/g, (match, key: string) => {
    const value = params[key];
    return value === undefined ? match : String(value);
  });
}
