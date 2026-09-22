"""Strategy lab: try many strategies without fooling ourselves.

Three rules make it safe to search:

1. **A locked holdout.** The most recent months are never used while
   developing. Each strategy may be evaluated on them once, at the end.
2. **Every trial is recorded.** Failures included, automatically. The
   winner is then judged by the Deflated Sharpe Ratio (Bailey & López de
   Prado, 2014), which raises the bar with the number of strategies tried.
3. **A portfolio of assets, not one.** So a lucky asset cannot carry a
   strategy.
"""
