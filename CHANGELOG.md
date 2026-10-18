# Changelog

## 0.1.0

First usable release.

- Fund tracing on TRON (TronGrid) and EVM chains (any JSON-RPC endpoint), forward or backward, from an address or a transaction, with time causality, fan-out caps, hop limits and labeled stops.
- Evidence store: every provider response kept byte for byte with its SHA-256; credentials never stored or logged.
- Live fund-flow graph with manual expansion.
- Cases with an append-only history and address notes.
- Labels: OFAC SDN import and contributed JSON datasets.
- Screening for direct and one-hop exposure; exposure on traces.
- Heuristic signals, starting with the collection wallet pattern.
- Contract analysis: verified source, static checks, live ownership, supply and liquidity control, deployer tracing.
- Frozen HTML and PDF reports with an evidence manifest.
