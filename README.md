# Open States Scrapers

This repository contains the code responsible for scraping bills & votes for Open States.

## Digital Democracy Project fork

This is [Digital Democracy Project](https://digitaldemocracyproject.org)'s fork, used to power our own civic-data pipeline.

- `origin` → this fork; `upstream` → the public project.
- Our own fixes land on this fork's `main` via a normal branch + PR — no cherry-picking, no separate patch branch.
- Public upstream is merged into `main` on a periodic (roughly monthly, or opportunistic) cadence.
- Fixes with no DDP-specific assumptions baked in are contributed back upstream when practical — e.g. our FL WAF-session-refresh fix, merged upstream as [openstates/openstates-scrapers#5751](https://github.com/openstates/openstates-scrapers/pull/5751).

## Links

* [Contributor's Guide](https://docs.openstates.org/contributing/)
* [Documentation](https://docs.openstates.org/contributing/scrapers/)
* [Open States Issues](https://github.com/openstates/issues/issues)
* [Open States Discussions](https://github.com/openstates/issues/discussions)
* [Code of Conduct](https://docs.openstates.org/code-of-conduct/)
