# PredictionPool

**Pari-Mutuel Prediction Markets with AI-Verified Resolution on GenLayer**

A staking-based prediction market where anyone can open a YES/NO topic
against a real, checkable source, let others stake on either side, and have
the outcome resolved by an on-chain LLM reading live evidence — with
winners splitting the losing side's pool pari-mutuel style.

---

## What it does

1. Anyone can **open a topic** — a factual prediction, a source URL that
   will contain the evidence, and a resolution window.
2. Anyone can **stake GEN on YES or NO** while the topic is still open,
   once per address per topic.
3. Once the resolution window has passed, anyone can trigger **resolution**:
   the contract fetches the live content at the source URL and asks an LLM
   to judge, strictly from that evidence, whether the prediction came true.
   GenLayer's validator consensus (`gl.eq_principle.prompt_comparative`)
   ensures multiple independent LLM runs agree on the categorical `YES`/`NO`
   outcome before it's accepted on-chain.
4. Winners **claim their payout**: their original stake back, plus a
   proportional share of the losing side's entire pool (pari-mutuel —
   the fewer winners, the bigger each share).
5. Safety exits: the opener can **cancel** a topic before any stakes are
   placed, and anyone can trigger an **abandoned-topic refund** if a topic
   sits unresolved for 30 days past its deadline.

## Why this is different

Most prediction-market designs either rely on a centralized oracle to
report the outcome, or push resolution onto a slow, manual dispute process.
PredictionPool resolves directly against live web content through an LLM,
with GenLayer's validator consensus making sure the categorical outcome
(not the exact wording) is what multiple independent model runs agree on —
so the "oracle" is transparent, on-chain, and reproducible, not a black box
or a trusted third party.

## Architecture

| Concern | Mechanism |
|---|---|
| Topic state | Parallel `TreeMap[str, ...]` fields per topic ID (opener, description, source URL, deadline, abandon deadline, status, outcome, pool sizes, staker counts) |
| Stakes | Parallel `TreeMap[str, ...]` keyed by `topic_id:address` (side, claimed status) and `topic_id:side:address` (stake amount) |
| AI resolution | `gl.nondet.web.render` fetches the source URL; `gl.nondet.exec_prompt` inside a closure, reconciled across validators via `gl.eq_principle.prompt_comparative` |
| Output safety | Resolver output is validated (JSON parse, structure, field presence, type, and domain of the `outcome` field) before any state mutation or fund transfer |
| Payout | Pari-mutuel — each winner receives their own stake back plus `losing_pool // winning_count` |
| Fund safety | Funds only move on `claim_winnings` (after `RESOLVED`), `cancel_topic` (only before any stakes placed), or `claim_abandoned_refund` (30 days past deadline, topic still unresolved) |

Address-derived lookup keys are built with `str(gl.message.sender_address).lower()`
on the write side and `address.lower()` on the read side. GenLayer's
`Address` string representation is checksummed (mixed-case), so without
lowercasing on both sides, a key written during `stake_prediction` can fail
to match the same address pasted with different casing into a view method
later — the contract would otherwise report "no position" for a wallet
that actually staked and claimed successfully.

## Contract methods

### Write

- **`open_topic(description: str, source_url: str, minutes_until_resolution: int) -> str`**
  Opens a new topic. Returns the new `topic_id` (e.g. `"T0"`).
- **`stake_prediction(topic_id: str, side: str)`** *(payable)*
  Stakes GEN on `"YES"` or `"NO"` for an open topic, once per address.
- **`cancel_topic(topic_id: str)`**
  Opener can cancel, but only before any stakes have been placed.
- **`resolve_topic(topic_id: str) -> str`**
  Triggers AI resolution: fetches the source URL, prompts the LLM for a
  `YES`/`NO` outcome with reasoning, reaches validator consensus, validates
  the output, and marks the topic `RESOLVED`. Returns the outcome.
- **`claim_winnings(topic_id: str) -> str`**
  Winning stakers claim their stake plus a pari-mutuel share of the losing
  pool. Losing stakers have nothing to claim.
- **`claim_abandoned_refund(topic_id: str)`**
  Anyone who staked can reclaim their stake if a topic is still `OPEN` 30
  days past its original deadline (nobody triggered resolution).

### View

- **`get_topic(topic_id: str) -> dict`**
  Full current state of a topic (opener, description, source URL, deadline,
  status, outcome, pool sizes, staker counts).
- **`get_my_position(topic_id: str, address: str) -> dict`**
  A given address's side, stake amount, and claim status for a topic.
- **`get_topic_count() -> int`**

## Tested end-to-end in GenLayer Studio

- `open_topic` confirmed opening a topic with a real Wikipedia URL as
  evidence source and a short resolution window, returning `"T0"`.
- `stake_prediction` confirmed staking 2 GEN on `YES`, with the transaction
  reaching `FINALIZED`/`SUCCESS`.
- `resolve_topic` confirmed fetching the live page and reaching full
  validator consensus on `"YES"`, with reasoning explicitly citing the
  page's own wording (*"The evidence explicitly states that 'Python is...'"*),
  and `Accepted` through the full `PENDING → PROPOSING → COMMITTING →
  REVEALING → ACCEPTED` consensus flow.
- `claim_winnings` confirmed paying out `"Claimed 2000000000000000000 wei"`
  (the full 2 GEN stake back, correctly reduced to the stake alone since
  this test had no losing pool to split), `FINALIZED`/`SUCCESS`.
- `get_my_position` confirmed `side: "YES"`, `claimed: "yes"`,
  `stake: "2000000000000000000"` — correctly matching on-chain state after
  the address-casing fix.
- `get_topic_count` confirmed `1`.
- All test transactions reached `FINALIZED`/`SUCCESS` with validator
  agreement across multiple LLM policies (GPT, Gemini, Mistral, Gemma,
  MiniMax).

## Deployment

```
# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
```

No VecDB/embeddings dependency needed for this contract. Constructor takes
no arguments. Deploy directly in GenLayer Studio or via `genlayer-js`
against Studionet / Bradbury testnet.

## Notes on GenVM quirks discovered while building this

- Contract method parameters only support GenVM's own type set (`str`,
  `int`, `bool`, `Address`, `bytes`, etc.) — a plain Python `float`
  parameter fails schema generation entirely (`Could not load contract
  schema`). Sub-hour testing windows were handled by using
  `minutes_until_resolution: int` instead of a fractional-hours `float`.
- `str(gl.message.sender_address)` produces a **checksummed** (mixed-case)
  address string. Any `TreeMap` key built from it must be lowercased
  consistently on both the write side (`str(gl.message.sender_address).lower()`)
  and the read side (`address.lower()` on a user-supplied address string),
  or lookups silently miss for addresses that are the same wallet but
  different casing.
- Pari-mutuel payout math (`losing_pool // winning_count`) is done entirely
  in integer `u256` arithmetic — no floats anywhere in the payout path, to
  keep every validator's computation byte-identical.

## Notes on design decisions

- The resolver is restricted to a strict `YES`/`NO` categorical output,
  validated for JSON structure, field presence, type, and domain before any
  state change — the same safety pattern applied proactively across every
  contract in this series after it was flagged as a required fix on an
  earlier contract (SemanticDisputeRouter).
- Pari-mutuel payout (rather than a fixed-odds payout) means the contract
  never needs to pre-commit to an exchange rate or odds — the pool simply
  splits proportionally among however many winners there are, which keeps
  the contract's own logic simple and fully determined by on-chain state.

## License

MIT
